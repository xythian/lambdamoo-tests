"""Session backend: listen() ports and outbound connections through the edge (SNT-001 through SNT-012).

A session server listens only on its Unix socket. Ports opened with listen()
and connections made with open_network_connection() are the edge's: the
server asks for them over the edge's control attachment, so they belong to
the edge's process and outlast the server.
"""

import shutil
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path

import pytest

from lib.moo_server import MooClient
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


class NetWorld:
    """A session server started with +O, its edge, and a Wizard client."""

    def __init__(self, manager, database: Path, socket_path: Path, outbound: bool = True,
                 tls_context: ssl.SSLContext = None):
        self.manager = manager
        self.socket_path = socket_path
        self.args = ['+O' if outbound else '-O']
        self.instance = manager.start(database=database, session_socket=socket_path,
                                      extra_args=self.args)
        self.edge = SessionEdge(str(socket_path), hold=15.0, tls_context=tls_context).start()
        self.clients = []
        self.wizard = self.connect(self.edge.port, 'Wizard')

    def connect(self, port: int, player: str) -> MooClient:
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
    return server, client


@pytest.fixture
def tls_world(requires_session, candidate_server, multiplayer_db, tmp_path, certificate):
    world = NetWorld(candidate_server, multiplayer_db, tmp_path / "moo.sock",
                     tls_context=certificate[1])
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
            f'"tcp:127.0.0.1:{local}"'
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
            assert net_world.wizard.eval_expect_success(f'connection_name({conn})') == \
                f'"tcp:127.0.0.1:{remote.port}"'
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


class TestOutboundTls:
    """The edge can wrap an outbound connection in TLS."""

    def test_snt_010_outbound_tls(self, tls_world, certificate):
        """SNT-010: {{"tls", 1}} makes the edge connect with TLS, verifying the host."""
        remote = Remote(tls_context=certificate[0])
        try:
            conn = tls_world.wizard.eval_expect_success(
                f'open_network_connection("localhost", {remote.port}, {{{{"tls", 1}}}})')
            assert tls_world.wizard.eval_expect_success(f'connection_name({conn})') == \
                f'"tls:localhost:{remote.port}"'
            tls_world.wizard.eval_expect_success(f'notify({conn}, "secret")')
            assert remote.wait_for(b'secret\r\n')
        finally:
            remote.close()

    def test_snt_011_outbound_tls_unverified(self, tls_world, certificate):
        """SNT-011: a certificate that doesn't match the host name is refused."""
        remote = Remote(tls_context=certificate[0])
        try:
            assert error_of(tls_world.wizard, 
                f'open_network_connection("127.0.0.1", {remote.port}, {{{{"tls", 1}}}})') \
                == 'E_INVARG'
        finally:
            remote.close()
