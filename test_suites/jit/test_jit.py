"""JIT correctness tests.

Each test warms a verb past the JIT's hot threshold with repeated calls and
checks that native execution is indistinguishable from the interpreter:
same values, same errors, same tracebacks, and the same handling of ticks,
suspension, reprogramming and property changes.  Expected values come from
the same verb run cold (interpreted) before warm-up, so the interpreter is
the reference, plus independent Python values where they are well defined.
"""

import pytest

from lib.jit import Raw, expect_calls, moo_literal


MAX_INT = 2**63 - 1
MIN_INT = -2**63

pytestmark = pytest.mark.jit


class TestJitDetection:
    """The JIT's MOO-visible surface is present exactly when the server has it."""

    def test_jit_feature_and_builtins(self, client, requires_jit):
        """A JIT server lists "jit" in its features and provides the jit_* builtins."""
        ok, features = client.eval('server_version("features")')
        assert ok and '"jit"' in features, features
        for name in ('jit_compile', 'jit_pool_policy', 'jit_pool_rotate', 'jit_profile_detail'):
            ok, info = client.eval(f'function_info("{name}")')
            assert ok, f"{name} missing: {info}"

    def test_no_jit_surface_without_jit(self, client, requires_no_jit):
        """A server built without the JIT has no jit_* builtins."""
        ok, features = client.eval('server_version("features")')
        assert ok and '"jit"' not in features, features
        assert client.eval('`function_info("jit_compile") ! ANY\'') == (True, 'E_INVARG')


class TestJitWarmup:
    """Repeated calls get a verb compiled and running natively."""

    def test_repeated_calls_compile_hot_verb(self, jit):
        """An integer loop verb compiles after repeated calls and keeps returning correct values."""
        jit.define('fib', '''
            n = args[1];
            a = 0;
            b = 1;
            for i in [1..n]
              t = a + b;
              a = b;
              b = t;
            endfor
            return a;
        ''')
        before = jit.stats('fib', ['state', 'eligible'])
        assert before == {'state': 'pending', 'eligible': 1}, before

        fibs = [0, 1]
        while len(fibs) < 91:
            fibs.append(fibs[-1] + fibs[-2])
        for n in range(90):
            assert jit.value(f'#0:fib({n})') == fibs[n]
        jit.assert_native('fib')

    def test_jit_compile_builtin(self, jit):
        """jit_compile() compiles a cold verb immediately and reports its metadata."""
        jit.define('square', 'return args[1] * args[1];')
        meta = dict(jit.value('jit_compile(#0, "square")'))
        assert meta['state'] == 'compiled', meta
        assert jit.value('#0:square(12)') == 144
        jit.assert_native('square')

    def test_jit_compile_requires_wizard(self, jit):
        """jit_compile() refuses non-wizard programmers."""
        jit.define('square', 'return args[1] * args[1];')
        jit.define('as_nonwizard', '''
            set_task_perms(#-1);
            return jit_compile(#0, "square");
        ''')
        assert jit.value('`#0:as_nonwizard() ! ANY\'') == 'E_PERM'


