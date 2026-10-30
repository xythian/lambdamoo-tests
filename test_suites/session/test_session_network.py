"""Session backend: listen() ports and outbound connections through the edge (SNT-001 through SNT-024).

A session server listens only on its Unix socket. Ports opened with listen()
and connections made with open_network_connection() are the edge's: the
server asks for them over the edge's control attachment, so they belong to
the edge's process and outlast the server. The edge also terminates TLS for
ports the server asks for with the "tls" option, and for the -t port, with
certificate files the server names, a certificate the edge gets by ACME, or
its own.
"""

import shutil
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path
from typing import NamedTuple

import pytest

from lib.moo_server import MooClient
from lib.moocode import define_verb, moo_string
from lib.session import MODE_GRACEFUL, MODE_INITIAL, SessionEdge


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def port_is_open(port: int) -> bool:
    try:
        socket.create_connection(('127.0.0.1', port), timeout=0.5).close()
        return True
    except OSError:
        return False


def error_of(client: MooClient, expression: str) -> str:
    """Return the error an expression raises, or its value if it raises none."""
    return client.eval_expect_success(f"`{expression} ! ANY'")


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class Remote:
    """A TCP (or TLS) server standing in for the far end of an outbound connection."""

    def __init__(self, tls_context: ssl.SSLContext = None):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(4)
        self.port = self.listener.getsockname()[1]
        self.tls_context = tls_context
        self.connections = []
        self.received = b''
        self.closed = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        try:
            sock, _ = self.listener.accept()
            if self.tls_context:
                sock = self.tls_context.wrap_socket(sock, server_side=True)
        except (OSError, ssl.SSLError):
            return
        self.connections.append(sock)
        while True:
            try:
                data = sock.recv(4096)
            except (OSError, ssl.SSLError):
                data = b''
            if not data:
                self.closed.set()
                return
            self.received += data

    def wait_for(self, data: bytes, timeout: float = 5.0) -> bool:
        return wait_until(lambda: data in self.received, timeout)

    def close(self) -> None:
        for sock in self.connections:
            sock.close()
        self.listener.close()


class TlsClient(MooClient):
    """A client that connects with TLS, trusting the test certificate."""

    def __init__(self, port: int, context: ssl.SSLContext):
        super().__init__(host='127.0.0.1', port=port, timeout=5.0)
        self.context = context

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._socket = self.context.wrap_socket(sock, server_hostname='localhost')
        self._connected = True
        self._read_available(first_timeout=self.SETTLE_TIMEOUT)


class Certificate(NamedTuple):
    """A self-signed certificate for localhost, its files, and contexts using it."""
    server: ssl.SSLContext
    client: ssl.SSLContext
    cert: Path
    key: Path


class NetWorld:
    """A session server started with +O, its edge, and a Wizard client."""

    def __init__(self, manager, database: Path, socket_path: Path, outbound: bool = True,
                 tls_context: ssl.SSLContext = None, extra_args=(),
                 certificate: Certificate = None, acme=None):
        self.manager = manager
        self.socket_path = socket_path
        self.args = ['+O' if outbound else '-O', *extra_args]
        self.instance = manager.start(database=database, session_socket=socket_path,
                                      extra_args=self.args)
        self.edge = SessionEdge(str(socket_path), hold=15.0, tls_context=tls_context,
                                certificate=certificate and str(certificate.cert),
                                key=certificate and str(certificate.key), acme=acme).start()
        self.clients = []
        self.wizard = self.connect(self.edge.port, 'Wizard')

    def connect(self, port: int, player: str, tls: ssl.SSLContext = None) -> MooClient:
        if tls:
            client = TlsClient(port, tls)
        else:
            client = MooClient(host='127.0.0.1', port=port, timeout=5.0)
        client.connect()
        client.authenticate(player)
        self.clients.append(client)
        return client

    def graceful_restart(self):
        output = self.manager.stop(self.instance)
        self.instance = self.manager.start(database=output, session_socket=self.socket_path,
                                           extra_args=self.args)
        return self.instance

    def close(self) -> None:
        for client in self.clients:
            client.close()
        self.edge.close()
        if self.instance.is_running():
            self.manager.stop(self.instance)


