"""Persistence tests for MOO tasks.

These tests verify that forked/suspended tasks resume correctly after a
write→checkpoint→read cycle. This is particularly important for
upgrade testing where bytecode representation may have changed.

Note: These tests focus on observable behavior (task completes correctly)
rather than implementation details (bytecode matching).
"""

import shutil
import time
import pytest

from lib.protocol import ServerPair
from lib.assertions import assert_moo_success, assert_moo_int


def setup_forked_task(client, verb_name: str, prop_name: str, delay_seconds: int,
                      final_value: int, extra_code: list = None):
    """Helper to set up a forked task that will write to a property.

    Creates:
    - A property to store the result
    - A verb that forks a delayed task
    """
    # Create result property
    client.eval(f'add_property(#0, "{prop_name}", 0, {{#1, "rw"}});')

    # Create the verb that forks
    client.eval(f'add_verb(#0, {{#1, "rxd", "{verb_name}"}}, {{"this", "none", "this"}});')

    # Build verb code - fork a task that runs after delay and writes to property
    code_lines = [f'fork ({delay_seconds})']
    if extra_code:
        code_lines.extend(f'  {line}' for line in extra_code)
    code_lines.append(f'  #0.{prop_name} = {final_value};')
    code_lines.append('endfork')
    code_lines.append('return queued_tasks();')

    code_str = '{' + ', '.join(f'"{line}"' for line in code_lines) + '}'
    result = client.eval(f'set_verb_code(#0, "{verb_name}", {code_str});')
    success, msg = result
    if not success or (msg and 'error' in msg.lower()):
        # set_verb_code returns {} on success, list of errors on failure
        if msg != '{}':
            raise RuntimeError(f"Failed to set verb code for {verb_name}: {msg}")


@pytest.mark.persistence
@pytest.mark.slow
class TestTaskPersistence:
    """Tests for task persistence through checkpoint/upgrade."""

    def test_forked_task_persists(self, server_pair: ServerPair, write_server_db, tmp_path):
        """A forked task persists through checkpoint and completes after restart."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Fork a task, checkpoint before it runs
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Create a forked task that runs in 30 seconds
            setup_forked_task(write_client, 'delayed_task', 'task_result',
                              delay_seconds=30, final_value=42)

            # Start the forked task
            result = write_client.eval('#0:delayed_task();')
            success, queued = result
            assert success, f"Failed to fork task: {queued}"
            assert queued != '{}', "No task was queued"

            # Checkpoint while task is pending
            write_client.checkpoint()
            time.sleep(0.5)

            # Verify task is still queued
            result = write_client.eval('queued_tasks();')
            success, queued = result
            assert success and queued != '{}', "Task should still be queued before restart"

        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Restart and verify task is still queued
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # Check that task persisted
            result = read_client.eval('queued_tasks();')
            success, queued = result
            assert success, f"Failed to get queued_tasks: {queued}"
            assert queued != '{}', f"Forked task did not persist through restart"

            # Property should still be 0 (task hasn't run yet)
            result = read_client.eval('#0.task_result;')
            success, value = result
            assert success and value == '0', f"Task ran too early: {value}"

        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_suspended_task_resumes(self, server_pair: ServerPair, write_server_db, tmp_path):
        """A suspended task resumes and completes after restart."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Create and start a task that suspends
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Create property and verb
            write_client.eval('add_property(#0, "suspend_result", 0, {#1, "rw"});')
            write_client.eval('add_verb(#0, {#1, "rxd", "suspend_task"}, {"this", "none", "this"});')

            # This verb: forks immediately, then suspends for 30s, then writes result
            code = [
                'fork (0)',
                '  suspend(30);',
                '  #0.suspend_result = 999;',
                'endfork',
                'return queued_tasks();'
            ]
            code_str = '{' + ', '.join(f'"{line}"' for line in code) + '}'
            write_client.eval(f'set_verb_code(#0, "suspend_task", {code_str});')

            # Start the task
            result = write_client.eval('#0:suspend_task();')
            success, queued = result
            assert success, f"Failed to start task: {queued}"

            # Wait for it to suspend
            time.sleep(1)

            # Verify it's suspended
            result = write_client.eval('queued_tasks();')
            success, queued = result
            assert success and queued != '{}', "Task should be suspended"

            # Checkpoint
            write_client.checkpoint()
            time.sleep(0.5)

        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Verify task persisted in suspended state
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # Task should still be suspended
            result = read_client.eval('queued_tasks();')
            success, queued = result
            assert success and queued != '{}', "Suspended task should persist through restart"

            # Result should still be 0 (task hasn't completed)
            result = read_client.eval('#0.suspend_result;')
            success, value = result
            assert success and value == '0', f"Suspended task completed too early: {value}"

        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_multiple_tasks_persist(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Multiple forked tasks all persist and remain queued after restart."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Create multiple forked tasks
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Create three tasks with different delays
            setup_forked_task(write_client, 'task1', 'result1', 60, 111)
            setup_forked_task(write_client, 'task2', 'result2', 90, 222)
            setup_forked_task(write_client, 'task3', 'result3', 120, 333)

            # Start all tasks
            write_client.eval('#0:task1();')
            write_client.eval('#0:task2();')
            write_client.eval('#0:task3();')

            # Count queued tasks
            result = write_client.eval('length(queued_tasks());')
            success, count = result
            assert success and int(count) == 3, f"Should have 3 queued tasks, got {count}"

            # Checkpoint
            write_client.checkpoint()
            time.sleep(0.5)

        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: All tasks should persist
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # All three tasks should still be queued
            result = read_client.eval('length(queued_tasks());')
            success, count = result
            assert success and int(count) == 3, f"All 3 tasks should persist, got {count}"

            # All results should still be 0
            for prop in ['result1', 'result2', 'result3']:
                result = read_client.eval(f'#0.{prop};')
                success, value = result
                assert success and value == '0', f"{prop} should be 0, got {value}"

        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_task_with_locals_persists(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Task with local variables persists correctly."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Create task that sets locals then suspends
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_property(#0, "locals_result", 0, {#1, "rw"});')
            write_client.eval('add_verb(#0, {#1, "rxd", "locals_task"}, {"this", "none", "this"});')

            # Verb sets local variables, suspends, then uses them
            code = [
                'fork (0)',
                '  x = 100;',
                '  y = 200;',
                '  suspend(60);',
                '  #0.locals_result = x + y;',
                'endfork',
                'return 1;'
            ]
            code_str = '{' + ', '.join(f'"{line}"' for line in code) + '}'
            write_client.eval(f'set_verb_code(#0, "locals_task", {code_str});')

            write_client.eval('#0:locals_task();')
            time.sleep(1)  # Let it suspend

            write_client.checkpoint()
            time.sleep(0.5)

        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Task should persist with its locals
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # Task should still be queued
            result = read_client.eval('queued_tasks();')
            success, queued = result
            assert success and queued != '{}', "Task with locals should persist"

            # Result should still be 0 (task suspended)
            result = read_client.eval('#0.locals_result;')
            success, value = result
            assert success and value == '0', f"Task ran too early: {value}"

        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)