# (name, source with params x and y, warm-up args, inputs checked cold and hot)
EDGE_CASES = [
    ("add_wraps", "return x + y;", [1, 2],
     [[1, 2], [MAX_INT, 1], [MIN_INT, -1], [1.5, 2.25], ["a", "b"], [[1], [2]], [Raw("#1"), 1]]),
    ("sub_wraps", "return x - y;", [5, 3],
     [[5, 3], [MIN_INT, 1], [MAX_INT, -1], [0, MIN_INT], [2.5, 1]]),
    ("mul_wraps", "return x * y;", [6, 7],
     [[6, 7], [2**62, 2], [MIN_INT, -1], [-1, MIN_INT], [3, 1.5]]),
    ("division", "return x / y;", [7, 2],
     [[7, 2], [-7, 2], [7, -2], [-7, -2], [1, 0], [MIN_INT, -1], [7.0, 2.0], [7, 2.0]]),
    ("remainder", "return x % y;", [7, 3],
     [[7, 3], [-7, 3], [7, -3], [-7, -3], [1, 0], [MIN_INT, -1], [9, 4294967296], [-9, 4294967296]]),
    ("power", "return x ^ y;", [2, 10],
     [[2, 10], [2, 62], [2, 63], [-2, 63], [2, -1], [0, -1], [-1, -3], [1, MIN_INT], [2.0, 0.5]]),
    ("negate", "return -x;", [5, 0],
     [[5, 0], [MIN_INT, 0], [MAX_INT, 0], [1.5, 0], ["x", 0]]),
    ("shift_left", "return x << y;", [1, 2],
     [[1, 2], [-5, 3], [1, 63], [1, 64], [1, -1], [0, 63], [1.5, 2]]),
    ("shift_right", "return x >> y;", [256, 2],
     [[256, 2], [-256, 2], [MIN_INT, 63], [1, 64], [1, -1], [-1, 100]]),
    ("shift_right_logical", "return x >>> y;", [256, 2],
     [[256, 2], [-256, 2], [-1, 63], [-1, 64], [1, -1]]),
    ("bit_and_xor", "return (x .&. y) .^. (x .|. y);", [12, 10],
     [[12, 10], [-1, MIN_INT], [MAX_INT, MIN_INT], [1.5, 1], ["a", 1]]),
    ("compare_branch", "if (x < y) return x; elseif (x == y) return 0; else return y; endif", [1, 2],
     [[1, 2], [2, 1], [3, 3], [1, 2.0], [1.0, 2.0], ["a", "b"], [[1], [2]]]),
    ("truthiness", "if (x) return 1; else return y; endif", [1, 0],
     [[1, 0], [0, 7], [-1, 0], [0.0, 7], ["", 7], ["x", 7], [[], 7], [[0], 7]]),
    ("index", "return x[y];", [[10, 20, 30], 2],
     [[[10, 20, 30], 2], [[10, 20, 30], 0], [[10, 20, 30], 4], [[10, 20, 30], -1],
      ["abc", 2], [[10, 20, 30], 1.0], [5, 1]]),
    ("slice", "return x[y..y + 1];", [[1, 2, 3], 1],
     [[[1, 2, 3], 1], [[1, 2, 3], 2], [[1, 2, 3], 3], [[1, 2, 3], 0], [[], 1], ["abcd", 2]]),
    ("indexed_assign", "x[y] = y * 10; return x;", [[0, 0, 0], 2],
     [[[0, 0, 0], 2], [[0, 0, 0], 4], [[0, 0, 0], 0], ["abc", 1], [5, 1]]),
    ("sum_loop", "r = 0; for i in [1..x] r = r + i * y; endfor return r;", [10, 1],
     [[10, 1], [0, 1], [-5, 1], [100, 2**58], [3, 1.5], [3, "x"]]),
    ("while_break_continue",
     "r = 0; i = 0; while (1) i = i + 1; if (i > x) break; endif if (i % y) continue; endif r = r + i; endwhile return r;",
     [20, 3], [[20, 3], [0, 3], [20, 1], [20, 0], [5, -2]]),
    ("for_over_list", "r = 0; for v in (x) r = r * 31 + v; endfor return r + y;", [[1, 2, 3], 0],
     [[[1, 2, 3], 0], [[], 5], [[MAX_INT, MAX_INT], 0], [[1, "a"], 0], ["abc", 0], [42, 0]]),
]


@pytest.mark.parametrize("name,body,warm,inputs", EDGE_CASES, ids=[c[0] for c in EDGE_CASES])
def test_hot_verb_matches_interpreter(jit, name, body, warm, inputs):
    """A warmed-up verb and a caller stitched to it give the interpreter's results and errors.

    Warming uses integer arguments, so the other inputs also exercise the
    guards that must send non-integer and overflowing cases back to the
    interpreter's semantics.
    """
    jit.define(name, f'{{x, y}} = args; {body}')
    jit.define(f'{name}_caller', f'return this:{name}(args[1], args[2]);')

    cold = expect_calls(jit, name, inputs)

    jit.warm_and_rotate(f'#0:{name}_caller(@{moo_literal(warm)})')
    jit.assert_native(name, f'{name}_caller')

    assert expect_calls(jit, name, inputs) == cold, "direct hot calls differ from interpreter"
    assert expect_calls(jit, f'{name}_caller', inputs) == cold, "stitched hot calls differ from interpreter"


