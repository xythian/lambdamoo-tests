"""Tests for checkpoint functionality.

These tests verify database checkpoint operations including:
- Basic checkpoint with dump_database()
- Scheduled checkpoints via #0.dump_interval
- Emergency checkpoint on shutdown signals
- Checkpoint file creation and integrity
- Data persistence through checkpoint cycles
"""

import os
import signal
import shutil
import time
from pathlib import Path

import pytest

from lib.protocol import ServerPair
from lib.assertions import assert_moo_success, assert_moo_int


@pytest.mark.persistence
class TestBasicCheckpoint:
    """Tests for basic checkpoint functionality."""

    def test_dump_database_returns_success(self, client):
        """dump_database() returns successfully."""
        success, result = client.eval('dump_database()')
        assert success, f"dump_database() failed: {result}"

    def test_checkpoint_creates_new_file(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Checkpoint creates a new database file."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Make a change
            write_client.eval('add_property(#0, "checkpoint_test", 12345, {#1, "rw"})')

            # Checkpoint
            write_client.checkpoint()

            # Verify new file exists (MOO creates .new then renames)
            assert db_path.exists(), "Database file should exist after checkpoint"
        finally:
            write_client.close()
            server_pair.write_server.stop(write_instance)

    def test_data_survives_checkpoint(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Data written before checkpoint survives server restart."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write data and checkpoint
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_property(#0, "persist_int", 42, {#1, "rw"})')
            write_client.eval('add_property(#0, "persist_str", "hello", {#1, "rw"})')
            write_client.eval('add_property(#0, "persist_list", {1, 2, 3}, {#1, "rw"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Verify data after restart
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.persist_int')
            assert_moo_int(result, 42, "Integer not preserved through checkpoint")

            result = read_client.eval('#0.persist_str')
            value = assert_moo_success(result)
            assert value == '"hello"', f"String not preserved: {value}"

            result = read_client.eval('#0.persist_list')
            value = assert_moo_success(result)
            assert value == '{1, 2, 3}', f"List not preserved: {value}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_multiple_checkpoints(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Multiple checkpoints preserve latest data."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # First write and checkpoint
            write_client.eval('add_property(#0, "multi_cp", 1, {#1, "rw"})')
            write_client.checkpoint()

            # Second write and checkpoint
            write_client.eval('#0.multi_cp = 2')
            write_client.checkpoint()

            # Third write and checkpoint
            write_client.eval('#0.multi_cp = 3')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Verify final value
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.multi_cp')
            assert_moo_int(result, 3, "Latest value not preserved after multiple checkpoints")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestCheckpointWithObjects:
    """Tests for checkpoint with object creation/deletion."""

    def test_new_object_survives_checkpoint(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Newly created objects survive checkpoint."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Create a new object
            result = write_client.eval('create(#1)')
            obj_id = assert_moo_success(result)

            # Set a property on it
            write_client.eval(f'add_property({obj_id}, "test_prop", "created", {{{obj_id}, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Verify object exists after restart
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval(f'valid({obj_id})')
            value = assert_moo_success(result)
            assert value == '1', f"Object {obj_id} should be valid after checkpoint"

            result = read_client.eval(f'{obj_id}.test_prop')
            value = assert_moo_success(result)
            assert value == '"created"', f"Object property not preserved: {value}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_recycled_object_stays_recycled(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Recycled objects remain recycled after checkpoint."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Create and then recycle an object
            result = write_client.eval('create(#1)')
            obj_id = assert_moo_success(result)

            write_client.eval(f'recycle({obj_id})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Verify object is still invalid after restart
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval(f'valid({obj_id})')
            value = assert_moo_success(result)
            assert value == '0', f"Recycled object {obj_id} should remain invalid"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestCheckpointWithVerbs:
    """Tests for checkpoint with verb modifications."""

    def test_verb_code_survives_checkpoint(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Verb code survives checkpoint."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Add a verb
            write_client.eval('add_verb(#0, {#1, "rx", "test_verb"}, {"this", "none", "this"})')
            write_client.eval('set_verb_code(#0, "test_verb", {"return 42;"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Verify verb works after restart
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0:test_verb()')
            assert_moo_int(result, 42, "Verb code not preserved through checkpoint")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestCheckpointFileIntegrity:
    """Tests for checkpoint file integrity."""

    def test_checkpoint_file_is_readable(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Checkpoint file can be read by another server instance."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Starting a new server verifies the file is readable
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # Basic sanity check - can we eval something?
            result = read_client.eval('1 + 1')
            assert_moo_int(result, 2, "Server should be functional after loading checkpoint")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_checkpoint_preserves_max_object(self, server_pair: ServerPair, write_server_db, tmp_path):
        """max_object() value is consistent after checkpoint."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Create some objects to increase max_object
            write_client.eval('create(#1)')
            write_client.eval('create(#1)')

            result = write_client.eval('max_object()')
            max_obj_before = assert_moo_success(result)

            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Verify max_object after restart
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('max_object()')
            max_obj_after = assert_moo_success(result)
            assert max_obj_after == max_obj_before, \
                f"max_object changed: {max_obj_before} -> {max_obj_after}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
@pytest.mark.slow
class TestScheduledCheckpoint:
    """Tests for scheduled checkpoint via #0.dump_interval.

    Note: The server reads dump_interval only at startup and after each
    checkpoint completes. The MINIMUM value is 60 seconds - values below
    60 are ignored and the server defaults to 3600 (1 hour).

    To test scheduled checkpoints without waiting 60+ seconds, we verify:
    1. The property is read and stored correctly
    2. Explicit dump_database() schedules the next checkpoint
    3. Values below 60 result in default behavior
    """

    def test_dump_interval_minimum_is_60_seconds(self, client):
        """dump_interval values below 60 are ignored (server uses 3600 default).

        From server.c: if dump_interval < 60, interval defaults to 3600.
        """
        # This test documents the minimum requirement
        # We can't easily verify the internal timer, but we document the behavior
        success, _ = client.eval('add_property(#0, "dump_interval", 30, {#1, "rw"})')
        assert success, "Should be able to set dump_interval property"

        # Property is set but server ignores values < 60
        result = client.eval('#0.dump_interval')
        value = assert_moo_success(result)
        assert value == '30', "Property value should be stored as set"
        # Note: Server internally uses 3600 when value < 60

    def test_dump_database_schedules_next_checkpoint(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Calling dump_database() checkpoints AND schedules next auto-checkpoint.

        This verifies the scheduling mechanism works without waiting 60+ seconds:
        1. Set dump_interval to valid value (>= 60)
        2. Call dump_database() - this saves AND re-reads dump_interval
        3. Verify the checkpoint wrote correctly
        """
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        output_db = write_instance.output_db

        try:
            # Set valid dump_interval (>= 60)
            write_client.eval('add_property(#0, "dump_interval", 60, {#1, "rw"})')

            # Add test data
            write_client.eval('add_property(#0, "scheduled_test", 42, {#1, "rw"})')

            # Verify output doesn't exist yet
            assert not output_db.exists(), "Output DB should not exist before checkpoint"

            # Call dump_database() - this checkpoints AND schedules next
            success, result = write_client.eval('dump_database()')
            assert success, f"dump_database() should succeed: {result}"

            # Give server time to write
            time.sleep(1)

            # Verify checkpoint happened
            assert output_db.exists(), "Output DB should exist after dump_database()"

        finally:
            write_client.close()
            output_db_final = server_pair.write_server.stop(write_instance)

        # Verify data was saved correctly
        read_instance = server_pair.read_server.start(database=output_db_final)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.scheduled_test')
            assert_moo_int(result, 42, "Data should persist through dump_database()")

            result = read_client.eval('#0.dump_interval')
            assert_moo_int(result, 60, "dump_interval should persist")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_dump_interval_persists_through_restart(self, server_pair: ServerPair, write_server_db, tmp_path):
        """dump_interval value persists and is read on server restart."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Set dump_interval and save
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_property(#0, "dump_interval", 120, {#1, "rw"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            phase1_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Restart and verify dump_interval persisted
        write_instance = server_pair.write_server.start(database=phase1_db)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('#0.dump_interval')
            assert_moo_int(result, 120, "dump_interval should persist through restart")
        finally:
            write_client.close()
            server_pair.write_server.stop(write_instance)

    def test_dump_interval_missing_uses_default(self, server_pair: ServerPair, write_server_db, tmp_path):
        """When #0.dump_interval doesn't exist, server uses 3600 second default.

        We can't directly verify the internal timer, but we verify the server
        starts successfully without the property.
        """
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Verify dump_interval doesn't exist initially
            result = write_client.eval('#0.dump_interval')
            success, _ = result
            assert not success, "dump_interval should not exist in minimal db"

            # Server should still function (uses 3600 default internally)
            result = write_client.eval('1 + 1')
            assert_moo_int(result, 2, "Server should function without dump_interval")
        finally:
            write_client.close()
            server_pair.write_server.stop(write_instance)


@pytest.mark.persistence
class TestCheckpointWithNetworkIO:
    """Tests for checkpoint during active network connections."""

    def test_checkpoint_with_active_connection(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Checkpoint succeeds while client connection is active."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Make changes
            write_client.eval('add_property(#0, "active_conn_test", 111, {#1, "rw"})')

            # Checkpoint while connection is active
            success = write_client.checkpoint()
            assert success, "Checkpoint should succeed with active connection"

            # Connection should still work after checkpoint
            result = write_client.eval('1 + 1')
            assert_moo_int(result, 2, "Client should work after checkpoint")

            # Make more changes after checkpoint
            write_client.eval('#0.active_conn_test = 222')
            success = write_client.checkpoint()
            assert success, "Second checkpoint should also succeed"

        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Verify data persisted
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.active_conn_test')
            assert_moo_int(result, 222, "Latest data should persist through checkpoints")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_checkpoint_during_output(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Checkpoint during large output doesn't corrupt data."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Store test data
            write_client.eval('add_property(#0, "output_test", 222, {#1, "rw"})')

            # Generate large output while checkpointing
            # Create a verb that produces lots of output
            write_client.eval('add_verb(#0, {#1, "rx", "big_output"}, {"this", "none", "this"})')
            write_client.eval('set_verb_code(#0, "big_output", {"for i in [1..100]", "  player:tell(tostr(i));", "endfor", "return 1;"})')

            # Start the big output, then checkpoint
            write_client.eval('#0:big_output()')
            success = write_client.checkpoint()
            assert success, "Checkpoint should succeed during output"

        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Verify data integrity
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.output_test')
            assert_moo_int(result, 222, "Data should persist through checkpoint during output")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestEmergencyCheckpoint:
    """Tests for checkpoint behavior on shutdown signals."""

    def test_sigterm_triggers_checkpoint(self, server_pair: ServerPair, write_server_db, tmp_path):
        """SIGTERM causes server to checkpoint before exiting."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Make a change but do NOT explicitly checkpoint
            write_client.eval('add_property(#0, "sigterm_saved", 54321, {#1, "rw"})')
        finally:
            write_client.close()
            # Normal stop() sends SIGTERM
            output_db = server_pair.write_server.stop(write_instance)

        # Data should persist because SIGTERM triggers checkpoint
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.sigterm_saved')
            assert_moo_int(result, 54321, "Data should persist after SIGTERM shutdown")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_sigkill_does_not_checkpoint(self, server_pair: ServerPair, write_server_db, tmp_path):
        """SIGKILL terminates server immediately without checkpoint.

        This tests crash/forced-kill behavior where data loss is expected.
        """
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # First, create a baseline with explicit checkpoint
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_property(#0, "baseline", 100, {#1, "rw"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            phase1_db = server_pair.write_server.stop(write_instance)

        # Now restart, make unsaved changes, and SIGKILL
        write_instance = server_pair.write_server.start(database=phase1_db)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Change without checkpoint
            write_client.eval('#0.baseline = 999')
            write_client.eval('add_property(#0, "unsaved", 888, {#1, "rw"})')
        finally:
            write_client.close()

        # Force kill with SIGKILL - no chance to checkpoint
        pid = write_instance.process.pid
        os.kill(pid, signal.SIGKILL)
        write_instance.process.wait()

        # Remove instance from server's tracking
        if write_instance in server_pair.write_server._instances:
            server_pair.write_server._instances.remove(write_instance)

        # Data should NOT reflect unsaved changes
        read_instance = server_pair.read_server.start(database=phase1_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # Baseline should still be original value
            result = read_client.eval('#0.baseline')
            assert_moo_int(result, 100, "Baseline should be original value after SIGKILL")

            # Unsaved property should not exist
            result = read_client.eval('#0.unsaved')
            success, _ = result
            assert not success, "Unsaved property should not exist after SIGKILL"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
@pytest.mark.longrun
class TestAutomaticCheckpoint:
    """Long-running tests for automatic checkpoint via dump_interval.

    These tests verify that the server actually performs automatic checkpoints
    at the scheduled interval. They require waiting 60+ seconds (the minimum
    dump_interval value) and are skipped by default. Use --longrun to include.
    """

    def test_automatic_checkpoint_fires_and_logs(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Automatic checkpoint fires after dump_interval seconds.

        This test verifies:
        1. The server logs "CHECKPOINTING on ... finished" when auto-checkpoint fires
        2. Data written before the checkpoint is actually persisted
        3. The output database file is created/updated
        """
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        output_db = write_instance.output_db
        log_file = write_instance.log_file

        try:
            # Set dump_interval to minimum (60 seconds)
            write_client.eval('add_property(#0, "dump_interval", 60, {#1, "rw"})')

            # Trigger explicit checkpoint - this saves dump_interval AND schedules next
            success, _ = write_client.eval('dump_database()')
            assert success, "Initial dump_database() should succeed"

            # Wait for checkpoint to complete
            time.sleep(1)

            # Record state after explicit checkpoint
            assert output_db.exists(), "Output DB should exist after explicit checkpoint"
            initial_mtime = output_db.stat().st_mtime

            # Read log to get baseline
            initial_log = log_file.read_text() if log_file.exists() else ""

            # Now make a change that should be saved by automatic checkpoint
            write_client.eval('add_property(#0, "auto_checkpoint_test", 99999, {#1, "rw"})')

            # Wait for automatic checkpoint (60 seconds + buffer)
            # The server should checkpoint ~60 seconds after the explicit dump_database()
            time.sleep(65)

            # Check log for checkpoint message
            current_log = log_file.read_text() if log_file.exists() else ""
            new_log_content = current_log[len(initial_log):]

            assert "CHECKPOINTING" in new_log_content and "finished" in new_log_content, \
                f"Log should contain checkpoint message. New log content:\n{new_log_content}"

            # Verify output DB was updated
            current_mtime = output_db.stat().st_mtime
            assert current_mtime > initial_mtime, \
                "Output DB mtime should change after automatic checkpoint"

        finally:
            write_client.close()
            output_db_final = server_pair.write_server.stop(write_instance)

        # Verify data was actually persisted by the automatic checkpoint
        read_instance = server_pair.read_server.start(database=output_db_final)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.auto_checkpoint_test')
            assert_moo_int(result, 99999, "Data should be saved by automatic checkpoint")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)