@pytest.fixture
def net_world(requires_session, candidate_server, multiplayer_db, tmp_path):
    world = NetWorld(candidate_server, multiplayer_db, tmp_path / "moo.sock")
    yield world
    world.close()


@pytest.fixture
def certificate(tmp_path):
    """A self-signed certificate for localhost, and a context that trusts it."""
    if shutil.which('openssl') is None:
        pytest.skip("TLS tests need the openssl command to make a certificate")
    cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
                    '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    server = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server.load_cert_chain(cert, key)
    client = ssl.create_default_context(cafile=str(cert))
    return Certificate(server, client, cert, key)


@pytest.fixture
def tls_world(requires_session, candidate_server, multiplayer_db, tmp_path, certificate):
    world = NetWorld(candidate_server, multiplayer_db, tmp_path / "moo.sock",
                     tls_context=certificate.client, certificate=certificate)
    yield world
    world.close()


class TestListen:
    """listen() and unlisten() open and close ports on the edge."""

    def test_snt_001_listen_opens_edge_port(self, net_world):
        """SNT-001: listen() makes the edge accept clients on that port for the server."""
        port = free_port()
        assert net_world.wizard.eval_expect_success(f'listen(#0, {port})') == str(port)
        assert wait_until(lambda: port in net_world.edge.listening_ports)

        player2 = net_world.connect(port, 'Player2')
        assert player2.eval_expect_success('player') == '#4'
        local = player2._socket.getsockname()[1]
        assert net_world.wizard.eval_expect_success('connection_name(#4)') == \
            f'"port {port} from 127.0.0.1, port {local}"'
        session = next(s for s in net_world.edge.sessions.values() if s.player == 4)
        assert session.listen_port == port

    def test_snt_002_listen_needs_a_port(self, net_world):
        """SNT-002: the edge picks no ports, so listen() needs a port number."""
        assert error_of(net_world.wizard, 'listen(#0, 0)') == 'E_INVARG'
        assert error_of(net_world.wizard, 'listen(#0, 65536)') == 'E_INVARG'
        assert error_of(net_world.wizard, 'listen(#0, "/tmp/other.sock")') == 'E_TYPE'

    def test_snt_003_unlisten_closes_edge_port(self, net_world):
        """SNT-003: unlisten() makes the edge stop accepting on the port."""
        port = free_port()
        net_world.wizard.eval_expect_success(f'listen(#0, {port})')
        assert wait_until(lambda: port_is_open(port))
        net_world.wizard.eval_expect_success(f'unlisten({port})')
        assert wait_until(lambda: not port_is_open(port))

    def test_snt_004_listen_port_session_survives_restart(self, net_world):
        """SNT-004: a player who came in on a listen() port resumes after a
        graceful restart, and the edge drops the port the new server didn't
        ask for."""
        port = free_port()
        net_world.wizard.eval_expect_success(f'listen(#0, {port})')
        assert wait_until(lambda: port in net_world.edge.listening_ports)
        player2 = net_world.connect(port, 'Player2')
        session = next(s for s in net_world.edge.sessions.values() if s.player == 4)

        new = net_world.graceful_restart()
        assert wait_until(lambda: "SESSION REATTACHED: #4" in new.get_log_contents(), 10)
        assert player2.eval_expect_success('player') == '#4'
        assert session.attachments == [MODE_INITIAL, MODE_GRACEFUL]
        assert wait_until(lambda: port not in net_world.edge.listening_ports)


