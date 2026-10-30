"""Task builtins (TASK-001 onward).

Covers raise, call_function, task_id, seconds_left, ticks_left, suspend,
resume, kill_task, queued_tasks, queue_info, task_stack, callers,
caller_perms, set_task_perms and pass, including the permission checks a
non-wizard programmer is subject to.

Background tasks are created with fork from inside eval(), so the command
that creates them returns at once with the task id.
"""

import re
import time

import pytest

from lib.assertions import (
    assert_moo_int,
    assert_moo_raises,
    assert_moo_string,
    assert_moo_success,
)
from lib.moocode import define_verb, moo_string


def fork_task(client, body, delay=0):
    """Fork a task running body (MOO statements) after delay seconds; return its id."""
    result = assert_moo_success(client.eval(
        f"eval({moo_string(f'fork t ({delay}) {body} endfork return t;')})"))
    match = re.fullmatch(r"\{1, (\d+)\}", result)
    assert match, f"fork failed: {result}"
    return int(match.group(1))


def wait_for(client, expr, expected, timeout=5.0):
    """Poll a MOO expression until it evaluates to expected; return the last value."""
    deadline = time.monotonic() + timeout
    while True:
        value = assert_moo_success(client.eval(expr))
        if value == expected or time.monotonic() > deadline:
            return value
        time.sleep(0.05)


@pytest.fixture
def box(client):
    """An object with a writable "got" property that background tasks report into."""
    obj = assert_moo_success(client.eval("create(#1)"))
    assert_moo_success(client.eval(f'add_property({obj}, "got", 0, {{player, "rw"}})'))
    return obj


class TestRaise:
    """raise() and the error values it produces."""

    def test_task_001_raise_fields(self, program):
        """TASK-001: raise(code, message, value) fills the first three fields of the caught list."""
        result, _ = program([
            "try",
            '  raise(E_INVARG, "custom", {1, 2});',
            "except e (ANY)",
            "  return e[1..3];",
            "endtry",
        ])
        assert assert_moo_success(result) == '{E_INVARG, "custom", {1, 2}}'

    def test_task_002_default_message_and_value(self, program):
        """TASK-002: Without a message, an error code's message is its description and the value is 0."""
        result, _ = program([
            "try",
            "  raise(E_PERM);",
            "except e (ANY)",
            "  return e[1..3];",
            "endtry",
        ])
        assert assert_moo_success(result) == '{E_PERM, "Permission denied", 0}'

    def test_task_003_non_error_code(self, program):
        """TASK-003: Any value can be raised; only an ANY handler catches it, and its message is tostr(code)."""
        result, _ = program([
            "try",
            '  raise("oops");',
            "except e (E_INVARG)",
            "  return 1;",
            "except e (ANY)",
            "  return e[1..3];",
            "endtry",
        ])
        assert assert_moo_success(result) == '{"oops", "oops", 0}'

    def test_task_004_traceback_field(self, program):
        """TASK-004: The fourth field is the stack, innermost frame first, with line numbers."""
        result, _ = program([
            "try",
            "  raise(E_RANGE);",
            "except e (ANY)",
            "  return e[4][1];",
            "endtry",
        ])
        assert assert_moo_success(result) == f'{{{program.obj}, "run1", #3, {program.obj}, #3, 2}}'

    def test_task_005_handler_selects_by_code(self, program):
        """TASK-005: An except arm only catches the codes it lists; the next arm sees the rest."""
        result, _ = program([
            "try",
            "  raise(E_PROPNF);",
            "except (E_PERM, E_VERBNF)",
            "  return 1;",
            "except (E_PROPNF)",
            "  return 2;",
            "endtry",
        ])
        assert_moo_int(result, 2)

    def test_task_006_uncaught_raise_aborts_with_message(self, client):
        """TASK-006: An uncaught raise ends the task and the traceback shows its message."""
        success, text = client.eval('raise(E_INVARG, "a custom message")')
        assert not success
        assert "a custom message" in text

    def test_task_007_argument_types(self, client):
        """TASK-007: The message must be a string; extra arguments are E_ARGS."""
        assert_moo_raises(client, "raise(E_PERM, 5)", "E_TYPE")
        assert_moo_raises(client, 'raise(E_PERM, "m", 1, 2)', "E_ARGS")
        assert_moo_raises(client, "raise()", "E_ARGS")


