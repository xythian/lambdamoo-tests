"""Builtins that walk a value must cope with shared and deeply nested lists.

Two shapes of list used to stop the server:

* Lists that share sublists.  ``x = {x, x}`` repeated 60 times makes only
  61 distinct lists but 2^60 paths through them.  Code that followed every
  path (sizes, equality between independent copies, encoding) ran forever.
* Lists nested about a million deep.  ``x = {x}`` repeated that often
  overflowed the C stack in any code that recursed into elements, freeing
  the list included, and the server died without a panic dump.

Every test here gives the server far longer than a correct server needs
and then checks that it still answers.
"""

import time

import pytest

from lib.assertions import assert_moo_error, assert_moo_success


HANG_TIMEOUT = 30.0
SHARED_DEPTH = 60
DEEP = 1_000_000
NUM_MAX_I64 = 2**63 - 1


@pytest.fixture
def program(client):
    """Return a function that runs MOO statements as a verb and returns the eval result.

    The verb lives on a fresh object, so tests can use statements (loops,
    assignments) that the expression-only eval command cannot.
    """
    obj = assert_moo_success(client.eval('create(#1)'))
    counter = [0]

    def run(lines, timeout=HANG_TIMEOUT):
        counter[0] += 1
        name = f"run{counter[0]}"
        assert_moo_success(client.eval(f'add_verb({obj}, {{player, "rxd", "{name}"}}, {{"this", "none", "this"}})'))
        code = ", ".join('"' + line.replace('\\', '\\\\').replace('"', '\\"') + '"' for line in lines)
        assert_moo_success(client.eval(f'set_verb_code({obj}, "{name}", {{{code}}})'))
        start = time.monotonic()
        result = client.eval(f'{obj}:{name}()', timeout=timeout)
        return result, time.monotonic() - start

    run.obj = obj
    return run


@pytest.fixture
def many_ticks(client):
    """Raise the foreground limits enough to build a list nested a million deep."""
    if '"server_options"' not in assert_moo_success(client.eval('properties(#0)')):
        assert_moo_success(client.eval('add_property(#0, "server_options", create(#1), {player, "r"})'))
    assert_moo_success(client.eval('add_property(#0.server_options, "fg_ticks", 100000000, {player, "r"})'))
    assert_moo_success(client.eval('add_property(#0.server_options, "fg_seconds", 120, {player, "r"})'))
    assert_moo_success(client.eval('load_server_options()'))


@pytest.fixture
def catchable_space(client):
    """Make running out of string space raise a catchable E_QUOTA instead of aborting the task."""
    if '"server_options"' not in assert_moo_success(client.eval('properties(#0)')):
        assert_moo_success(client.eval('add_property(#0, "server_options", create(#1), {player, "r"})'))
    assert_moo_success(client.eval('add_property(#0.server_options, "max_concat_catchable", 1, {player, "r"})'))
    assert_moo_success(client.eval('load_server_options()'))


def assert_server_responsive(client):
    """The server must still answer after the walk."""
    assert assert_moo_success(client.eval('1 + 1', timeout=HANG_TIMEOUT)) == '2'


def shared(name, depth=SHARED_DEPTH, leaf="{}"):
    """MOO statements setting NAME to {NAME, NAME} nested DEPTH deep around LEAF."""
    return [f'{name} = {leaf};', f'for i in [1..{depth}]', f'  {name} = {{{name}, {name}}};', 'endfor']


def deep(name, depth=DEEP):
    """MOO statements setting NAME to {NAME} nested DEPTH deep around {}."""
    return [f'{name} = {{}};', f'for i in [1..{depth}]', f'  {name} = {{{name}}};', 'endfor']