class TestOutbound:
    """open_network_connection() asks the edge to connect."""

    def test_snt_005_outbound_connection(self, net_world):
        """SNT-005: the edge makes the connection and the server can use it."""
        remote = Remote()
        try:
            conn = net_world.wizard.eval_expect_success(
                f'open_network_connection("127.0.0.1", {remote.port})')
            assert conn.startswith('#-')
            name = net_world.wizard.eval_expect_success(f'connection_name({conn})')
            assert name.startswith('"port ') and name.endswith(f' to 127.0.0.1, port {remote.port}"')
            info = net_world.wizard.eval_expect_success(f'connection_info({conn})')
            assert info.startswith('{{"direction", "outbound"}, {"transport", "tcp"}')
            net_world.wizard.eval_expect_success(f'notify({conn}, "hello")')
            assert remote.wait_for(b'hello\r\n')
            net_world.wizard.eval_expect_success(f'boot_player({conn})')
            assert remote.closed.wait(5)
        finally:
            remote.close()

    def test_snt_006_outbound_refused(self, net_world):
        """SNT-006: a refused connection raises E_INVARG, as in the TCP backend."""
        port = free_port()
        assert error_of(net_world.wizard, 
            f'open_network_connection("127.0.0.1", {port})') == 'E_INVARG'

    def test_snt_007_outbound_disabled(self, requires_session, candidate_server, multiplayer_db,
                                       tmp_path):
        """SNT-007: without +O, open_network_connection() raises E_PERM."""
        world = NetWorld(candidate_server, multiplayer_db, tmp_path / "moo.sock", outbound=False)
        try:
            assert error_of(world.wizard, 
                'open_network_connection("127.0.0.1", 1)') == 'E_PERM'
        finally:
            world.close()

    def test_snt_008_outbound_options(self, net_world):
        """SNT-008: options are {name, value} pairs; only "tls" is known."""
        wizard = net_world.wizard
        assert error_of(wizard, 'open_network_connection("127.0.0.1", 1, {{"bogus", 1}})') \
            == 'E_INVARG'
        assert error_of(wizard, 'open_network_connection("127.0.0.1", 1, "tls")') == 'E_TYPE'
        assert error_of(wizard, 'open_network_connection("127.0.0.1", 1, #0, {}, 1)') \
            == 'E_ARGS'

    def test_snt_009_unbound_outbound_closed_by_restart(self, net_world):
        """SNT-009: an outbound connection that is not logged in ends with the
        server that opened it, as in the TCP backend."""
        remote = Remote()
        try:
            net_world.wizard.eval_expect_success(
                f'open_network_connection("127.0.0.1", {remote.port})')
            net_world.graceful_restart()
            assert remote.closed.wait(10)
        finally:
            remote.close()


    def test_snt_012_logged_in_outbound_survives_restart(self, net_world):
        """SNT-012: an outbound connection the database logs in as a player
        stays connected through a graceful restart, like any session."""
        remote = Remote()
        try:
            net_world.wizard.eval_expect_success(
                f'open_network_connection("127.0.0.1", {remote.port})')
            assert wait_until(lambda: remote.connections)
            remote.connections[0].sendall(b'connect Player3\r\n')
            assert wait_until(lambda: '#5' in net_world.wizard.eval_expect_success('connected_players()'))

            new = net_world.graceful_restart()
            assert wait_until(lambda: "SESSION REATTACHED: #5" in new.get_log_contents(), 10)
            net_world.wizard.eval_expect_success('notify(#5, "after restart")')
            assert remote.wait_for(b'after restart\r\n')
            assert not remote.closed.is_set()
        finally:
            remote.close()