class TestCallFunction:
    """call_function() dispatches to a builtin by name."""

    def test_task_010_calls_by_name(self, client):
        """TASK-010: call_function passes the remaining arguments to the named builtin."""
        assert_moo_string(client.eval('call_function("tostr", 1, "a", 2.5)'), "1a2.5")
        assert_moo_int(client.eval('call_function("length", {1, 2, 3})'), 3)

    def test_task_011_builtin_that_calls_back(self, client):
        """TASK-011: A builtin that runs MOO code (eval) works through call_function."""
        assert assert_moo_success(client.eval('call_function("eval", "return 6 * 7;")')) == "{1, 42}"

    def test_task_012_errors_propagate(self, client):
        """TASK-012: Errors from the called builtin reach the caller unchanged."""
        assert_moo_raises(client, 'call_function("length", 5)', "E_TYPE")
        assert_moo_raises(client, 'call_function("abs")', "E_ARGS")

    def test_task_013_unknown_function(self, program):
        """TASK-013: An unknown name raises E_INVARG with the name as the value."""
        result, _ = program([
            "try",
            '  call_function("no_such_builtin");',
            "except e (ANY)",
            "  return e[1..3];",
            "endtry",
        ])
        assert assert_moo_success(result) == '{E_INVARG, "Unknown built-in function", "no_such_builtin"}'

    def test_task_014_name_must_be_string(self, client):
        """TASK-014: The function name must be a string."""
        assert_moo_raises(client, "call_function(5)", "E_TYPE")
        assert_moo_raises(client, "call_function()", "E_ARGS")


class TestTaskInfo:
    """task_id, seconds_left and ticks_left."""

    def test_task_020_task_id_is_stable_within_a_task(self, program):
        """TASK-020: task_id() is a positive integer that stays the same for the whole task."""
        result, _ = program(["a = task_id();", "suspend(0);", "return {a > 0, a == task_id()};"])
        assert assert_moo_success(result) == "{1, 1}"

    def test_task_021_task_ids_differ(self, client):
        """TASK-021: Separate commands run as separate tasks."""
        first = assert_moo_success(client.eval("task_id()"))
        second = assert_moo_success(client.eval("task_id()"))
        assert first != second

    def test_task_022_budgets_count_down(self, program):
        """TASK-022: ticks_left() decreases as code runs; seconds_left() is positive."""
        result, _ = program([
            "a = ticks_left();",
            "for i in [1..100]",
            "endfor",
            "return {a > ticks_left(), seconds_left() > 0};",
        ])
        assert assert_moo_success(result) == "{1, 1}"

    def test_task_023_suspend_switches_to_background_budget(self, program):
        """TASK-023: A command starts with the foreground tick budget; after suspend() it gets the background one.

        With no $server_options the limits are 30000 and 15000 ticks.
        """
        result, _ = program([
            "before = ticks_left();",
            "suspend(0);",
            "after = ticks_left();",
            "return {before > 15000, after > 14000, after <= 15000};",
        ])
        assert assert_moo_success(result) == "{1, 1, 1}"


