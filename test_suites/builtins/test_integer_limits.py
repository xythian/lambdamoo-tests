"""Integers at or past the C types they are stored in must not wrap.

A MOO integer is 64 bits on Waterpoint, but several builtins and server
options handed it straight to an ``int`` or ``unsigned``, so a large value
silently became a small one: ``fork (4294967296)`` ran at once,
``verb_info(o, 4294967297)`` described verb 1, and ``listen(o, 65536 + 7777)``
listened on port 7777.  Integer arithmetic relied on signed overflow, which
C leaves undefined.  These tests pin the checked or defined behaviour.
"""

import pytest

from lib.assertions import assert_moo_error, assert_moo_success


I64_MAX = 9223372036854775807
I64_MIN = -9223372036854775808
I32_MAX = 2147483647
I32_MIN = -2147483648


@pytest.fixture
def limits(detected_features):
    """The server's (smallest, largest) integer."""
    return (I64_MIN, I64_MAX) if detected_features.has_i64 else (I32_MIN, I32_MAX)


def assert_server_alive(client):
    """The server must still answer."""
    assert assert_moo_success(client.eval('1 + 1')) == '2'


@pytest.fixture
def program(client):
    """Return a function that runs MOO statements as a verb and returns the eval result."""
    obj = assert_moo_success(client.eval('create(#1)'))
    counter = [0]

    def run(lines):
        counter[0] += 1
        name = f"run{counter[0]}"
        assert_moo_success(client.eval(f'add_verb({obj}, {{player, "rxd", "{name}"}}, {{"this", "none", "this"}})'))
        code = ", ".join('"' + line.replace('\\', '\\\\').replace('"', '\\"') + '"' for line in lines)
        assert assert_moo_success(client.eval(f'set_verb_code({obj}, "{name}", {{{code}}})')) == '{}'
        return client.eval(f'{obj}:{name}()')

    run.obj = obj
    return run


def set_server_option(client, name, value):
    """Set a $server_options property and reload the options."""
    if '"server_options"' not in assert_moo_success(client.eval('properties(#0)')):
        assert_moo_success(client.eval('add_property(#0, "server_options", create(#1), {player, "r"})'))
    assert_moo_success(client.eval(f'add_property(#0.server_options, "{name}", {value}, {{player, "r"}})'))
    assert_moo_success(client.eval('load_server_options()'))


class TestWrappingArithmetic:
    """Integer overflow wraps around, as it always has in practice."""

    def test_add_subtract_multiply_wrap(self, client, limits):
        """max + 1 is min, min - 1 is max, and an overflowing product wraps."""
        low, high = limits
        result = assert_moo_success(client.eval(f'{{{high} + 1, ({low}) - 1, {high} * 2}}'))
        assert result == f'{{{low}, {high}, -2}}'

    def test_negating_the_minimum(self, client, limits):
        """-min and abs(min) wrap to min."""
        low, _ = limits
        result = assert_moo_success(client.eval(f'{{-(x = {low}), abs({low})}}'))
        assert result == f'{{{low}, {low}}}'

    def test_power_of_minus_one_with_negative_exponent(self, client):
        """(-1) ^ -n is -1 for odd n and 1 for even n."""
        result = assert_moo_success(client.eval('{(-1) ^ -1, (-1) ^ -2, (-1) ^ -3}'))
        assert result == '{-1, 1, -1}'

    def test_power_overflow_wraps(self, client, requires_i64):
        """2 ^ 62 is exact and 2 ^ 63 wraps to the minimum."""
        result = assert_moo_success(client.eval('{2 ^ 62, 2 ^ 63, 2 ^ 64}'))
        assert result == f'{{4611686018427387904, {I64_MIN}, 0}}'

    def test_power_overflow_wraps_32bit(self, client, requires_no_i64):
        """2 ^ 30 is exact and 2 ^ 31 wraps to the minimum."""
        result = assert_moo_success(client.eval('{2 ^ 30, 2 ^ 31, 2 ^ 32}'))
        assert result == f'{{1073741824, {I32_MIN}, 0}}'

    def test_power_wraps_through_repeated_squaring(self, client, limits):
        """A power that overflows partway through squaring wraps to 3 ^ n mod 2 ^ bits."""
        low, high = limits
        exponent = 41 if high == I64_MAX else 21
        span = high - low + 1
        expected = (3 ** exponent - low) % span + low
        assert assert_moo_success(client.eval(f'3 ^ {exponent}')) == str(expected)

    def test_minimum_literal(self, client, limits):
        """The most negative integer can be written as a literal."""
        low, _ = limits
        assert assert_moo_success(client.eval(f'{{{low}, {low} + 1}}')) == f'{{{low}, {low + 1}}}'


