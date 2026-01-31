import pytest
import time
from lib.assertions import assert_moo_success, assert_moo_int
from lib.client import MooClient

class TestNetworkConnections:
    """Tests for Network - Connections TODO items."""

    def test_connection_name(self, client):
        """Test connection_name() returns a string identifier."""
        # connection_name(player) should return a string
        result = client.eval_expect_success('connection_name(player)')
        assert isinstance(result, str)
        assert len(result) > 0
        # It typically looks like "port <number> from <ip>" or similar, but structure varies.
        # Just checking it returns a non-empty string is a good start.

    def test_connection_name_not_connected(self, client):
        """Test connection_name() on a non-connected object."""
        # #0 is the System Object, typically not connected
        success, result = client.eval('connection_name(#0)')
        assert not success
        # Should error because #0 is not connected

    def test_connection_options(self, multiplayer_server, candidate_server):
        """Test getting and setting connection options."""
        # We use a separate victim connection because setting "binary" on the
        # control connection might break the command parser/protocol.

        # Connect Admin (Wizard)
        admin = candidate_server.connect(multiplayer_server)
        admin.authenticate('Wizard')

        # Connect Victim (Player2, #4)
        victim = candidate_server.connect(multiplayer_server)
        victim.authenticate('Player2')

        try:
            # Set 'binary' to 0 (ensure default) on #4
            admin.eval('set_connection_option(#4, "binary", 0)')
            result = admin.eval_expect_success('connection_option(#4, "binary")')
            assert result == '0'

            # Set 'binary' to 1 on #4
            admin.eval('set_connection_option(#4, "binary", 1)')
            result = admin.eval_expect_success('connection_option(#4, "binary")')
            assert result == '1'

            # Clean up - set back to 0
            admin.eval('set_connection_option(#4, "binary", 0)')
            result = admin.eval_expect_success('connection_option(#4, "binary")')
            assert result == '0'

        finally:
            admin.close()
            victim.close()

    def test_connection_option_invalid(self, client):
        """Test connection_option() with invalid option."""
        success, result = client.eval('connection_option(player, "this-option-does-not-exist")')
        # Should fail with E_INVARG
        assert not success

    def test_connected_stats(self, client):
        """Test connected_players(), connected_seconds(), idle_seconds()."""
        # Get current player object
        player = client.eval_expect_success('player')

        # connected_players() should include the current player
        result = client.eval_expect_success('connected_players()')
        assert player in result

        # We can check if it returns a list containing at least one item
        assert result.startswith('{') and result.endswith('}')

        # connected_seconds() should be a positive integer
        result = client.eval_expect_success('connected_seconds(player)')
        assert result.isdigit()
        conn_secs = int(result)
        assert conn_secs >= 0

        # Wait a bit and check if connected_seconds increases
        time.sleep(2)
        result_later = client.eval_expect_success('connected_seconds(player)')
        assert int(result_later) >= conn_secs + 1

        # idle_seconds() should be a positive integer
        result = client.eval_expect_success('idle_seconds(player)')
        assert result.isdigit()
        assert int(result) >= 0

    def test_notify_self_receive(self, client):
        """Test notifying self and receiving output."""
        # We use send() directly to avoid eval() consuming the output
        client.send(';notify(player, "Hello Self");')
        time.sleep(0.1)
        output = client.receive()
        assert "Hello Self" in output

    def test_notify_other_player(self, multiplayer_server, candidate_server):
        """Test notifying another connected player."""
        # Connect two players
        client1 = candidate_server.connect(multiplayer_server)
        client1.authenticate('Wizard')

        client2 = candidate_server.connect(multiplayer_server)
        client2.authenticate('Player2') # #4 is Player2 in multiplayer_db

        try:
            # Client 1 notifies Client 2
            client1.eval('notify(#4, "Hello Player2")')

            # Client 2 should receive the message
            time.sleep(0.1)
            output = client2.receive()
            assert "Hello Player2" in output

        finally:
            client1.close()
            client2.close()

    def test_read(self, client):
        """Test read() function."""
        # Create a verb that reads input
        client.eval('add_verb(#0, {#1, "xd", "do_read"}, {"this", "none", "this"})')
        client.eval('set_verb_code(#0, "do_read", {"return read();"})')

        # Send command to call the verb
        # This will suspend waiting for input
        client.send(';return #0:do_read()')

        # Wait a bit to ensure server is ready to read
        time.sleep(0.2)

        # Send input
        input_str = "This is the input"
        client.send(input_str)

        # Now we should receive the result of the eval
        response = client.receive(timeout=2.0)
        assert f'=> "{input_str}"' in response

    def test_force_input(self, client):
        """Test force_input() function."""
        # Inject a command into the connection
        # The command ';notify(player, "Forced Output")' will be processed as if typed
        success, result = client.eval('force_input(player, ";notify(player, \\"Forced Output\\")")')
        assert success

        # We should receive the output from the forced command
        # It might take a moment to be processed
        output = client.receive(timeout=2.0)
        assert "Forced Output" in output

    def test_boot_player(self, multiplayer_server, candidate_server):
        """Test boot_player() function."""
        # Connect Wizard (admin) who will do the booting
        admin_client = candidate_server.connect(multiplayer_server)
        admin_client.authenticate('Wizard')

        # Connect another player to be booted
        victim_client = candidate_server.connect(multiplayer_server)
        victim_client.authenticate('Player2') # #4

        try:
            assert victim_client.is_connected()

            # Verify victim is in connected_players
            players = admin_client.eval_expect_success('connected_players()')
            assert '#4' in players

            # Boot the victim
            success, result = admin_client.eval('boot_player(#4)')
            assert success

            # Wait for disconnect
            time.sleep(0.5)

            # Verify victim is NOT in connected_players anymore
            players = admin_client.eval_expect_success('connected_players()')
            assert '#4' not in players

        finally:
            admin_client.close()
            victim_client.close()

    def test_open_network_connection(self, client):
        """Test open_network_connection() functionality."""
        # Check if function exists
        success, _ = client.eval('function_info("open_network_connection")')
        if not success:
            pytest.skip("open_network_connection builtin not available")

        # Start a simple listener
        import socket
        import threading

        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Bind to localhost
        server_sock.bind(('127.0.0.1', 0))
        listener_port = server_sock.getsockname()[1]
        server_sock.listen(1)

        received_connection = [False]

        def listener_thread():
            try:
                server_sock.settimeout(2.0)
                conn, addr = server_sock.accept()
                received_connection[0] = True
                conn.close()
            except socket.timeout:
                pass
            except Exception:
                pass
            finally:
                server_sock.close()

        t = threading.Thread(target=listener_thread)
        t.start()

        try:
            # Try to connect
            # Note: 127.0.0.1 is safer than localhost which might resolve to IPv6
            success, result = client.eval(f'open_network_connection("127.0.0.1", {listener_port})')

            if success:
                # Wait for connection to be established
                time.sleep(0.5)
                assert received_connection[0], "Target did not receive connection"
            else:
                # Accept failure if it's strictly permission related
                # E_PERM means wizard only (we are wizard) or outbound disabled
                if "E_PERM" in result:
                    pytest.skip("open_network_connection disabled (E_PERM)")
                else:
                    pytest.fail(f"open_network_connection failed: {result}")
        finally:
            t.join(timeout=3.0)
