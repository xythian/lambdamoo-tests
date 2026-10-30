"""Tasks suspended inside a builtin's verb call survive a restart (PERSIST-BI-001 onward).

create(), move(), recycle() and call_function() call MOO verbs part way
through their work. When the task suspends inside one of those verbs, the
database has to record where the builtin was, so that after a restart the
builtin can finish once the verb returns. Each test suspends a task inside
such a verb, restarts the server from the checkpoint, resumes the task and
checks the builtin finished its job.
"""

import re
import shutil
import time

import pytest

from lib.assertions import assert_moo_success
from lib.moocode import define_verb, moo_string


def wait_for(client, expr, expected, timeout=5.0):
    """Poll a MOO expression until it evaluates to expected; return the last value."""
    deadline = time.monotonic() + timeout
    while True:
        value = assert_moo_success(client.eval(expr))
        if value == expected or time.monotonic() > deadline:
            return value
        time.sleep(0.05)


def suspend_then_restart(server_pair, write_server_db, tmp_path, setup):
    """Run setup on a fresh server, restart from its database, and return (instance, client).

    setup(client) must leave exactly one suspended task behind.
    """
    db_path = tmp_path / "test.db"
    shutil.copy(write_server_db, db_path)
    instance = server_pair.write_server.start(database=db_path)
    client = server_pair.write_server.connect(instance)
    client.authenticate("Wizard")
    try:
        setup(client)
        assert wait_for(client, "length(queued_tasks())", "1") == "1"
    finally:
        client.close()
        output_db = server_pair.write_server.stop(instance)

    instance = server_pair.read_server.start(database=output_db)
    client = server_pair.read_server.connect(instance)
    client.authenticate("Wizard")
    return instance, client


def resume_only_task(client):
    """Resume the single suspended task and wait for it to finish."""
    tid = assert_moo_success(client.eval("queued_tasks()[1][1]"))
    assert assert_moo_success(client.eval(f"resume({tid})")) == "0"
    assert wait_for(client, "length(queued_tasks())", "0") == "0"


def fork_in_eval(client, body):
    """Fork a background task running body (MOO statements)."""
    result = assert_moo_success(client.eval(f"eval({moo_string(f'fork (0) {body} endfork return 1;')})"))
    assert result == "{1, 1}", result


@pytest.mark.persistence
class TestSuspendedInsideBuiltin:
    """create, move, recycle and call_function resume after a restart."""

    def test_persist_bi_001_create_initialize(self, server_pair, write_server_db, tmp_path):
        """PERSIST-BI-001: create() finishes and returns the new object when :initialize resumes."""
        def setup(client):
            parent = assert_moo_success(client.eval("create(#1)"))
            assert_moo_success(client.eval('add_property(#0, "made", 0, {#3, "rw"})'))
            define_verb(client, parent, "initialize", ["suspend();", 'this.name = "initialized";'])
            fork_in_eval(client, f"#0.made = create({parent});")

        instance, client = suspend_then_restart(server_pair, write_server_db, tmp_path, setup)
        try:
            resume_only_task(client)
            made = assert_moo_success(client.eval("#0.made"))
            assert re.fullmatch(r"#\d+", made)
            assert assert_moo_success(client.eval(f"{made}.name")) == '"initialized"'
        finally:
            client.close()
            server_pair.read_server.stop(instance)

    def test_persist_bi_002_move_accept(self, server_pair, write_server_db, tmp_path):
        """PERSIST-BI-002: move() finishes the move when :accept resumes and returns true."""
        def setup(client):
            dest = assert_moo_success(client.eval("create(#1)"))
            thing = assert_moo_success(client.eval("create(#1)"))
            assert_moo_success(client.eval(f'add_property(#0, "pair", {{{dest}, {thing}}}, {{#3, "rw"}})'))
            define_verb(client, dest, "accept", ["suspend();", "return 1;"])
            fork_in_eval(client, f"move({thing}, {dest});")

        instance, client = suspend_then_restart(server_pair, write_server_db, tmp_path, setup)
        try:
            resume_only_task(client)
            assert assert_moo_success(client.eval("#0.pair[2].location == #0.pair[1]")) == "1"
        finally:
            client.close()
            server_pair.read_server.stop(instance)

    def test_persist_bi_003_move_enterfunc(self, server_pair, write_server_db, tmp_path):
        """PERSIST-BI-003: A task suspended in :enterfunc completes the move after a restart."""
        def setup(client):
            dest = assert_moo_success(client.eval("create(#1)"))
            thing = assert_moo_success(client.eval("create(#1)"))
            assert_moo_success(client.eval('add_property(#0, "done", 0, {#3, "rw"})'))
            define_verb(client, dest, "enterfunc", ["suspend();", "#0.done = args[1];"])
            fork_in_eval(client, f"move({thing}, {dest}); #0.done = {{#0.done}};")

        instance, client = suspend_then_restart(server_pair, write_server_db, tmp_path, setup)
        try:
            resume_only_task(client)
            assert re.fullmatch(r"\{#\d+\}", assert_moo_success(client.eval("#0.done")))
        finally:
            client.close()
            server_pair.read_server.stop(instance)

    def test_persist_bi_004_recycle(self, server_pair, write_server_db, tmp_path):
        """PERSIST-BI-004: recycle() destroys the object once its :recycle verb resumes."""
        def setup(client):
            obj = assert_moo_success(client.eval("create(#1)"))
            assert_moo_success(client.eval(f'add_property(#0, "victim", {obj}, {{#3, "rw"}})'))
            define_verb(client, obj, "recycle", ["suspend();"])
            fork_in_eval(client, f"recycle({obj});")

        instance, client = suspend_then_restart(server_pair, write_server_db, tmp_path, setup)
        try:
            assert assert_moo_success(client.eval("valid(#0.victim)")) == "1"
            resume_only_task(client)
            assert assert_moo_success(client.eval("valid(#0.victim)")) == "0"
        finally:
            client.close()
            server_pair.read_server.stop(instance)

    def test_persist_bi_005_call_function(self, server_pair, write_server_db, tmp_path):
        """PERSIST-BI-005: call_function() returns the inner builtin's result after a restart."""
        def setup(client):
            assert_moo_success(client.eval('add_property(#0, "cf", 0, {#3, "rw"})'))
            fork_in_eval(client, '#0.cf = call_function("eval", "suspend(); return 42;");')

        instance, client = suspend_then_restart(server_pair, write_server_db, tmp_path, setup)
        try:
            resume_only_task(client)
            assert assert_moo_success(client.eval("#0.cf")) == "{1, 42}"
        finally:
            client.close()
            server_pair.read_server.stop(instance)