class TestJitSemantics:
    """Observable behavior that native code must preserve."""

    def test_error_traceback_matches_interpreter(self, jit):
        """An error raised in hot code produces the interpreter's traceback, line number included."""
        jit.define('divide', '''
            x = args[1];
            y = args[2];
            z = x + 1;
            return z / y;
        ''')
        cold = jit.eval('#0:divide(1, 0)')
        assert not cold[0]
        jit.warm('#0:divide(1, 1)')
        jit.assert_native('divide')
        assert jit.eval('#0:divide(1, 0)') == cold
        assert jit.value('#0:divide(5, 2)') == 3

    def test_caught_error_in_hot_verb(self, jit):
        """try/except around an error raised in hot code still catches it."""
        jit.define('safe_div', '''
            try
              return args[1] / args[2];
            except e (E_DIV)
              return -1;
            endtry
        ''')
        jit.warm('#0:safe_div(9, 3)')
        assert jit.value('#0:safe_div(9, 0)') == -1
        assert jit.value('#0:safe_div(9, 3)') == 3

    def test_ticks_enforced_in_hot_loop(self, jit):
        """A hot loop still runs out of ticks rather than running forever."""
        jit.define('count', '''
            r = 0;
            for i in [1..args[1]]
              r = r + i;
            endfor
            return r;
        ''')
        jit.warm('#0:count(100)')
        jit.assert_native('count')
        ok, result = jit.eval('#0:count(1000000000)', timeout=60)
        assert not ok and 'ran out of ticks' in result, result
        assert jit.value('#0:count(100)') == 5050

    def test_suspend_in_hot_verb(self, jit):
        """A hot verb that suspends mid-loop resumes with its local state intact."""
        jit.define('sum_suspending', '''
            {n, at} = args;
            r = 0;
            for i in [1..n]
              r = r + i;
              if (i == at)
                suspend(0);
              endif
            endfor
            return r;
        ''')
        jit.warm('#0:sum_suspending(100, 0)')
        jit.assert_native('sum_suspending')
        assert jit.value('#0:sum_suspending(100, 50)') == 5050
        assert jit.value('#0:sum_suspending(100, 0)') == 5050

    def test_reprogrammed_verb_is_not_stale(self, jit):
        """set_verb_code on a hot verb takes effect on the next call."""
        jit.define('bump', 'return args[1] + 1;')
        jit.define('bump_caller', 'return this:bump(args[1]);')
        jit.warm_and_rotate('#0:bump_caller(1)')
        jit.assert_native('bump')
        jit.define('bump', 'return args[1] + 2;')
        assert jit.value('#0:bump(1)') == 3
        assert jit.value('#0:bump_caller(1)') == 3

    def test_redefined_callee_is_not_stale(self, jit):
        """Replacing a stitched callee with a new verb of the same name takes effect."""
        jit.define('leaf', 'return args[1] * 2;')
        jit.define('outer', 'return this:leaf(args[1]) + 1;')
        jit.warm_and_rotate('#0:outer(5)')
        jit.value('delete_verb(#0, "leaf")')
        jit.define('leaf', 'return args[1] * 3;')
        assert jit.value('#0:outer(5)') == 16

    def test_property_change_is_not_stale(self, jit):
        """A hot verb reading a property sees changes made between calls."""
        jit.value('add_property(#0, "jit_scale", 2, {player, "r"})')
        jit.define('scaled', 'return args[1] * this.jit_scale;')
        jit.warm('#0:scaled(10)')
        jit.value('#0.jit_scale = 5')
        assert jit.value('#0:scaled(10)') == 50

    def test_property_write_in_hot_loop(self, jit):
        """Property writes from hot code are all visible afterwards."""
        jit.value('add_property(#0, "jit_counter", 0, {player, "rw"})')
        jit.define('tick_counter', '''
            for i in [1..args[1]]
              this.jit_counter = this.jit_counter + 1;
            endfor
            return this.jit_counter;
        ''')
        jit.warm('#0:tick_counter(3)')
        total = 3 * 40
        assert jit.value('#0.jit_counter') == total
        assert jit.value('#0:tick_counter(10)') == total + 10

    def test_recursion_depth_limit(self, jit):
        """Deep recursion through hot verbs still raises the interpreter's max-recursion error."""
        jit.define('depth', '''
            if (args[1] <= 0)
              return 0;
            endif
            return 1 + this:depth(args[1] - 1);
        ''')
        cold = jit.eval('#0:depth(100000)', timeout=60)
        jit.warm('#0:depth(20)')
        assert jit.value('#0:depth(20)') == 20
        hot = jit.eval('#0:depth(100000)', timeout=60)
        assert hot[0] == cold[0] and ('recursion' in hot[1]) == ('recursion' in cold[1]), (cold, hot)

    def test_recursive_hot_verbs(self, jit):
        """Mutually recursive hot verbs compute the same values as Python."""
        jit.define('is_even', 'return args[1] == 0 ? 1 | this:is_odd(args[1] - 1);')
        jit.define('is_odd', 'return args[1] == 0 ? 0 | this:is_even(args[1] - 1);')
        jit.define('rfib', 'n = args[1]; return n < 2 ? n | this:rfib(n - 1) + this:rfib(n - 2);')
        jit.warm_and_rotate('#0:is_even(10)', '#0:rfib(5)')
        jit.assert_native('is_even', 'is_odd', 'rfib')
        assert [jit.value(f'#0:is_even({n})') for n in range(12)] == [int(n % 2 == 0) for n in range(12)]
        fibs = [0, 1]
        while len(fibs) < 16:
            fibs.append(fibs[-1] + fibs[-2])
        assert [jit.value(f'#0:rfib({n})') for n in range(16)] == fibs

    def test_ticks_exhausted_in_recursive_verb_chain(self, jit):
        """Running out of ticks deep in hot recursive verb calls aborts the task, not the server.

        rfib(17) needs more ticks than a foreground task gets; the interpreter
        reports "Task ran out of ticks".
        """
        jit.define('rfib', 'n = args[1]; return n < 2 ? n | this:rfib(n - 1) + this:rfib(n - 2);')
        jit.warm_and_rotate('#0:rfib(5)')
        ok, result = jit.eval('#0:rfib(17)', timeout=60)
        assert not ok and 'ran out of ticks' in result, result
        assert jit.value('#0:rfib(10)') == 55

    def test_task_local_state_across_callers(self, jit):
        """A hot callee called from different callers with different argument types stays correct."""
        jit.define('twice', 'return args[1] + args[1];')
        jit.define('ints', 'return this:twice(args[1]);')
        jit.define('floats', 'return this:twice(tofloat(args[1]));')
        jit.define('strs', 'return this:twice(tostr(args[1]));')
        jit.warm_and_rotate('#0:ints(21)')
        assert jit.value('#0:ints(21)') == 42
        assert jit.value('#0:floats(21)') == 42.0
        assert jit.value('#0:strs(21)') == '2121'
        assert jit.value(f'#0:ints({MAX_INT})') == -2


TABLE_BUILDER = 't = {}; for i in [0..255] t = {@t, i}; endfor return t;'
TABLE_LOOKUP = '{b, t} = args; r = 0; for c in (b) r = t[c + 1]; endfor return r;'


@pytest.mark.parametrize("wrapper,expected", [
    ('return {this:lookup(args[1], this:table())};', [8]),
    ('return {this:one(), this:lookup(args[1], this:table())};', [1, 8]),
], ids=['alone', 'after_sibling_call'])
def test_nested_call_argument_in_list_literal(jit, wrapper, expected):
    """A verb call whose argument is another verb call, inside a list literal, stays correct when hot.

    The looping callee receives a 256-element list built by the inner call.
    """
    jit.define('table', TABLE_BUILDER)
    jit.define('lookup', TABLE_LOOKUP)
    jit.define('one', 'return 1;')
    jit.define('wrapper', wrapper)
    for i in range(3 * 40):
        assert jit.value('#0:wrapper({1, 2, 3, 4, 5, 6, 7, 8})') == expected, f"call {i + 1}"
