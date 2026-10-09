"""Runaway tasks must be stopped by the tick and seconds limits.

Each case here once hung an entire single-threaded server: the task spun
inside the interpreter or a C builtin without ever checking its limits, so
the server stopped answering connections, made no system calls and ignored
SIGTERM.  Every test gives the server far longer than a correct server needs
and then checks it still answers, so a regression fails instead of hanging.
"""

import time

import pytest

from lib.assertions import assert_moo_error, assert_moo_success


SECONDS_LIMIT = 1
HANG_TIMEOUT = 20.0


@pytest.fixture
def program(client):
    """Return a function that runs MOO statements as a verb and returns the eval result.

    The verb lives on a fresh object, so tests can use statements (loops,
    assignments) that the expression-only eval command cannot.
    """
    obj = assert_moo_success(client.eval('create(#1)'))
    counter = [0]

    def run(lines, args="", timeout=HANG_TIMEOUT):
        counter[0] += 1
        name = f"run{counter[0]}"
        assert_moo_success(client.eval(f'add_verb({obj}, {{player, "rxd", "{name}"}}, {{"this", "none", "this"}})'))
        code = ", ".join('"' + line.replace('\\', '\\\\').replace('"', '\\"') + '"' for line in lines)
        assert_moo_success(client.eval(f'set_verb_code({obj}, "{name}", {{{code}}})'))
        start = time.monotonic()
        result = client.eval(f'{obj}:{name}({args})', timeout=timeout)
        return result, time.monotonic() - start

    run.obj = obj
    return run


@pytest.fixture
def short_seconds_limit(client):
    """Lower the foreground seconds limit so seconds-limit tests run quickly."""
    if '"server_options"' not in assert_moo_success(client.eval('properties(#0)')):
        assert_moo_success(client.eval('add_property(#0, "server_options", create(#1), {player, "r"})'))
    assert_moo_success(client.eval(
        f'add_property(#0.server_options, "fg_seconds", {SECONDS_LIMIT}, {{player, "r"}})'))
    assert_moo_success(client.eval('load_server_options()'))


def assert_server_responsive(client):
    """The server must still answer after the runaway task is stopped."""
    assert assert_moo_success(client.eval('1 + 1', timeout=HANG_TIMEOUT)) == '2'


class TestLabelledWhileLimits:
    """Labelled while loops compile to an extended opcode that skipped the limit checks."""

    @pytest.mark.parametrize("body", [
        ["while x (1)", "endwhile"],
        ["while x (1)", "  continue x;", "endwhile"],
        ["flag = 1;", "while x (flag)", "endwhile"],
    ], ids=["empty-body", "continue-label", "variable-condition"])
    def test_labelled_while_runs_out_of_ticks(self, client, program, body):
        """A labelled loop with a trivial body is aborted for ticks."""
        result, elapsed = program(body)
        assert_moo_error(result, "out of ticks")
        assert elapsed < HANG_TIMEOUT
        assert_server_responsive(client)

    def test_unlabelled_while_runs_out_of_ticks(self, client, program):
        """Control case: the unlabelled form was always stopped."""
        result, _ = program(["while (1)", "endwhile"])
        assert_moo_error(result, "out of ticks")
        assert_server_responsive(client)


@pytest.mark.regexp
class TestRegexSecondsLimit:
    """A backtracking pattern over a long subject must stop at the seconds limit.

    PCRE's match limit applies to each starting position separately, so total
    work grows with the subject length and was not bounded by any limit.  On
    a 16 KB subject an unfixed server spends about a minute in one match.
    """

    PATTERN = "a?" * 16 + "a" * 16 + "y%W"

    @pytest.mark.parametrize("function", ["match", "rmatch"])
    def test_backtracking_match_stops_at_seconds_limit(self, client, program, requires_regexp,
                                                       short_seconds_limit, function):
        """The task gives up within a few seconds instead of running for minutes."""
        result, elapsed = program([
            's = "a";',
            'for i in [1..14]',
            '  s = s + s;',
            'endfor',
            f'return {function}(s + "yb", "{self.PATTERN}");',
        ])
        assert not result[0], f"expected the task to be stopped, got {result[1]}"
        assert result[1] != "(no response)", "server did not answer before the timeout"
        assert elapsed < SECONDS_LIMIT + 5
        assert_server_responsive(client)

    def test_bounded_backtracking_still_matches(self, client, requires_regexp):
        """Control case: the same pattern on a short subject still works."""
        value = assert_moo_success(client.eval(f'match("aaaaaaaaaaaaaaaaaaaay!", "{self.PATTERN}")[1..2]'))
        assert value == "{1, 22}"


@pytest.mark.waifs
class TestWaifSharedStructure:
    """Storing a value in a waif property searches it for the waif itself.

    The search followed every path through the value, so a list that shares
    its sublists ({x, x} nested d deep) took 2^d steps.
    """

    @pytest.fixture
    def waif_class(self, client, requires_waifs, program):
        obj = program.obj
        assert_moo_success(client.eval(f'add_property({obj}, ":p", 0, {{player, "rw"}})'))
        return obj

    def test_store_deeply_shared_list(self, client, program, waif_class):
        """A list with 2^60 paths but only 60 distinct sublists is stored quickly."""
        result, elapsed = program([
            'w = new_waif();',
            'x = {};',
            'for i in [1..60]',
            '  x = {x, x};',
            'endfor',
            'w.p = x;',
            'return w.p == x;',
        ])
        assert assert_moo_success(result) == '1'
        assert elapsed < 5

    def test_self_reference_through_shared_list_rejected(self, client, program, waif_class):
        """Self-reference is still detected when it sits behind shared sublists."""
        result, _ = program([
            'w = new_waif();',
            'x = {};',
            'for i in [1..30]',
            '  x = {x, x};',
            'endfor',
            'v = new_waif();',
            'v.p = {x, {w}};',
            'try',
            '  w.p = {x, v};',
            'except e (E_RECMOVE)',
            '  return "E_RECMOVE";',
            'endtry',
            'return "stored";',
        ])
        assert assert_moo_success(result) == '"E_RECMOVE"'