class TestPendingOutbound:
    """A task waiting for the edge to connect is part of the edge's request,
    not a suspended task: it isn't saved with the database and resume()
    can't wake it, but kill_task() can kill it."""

    @staticmethod
    def stall_connects(world) -> threading.Event:
        """Make the edge hold every CONNECT until the returned event is set."""
        release = threading.Event()
        connect = world.edge._connect_outbound

        def stalled(request):
            release.wait(30)
            connect(request)
        world.edge._connect_outbound = stalled
        return release

    @staticmethod
    def task_status(client: MooClient, task: str) -> str:
        code = f'for t in (queued_tasks()) if (t[1] == {task}) return t[2]; endif endfor return 0;'
        return client.eval_expect_success(f'eval({moo_string(code)})')

    def start_connecting(self, world, port: int) -> str:
        code = f'fork t (0) open_network_connection("127.0.0.1", {port}); endfork return t;'
        task = world.wizard.eval_expect_success(f'eval({moo_string(code)})')[4:-1]
        assert wait_until(lambda: self.task_status(world.wizard, task) == '{1, "connecting"}')
        return task

    def test_snt_022_pending_connect_is_not_saved(self, net_world):
        """SNT-022: resume() can't wake a task waiting for the edge, and a
        server replacement doesn't carry it over."""
        release = self.stall_connects(net_world)
        remote = Remote()
        try:
            task = self.start_connecting(net_world, remote.port)
            assert error_of(net_world.wizard, f'resume({task})') == 'E_INVARG'
            net_world.graceful_restart()
            assert wait_until(lambda: "SESSION REATTACHED: #3" in
                              net_world.instance.get_log_contents(), 10)
            assert self.task_status(net_world.wizard, task) == '{1, 0}'
        finally:
            release.set()
            remote.close()

    def test_snt_023_pending_connect_can_be_killed(self, net_world):
        """SNT-023: kill_task() kills a task waiting for the edge, and the
        connection the edge then makes is refused and closed."""
        release = self.stall_connects(net_world)
        remote = Remote()
        try:
            task = self.start_connecting(net_world, remote.port)
            net_world.wizard.eval_expect_success(f'kill_task({task})')
            assert self.task_status(net_world.wizard, task) == '{1, 0}'
            release.set()
            assert remote.closed.wait(10)
            assert net_world.instance.is_running()
        finally:
            release.set()
            remote.close()

    def test_snt_024_outbound_with_unlistening_listener_survives_restart(self, net_world):
        """SNT-024: an outbound connection whose listener object isn't
        listening, logged in as a player, resumes after a graceful restart."""
        remote = Remote()
        try:
            handler = net_world.wizard.eval_expect_success('create(#-1)')
            define_verb(net_world.wizard, handler, 'do_login_command', ['return #5;'])
            net_world.wizard.eval_expect_success(
                f'open_network_connection("127.0.0.1", {remote.port}, {handler})')
            assert wait_until(lambda: remote.connections)
            remote.connections[0].sendall(b'hello\r\n')
            assert wait_until(lambda: '#5' in net_world.wizard.eval_expect_success('connected_players()'))

            new = net_world.graceful_restart()
            assert wait_until(lambda: "SESSION REATTACHED: #5" in new.get_log_contents(), 10)
            net_world.wizard.eval_expect_success('notify(#5, "after restart")')
            assert remote.wait_for(b'after restart\r\n')
        finally:
            remote.close()


class TestOutboundTls:
    """The edge can wrap an outbound connection in TLS."""

    def test_snt_010_outbound_tls(self, tls_world, certificate):
        """SNT-010: {{"tls", 1}} makes the edge connect with TLS, verifying the host."""
        remote = Remote(tls_context=certificate.server)
        try:
            conn = tls_world.wizard.eval_expect_success(
                f'open_network_connection("localhost", {remote.port}, {{{{"tls", 1}}}})')
            name = tls_world.wizard.eval_expect_success(f'connection_name({conn})')
            assert name.endswith(f' to localhost, port {remote.port}"')
            info = tls_world.wizard.eval_expect_success(f'connection_info({conn})')
            assert '{"transport", "tls"}' in info and '{"remote-host", "localhost"}' in info
            tls_world.wizard.eval_expect_success(f'notify({conn}, "secret")')
            assert remote.wait_for(b'secret\r\n')
        finally:
            remote.close()

    def test_snt_011_outbound_tls_unverified(self, tls_world, certificate):
        """SNT-011: a certificate that doesn't match the host name is refused."""
        remote = Remote(tls_context=certificate.server)
        try:
            assert error_of(tls_world.wizard, 
                f'open_network_connection("127.0.0.1", {remote.port}, {{{{"tls", 1}}}})') \
                == 'E_INVARG'
        finally:
            remote.close()


