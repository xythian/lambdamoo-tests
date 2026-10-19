"""Options lists for listen() and open_network_connection().

Both builtins take an optional list of {name, value} pairs, the same on every
network backend:

    listen(OBJECT, POINT [, PRINT-MESSAGES] [, OPTIONS])
        "print-messages", "tls", "certificate", "key"
    open_network_connection(HOST, PORT [, LISTENER] [, OPTIONS])
        "listener", "tls"

A backend that can't do TLS raises E_INVARG for "tls" rather than quietly
making a plain connection. Servers that predate options lists are skipped.
"""

import socket

import pytest


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def result_of(client, expression: str) -> str:
    """Return the value of expression, or the error it raises."""
    return client.eval_expect_success(f"`{expression} ! ANY'")


@pytest.fixture
def requires_options(client):
    """Skip servers whose listen() takes no options list."""
    port = free_port()
    if result_of(client, f'listen(#0, {port}, 0, {{}})') == 'E_ARGS':
        pytest.skip("Test requires listen() and open_network_connection() options lists")
    result_of(client, f'unlisten({port})')


@pytest.fixture
def port(client):
    """A free port, unlistened afterwards if a test listened on it."""
    port = free_port()
    yield port
    result_of(client, f'unlisten({port})')


class TestListenOptions:
    """listen() options on every backend."""

    def test_print_messages_option(self, client, requires_options, port):
        """"print-messages" in the options list sets the listener's print-messages flag."""
        assert client.eval_expect_success(f'listen(#0, {port}, {{{{"print-messages", 1}}}})') \
            == str(port)
        assert f'{{#0, {port}, 1}}' in client.eval_expect_success('listeners()')

    def test_options_after_print_messages(self, client, requires_options, port):
        """The options list may follow a print-messages argument."""
        assert client.eval_expect_success(f'listen(#0, {port}, 1, {{}})') == str(port)
        assert f'{{#0, {port}, 1}}' in client.eval_expect_success('listeners()')

    def test_unknown_option(self, client, requires_options, port):
        """An option listen() doesn't know raises E_INVARG."""
        assert result_of(client, f'listen(#0, {port}, {{{{"bogus", 1}}}})') == 'E_INVARG'
        assert result_of(client, f'listen(#0, {port}, {{{{"listener", #0}}}})') == 'E_INVARG'

    def test_malformed_options(self, client, requires_options, port):
        """Each option is a {name, value} pair."""
        assert result_of(client, f'listen(#0, {port}, 0, "tls")') == 'E_TYPE'
        assert result_of(client, f'listen(#0, {port}, {{"tls"}})') == 'E_INVARG'
        assert result_of(client, f'listen(#0, {port}, {{{{1, 1}}}})') == 'E_INVARG'

    def test_certificate_needs_tls(self, client, requires_options, port):
        """"certificate" and "key" mean nothing without "tls"."""
        assert result_of(client, f'listen(#0, {port}, {{{{"certificate", "c.pem"}}, '
                                 f'{{"key", "k.pem"}}}})') == 'E_INVARG'


class TestTlsWithoutTlsSupport:
    """A backend without TLS refuses "tls" instead of making a plain connection."""

    def test_listen_tls_refused(self, client, requires_options, requires_tcp_listeners, port):
        """listen() with "tls" raises E_INVARG and opens no port."""
        assert result_of(client, f'listen(#0, {port}, {{{{"tls", 1}}}})') == 'E_INVARG'
        assert str(port) not in client.eval_expect_success('listeners()')

    def test_listen_tls_off_accepted(self, client, requires_options, requires_tcp_listeners,
                                     port):
        """{"tls", 0} asks for nothing the backend lacks."""
        assert client.eval_expect_success(f'listen(#0, {port}, {{{{"tls", 0}}}})') == str(port)

    def test_open_tls_refused(self, candidate_server, minimal_db, tmp_path, requires_options,
                              requires_tcp_listeners, requires_outbound_switch):
        """open_network_connection() with "tls" raises E_INVARG, though the
        same connection without it succeeds."""
        remote = socket.socket()
        remote.bind(('127.0.0.1', 0))
        remote.listen(4)
        remote_port = remote.getsockname()[1]
        instance = candidate_server.start(minimal_db, work_dir=tmp_path / 'outbound',
                                          extra_args=['+O'])
        wizard = candidate_server.connect(instance)
        try:
            wizard.authenticate('Wizard')
            assert result_of(wizard, f'open_network_connection("127.0.0.1", {remote_port}, '
                                     '{{"tls", 1}})') == 'E_INVARG'
            assert result_of(wizard, f'open_network_connection("127.0.0.1", {remote_port}, '
                                     '{{"tls", 0}})').startswith('#-')
        finally:
            wizard.close()
            candidate_server.stop(instance)
            remote.close()
