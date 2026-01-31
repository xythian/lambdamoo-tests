"""Tests for emergency wizard mode (-e flag).

Emergency mode allows administrators to run MOO commands without a network
listener, reading commands from stdin and writing output to stdout. This is
useful for database maintenance, scripted operations, and recovery scenarios.
"""

import shutil
import socket
import pytest

from lib.assertions import assert_moo_success


class TestEmergencyWizardMode:
    """Tests for emergency wizard mode functionality."""

    def test_emergency_mode_starts(self, candidate_server, minimal_db, tmp_path):
        """Server starts in emergency mode with -e flag."""
        db_path = tmp_path / "test.db"
        shutil.copy(minimal_db, db_path)

        instance = candidate_server.start(database=db_path, emergency_mode=True)
        try:
            assert instance.process.poll() is None, "Server should be running"
            assert instance.port == 0, "Emergency mode should have no port"
        finally:
            instance.process.terminate()
            instance.process.wait()

    def test_emergency_mode_accepts_commands(self, candidate_server, minimal_db, tmp_path):
        """Commands sent via stdin are executed and produce output."""
        db_path = tmp_path / "test.db"
        shutil.copy(minimal_db, db_path)

        commands = ";1 + 2\n"
        output, _ = candidate_server.run_emergency(db_path, commands, work_dir=tmp_path)

        assert "3" in output, f"Expected '3' in output, got: {output}"

    def test_emergency_mode_saves_database(self, candidate_server, minimal_db, tmp_path):
        """Changes made in emergency mode persist to output database."""
        db_path = tmp_path / "test.db"
        shutil.copy(minimal_db, db_path)

        # Create a property in emergency mode
        commands = ';add_property(#0, "emergency_test", 12345, {#1, "rw"})\n'
        output, output_db = candidate_server.run_emergency(db_path, commands, work_dir=tmp_path)

        assert output_db.exists(), "Output database should exist"

        # Start a normal server with the output database and verify the property exists
        instance = candidate_server.start(database=output_db)
        try:
            client = candidate_server.connect(instance)
            client.authenticate('Wizard')
            try:
                result = client.eval('#0.emergency_test')
                success, value = result
                assert success, f"Property should exist: {value}"
                assert value == "12345", f"Property value should be 12345, got: {value}"
            finally:
                client.close()
        finally:
            candidate_server.stop(instance)

    def test_emergency_mode_no_network(self, candidate_server, minimal_db, tmp_path):
        """Emergency mode doesn't listen on network."""
        db_path = tmp_path / "test.db"
        shutil.copy(minimal_db, db_path)

        instance = candidate_server.start(database=db_path, emergency_mode=True)
        try:
            # Port should be 0 (no listener)
            assert instance.port == 0

            # Try to connect to common ports - should fail
            for port in [7777, 8888, 9999]:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                try:
                    result = sock.connect_ex(('localhost', port))
                    # Connection should fail (result != 0) or we connected to
                    # something else (not our server)
                except socket.error:
                    pass
                finally:
                    sock.close()
        finally:
            instance.process.terminate()
            instance.process.wait()

    def test_emergency_mode_wizard_privileges(self, candidate_server, minimal_db, tmp_path):
        """Emergency mode has full wizard privileges."""
        db_path = tmp_path / "test.db"
        shutil.copy(minimal_db, db_path)

        # Try wizard-only operations
        commands = """;create(#1)
;add_verb(#0, {#1, "rxd", "emergency_test"}, {"this", "none", "this"})
;set_verb_code(#0, "emergency_test", {"return 999;"})
"""
        output, output_db = candidate_server.run_emergency(db_path, commands, work_dir=tmp_path)

        # Verify the verb was created
        instance = candidate_server.start(database=output_db)
        try:
            client = candidate_server.connect(instance)
            client.authenticate('Wizard')
            try:
                result = client.eval('#0:emergency_test()')
                success, value = result
                assert success, f"Verb should work: {value}"
                assert value == "999", f"Verb should return 999, got: {value}"
            finally:
                client.close()
        finally:
            candidate_server.stop(instance)

    def test_emergency_mode_multiple_commands(self, candidate_server, minimal_db, tmp_path):
        """Multiple commands can be executed in sequence."""
        db_path = tmp_path / "test.db"
        shutil.copy(minimal_db, db_path)

        commands = """;1 + 1
;2 + 2
;3 + 3
"""
        output, _ = candidate_server.run_emergency(db_path, commands, work_dir=tmp_path)

        assert "2" in output, "First result should be 2"
        assert "4" in output, "Second result should be 4"
        assert "6" in output, "Third result should be 6"

    def test_emergency_mode_error_handling(self, candidate_server, minimal_db, tmp_path):
        """Errors in emergency mode are reported but don't crash the server."""
        db_path = tmp_path / "test.db"
        shutil.copy(minimal_db, db_path)

        # Mix valid and invalid commands
        commands = """;1 + 1
;invalid_builtin()
;2 + 2
"""
        output, output_db = candidate_server.run_emergency(db_path, commands, work_dir=tmp_path)

        # Should have results from valid commands
        assert "2" in output, "First valid command should produce result"
        assert "4" in output, "Last valid command should produce result"
        # Database should still be written
        assert output_db.exists(), "Database should be written even with errors"

    def test_emergency_mode_reads_existing_data(self, candidate_server, minimal_db, tmp_path):
        """Emergency mode can read existing database content."""
        db_path = tmp_path / "test.db"
        shutil.copy(minimal_db, db_path)

        # Query existing objects
        commands = """;valid(#0)
;valid(#1)
;typeof(#0)
"""
        output, _ = candidate_server.run_emergency(db_path, commands, work_dir=tmp_path)

        # #0 and #1 should be valid
        assert "1" in output, "Objects should be valid"