class TestSharedSublists:
    """Walks over lists that share sublists finish in time proportional to the distinct lists."""

    @pytest.mark.parametrize("depth", [40, 61])
    def test_value_bytes_counts_every_path(self, client, program, requires_i64, depth):
        """value_bytes() still counts a shared sublist once per appearance, sticking at the largest integer."""
        result, elapsed = program(shared("x", depth) + ['return {value_bytes(x), value_bytes({})};'])
        total, empty = (int(n) for n in assert_moo_success(result).strip('{}').split(', '))
        assert total == min(empty * (2 ** (depth + 1) - 1), NUM_MAX_I64)
        assert elapsed < 10
        assert_server_responsive(client)

    def test_object_bytes(self, client, program):
        """object_bytes() of an object holding the list finishes quickly."""
        result, elapsed = program(shared("x") + [
            'add_property(this, "big", x, {player, "r"});',
            'return object_bytes(this) > value_bytes(x) / 2;',
        ])
        assert assert_moo_success(result) == '1'
        assert elapsed < 10
        assert_server_responsive(client)

    def test_queued_tasks_bytes(self, client, program):
        """queued_tasks() sizes a task holding the list quickly."""
        result, elapsed = program(shared("x") + [
            'fork t (600)',
            '  x = x;',
            'endfork',
            'for q in (queued_tasks())',
            '  if (q[1] == t)',
            '    kill_task(t);',
            '    return q[10] > 0;',
            '  endif',
            'endfor',
            'return "task not found";',
        ])
        assert assert_moo_success(result) == '1'
        assert elapsed < 10
        assert_server_responsive(client)

    @pytest.mark.parametrize("expr, expected", [
        ("x == y", "1"),
        ("x != y", "0"),
        ("y in {1, x}", "2"),
        ("is_member(x, {y})", "1"),
        ("equal(x, y)", "1"),
        ("x == z", "0"),
    ], ids=["eq", "ne", "in", "is_member", "equal", "differ-at-leaf"])
    def test_compare_independent_copies(self, client, program, expr, expected):
        """Two separately built copies compare without following every path."""
        result, elapsed = program(shared("x") + shared("y") + shared("z", leaf="{1}") + [f'return {expr};'])
        assert assert_moo_success(result) == expected
        assert elapsed < 10
        assert_server_responsive(client)

    def test_compare_differs_after_shared_half(self, client, program):
        """A difference found only after comparing a large shared half is still seen."""
        result, elapsed = program(shared("a", 59) + shared("b", 59) + shared("c", 59, leaf="{1}") + [
            'x = {a, a};',
            'y = {b, c};',
            'return {x == y, x == {b, b}, {a, c} == {b, c}};',
        ])
        assert assert_moo_success(result) == '{0, 1, 1}'
        assert elapsed < 10
        assert_server_responsive(client)

    def test_encode_binary_of_empty_sublists(self, client, program):
        """encode_binary() of lists holding only empty lists returns the empty string."""
        result, elapsed = program(shared("x") + ['return encode_binary(x);'])
        assert assert_moo_success(result) == '""'
        assert elapsed < 10
        assert_server_responsive(client)

    def test_encode_chars_of_empty_sublists(self, client, program, requires_unicode):
        """encode_chars() of lists holding only empty lists returns the empty string."""
        result, elapsed = program(shared("x") + ['return encode_chars(x, "UTF-8");'])
        assert assert_moo_success(result) == '""'
        assert elapsed < 10
        assert_server_responsive(client)

    def test_value_hash_runs_out_of_space(self, client, program, catchable_space):
        """value_hash() of a list whose literal is 2^60 braces long raises E_QUOTA quickly, like toliteral()."""
        result, elapsed = program(shared("x") + [
            "return {`value_hash(x) ! E_QUOTA => 0', `toliteral(x) ! E_QUOTA => 0'};",
        ])
        assert assert_moo_success(result) == '{0, 0}'
        assert elapsed < 10
        assert_server_responsive(client)

    def test_value_hash_repeats_shared_output(self, client, program):
        """A shared sublist is hashed at every place it occurs, as in its literal."""
        result, _ = program([
            'x = {"a", 1};',
            'for i in [1..12]',
            '  x = {"<", x, x, ">"};',
            'endfor',
            'return value_hash(x) == string_hash(toliteral(x));',
        ])
        assert assert_moo_success(result) == '1'

    def test_encode_binary_repeats_shared_output(self, client, program):
        """A shared sublist's bytes appear at every place it occurs."""
        result, _ = program([
            'x = {"a"};',
            's = "a";',
            'for i in [1..13]',
            '  x = {"<", x, "|", x, ">"};',
            '  s = "<" + s + "|" + s + ">";',
            'endfor',
            'return {encode_binary(x) == s, length(s)};',
        ])
        assert assert_moo_success(result) == f'{{1, {4 * 2**13 - 3}}}'

    def test_encode_chars_repeats_shared_output(self, client, program, requires_unicode):
        """encode_chars() gives the same bytes as encoding the flattened string."""
        result, _ = program([
            'x = {"a"};',
            's = "a";',
            'for i in [1..13]',
            '  x = {"<", x, 124, x, ">"};',
            '  s = "<" + s + "|" + s + ">";',
            'endfor',
            'return encode_chars(x, "UTF-8") == encode_chars({s}, "UTF-8");',
        ])
        assert assert_moo_success(result) == '1'


