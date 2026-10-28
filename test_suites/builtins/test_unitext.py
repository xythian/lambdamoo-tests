"""Unicode text builtins from --enable-unitext.

A server built with the extension lists "unitext" in
server_version("features") and must have every builtin tested here;
one without it has none of them.  The builtins work without Unicode too,
treating every character as one ASCII character.

string_width() (WID-001 onward)
-------------------------------

string_width(str) returns the number of terminal columns str occupies, so
MOO code can pad fixed-width columns (@who and the like) around names that
contain emoji or East Asian characters.  length() counts characters, which
is one column short for every wide character.
"""

import string

import pytest

from lib.assertions import assert_moo_int, assert_moo_raises, assert_moo_success


PRINTABLE_ASCII = ''.join(chr(c) for c in range(0x20, 0x7f))


def moo_literal(text: str) -> str:
    """Quote text as a MOO string literal."""
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


class TestStringWidth:
    """string_width() on servers that have it."""

    pytestmark = pytest.mark.usefixtures("requires_unitext")

    def test_wid_001_ascii_is_one_column_each(self, client):
        """WID-001: every printable ASCII character is one column."""
        assert_moo_int(client.eval(f'string_width({moo_literal(PRINTABLE_ASCII)})'),
                       len(PRINTABLE_ASCII))

    def test_wid_002_empty_string(self, client):
        """WID-002: the empty string is zero columns."""
        assert_moo_int(client.eval('string_width("")'), 0)

    def test_wid_003_matches_length_for_ascii(self, client):
        """WID-003: for ASCII text width and length() agree."""
        text = string.ascii_letters + string.digits + " Xythian Tent"
        width = assert_moo_success(client.eval(f'string_width({moo_literal(text)})'))
        length = assert_moo_success(client.eval(f'length({moo_literal(text)})'))
        assert width == length

    def test_wid_004_tab_counts_as_one(self, client):
        """WID-004: tab counts as one column, like length()."""
        assert_moo_int(client.eval('string_width("a" + tochar(9) + "b")'), 3)

    def test_wid_005_wrong_type(self, client):
        """WID-005: a non-string argument raises E_TYPE."""
        assert_moo_raises(client, 'string_width(17)', 'E_TYPE')
        assert_moo_raises(client, 'string_width({"a"})', 'E_TYPE')

    def test_wid_006_wrong_arg_count(self, client):
        """WID-006: string_width() takes exactly one argument."""
        assert_moo_raises(client, 'string_width()', 'E_ARGS')
        assert_moo_raises(client, 'string_width("a", "b")', 'E_ARGS')

    def test_wid_007_function_info(self, client):
        """WID-007: function_info() describes the builtin as (STR) -> 1..1 args."""
        result = assert_moo_success(client.eval('function_info("string_width")'))
        assert result == '{"string_width", 1, 1, {2}}'


class TestStringWidthUnicode:
    """Display widths of non-ASCII characters on a Unicode server."""

    pytestmark = pytest.mark.usefixtures("requires_unitext", "requires_unicode")

    @pytest.mark.parametrize("text, width", [
        pytest.param('\U0001F991', 2, id="emoji-squid"),
        pytest.param('\U0001F479', 2, id="emoji-ogre"),
        pytest.param('\U0001F9DB', 2, id="emoji-vampire"),
        pytest.param('中文', 4, id="cjk-ideographs"),
        pytest.param('한', 2, id="hangul-syllable"),
        pytest.param('ＡＢ', 4, id="fullwidth-latin"),
        pytest.param('ᴋᴇɴ', 3, id="small-capitals"),
        pytest.param('café', 4, id="precomposed-accent"),
        pytest.param('αβ', 2, id="greek"),
    ])
    def test_wid_010_character_widths(self, client, text, width):
        """WID-010: wide characters are two columns, others one."""
        assert_moo_int(client.eval(f'string_width({moo_literal(text)})'), width)

    @pytest.mark.parametrize("text", [
        pytest.param('́', id="combining-acute"),
        pytest.param('‍', id="zero-width-joiner"),
        pytest.param('​', id="zero-width-space"),
        pytest.param('️', id="variation-selector-16"),
        pytest.param('­', id="soft-hyphen"),
        pytest.param('ᅠ', id="hangul-medial-vowel"),
    ])
    def test_wid_011_zero_width_characters(self, client, text):
        """WID-011: combining marks and format characters take no column."""
        assert_moo_int(client.eval(f'string_width({moo_literal(text)})'), 0)

    def test_wid_012_combining_sequence(self, client):
        """WID-012: a base letter plus a combining mark is one column, two characters."""
        text = 'é'
        assert_moo_int(client.eval(f'string_width({moo_literal(text)})'), 1)
        assert_moo_int(client.eval(f'length({moo_literal(text)})'), 2)

    @pytest.mark.parametrize("name, width", [
        pytest.param('\U0001F991 KRAKEN', 9, id="leading-emoji"),
        pytest.param('\U0001F525balwRog\U0001F525', 11, id="emoji-both-ends"),
        pytest.param('stuckula \U0001F9DB', 11, id="trailing-emoji"),
        pytest.param('Franᴋᴇɴɴʏstei', 13, id="small-caps"),
    ])
    def test_wid_013_who_names(self, client, name, width):
        """WID-013: names from a Halloween @who are one column wider per emoji than length()."""
        assert_moo_int(client.eval(f'string_width({moo_literal(name)})'), width)
        emoji = sum(1 for ch in name if ord(ch) >= 0x1F000)
        assert_moo_int(client.eval(f'length({moo_literal(name)})'), width - emoji)


class TestStringWidthAscii:
    """string_width() on a server built without Unicode."""

    pytestmark = pytest.mark.usefixtures("requires_unitext", "requires_no_unicode")

    def test_wid_020_every_character_is_one_column(self, client):
        """WID-020: without Unicode, width always equals length()."""
        text = PRINTABLE_ASCII + "~F0~9F~A6~91"
        assert_moo_int(client.eval(f'string_width({moo_literal(text)})'), len(text))


class TestNoUnitext:
    """Servers built without the unitext extension."""

    pytestmark = pytest.mark.usefixtures("requires_no_unitext")

    def test_wid_030_function_info_rejects_name(self, client):
        """WID-030: function_info() reports no such builtin."""
        assert_moo_raises(client, 'function_info("string_width")', 'E_INVARG')

    def test_wid_031_call_does_not_compile(self, client):
        """WID-031: code naming string_width() directly fails to compile."""
        success, output = client.eval('string_width("x")')
        assert not success
        assert 'Unknown built-in function: string_width' in output

    def test_wid_032_call_function_fallback(self, client):
        """WID-032: call_function() raises E_INVARG, so code can fall back to length()."""
        assert_moo_raises(client, 'call_function("string_width", "x")', 'E_INVARG')
        assert_moo_int(client.eval(
            '`call_function("string_width", "ab") ! E_INVARG => length("ab")\''), 2)