class TestSuspendResume:
    """suspend() and resume()."""

    def test_task_030_resume_supplies_value(self, client, box):
        """TASK-030: resume(id, value) wakes a suspended task and suspend() returns value."""
        tid = fork_task(client, f"{box}.got = suspend();")
        assert wait_for(client, "length(queued_tasks())", "1") == "1"
        assert_moo_int(client.eval(f'resume({tid}, {{"woke", 1}})'), 0)
        assert wait_for(client, f"{box}.got", '{"woke", 1}') == '{"woke", 1}'
        assert assert_moo_success(client.eval("queued_tasks()")) == "{}"

    def test_task_031_resume_default_value(self, client, box):
        """TASK-031: resume(id) with no value makes suspend() return 0."""
        tid = fork_task(client, f"{box}.got = {{suspend()}};")
        wait_for(client, "length(queued_tasks())", "1")
        client.eval(f"resume({tid})")
        assert wait_for(client, f"{box}.got", "{0}") == "{0}"

    def test_task_032_timed_suspend_returns_zero(self, client, box):
        """TASK-032: suspend(n) wakes on its own after n seconds and returns 0."""
        fork_task(client, f"{box}.got = {{suspend(1)}};")
        assert assert_moo_success(client.eval(f"{box}.got")) == "0"
        assert wait_for(client, f"{box}.got", "{0}", timeout=5) == "{0}"

    def test_task_033_resume_timed_suspend_early(self, client, box):
        """TASK-033: A task in suspend(n) can be resumed before n seconds pass."""
        tid = fork_task(client, f"{box}.got = suspend(3600);")
        wait_for(client, "length(queued_tasks())", "1")
        client.eval(f'resume({tid}, "early")')
        assert wait_for(client, f"{box}.got", '"early"') == '"early"'

    def test_task_034_suspend_zero(self, program):
        """TASK-034: suspend(0) yields and continues, returning 0."""
        result, _ = program(["return {suspend(0), suspend(0)};"])
        assert assert_moo_success(result) == "{0, 0}"

    def test_task_035_negative_suspend(self, client):
        """TASK-035: A negative delay is E_INVARG; a non-integer is E_TYPE."""
        assert_moo_raises(client, "suspend(-1)", "E_INVARG")
        assert_moo_raises(client, "suspend(1.5)", "E_TYPE")

    def test_task_036_resume_unknown_or_unsuspended(self, client):
        """TASK-036: resume() of a missing task, or of a forked task still waiting to start, is E_INVARG."""
        assert_moo_raises(client, "resume(123456789)", "E_INVARG")
        tid = fork_task(client, "return;", delay=3600)
        assert_moo_raises(client, f"resume({tid})", "E_INVARG")

    def test_task_037_programmer_cannot_resume_others(self, wizard_and_programmer):
        """TASK-037: Only the task's owner or a wizard may resume it."""
        wiz, prog = wizard_and_programmer
        tid = fork_task(wiz, "suspend();")
        wait_for(wiz, "length(queued_tasks())", "1")
        assert_moo_raises(prog, f"resume({tid})", "E_PERM")
        mine = fork_task(prog, "suspend();")
        assert_moo_int(prog.eval(f"resume({mine})"), 0)
        assert_moo_int(wiz.eval(f"resume({tid})"), 0)


class TestKillTask:
    """kill_task()."""

    def test_task_040_kill_waiting_fork(self, client, box):
        """TASK-040: Killing a forked task stops it from ever running."""
        tid = fork_task(client, f"{box}.got = 1;", delay=1)
        assert_moo_int(client.eval(f"kill_task({tid})"), 0)
        assert assert_moo_success(client.eval("queued_tasks()")) == "{}"
        time.sleep(1.5)
        assert_moo_int(client.eval(f"{box}.got"), 0)

    def test_task_041_kill_suspended(self, client, box):
        """TASK-041: Killing a suspended task removes it, and it does not run again."""
        tid = fork_task(client, f"suspend(); {box}.got = 1;")
        wait_for(client, "length(queued_tasks())", "1")
        assert_moo_int(client.eval(f"kill_task({tid})"), 0)
        assert_moo_raises(client, f"resume({tid})", "E_INVARG")
        assert_moo_int(client.eval(f"{box}.got"), 0)

    def test_task_042_kill_twice(self, client):
        """TASK-042: Killing a task that is gone is E_INVARG."""
        tid = fork_task(client, "return;", delay=3600)
        client.eval(f"kill_task({tid})")
        assert_moo_raises(client, f"kill_task({tid})", "E_INVARG")

    def test_task_043_kill_self(self, program, client, box):
        """TASK-043: kill_task(task_id()) ends the current task on the spot."""
        result, _ = program([f"{box}.got = 1;", "kill_task(task_id());", f"{box}.got = 2;", "return 3;"])
        assert not result[0] or result[1] != "3"
        assert_moo_int(client.eval(f"{box}.got"), 1)

    def test_task_044_programmer_cannot_kill_others(self, wizard_and_programmer):
        """TASK-044: Only the task's owner or a wizard may kill it."""
        wiz, prog = wizard_and_programmer
        tid = fork_task(wiz, "return;", delay=3600)
        assert_moo_raises(prog, f"kill_task({tid})", "E_PERM")
        mine = fork_task(prog, "return;", delay=3600)
        assert_moo_int(prog.eval(f"kill_task({mine})"), 0)
        assert_moo_int(wiz.eval(f"kill_task({tid})"), 0)


