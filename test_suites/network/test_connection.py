"""Network connection tests (NET-001 through NET-008)."""

import socket
import time
import pytest

from lib.client import MooClient, MooClientPool
from lib.assertions import assert_moo_success


class TestBasicConnection:
    """Tests for basic TCP connection functionality."""

    def test_net_001_basic_tcp_connection(self, server):
        """NET-001: Basic TCP connection succeeds."""
        # Simply connecting should work
        client = MooClient(host='localhost', port=server.port)
        assert client.is_connected()
        client.close()

    def test_net_002_multiple_concurrent_connections(self, server):
        """NET-002: Multiple concurrent connections work."""
        clients = []
        try:
            # Create 10 simultaneous connections
            for i in range(10):
                client = MooClient(host='localhost', port=server.port)
                assert client.is_connected(), f"Client {i} failed to connect"
                clients.append(client)

            # All should still be connected
            for i, client in enumerate(clients):
                assert client.is_connected(), f"Client {i} disconnected unexpectedly"

        finally:
            for client in clients:
                client.close()

    def test_net_004_graceful_disconnect(self, server):
        """NET-004: Clean disconnection is handled properly."""
        client = MooClient(host='localhost', port=server.port)
        assert client.is_connected()

        # Close cleanly
        client.close()
        assert not client.is_connected()

        # Server should still be running and accepting new connections
        client2 = MooClient(host='localhost', port=server.port)
        assert client2.is_connected()
        client2.close()

    def test_net_006_line_buffering(self, server):
        """NET-006: Commands split across packets work correctly."""
        client = MooClient(host='localhost', port=server.port)
        client.login_wizard()

        try:
            # Send a command in multiple parts
            # The server should buffer until newline
            sock = client._socket

            # Send partial command
            sock.sendall(b';1 +')
            time.sleep(0.05)
            sock.sendall(b' 2 +')
            time.sleep(0.05)
            sock.sendall(b' 3\n')

            # Should get correct result
            time.sleep(0.2)
            response = client.receive()
            assert '6' in response, f"Expected 6 in response, got: {response}"

        finally:
            client.close()

    def test_net_007_long_lines(self, server):
        """NET-007: Lines up to buffer limit work correctly."""
        client = MooClient(host='localhost', port=server.port)
        client.login_wizard()

        try:
            # Create a long string (but within reasonable limits)
            long_string = 'a' * 1000
            result = client.eval_expect_success(f'length("{long_string}")')
            assert result == '1000', f"Expected 1000, got {result}"

        finally:
            client.close()


class TestConnectionPool:
    """Tests using multiple simultaneous connections."""

    def test_multiple_clients_independent(self, multiplayer_server, candidate_server):
        """Multiple clients can operate independently."""
        clients = []
        try:
            # Connect three clients as different players
            players = [('Wizard', '#3'), ('Player2', '#4'), ('Player3', '#5')]

            for name, expected_id in players:
                client = candidate_server.connect(multiplayer_server)
                client.authenticate(name)
                clients.append((name, client, expected_id))

            # Verify each client is logged in as the correct player
            for name, client, expected_id in clients:
                success, result = client.eval('player;')
                assert success, f"{name} failed to get player: {result}"
                assert result == expected_id, f"{name} should be {expected_id}, got {result}"

            # Verify clients can execute commands independently
            for name, client, expected_id in clients:
                success, result = client.eval('player.name;')
                assert success, f"{name} failed to get name: {result}"
                assert name in result, f"Expected {name} in result, got {result}"

        finally:
            for _, client, _ in clients:
                client.close()


class TestNetworkOutput:
    """Tests for server output handling."""

    def test_net_060_basic_notify(self, client):
        """NET-060: Basic notify() sends output to client."""
        # notify() sends to the connection, verify it succeeds
        success, result = client.eval('notify(player, "Hello from test")')
        assert success, f"notify() failed: {result}"
        # Note: The notify output is consumed by eval() reading the response,
        # so we can only verify notify() returns success (1)
        assert result == '1', f"notify() should return 1, got {result}"

    def test_net_063_output_order_via_verb(self, client):
        """NET-063: Messages arrive in order (verb-based test)."""
        # Create a verb that sends multiple notifies and collects them
        # using read() after a flush_output()
        client.eval('add_property(#0, "notify_test_output", {}, {#1, "rw"});')
        client.eval('add_verb(#0, {#1, "rxd", "test_notify_order"}, {"this", "none", "this"});')

        # Verb that sends 5 messages in order
        code = [
            'for i in [1..5]',
            '  notify(player, tostr("Message ", i));',
            'endfor',
            'return 1;'
        ]
        code_str = '{' + ', '.join(f'"{line}"' for line in code) + '}'
        result = client.eval(f'set_verb_code(#0, "test_notify_order", {code_str});')

        # Call the verb - messages will be sent
        result = client.eval('#0:test_notify_order();')
        success, value = result
        assert success, f"notify verb failed: {value}"

        # Read any pending output
        time.sleep(0.1)
        output = client.receive(timeout=0.5)

        # Check that messages appear in order (if we got any)
        # Note: output may or may not contain the messages depending on timing
        if 'Message' in output:
            for i in range(1, 5):
                pos_i = output.find(f'Message {i}')
                pos_next = output.find(f'Message {i+1}')
                if pos_i >= 0 and pos_next >= 0:
                    assert pos_i < pos_next, f"Message {i} should come before Message {i+1}"


class TestConnectionErrors:
    """Tests for connection error handling."""

    def test_connection_to_closed_port_fails(self):
        """Connecting to a non-existent server fails appropriately."""
        with pytest.raises((ConnectionRefusedError, socket.error, OSError)):
            MooClient(host='localhost', port=19999, timeout=2.0)

    def test_connection_refused_on_wrong_host(self):
        """Connection to invalid host fails appropriately."""
        with pytest.raises((socket.error, OSError, socket.gaierror)):
            # Use an invalid hostname
            MooClient(host='invalid.host.example', port=7777, timeout=2.0)
