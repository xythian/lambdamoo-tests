"""connection_info() and the connection_name() format it agrees with.

connection_info(PLAYER) returns a list of {NAME, VALUE} pairs describing how
the connection was made, the same shape on every network backend. TCP
connections, whether the server accepts them itself or an edge accepts them
for a session build, report:

    {"direction", "inbound" | "outbound"}
    {"transport", "tcp" | "tls" | ...}
    {"local-port", INT}
    {"remote-host", STR}        only when a name lookup found one
    {"remote-address", STR}
    {"remote-port", INT}

and connection_name() reads "port LOCAL from HOST, port REMOTE", HOST being
the remote host if known and the address otherwise. Servers without
connection_info() are skipped.
"""

import socket

import pytest


@pytest.fixture
def requires_connection_info(client):
    """Skip servers that have no connection_info() builtin."""
    if client.eval_expect_success('`function_info("connection_info") ! ANY => 0\'') == '0':
        pytest.skip("Test requires connection_info()")


def info_value(info: str, name: str):
    """The value text of NAME in a connection_info() result, or None."""
    marker = f'{{"{name}", '
    start = info.find(marker)
    if start < 0:
        return None
    return info[start + len(marker):info.index('}', start)]


class TestConnectionInfo:
    """connection_info() on the player's own connection."""

    def test_tcp_client_info(self, client, requires_connection_info):
        """A TCP client is described by direction, transport, both ports and
        its address, in that order."""
        info = client.eval_expect_success('connection_info(player)')
        server_port = client._socket.getpeername()[1]
        client_port = client._socket.getsockname()[1]
        assert info.startswith(f'{{{{"direction", "inbound"}}, {{"transport", "tcp"}}, '
                               f'{{"local-port", {server_port}}}, ')
        assert info.endswith(f'{{"remote-address", "127.0.0.1"}}, '
                             f'{{"remote-port", {client_port}}}}}')

    def test_connection_name_agrees(self, client, requires_connection_info):
        """connection_name() is built from the same facts connection_info() reports."""
        info = client.eval_expect_success('connection_info(player)')
        host = info_value(info, 'remote-host') or info_value(info, 'remote-address')
        assert client.eval_expect_success('connection_name(player)') == \
            f'"port {info_value(info, "local-port")} from {host[1:-1]}, ' \
            f'port {info_value(info, "remote-port")}"'

    def test_not_connected(self, client, requires_connection_info):
        """An object with no connection raises E_INVARG."""
        assert client.eval_expect_success('`connection_info(#0) ! ANY\'') == 'E_INVARG'

    def test_argument_type(self, client, requires_connection_info):
        """The argument must be an object."""
        assert client.eval_expect_success('`connection_info("x") ! ANY\'') == 'E_TYPE'


class TestConnectionInfoPermissions:
    """Only a wizard or the player themselves may ask."""

    def test_other_players_connection(self, multiplayer_server, candidate_server):
        """A non-wizard gets E_PERM for someone else's connection; a wizard does not."""
        wizard = candidate_server.connect(multiplayer_server)
        wizard.authenticate('Wizard')
        player = candidate_server.connect(multiplayer_server)
        player.authenticate('Player2')
        try:
            if wizard.eval_expect_success(
                    '`function_info("connection_info") ! ANY => 0\'') == '0':
                pytest.skip("Test requires connection_info()")
            assert player.eval_expect_success('`connection_info(#3) ! ANY\'') == 'E_PERM'
            assert player.eval_expect_success('connection_info(player)').startswith(
                '{{"direction", "inbound"}')
            assert wizard.eval_expect_success('connection_info(#4)').startswith(
                '{{"direction", "inbound"}')
        finally:
            player.close()
            wizard.close()


class TestOutboundConnectionInfo:
    """A connection the server opened describes itself as outbound."""

    def test_outbound_tcp(self, candidate_server, minimal_db, tmp_path, requires_tcp_listeners,
                          requires_outbound_switch):
        """open_network_connection() on the TCP backend reports "outbound", the
        host name it was given, and the remote port."""
        remote = socket.socket()
        remote.bind(('127.0.0.1', 0))
        remote.listen(4)
        remote_port = remote.getsockname()[1]
        instance = candidate_server.start(minimal_db, work_dir=tmp_path / 'outbound',
                                          extra_args=['+O'])
        wizard = candidate_server.connect(instance)
        try:
            wizard.authenticate('Wizard')
            if wizard.eval_expect_success(
                    '`function_info("connection_info") ! ANY => 0\'') == '0':
                pytest.skip("Test requires connection_info()")
            conn = wizard.eval_expect_success(
                f'open_network_connection("localhost", {remote_port})')
            info = wizard.eval_expect_success(f'connection_info({conn})')
            assert info.startswith('{{"direction", "outbound"}, {"transport", "tcp"}, ')
            assert '{"remote-host", "localhost"}, {"remote-address", "127.0.0.1"}, ' \
                f'{{"remote-port", {remote_port}}}}}' in info
            name = wizard.eval_expect_success(f'connection_name({conn})')
            assert name == f'"port {info_value(info, "local-port")} to localhost, port {remote_port}"'
        finally:
            wizard.close()
            candidate_server.stop(instance)
            remote.close()