class TestQueuedTasks:
    """queued_tasks(), queue_info() and task_stack()."""

    def test_task_050_queued_task_fields(self, client, box):
        """TASK-050: Each entry is {id, start, 0, ticks, programmer, verb loc, verb name, line, this, bytes}."""
        define_verb(client, box, "waiter", ["x = 1;", "suspend(3600);"])
        tid = fork_task(client, f"{box}:waiter();")
        wait_for(client, "length(queued_tasks())", "1")
        entry = assert_moo_success(client.eval("queued_tasks()[1]"))
        assert assert_moo_success(client.eval("length(queued_tasks()[1])")) == "10"
        assert entry.startswith(f"{{{tid}, ")
        assert assert_moo_success(client.eval("queued_tasks()[1][5..9]")) == f'{{#3, {box}, "waiter", 2, {box}}}'
        assert_moo_int(client.eval("queued_tasks()[1][10] > 0"), 1)

    def test_task_051_forked_start_time(self, client):
        """TASK-051: A forked task's start time is when it is due to run."""
        fork_task(client, "return;", delay=1000)
        assert_moo_int(client.eval("abs(queued_tasks()[1][2] - (time() + 1000)) <= 2"), 1)

    def test_task_052_programmer_sees_only_own(self, wizard_and_programmer):
        """TASK-052: A programmer's queued_tasks() lists only its own tasks; a wizard sees all."""
        wiz, prog = wizard_and_programmer
        theirs = fork_task(wiz, "return;", delay=3600)
        mine = fork_task(prog, "return;", delay=3600)
        assert assert_moo_success(prog.eval("{queued_tasks()[1][1], length(queued_tasks())}")) == f"{{{mine}, 1}}"
        ids = assert_moo_success(wiz.eval("{queued_tasks()[1][1], queued_tasks()[2][1]}"))
        assert sorted(int(i) for i in ids.strip("{}").split(", ")) == sorted((theirs, mine))

    def test_task_053_queue_info(self, wizard_and_programmer):
        """TASK-053: queue_info() lists players with task queues; queue_info(p) counts p's background tasks."""
        wiz, prog = wizard_and_programmer
        assert_moo_int(wiz.eval("queue_info(#4)"), 0)
        fork_task(prog, "return;", delay=3600)
        fork_task(prog, "return;", delay=3600)
        assert_moo_int(wiz.eval("queue_info(#4)"), 2)
        assert_moo_int(wiz.eval("(#4 in queue_info()) > 0 && (#3 in queue_info()) > 0"), 1)
        assert_moo_int(wiz.eval("queue_info(#1)"), 0)

    def test_task_054_task_stack(self, client, box):
        """TASK-054: task_stack(id) lists a suspended task's frames, innermost first."""
        define_verb(client, box, "inner", ["suspend();"])
        define_verb(client, box, "outer", ["this:inner();"])
        tid = fork_task(client, f"{box}:outer();")
        wait_for(client, "length(queued_tasks())", "1")
        assert assert_moo_success(client.eval(f"task_stack({tid})[1..2]")) == (
            f'{{{{{box}, "inner", #3, {box}, #3}}, {{{box}, "outer", #3, {box}, #3}}}}')
        assert assert_moo_success(client.eval(f"task_stack({tid}, 1)[1]")) == f'{{{box}, "inner", #3, {box}, #3, 1}}'
        assert_moo_int(client.eval(f"length(task_stack({tid}))"), 3)

    def test_task_055_task_stack_errors(self, wizard_and_programmer):
        """TASK-055: task_stack of a task that isn't suspended is E_INVARG; of another's task, E_PERM."""
        wiz, prog = wizard_and_programmer
        assert_moo_raises(wiz, "task_stack(123456789)", "E_INVARG")
        waiting = fork_task(wiz, "return;", delay=3600)
        assert_moo_raises(wiz, f"task_stack({waiting})", "E_INVARG")
        tid = fork_task(wiz, "suspend();")
        wait_for(wiz, "length(queued_tasks())", "2")
        assert_moo_raises(prog, f"task_stack({tid})", "E_PERM")
        assert_moo_success(wiz.eval(f"task_stack({tid})"))