class TestListenTls:
    """The edge accepts TLS clients on ports the server asks for with TLS."""

    def test_snt_013_listen_tls_with_edge_certificate(self, tls_world, certificate):
        """SNT-013: {{"tls", 1}} makes the edge accept TLS on the port, with its
        own certificate, and connection_info() reports the TLS transport."""
        port = free_port()
        assert tls_world.wizard.eval_expect_success(f'listen(#0, {port}, {{{{"tls", 1}}}})') \
            == str(port)
        assert wait_until(lambda: port in tls_world.edge.listening_ports)

        player2 = tls_world.connect(port, 'Player2', tls=certificate.client)
        assert player2.eval_expect_success('player') == '#4'
        local = player2._socket.getsockname()[1]
        assert tls_world.wizard.eval_expect_success('connection_name(#4)') == \
            f'"port {port} from 127.0.0.1, port {local}"'
        assert '{"transport", "tls"}' in tls_world.wizard.eval_expect_success('connection_info(#4)')

    def test_snt_014_listen_tls_with_named_certificate(self, net_world, certificate):
        """SNT-014: "certificate" and "key" name the files the edge accepts TLS
        with, so an edge with no certificate of its own can serve the port."""
        port = free_port()
        net_world.wizard.eval_expect_success(
            f'listen(#0, {port}, {{{{"tls", 1}}, {{"certificate", "{certificate.cert}"}}, '
            f'{{"key", "{certificate.key}"}}}})')
        assert wait_until(lambda: port in net_world.edge.listening_ports)
        player2 = net_world.connect(port, 'Player2', tls=certificate.client)
        assert player2.eval_expect_success('player') == '#4'

    def test_snt_015_listen_tls_options(self, net_world):
        """SNT-015: "certificate" and "key" need "tls" and each other, and must be strings."""
        wizard = net_world.wizard
        port = free_port()
        assert error_of(wizard, f'listen(#0, {port}, {{{{"certificate", "c.pem"}}}})') \
            == 'E_INVARG'
        assert error_of(wizard, f'listen(#0, {port}, {{{{"tls", 1}}, {{"key", "k.pem"}}}})') \
            == 'E_INVARG'
        assert error_of(wizard, f'listen(#0, {port}, {{{{"tls", 1}}, {{"certificate", 1}}}})') \
            == 'E_TYPE'
        assert error_of(wizard, f'listen(#0, {port}, {{{{"listener", #0}}}})') == 'E_INVARG'
        assert wizard.eval_expect_success('listeners()').count(str(port)) == 0

    def test_snt_016_main_tls_port_survives_restart(self, requires_session, candidate_server,
                                                    multiplayer_db, tmp_path, certificate):
        """SNT-016: -t PORT has the edge accept TLS clients for #0 on that port,
        and a player who came in on it resumes after a graceful restart."""
        port = free_port()
        world = NetWorld(candidate_server, multiplayer_db, tmp_path / "moo.sock",
                         extra_args=['-t', str(port)], certificate=certificate)
        try:
            assert wait_until(lambda: port in world.edge.listening_ports)
            player2 = world.connect(port, 'Player2', tls=certificate.client)
            assert player2.eval_expect_success('player') == '#4'
            assert '{"transport", "tls"}' in world.wizard.eval_expect_success('connection_info(#4)')

            new = world.graceful_restart()
            assert wait_until(lambda: "SESSION REATTACHED: #4" in new.get_log_contents(), 10)
            assert player2.eval_expect_success('player') == '#4'
            assert port in world.edge.listening_ports
        finally:
            world.close()