class TestDeepNesting:
    """Values nested a million deep are walked without overflowing the C stack."""

    def test_build_and_free(self, client, program, many_ticks):
        """Freeing the list when the verb returns does not crash the server."""
        result, _ = program(deep("x") + ['return 1;'])
        assert assert_moo_success(result) == '1'
        assert_server_responsive(client)

    def test_value_bytes(self, client, program, many_ticks):
        """value_bytes() counts every level."""
        result, _ = program(deep("x") + [f'return value_bytes(x) == value_bytes({{}}) * {DEEP + 1};'])
        assert assert_moo_success(result) == '1'
        assert_server_responsive(client)

    def test_equality(self, client, program, many_ticks):
        """Two separately built copies compare equal, and differ when one is a level shorter."""
        result, _ = program(deep("x") + deep("y") + deep("z", DEEP - 1) + ['return {x == y, x == z, x in {y}};'])
        assert assert_moo_success(result) == '{1, 0, 1}'
        assert_server_responsive(client)

    def test_toliteral(self, client, program, many_ticks):
        """toliteral() writes every brace."""
        result, _ = program(deep("x") + ['s = toliteral(x);',
                                         'return {length(s), s[1..3], s[$-2..$]};'])
        assert assert_moo_success(result) == f'{{{2 * (DEEP + 1)}, "{{{{{{", "}}}}}}"}}'
        assert_server_responsive(client)

    def test_value_hash(self, client, program, many_ticks):
        """value_hash() hashes every brace, the same as string_hash(toliteral())."""
        result, _ = program(deep("x") + ['return value_hash(x) == string_hash(toliteral(x));'])
        assert assert_moo_success(result) == '1'
        assert_server_responsive(client)

    def test_encode_binary(self, client, program, many_ticks):
        """encode_binary() reaches the innermost element."""
        result, _ = program(['x = {"a"};', f'for i in [1..{DEEP}]', '  x = {x};', 'endfor',
                             'return encode_binary(x);'])
        assert assert_moo_success(result) == '"a"'
        assert_server_responsive(client)

    def test_object_bytes(self, client, program, many_ticks):
        """object_bytes() of an object holding the list."""
        result, _ = program(deep("x") + ['add_property(this, "big", x, {player, "r"});',
                                         'return object_bytes(this) > value_bytes(x);'])
        assert assert_moo_success(result) == '1'
        assert_server_responsive(client)

    @pytest.mark.waifs
    def test_store_in_waif(self, client, program, many_ticks, requires_waifs):
        """Storing the list in a waif property searches it for the waif."""
        assert_moo_success(client.eval(f'add_property({program.obj}, ":p", 0, {{player, "rw"}})'))
        result, _ = program(deep("x") + ['w = new_waif();', 'w.p = x;',
                                         'try', '  w.p = {x, w};', 'except (E_RECMOVE)',
                                         '  return "E_RECMOVE";', 'endtry', 'return "stored";'])
        assert assert_moo_success(result) == '"E_RECMOVE"'
        assert_server_responsive(client)


class TestBesselOrder:
    """j() and y() run in time proportional to the order and cannot be interrupted.

    An order near 2^31 kept the whole server busy for 15 to 25 seconds,
    ignoring the task's limits.
    """

    @pytest.mark.parametrize("call", [
        "j(2147483647, 1.0)", "j(-2147483647, 1.0)", "j(1000001, 1.0)",
        "y(2147483647, 1.0)", "y(1000001, 1.0)",
    ])
    def test_huge_order_rejected(self, client, call):
        """An order beyond one million raises E_INVARG at once."""
        start = time.monotonic()
        assert_moo_error(client.eval(call, timeout=HANG_TIMEOUT), "Invalid argument")
        assert time.monotonic() - start < 5

    def test_order_one_million_allowed(self, client):
        """The largest allowed order still computes."""
        assert assert_moo_success(client.eval('j(1000000, 1.0e6) > 0.0')) == '1'
        assert assert_moo_success(client.eval('j(-1000000, 1.0e6) == j(1000000, 1.0e6)')) == '1'
        assert assert_moo_success(client.eval('y(1000000, 1.0e6) < 0.0')) == '1'
