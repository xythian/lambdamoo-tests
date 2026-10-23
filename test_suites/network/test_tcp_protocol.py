"""The TCP/IP protocol layer: listening, accepting, connecting out (NET-110 onward).

These cover the server's edge with the operating system's sockets:
listen() errors that come from the socket layer, how connections are named,
open_network_connection()'s argument checks and failures, its connect
timeout, and the protocol's command-line options.
"""

import re
import socket
import time

import pytest

from lib.assertions import assert_moo_raises, assert_moo_success


@pytest.fixture
def start_server(candidate_server, minimal_db, tmp_path, requires_dns_switch,
                 requires_outbound_switch):
    """Start servers with extra command-line arguments; stop them afterwards."""
    instances = []

    def start(*args):
        instance = candidate_server.start(minimal_db, work_dir=tmp_path / f'server{len(instances)}',
                                          extra_args=list(args))
        instances.append(instance)
        return instance

    yield start
    for instance in instances:
        candidate_server.stop(instance)


@pytest.fixture
def outbound(candidate_server, start_server):
    """A Wizard connection to a server started with -N +O."""
    client = candidate_server.connect(start_server('-N', '+O'))
    client.authenticate('Wizard')
    yield client
    client.close()


@pytest.fixture
def tcp_listener():
    """A local TCP listener for outbound connections to reach.

    Yields:
        The port it is listening on (127.0.0.1).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(5)
    yield sock.getsockname()[1]
    sock.close()


@pytest.fixture
def unanswered_port():
    """A local port where connects get no answer.

    A listener that never accepts, with its accept queue already full: Linux
    drops further SYNs, so a connect neither completes nor fails.

    Yields:
        The port (127.0.0.1).
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(0)
    port = listener.getsockname()[1]
    fillers = []
    for _ in range(4):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setblocking(False)
        s.connect_ex(('127.0.0.1', port))
        fillers.append(s)
    time.sleep(0.3)
    yield port
    for s in fillers:
        s.close()
    listener.close()


def closed_port() -> int:
    """A local port that nothing is listening on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class TestListen:
    """listen() errors from the socket layer."""

    def test_net_110_port_out_of_range(self, client):
        """NET-110: Ports outside 0..65535 raise E_INVARG rather than wrapping."""
        obj = assert_moo_success(client.eval("create(#1)"))
        assert_moo_raises(client, f"listen({obj}, -1)", "E_INVARG")
        assert_moo_raises(client, f"listen({obj}, 65536)", "E_INVARG")
        assert_moo_raises(client, f"listen({obj}, 65536 + 7777)", "E_INVARG")

    def test_net_111_port_in_use(self, client):
        """NET-111: A port another process is listening on raises E_QUOTA."""
        obj = assert_moo_success(client.eval("create(#1)"))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other:
            other.bind(('0.0.0.0', 0))
            other.listen(1)
            port = other.getsockname()[1]
            assert_moo_raises(client, f"listen({obj}, {port})", "E_QUOTA")


class TestConnectionNames:
    """How the protocol names connections."""

    def test_net_112_inbound_name(self, candidate_server, start_server):
        """NET-112: An inbound connection is 'port L from HOST, port R'."""
        instance = start_server('-N')
        client = candidate_server.connect(instance)
        client.authenticate('Wizard')
        try:
            name = assert_moo_success(client.eval('connection_name(player)'))
            assert re.fullmatch(rf'"port {instance.port} from 127\.0\.0\.1, port \d+"', name), name
        finally:
            client.close()

    def test_net_113_outbound_name(self, outbound, tcp_listener):
        """NET-113: An outbound connection is 'port L to HOST, port R', HOST as given."""
        conn = assert_moo_success(outbound.eval(f'open_network_connection("127.0.0.1", {tcp_listener})'))
        name = assert_moo_success(outbound.eval(f'connection_name({conn})'))
        assert re.fullmatch(rf'"port \d+ to 127\.0\.0\.1, port {tcp_listener}"', name), name


class TestOpenNetworkConnection:
    """open_network_connection() argument checks and failures."""

    def test_net_114_argument_errors(self, outbound):
        """NET-114: Wrong argument counts, types and port ranges are rejected."""
        assert_moo_raises(outbound, 'open_network_connection("127.0.0.1")', "E_ARGS")
        assert_moo_raises(outbound, 'open_network_connection(1, 2)', "E_TYPE")
        assert_moo_raises(outbound, 'open_network_connection("127.0.0.1", "80")', "E_TYPE")
        assert_moo_raises(outbound, 'open_network_connection("127.0.0.1", -1)', "E_INVARG")
        assert_moo_raises(outbound, 'open_network_connection("127.0.0.1", 65536)', "E_INVARG")

    def test_net_115_connection_refused(self, outbound):
        """NET-115: A refused connection raises E_INVARG."""
        assert_moo_raises(outbound, f'open_network_connection("127.0.0.1", {closed_port()})',
                          "E_INVARG")

    def test_net_116_connect_timeout(self, outbound, unanswered_port):
        """NET-116: outbound_connect_timeout bounds a connect that gets no answer.

        The timeout is read from the server_options of the listener object
        given as the third argument.  The connect must fail with E_INVARG
        after about that long, well before the kernel's own connect timeout
        of a minute or more.
        """
        listener = assert_moo_success(outbound.eval('create(#1)'))
        assert_moo_success(outbound.eval(f'add_property({listener}, "server_options", create(#1), {{player, "r"}})'))
        assert_moo_success(outbound.eval(
            f'add_property({listener}.server_options, "outbound_connect_timeout", 2, {{player, "r"}})'))
        start = time.monotonic()
        result = assert_moo_success(outbound.eval(
            f"`open_network_connection(\"127.0.0.1\", {unanswered_port}, {listener}) ! ANY'", timeout=30))
        elapsed = time.monotonic() - start
        assert result == 'E_INVARG'
        # A timer with one-second resolution may fire up to a second early.
        assert 0.9 < elapsed < 5, f"connect gave up after {elapsed:.1f}s with a 2-second timeout"


class TestCommandLine:
    """The protocol's command-line options."""

    def test_net_117_source_address(self, candidate_server, start_server):
        """NET-117: -a restricts the listening address and is logged."""
        instance = start_server('-a', '127.0.0.1')
        assert 'Source address restricted to 127.0.0.1' in instance.get_log_contents()
        client = candidate_server.connect(instance)
        client.authenticate('Wizard')
        try:
            assert assert_moo_success(client.eval('1 + 1')) == '2'
        finally:
            client.close()

    @pytest.mark.parametrize('args', [['-a', 'not-an-address'], ['12x'], ['-a']])
    def test_net_118_bad_arguments_stop_startup(self, start_server, args):
        """NET-118: A malformed protocol argument stops the server from starting."""
        with pytest.raises(RuntimeError):
            start_server(*args)