class TestListenAcme:
    """The "acme" option asks the edge to get the port's certificate by ACME."""

    def test_snt_017_listen_acme(self, requires_session, candidate_server, multiplayer_db,
                                 tmp_path, certificate):
        """SNT-017: the edge is given the names to get a certificate for, and
        accepts TLS on the port with the certificate it got."""
        requests = []

        def acme(names):
            requests.append(names)
            return str(certificate.cert), str(certificate.key)

        world = NetWorld(candidate_server, multiplayer_db, tmp_path / "moo.sock", acme=acme)
        try:
            port = free_port()
            world.wizard.eval_expect_success(
                f'listen(#0, {port}, {{{{"tls", 1}}, {{"acme", "localhost"}}}})')
            assert wait_until(lambda: port in world.edge.listening_ports)
            assert requests == [('localhost',)]
            player2 = world.connect(port, 'Player2', tls=certificate.client)
            assert player2.eval_expect_success('player') == '#4'
        finally:
            world.close()

    def test_snt_018_acme_names_reach_edge(self, net_world):
        """SNT-018: a list of names reaches the edge in order, and an edge that
        can't do ACME doesn't open the port and says so."""
        port = free_port()
        net_world.wizard.eval_expect_success(
            f'listen(#0, {port}, {{{{"tls", 1}}, {{"acme", {{"moo.example.org", '
            f'"*.moo.example.org"}}}}}})')
        assert wait_until(lambda: port in net_world.edge.seen)
        listen = net_world.edge.seen[port]
        assert (listen.tls, listen.certificate, listen.acme) == \
            (True, None, ('moo.example.org', '*.moo.example.org'))
        assert port not in net_world.edge.listening_ports
        assert wait_until(lambda: f"edge can't get a certificate for port {port}"
                          in net_world.instance.get_log_contents())

    def test_snt_019_acme_options(self, net_world):
        """SNT-019: "acme" needs "tls", excludes "certificate" and "key", and
        takes a host name or a non-empty list of them."""
        wizard = net_world.wizard
        port = free_port()

        def listen(options: str) -> str:
            return error_of(wizard, f'listen(#0, {port}, {{{{"tls", 1}}, {options}}})')

        assert error_of(wizard, f'listen(#0, {port}, {{{{"acme", "moo.example.org"}}}})') \
            == 'E_INVARG'
        assert listen('{"acme", "moo.example.org"}, {"certificate", "c.pem"}, '
                      '{"key", "k.pem"}') == 'E_INVARG'
        assert listen('{"acme", {}}') == 'E_INVARG'
        assert listen('{"acme", "moo.example.org,other.example.org"}') == 'E_INVARG'
        assert listen('{"acme", ""}') == 'E_INVARG'
        assert listen('{"acme", 1}') == 'E_TYPE'
        assert listen('{"acme", {"moo.example.org", 1}}') == 'E_TYPE'
        assert str(port) not in wizard.eval_expect_success('listeners()')


class TestListenFailures:
    """The edge tells the server about ports it can't serve."""

    def test_snt_020_port_in_use(self, net_world):
        """SNT-020: when the edge can't bind a port, the server logs it and
        drops the listener, as if listen() had failed."""
        blocker = socket.socket()
        blocker.bind(('127.0.0.1', 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]
        try:
            assert net_world.wizard.eval_expect_success(f'listen(#0, {port})') == str(port)
            assert wait_until(lambda: f"edge can't listen on port {port}"
                              in net_world.instance.get_log_contents())
            assert wait_until(lambda: str(port) not in
                              net_world.wizard.eval_expect_success('listeners()'))
        finally:
            blocker.close()

    def test_snt_021_certificate_missing(self, net_world, tmp_path):
        """SNT-021: a TLS port whose certificate the edge can't load is
        reported and dropped, and the server's other ports are unaffected."""
        port = free_port()
        missing = tmp_path / "missing.pem"
        net_world.wizard.eval_expect_success(
            f'listen(#0, {port}, {{{{"tls", 1}}, {{"certificate", "{missing}"}}, '
            f'{{"key", "{missing}"}}}})')
        assert wait_until(lambda: f"edge can't get a certificate for port {port}"
                          in net_world.instance.get_log_contents())
        assert wait_until(lambda: str(port) not in
                          net_world.wizard.eval_expect_success('listeners()'))
        assert port not in net_world.edge.listening_ports
        assert net_world.wizard.eval_expect_success('1 + 1') == '2'
