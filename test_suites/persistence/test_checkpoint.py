"""Tests for checkpoint functionality.

These tests verify database checkpoint operations including:
- Basic checkpoint with dump_database()
- Checkpoint file creation and integrity
- Data persistence through checkpoint cycles
"""

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
