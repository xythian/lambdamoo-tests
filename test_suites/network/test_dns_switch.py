"""The +N/-N command-line switch for enabling/disabling DNS lookups.

With -N the server never starts its name-lookup helper: inbound connections
are named by numeric address, and open_network_connection() accepts only
numeric addresses.  +N (the default) keeps DNS lookups enabled.  Servers
without the switch (no "[+N|-N]" in their usage message) are skipped.
"""

import socket

import pytest

DNS_ENABLED = 'DNS name lookups enabled'
DNS_DISABLED = 'DNS name lookups disabled'
HELPER_STARTED = 'NAME_LOOKUP: Started new lookup process'


@pytest.fixture
def start_server(candidate_server, minimal_db, tmp_path, requires_dns_switch):
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


def wizard(candidate_server, instance):
    """Connect to instance as Wizard."""
    client = candidate_server.connect(instance)
    client.authenticate('Wizard')
    return client


def try_open(client, host: str, port: int) -> str:
    """Call open_network_connection(), returning its result or the error raised."""
    return client.eval_expect_success(f'`open_network_connection("{host}", {port}) ! ANY\'')


class TestDnsSwitch:
    """Behavior of the +N/-N switch."""

    def test_dns_enabled_by_default(self, start_server):
        """Without the switch, DNS is enabled and the lookup helper starts."""
        log = start_server().get_log_contents()
        assert DNS_ENABLED in log
        assert HELPER_STARTED in log

    def test_plus_n_enables_dns(self, start_server):
        """+N enables DNS and starts the lookup helper."""
        log = start_server('+N').get_log_contents()
        assert DNS_ENABLED in log
        assert HELPER_STARTED in log

    def test_minus_n_disables_dns(self, start_server):
        """-N disables DNS and never starts the lookup helper."""
        log = start_server('-N').get_log_contents()
        assert DNS_DISABLED in log
        assert HELPER_STARTED not in log

    def test_minus_n_names_connections_numerically(self, candidate_server, start_server):
        """With -N, inbound connections are named by numeric address."""
        client = wizard(candidate_server, start_server('-N'))
        try:
            name = client.eval_expect_success('connection_name(player)')
            assert '127.0.0.1' in name
        finally:
            client.close()


class TestDnsSwitchOutbound:
    """Outbound connections with DNS enabled and disabled."""

    @pytest.fixture(autouse=True)
    def _outbound(self, requires_outbound_switch):
        pass

    def test_minus_n_outbound_accepts_numeric_address(self, candidate_server, start_server,
                                                      tcp_listener):
        """With -N, open_network_connection() still connects to a numeric address."""
        client = wizard(candidate_server, start_server('-N', '+O'))
        try:
            assert try_open(client, '127.0.0.1', tcp_listener).startswith('#')
        finally:
            client.close()

    def test_minus_n_outbound_rejects_host_name(self, candidate_server, start_server,
                                                tcp_listener):
        """With -N, open_network_connection() can't resolve host names."""
        client = wizard(candidate_server, start_server('-N', '+O'))
        try:
            assert try_open(client, 'localhost', tcp_listener) == 'E_INVARG'
        finally:
            client.close()

    def test_plus_n_outbound_resolves_host_name(self, candidate_server, start_server,
                                                tcp_listener):
        """With +N, open_network_connection() resolves host names."""
        client = wizard(candidate_server, start_server('+N', '+O'))
        try:
            assert try_open(client, 'localhost', tcp_listener).startswith('#')
        finally:
            client.close()