class TestBuiltinArguments:
    """Builtins reject values their C argument types can't hold."""

    def test_bessel_order_beyond_int(self, client, requires_i64):
        """j() and y() reject an order that would truncate to a small int."""
        assert_moo_error(client.eval('j(4294967296, 1.0)'), 'Invalid argument')
        assert_moo_error(client.eval('y(4294967297, 1.0)'), 'Invalid argument')
        assert_moo_error(client.eval('j(-4294967296, 1.0)'), 'Invalid argument')

    def test_tochar_out_of_range(self, client, requires_unicode, requires_i64):
        """tochar() rejects code points that would truncate to a printable one."""
        assert_moo_error(client.eval('tochar(-4294967231)'), 'Invalid argument')
        assert_moo_error(client.eval('tochar(4294967361)'), 'Invalid argument')

    def test_encode_chars_out_of_range(self, client, requires_unicode, requires_i64):
        """encode_chars() rejects code points that would truncate to a valid one."""
        assert_moo_error(client.eval('encode_chars({4294967361}, "utf-8")'), 'Invalid argument')
        assert_moo_error(client.eval('encode_chars({-1}, "utf-8")'), 'Invalid argument')

    def test_verb_index_beyond_unsigned(self, client, requires_i64):
        """A verb index past 32 bits does not wrap around to verb 1."""
        obj = assert_moo_success(client.eval('create(#1)'))
        assert_moo_success(client.eval(f'add_verb({obj}, {{player, "rxd", "first"}}, {{"this", "none", "this"}})'))
        assert_moo_error(client.eval(f'verb_info({obj}, 4294967297)'), 'Invalid argument')
        assert_moo_error(client.eval(f'delete_verb({obj}, 4294967297)'), 'Invalid argument')
        assert assert_moo_success(client.eval(f'verbs({obj})')) == '{"first"}'

    def test_verb_preposition_number_beyond_long(self, client):
        """A numeric preposition that doesn't fit the table is rejected, not truncated."""
        obj = assert_moo_success(client.eval('create(#1)'))
        assert_moo_success(client.eval(f'add_verb({obj}, {{player, "rxd", "v"}}, {{"this", "none", "this"}})'))
        assert_moo_error(client.eval(f'set_verb_args({obj}, "v", {{"this", "4294967297", "this"}})'), 'Invalid argument')

    def test_substitute_offsets_beyond_int(self, client, requires_i64):
        """substitute() rejects offsets that would truncate into the subject."""
        groups = ', '.join(['{0, -1}'] * 8)
        subs = f'{{1, 3, {{{{4294967297, 4294967297}}, {groups}}}, "abc"}}'
        assert_moo_error(client.eval(f'substitute("%1", {subs})'), 'Invalid argument')

    def test_substitute_unmatched_group(self, client):
        """An unmatched group {0, -1} substitutes as the empty string."""
        groups = ', '.join(['{0, -1}'] * 9)
        result = assert_moo_success(client.eval(f'substitute("<%1>", {{1, 3, {{{groups}}}, "abc"}})'))
        assert result == '"<>"'

    def test_listen_port_out_of_range(self, client):
        """listen() rejects a port that would wrap onto a low one."""
        assert_moo_error(client.eval('listen(#0, 65536 + 7777)'), 'Invalid argument')
        assert_moo_error(client.eval('listen(#0, -1)'), 'Invalid argument')
        assert_server_alive(client)


class TestTaskDelays:
    """fork and suspend() delays are not truncated to 32 bits."""

    def test_fork_delay_beyond_unsigned(self, client, program, requires_i64):
        """A fork delayed by 2^32 seconds stays queued in the far future."""
        result = assert_moo_success(program([
            "fork t (4294967296)",
            "  return;",
            "endfork",
            "for q in (queued_tasks())",
            "  if (q[1] == t)",
            "    kill_task(t);",
            "    return q[2] > time() + 3600;",
            "  endif",
            "endfor",
            "return \"not queued\";",
        ]))
        assert result == '1'

    def test_fork_delay_maxint(self, client, program, limits):
        """A fork delayed by the largest integer stays queued."""
        _, high = limits
        result = assert_moo_success(program([
            f"fork t ({high})",
            "  return;",
            "endfork",
            "for q in (queued_tasks())",
            "  if (q[1] == t)",
            "    kill_task(t);",
            "    return q[2] > time() + 3600;",
            "  endif",
            "endfor",
            "return \"not queued\";",
        ]))
        assert result == '1'
        assert_server_alive(client)

    @pytest.mark.parametrize("seconds", [4294967296, 2147483648, I64_MAX],
                             ids=["2^32", "2^31", "maxint"])
    def test_suspend_beyond_int(self, client, program, requires_i64, seconds):
        """suspend() with a delay past 32 bits stays suspended instead of waking at once."""
        result = assert_moo_success(program([
            "fork t (0)",
            f"  suspend({seconds});",
            "endfork",
            "suspend(0);",
            "for q in (queued_tasks())",
            "  if (q[1] == t)",
            "    kill_task(t);",
            "    return q[2] > time() + 3600;",
            "  endif",
            "endfor",
            "return \"not queued\";",
        ]))
        assert result == '1'


class TestServerOptions:
    """Wizard-set limits are clamped as integers, not truncated."""

    def test_negative_max_stack_depth(self, client):
        """A negative max_stack_depth falls back to the default instead of a huge stack."""
        set_server_option(client, "max_stack_depth", -1)
        assert assert_moo_success(client.eval('1 + 1')) == '2'
        assert_server_alive(client)

    def test_huge_fg_ticks(self, client, requires_i64):
        """fg_ticks of 2^32 + 1 is a huge limit, not a tiny one."""
        set_server_option(client, "fg_ticks", 4294967297)
        assert int(assert_moo_success(client.eval('ticks_left()'))) > 1000000