class TestCallers:
    """callers(), caller_perms() and set_task_perms()."""

    def test_task_060_callers_lists_frames(self, client, box):
        """TASK-060: callers() lists the calling frames, excluding the current one."""
        define_verb(client, box, "inner", ["return callers();"])
        define_verb(client, box, "outer", ["return this:inner();"])
        frames = assert_moo_success(client.eval(f"{box}:outer()[1]"))
        assert frames == f'{{{box}, "outer", #3, {box}, #3}}'

    def test_task_061_callers_line_numbers(self, client, box):
        """TASK-061: callers(1) adds the line each caller is on."""
        define_verb(client, box, "inner", ["return callers(1);"])
        define_verb(client, box, "outer", ["x = 1;", "return this:inner();"])
        assert assert_moo_success(client.eval(f"{box}:outer()[1]")) == f'{{{box}, "outer", #3, {box}, #3, 2}}'

    def test_task_062_builtin_frames(self, client, box):
        """TASK-062: A verb called by a builtin sees that builtin as a frame with #-1 objects."""
        define_verb(client, box, "inner", ["return callers();"])
        define_verb(client, box, "outer", [f'return call_function("eval", "return {box}:inner();");'])
        frames = assert_moo_success(client.eval(f"{box}:outer()[2]"))
        assert '#-1, "eval", #-1, #-1, #3' in frames

    def test_task_063_caller_perms(self, wizard_and_programmer):
        """TASK-063: caller_perms() is the permissions of the frame that called this verb."""
        wiz, prog = wizard_and_programmer
        obj = assert_moo_success(wiz.eval("create(#1)"))
        define_verb(wiz, obj, "who", ["return caller_perms();"])
        define_verb(wiz, obj, "via4", [f"return {obj}:who();"], owner="#4")
        assert assert_moo_success(wiz.eval(f"{obj}:via4()")) == "#4"
        assert assert_moo_success(prog.eval(f"{obj}:who()")) == "#4"
        assert assert_moo_success(wiz.eval(f"{obj}:who()")) == "#3"

    def test_task_064_set_task_perms(self, wizard_and_programmer):
        """TASK-064: set_task_perms changes the current frame's permissions; a programmer may only set its own."""
        wiz, prog = wizard_and_programmer
        obj = assert_moo_success(wiz.eval("create(#1)"))
        define_verb(wiz, obj, "who", ["return caller_perms();"])
        define_verb(wiz, obj, "drop", ["set_task_perms(#4);", f"return {{{obj}:who(), `set_task_perms(#3) ! ANY'}};"])
        assert assert_moo_success(wiz.eval(f"{obj}:drop()")) == "{#4, E_PERM}"
        assert_moo_raises(prog, "set_task_perms(#3)", "E_PERM")
        assert_moo_int(prog.eval("set_task_perms(#4)"), 0)


class TestPass:
    """pass() calls the parent's version of the running verb."""

    def test_task_070_pass_calls_parent(self, client):
        """TASK-070: pass(args) runs the inherited verb with this unchanged."""
        parent = assert_moo_success(client.eval("create(#1)"))
        child = assert_moo_success(client.eval(f"create({parent})"))
        define_verb(client, parent, "describe", ['return {"parent", this, args};'])
        define_verb(client, child, "describe", ['return {"child", pass(@args, "extra")};'])
        result = assert_moo_success(client.eval(f'{child}:describe("a")'))
        assert result == f'{{"child", {{"parent", {child}, {{"a", "extra"}}}}}}'

    def test_task_071_pass_without_parent_verb(self, client):
        """TASK-071: pass() when no ancestor defines the verb is E_VERBNF."""
        obj = assert_moo_success(client.eval("create(#1)"))
        define_verb(client, obj, "lonely", ["return pass();"])
        assert_moo_raises(client, f"{obj}:lonely()", "E_VERBNF")

    def test_task_072_pass_skips_to_nearest_definer(self, client):
        """TASK-072: pass() finds the verb on the nearest ancestor that has it, skipping those that don't."""
        top = assert_moo_success(client.eval("create(#1)"))
        middle = assert_moo_success(client.eval(f"create({top})"))
        bottom = assert_moo_success(client.eval(f"create({middle})"))
        define_verb(client, top, "v", ['return "top";'])
        define_verb(client, bottom, "v", ['return {"bottom", pass()};'])
        assert assert_moo_success(client.eval(f"{bottom}:v()")) == '{"bottom", "top"}'

    def test_task_073_pass_uses_verb_location_not_this(self, client):
        """TASK-073: pass() from an inherited verb continues above the verb's own location."""
        top = assert_moo_success(client.eval("create(#1)"))
        middle = assert_moo_success(client.eval(f"create({top})"))
        bottom = assert_moo_success(client.eval(f"create({middle})"))
        define_verb(client, top, "v", ['return {"top"};'])
        define_verb(client, middle, "v", ['return {"middle", @pass()};'])
        assert assert_moo_success(client.eval(f"{bottom}:v()")) == '{"middle", "top"}'
