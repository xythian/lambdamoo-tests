"""Huge indexes and range ends must give E_RANGE or a value, never a crash.

Waterpoint panicked on ``;"abc"[1..9223372036854775807]``.  OP_RANGE_REF
computed the end of the range as ``to + 1``, which wrapped to the most
negative integer, so the range looked empty and passed the bounds check.
substr() then subtracted the indexes, wrapped back to a huge length, and
memcpy() ran off the end of the string.  The same class of overflow lived
in range assignment, string index assignment, the Unicode character to
byte index translation, ``after - first`` in substr() itself, and the
position argument of listinsert()/listappend().
"""

import pytest

from lib.assertions import assert_moo_success


I64_MAX = 9223372036854775807
I32_MAX = 2147483647


def assert_server_alive(client):
    """The server must still answer after the expression."""
    assert assert_moo_success(client.eval('1 + 1')) == '2'


def assert_range_error(client, expression):
    """The expression raises E_RANGE and the server survives it."""
    success, output = client.eval(expression)
    assert not success, f"{expression} should raise E_RANGE, got {output}"
    assert 'Range error' in output or 'E_RANGE' in output, output
    assert_server_alive(client)


def run_statements(client, code):
    """Run MOO statements with eval() and return its result."""
    escaped = code.replace('\\', '\\\\').replace('"', '\\"')
    return client.eval(f'eval("{escaped}")')


@pytest.fixture
def maxint(detected_features):
    """The server's largest integer."""
    return I64_MAX if detected_features.has_i64 else I32_MAX


class TestRangeReference:
    """``x[from..to]`` with ``to`` or ``from`` at the integer limits."""

    def test_string_range_to_maxint(self, client, maxint):
        """The expression that crashed Waterpoint raises E_RANGE."""
        assert_range_error(client, f'"abc"[1..{maxint}]')

    def test_list_range_to_maxint(self, client, maxint):
        """A list range ending at the largest integer raises E_RANGE instead of returning {}."""
        assert_range_error(client, f'{{1, 2, 3}}[1..{maxint}]')

    def test_range_maxint_to_maxint(self, client, maxint):
        """A one-element range past the end is E_RANGE, not empty."""
        assert_range_error(client, f'"abc"[{maxint}..{maxint}]')
        assert_range_error(client, f'{{1}}[{maxint}..{maxint}]')

    def test_empty_range_with_extreme_ends(self, client, maxint):
        """An empty range from the largest integer down to a very negative one is empty."""
        result = assert_moo_success(client.eval(f'"abc"[{maxint}..-{maxint}]'))
        assert result == '""'
        result = assert_moo_success(client.eval(f'{{1, 2}}[{maxint}..-{maxint}]'))
        assert result == '{}'

    def test_empty_range_just_below_maxint(self, client, maxint):
        """``[max..max-1]`` is an ordinary empty range."""
        result = assert_moo_success(client.eval(f'{{"abc"[{maxint}..{maxint - 1}], {{1}}[{maxint}..{maxint - 1}]}}'))
        assert result == '{"", {}}'

    def test_multibyte_string_range_near_maxint(self, client, requires_unicode, maxint):
        """Translating huge character indexes to byte indexes does not overflow."""
        assert_range_error(client, f'"é"[1..{maxint - 1}]')
        assert_range_error(client, f'"éé"[1..{maxint}]')
        result = assert_moo_success(client.eval(f'"éé"[{maxint - 2}..{maxint - 3}]'))
        assert result == '""'
        result = assert_moo_success(client.eval(f'"éé"[{maxint - 1}..-{maxint}]'))
        assert result == '""'


class TestIndexReference:
    """``x[i]`` with ``i`` at the integer limit."""

    def test_index_maxint(self, client, maxint):
        """Indexing at the largest integer raises E_RANGE."""
        assert_range_error(client, f'"abc"[{maxint}]')
        assert_range_error(client, f'{{1}}[{maxint}]')

    def test_multibyte_index_maxint(self, client, requires_unicode, maxint):
        """A huge character index into a multibyte string raises E_RANGE."""
        assert_range_error(client, f'"é"[{maxint}]')


class TestAssignment:
    """Index and range assignment with indexes at the integer limit."""

    def test_string_index_assign_maxint(self, client, maxint):
        """``s[max] = c`` raises E_RANGE."""
        assert_range_error(client, f'eval("s = \\"abc\\"; s[{maxint}] = \\"x\\";")')

    def test_multibyte_string_index_assign_maxint(self, client, requires_unicode, maxint):
        """``s[max] = c`` on a multibyte string raises E_RANGE."""
        assert_range_error(client, f'eval("s = \\"é\\"; s[{maxint}] = \\"x\\";")')

    def test_string_range_assign_to_maxint(self, client, maxint):
        """A range assignment ending at the largest integer replaces the tail, like any end past the length."""
        result = assert_moo_success(run_statements(client, f's = "abc"; s[2..{maxint}] = "z"; return s;'))
        assert result == '{1, "az"}'
        result = assert_moo_success(run_statements(client, f's = "abc"; s[2..{maxint - 1}] = "z"; return s;'))
        assert result == '{1, "az"}'

    def test_list_range_assign_to_maxint(self, client, maxint):
        """A list range assignment ending at the largest integer replaces the tail."""
        result = assert_moo_success(run_statements(client, f'l = {{1, 2, 3}}; l[2..{maxint}] = {{9}}; return l;'))
        assert result == '{1, {1, 9}}'
        result = assert_moo_success(run_statements(client, f'l = {{1, 2, 3}}; l[2..{maxint}] = {{}}; return l;'))
        assert result == '{1, {1}}'

    def test_range_assign_from_maxint(self, client, maxint):
        """A range assignment starting past the end raises E_RANGE."""
        assert_range_error(client, f'eval("s = \\"abc\\"; s[{maxint}..5] = \\"x\\";")')
        assert_range_error(client, f'eval("l = {{1}}; l[{maxint}..5] = {{2}};")')

    def test_multibyte_range_assign_from_maxint(self, client, requires_unicode, maxint):
        """A huge start index on a multibyte string raises E_RANGE instead of wrapping negative."""
        assert_range_error(client, f'eval("s = \\"é\\"; s[{maxint}..5] = \\"x\\";")')


class TestListInsertPosition:
    """listinsert()/listappend() clamp the position without overflowing."""

    def test_listappend_maxint(self, client, maxint):
        """Appending after the largest index appends at the end."""
        result = assert_moo_success(client.eval(f'listappend({{1, 2}}, 3, {maxint})'))
        assert result == '{1, 2, 3}'

    def test_listinsert_maxint(self, client, maxint):
        """Inserting at the largest index appends at the end."""
        result = assert_moo_success(client.eval(f'listinsert({{1, 2}}, 3, {maxint})'))
        assert result == '{1, 2, 3}'

    def test_listinsert_beyond_32_bits(self, client, requires_i64):
        """A position that truncates to a small int still means past the end."""
        result = assert_moo_success(client.eval('listinsert({1, 2, 3}, "x", 4294967298)'))
        assert result == '{1, 2, 3, "x"}'

    def test_listinsert_most_negative(self, client, maxint):
        """A very negative position inserts at the front."""
        result = assert_moo_success(client.eval(f'listinsert({{1, 2}}, 3, -{maxint} - 1)'))
        assert result == '{3, 1, 2}'
        result = assert_moo_success(client.eval(f'listappend({{1, 2}}, 3, -{maxint} - 1)'))
        assert result == '{3, 1, 2}'
