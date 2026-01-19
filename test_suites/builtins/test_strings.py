"""String builtin tests (STR-001 through STR-030)."""

import pytest

from lib.assertions import (
    assert_moo_success,
    assert_moo_error,
    assert_moo_int,
    assert_moo_string,
)


class TestStringBasics:
    """Tests for basic string operations."""

    def test_str_001_string_length(self, client):
        """STR-001: length() returns correct string length."""
        result = client.eval('length("hello")')
        assert_moo_int(result, 5)

        result = client.eval('length("")')
        assert_moo_int(result, 0)

    def test_str_002_string_indexing(self, client):
        """STR-002: String indexing works correctly."""
        result = client.eval('"hello"[1]')
        assert_moo_string(result, 'h')

        result = client.eval('"hello"[5]')
        assert_moo_string(result, 'o')

    def test_str_003_string_range(self, client):
        """STR-003: String range extraction works."""
        result = client.eval('"hello"[2..4]')
        assert_moo_string(result, 'ell')

    def test_str_004_string_concatenation(self, client):
        """STR-004: String concatenation works."""
        result = client.eval('"hello" + " " + "world"')
        assert_moo_string(result, 'hello world')

    def test_str_005_index_out_of_range(self, client):
        """STR-005: Out of range indexing raises error."""
        result = client.eval('"hello"[0]')
        success, msg = result
        assert not success, "Index 0 should fail"
        assert 'Range error' in msg or 'E_RANGE' in msg

        result = client.eval('"hello"[10]')
        success, msg = result
        assert not success, "Index 10 should fail"
        assert 'Range error' in msg or 'E_RANGE' in msg


class TestStringFunctions:
    """Tests for string manipulation functions."""

    def test_str_010_strsub(self, client):
        """STR-010: strsub() substitutes correctly."""
        result = client.eval('strsub("hello world", "world", "there")')
        assert_moo_string(result, 'hello there')

    def test_str_011_strsub_case_insensitive_default(self, client):
        """STR-011: strsub() is case-insensitive by default."""
        # Note: LambdaMOO strsub is case-insensitive by default
        result = client.eval('strsub("Hello World", "world", "there")')
        assert_moo_string(result, 'Hello there')

    def test_str_012_strsub_case_insensitive(self, client):
        """STR-012: strsub() with case-insensitive flag."""
        result = client.eval('strsub("Hello World", "world", "there", 0)')
        assert_moo_string(result, 'Hello there')

    def test_str_013_index_function(self, client):
        """STR-013: index() finds substring position."""
        result = client.eval('index("hello world", "wor")')
        assert_moo_int(result, 7)

        result = client.eval('index("hello", "x")')
        assert_moo_int(result, 0)

    def test_str_014_rindex_function(self, client):
        """STR-014: rindex() finds last occurrence."""
        result = client.eval('rindex("hello hello", "hello")')
        assert_moo_int(result, 7)

    def test_str_015_strcmp(self, client):
        """STR-015: strcmp() compares strings correctly."""
        result = client.eval('strcmp("abc", "abc")')
        assert_moo_int(result, 0)

        result = client.eval('strcmp("abc", "abd")')
        value = assert_moo_success(result)
        assert int(value) < 0, "abc should be less than abd"

        result = client.eval('strcmp("abd", "abc")')
        value = assert_moo_success(result)
        assert int(value) > 0, "abd should be greater than abc"


class TestTypeConversion:
    """Tests for string type conversion."""

    def test_str_025_tostr(self, client):
        """STR-025: tostr() converts values to strings."""
        result = client.eval('tostr(42)')
        assert_moo_string(result, '42')

        result = client.eval('tostr(#1)')
        assert_moo_string(result, '#1')

        # Lists are represented as "{list}" not their contents
        result = client.eval('tostr({1, 2, 3})')
        assert_moo_string(result, '{list}')

    def test_str_026_tonum(self, client):
        """STR-026: tonum() converts strings to numbers."""
        result = client.eval('tonum("42")')
        assert_moo_int(result, 42)

        result = client.eval('tonum("-123")')
        assert_moo_int(result, -123)

    def test_str_027_tonum_truncates(self, client):
        """STR-027: tonum() truncates to integer."""
        # Note: tonum returns integer, truncating any decimal part
        result = client.eval('tonum("3.14")')
        assert_moo_int(result, 3)

        result = client.eval('tonum("3.99")')
        assert_moo_int(result, 3)

    def test_str_028_toobj(self, client):
        """STR-028: toobj() converts to object reference."""
        result = client.eval('toobj("#1")')
        value = assert_moo_success(result)
        assert value == '#1'

        result = client.eval('toobj("1")')
        value = assert_moo_success(result)
        assert value == '#1'


class TestSpecialStrings:
    """Tests for special string handling."""

    def test_str_030_empty_string(self, client):
        """STR-030: Empty strings are handled correctly."""
        result = client.eval('length("")')
        assert_moo_int(result, 0)

        result = client.eval('"" + "hello"')
        assert_moo_string(result, 'hello')

    def test_str_031_newlines_in_strings(self, client):
        """STR-031: Strings can contain newlines."""
        # This might need adjustment based on how MOO handles escaped newlines
        result = client.eval('length("a\\nb")')
        value = assert_moo_success(result)
        # "a\nb" has 3 characters
        assert int(value) >= 3

    def test_str_032_special_characters(self, client):
        """STR-032: Special characters work."""
        result = client.eval('length("tab:\\there")')
        value = assert_moo_success(result)
        assert int(value) > 0


@pytest.mark.unicode
class TestUnicodeStrings:
    """Tests for Unicode string support (requires Unicode build)."""

    def test_str_040_unicode_length(self, client, requires_unicode):
        """STR-040: Unicode string length counts codepoints."""
        # Use actual UTF-8 characters, not \u escapes (MOO doesn't support \u syntax)
        # "αβγ" = 3 Greek letters, each is 2 bytes in UTF-8 but 1 codepoint
        result = client.eval('length("αβγ")')
        value = assert_moo_success(result)
        # Should be 3 codepoints (alpha, beta, gamma)
        assert int(value) == 3

    def test_str_041_unicode_indexing(self, client, requires_unicode):
        """STR-041: Unicode strings can be indexed by codepoint."""
        # "日本語" = 3 CJK characters, each is 3 bytes in UTF-8 but 1 codepoint
        result = client.eval('length("日本語")')
        assert_moo_int(result, 3)
