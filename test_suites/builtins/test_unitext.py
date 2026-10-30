"""Unicode text builtins from --enable-unitext.

A server built with the extension lists "unitext" in
server_version("features") and must have every builtin tested here;
one without it has none of them.  The builtins work without Unicode too,
treating every character as one ASCII character.

string_width() (WID-001 onward), graphemes() (GRA-001 onward)
-------------------------------------------------------------

string_width(str) returns the number of terminal columns str occupies, so
MOO code can pad fixed-width columns (@who and the like) around names that
contain emoji or East Asian characters.  length() counts characters, which
is one column short for every wide character.  It measures each grapheme
cluster once, so an emoji ZWJ sequence or a flag is two columns, not the
sum of its parts.  graphemes(str) splits str into those clusters.

normalize() (NRM-001 onward), casefold() (CF-001 onward)
--------------------------------------------------------

normalize(str [, form]) returns str in Unicode normalization form NFC (the
default), NFD, NFKC or NFKD.  casefold(str) applies full case folding, so
names can be compared without regard to case even where == cannot (sharp s).

wrap() (WRP-001 onward)
-----------------------

wrap(str, width) breaks str into lines no wider than width columns, at the
places Unicode line breaking allows, or inside a word too long for a line.

char_category() and char_script() (CHR-001 onward)
--------------------------------------------------

char_category(ch) returns a one-character string's Unicode General Category
("Lu", "So", ...) and char_script(ch) its Script ("Latin", "Cyrillic",
"Common", ...), for example to spot look-alike letters in a name.
"""

import string
import unicodedata

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
        pytest.param('\u4E2D\u6587', 4, id="cjk-ideographs"),
        pytest.param('\uD55C', 2, id="hangul-syllable"),
        pytest.param('\uFF21\uFF22', 4, id="fullwidth-latin"),
        pytest.param('\u1D0B\u1D07\u0274', 3, id="small-capitals"),
        pytest.param('caf\u00E9', 4, id="precomposed-accent"),
        pytest.param('\u03B1\u03B2', 2, id="greek"),
    ])
    def test_wid_010_character_widths(self, client, text, width):
        """WID-010: wide characters are two columns, others one."""
        assert_moo_int(client.eval(f'string_width({moo_literal(text)})'), width)

    @pytest.mark.parametrize("text", [
        pytest.param('\u0301', id="combining-acute"),
        pytest.param('\u200D', id="zero-width-joiner"),
        pytest.param('\u200B', id="zero-width-space"),
        pytest.param('\uFE0F', id="variation-selector-16"),
        pytest.param('\u00AD', id="soft-hyphen"),
        pytest.param('\u1160', id="hangul-medial-vowel"),
    ])
    def test_wid_011_zero_width_characters(self, client, text):
        """WID-011: combining marks and format characters take no column."""
        assert_moo_int(client.eval(f'string_width({moo_literal(text)})'), 0)

    def test_wid_012_combining_sequence(self, client):
        """WID-012: a base letter plus a combining mark is one column, two characters."""
        text = 'e\u0301'
        assert_moo_int(client.eval(f'string_width({moo_literal(text)})'), 1)
        assert_moo_int(client.eval(f'length({moo_literal(text)})'), 2)

    @pytest.mark.parametrize("name, width", [
        pytest.param('\U0001F991 KRAKEN', 9, id="leading-emoji"),
        pytest.param('\U0001F525balwRog\U0001F525', 11, id="emoji-both-ends"),
        pytest.param('stuckula \U0001F9DB', 11, id="trailing-emoji"),
        pytest.param('Fran\u1D0B\u1D07\u0274\u0274\u028Fstei', 13, id="small-caps"),
    ])
    def test_wid_013_who_names(self, client, name, width):
        """WID-013: names from a Halloween @who are one column wider per emoji than length()."""
        assert_moo_int(client.eval(f'string_width({moo_literal(name)})'), width)
        emoji = sum(1 for ch in name if ord(ch) >= 0x1F000)
        assert_moo_int(client.eval(f'length({moo_literal(name)})'), width - emoji)


class TestGraphemeWidth:
    """string_width() counts each grapheme cluster once."""

    pytestmark = pytest.mark.usefixtures("requires_unitext", "requires_unicode")

    @pytest.mark.parametrize("text, width", [
        pytest.param('\U0001F468\u200D\U0001F469\u200D\U0001F467', 2, id="zwj-family"),
        pytest.param('\U0001F9DF\u200D\u2642\uFE0F', 2, id="zwj-with-selector"),
        pytest.param('\U0001F44D\U0001F3FD', 2, id="skin-tone-modifier"),
        pytest.param('\u2764\uFE0F', 2, id="emoji-presentation-selector"),
        pytest.param('\u2764', 1, id="text-presentation-heart"),
        pytest.param('1\uFE0F\u20E3', 2, id="keycap"),
        pytest.param('\U0001F1FA\U0001F1F8', 2, id="flag"),
        pytest.param('\U0001F1FA\U0001F1F8\U0001F1EB\U0001F1F7', 4, id="two-flags"),
        pytest.param('\u1100\u1161\u11A8', 2, id="hangul-conjoining-jamo"),
        pytest.param('\U0001F9DB\u200D\u2640\uFE0F Mina', 7, id="name-with-zwj-emoji"),
    ])
    def test_wid_014_grapheme_widths(self, client, text, width):
        """WID-014: emoji sequences, flags and conjoining jamo are one cluster wide."""
        assert_moo_int(client.eval(f'string_width({moo_literal(text)})'), width)


class TestGraphemes:
    """graphemes() splits a string into user-perceived characters (GRA-001 onward)."""

    pytestmark = pytest.mark.usefixtures("requires_unitext")

    def test_gra_001_ascii(self, client):
        """GRA-001: each ASCII character is its own grapheme."""
        assert assert_moo_success(client.eval('graphemes("abc")')) == '{"a", "b", "c"}'

    def test_gra_002_empty(self, client):
        """GRA-002: the empty string has no graphemes."""
        assert assert_moo_success(client.eval('graphemes("")')) == '{}'

    def test_gra_003_wrong_type(self, client):
        """GRA-003: a non-string argument raises E_TYPE."""
        assert_moo_raises(client, 'graphemes(1)', 'E_TYPE')

    def test_gra_004_rejoins(self, client):
        """GRA-004: joining the graphemes gives back the string."""
        text = PRINTABLE_ASCII
        assert_moo_int(client.eval(f'length(graphemes({moo_literal(text)}))'), len(text))
        result = assert_moo_success(client.eval(
            f'tostr(@graphemes({moo_literal(text)})) == {moo_literal(text)}'))
        assert result == '1'


class TestGraphemesUnicode:
    """graphemes() keeps multi-codepoint characters together."""

    pytestmark = pytest.mark.usefixtures("requires_unitext", "requires_unicode")

    @pytest.mark.parametrize("text, clusters", [
        pytest.param('e\u0301x', ['e\u0301', 'x'], id="combining-mark"),
        pytest.param('\U0001F468\u200D\U0001F469\u200D\U0001F467!',
                     ['\U0001F468\u200D\U0001F469\u200D\U0001F467', '!'], id="zwj-family"),
        pytest.param('\U0001F44D\U0001F3FD', ['\U0001F44D\U0001F3FD'], id="skin-tone"),
        pytest.param('\U0001F1FA\U0001F1F8\U0001F1EB\U0001F1F7',
                     ['\U0001F1FA\U0001F1F8', '\U0001F1EB\U0001F1F7'], id="two-flags"),
        pytest.param('\u1100\u1161\u11A8\uD55C', ['\u1100\u1161\u11A8', '\uD55C'],
                     id="hangul"),
        pytest.param('\U0001F991 KRAKEN', ['\U0001F991', ' ', 'K', 'R', 'A', 'K', 'E', 'N'],
                     id="who-name"),
    ])
    def test_gra_010_clusters(self, client, text, clusters):
        """GRA-010: combining marks, ZWJ sequences, modifiers and flag pairs stay whole."""
        expected = '{' + ', '.join(moo_literal(c) for c in clusters) + '}'
        assert assert_moo_success(client.eval(f'graphemes({moo_literal(text)})')) == expected

    def test_gra_011_truncate_without_splitting(self, client):
        """GRA-011: truncating by graphemes never cuts an emoji sequence in half."""
        text = 'ab\U0001F468\u200D\U0001F469\u200D\U0001F467cd'
        result = assert_moo_success(client.eval(f'tostr(@graphemes({moo_literal(text)})[1..3])'))
        assert result == moo_literal('ab\U0001F468\u200D\U0001F469\u200D\U0001F467')


def string_limit(client, limit):
    """Make strings longer than limit bytes raise E_QUOTA."""
    if '"server_options"' not in assert_moo_success(client.eval('properties(#0)')):
        assert_moo_success(client.eval('add_property(#0, "server_options", create(#1), {player, "r"})'))
    assert_moo_success(client.eval(f'add_property(#0.server_options, "max_string_concat", {limit}, {{player, "r"}})'))
    assert_moo_success(client.eval('add_property(#0.server_options, "max_concat_catchable", 1, {player, "r"})'))
    assert_moo_success(client.eval('load_server_options()'))


class TestNormalize:
    """normalize(str [, form]) (NRM-001 onward)."""

    pytestmark = pytest.mark.usefixtures("requires_unitext")

    def test_nrm_001_ascii_unchanged(self, client):
        """NRM-001: ASCII text is the same in every form."""
        for form in ("NFC", "NFD", "NFKC", "NFKD"):
            result = assert_moo_success(client.eval(f'normalize({moo_literal(PRINTABLE_ASCII)}, "{form}")'))
            assert result == moo_literal(PRINTABLE_ASCII)

    def test_nrm_002_form_names(self, client):
        """NRM-002: the form defaults to NFC and its name ignores case."""
        assert assert_moo_success(client.eval('normalize("abc")')) == '"abc"'
        assert assert_moo_success(client.eval('normalize("abc", "nfkd")')) == '"abc"'

    def test_nrm_003_bad_form(self, client):
        """NRM-003: an unknown form raises E_INVARG."""
        assert_moo_raises(client, 'normalize("abc", "NFX")', 'E_INVARG')
        assert_moo_raises(client, 'normalize("abc", "")', 'E_INVARG')

    def test_nrm_004_wrong_types(self, client):
        """NRM-004: non-string arguments raise E_TYPE; extra ones E_ARGS."""
        assert_moo_raises(client, 'normalize(1)', 'E_TYPE')
        assert_moo_raises(client, 'normalize("a", 1)', 'E_TYPE')
        assert_moo_raises(client, 'normalize("a", "NFC", 1)', 'E_ARGS')


class TestNormalizeUnicode:
    """Composition and compatibility mappings on a Unicode server."""

    pytestmark = pytest.mark.usefixtures("requires_unitext", "requires_unicode")

    @pytest.mark.parametrize("text, form, expected", [
        pytest.param('e\u0301', 'NFC', '\u00E9', id="compose-acute"),
        pytest.param('\u00E9', 'NFD', 'e\u0301', id="decompose-acute"),
        pytest.param('\u00E9', 'NFC', '\u00E9', id="already-composed"),
        pytest.param('\u1100\u1161\u11A8', 'NFC', '\uAC01', id="compose-hangul"),
        pytest.param('\uFF21\uFF22\uFF23', 'NFKC', 'ABC', id="fullwidth-to-ascii"),
        pytest.param('\uFF21\uFF22\uFF23', 'NFC', '\uFF21\uFF22\uFF23', id="fullwidth-kept-by-nfc"),
        pytest.param('\uFB01', 'NFKC', 'fi', id="ligature"),
        pytest.param('\u2460', 'NFKD', '1', id="circled-digit"),
        pytest.param('\u1D0B', 'NFKC', '\u1D0B', id="small-capital-has-no-mapping"),
    ])
    def test_nrm_010_forms(self, client, text, form, expected):
        """NRM-010: each form composes, decomposes or maps compatibility characters."""
        result = assert_moo_success(client.eval(f'normalize({moo_literal(text)}, "{form}")'))
        assert result == moo_literal(expected)

    def test_nrm_011_makes_spellings_equal(self, client):
        """NRM-011: two spellings of the same name compare equal once normalized."""
        composed = moo_literal('Jos\u00E9')
        decomposed = moo_literal('Jose\u0301')
        result = assert_moo_success(client.eval(
            f'{{{composed} == {decomposed}, normalize({composed}) == normalize({decomposed})}}'))
        assert result == '{0, 1}'

    def test_nrm_012_result_too_long(self, client):
        """NRM-012: a result longer than max_string_concat raises E_QUOTA."""
        string_limit(client, 1015)
        text = '\uFDFA' * 100
        assert_moo_int(client.eval(f'length(normalize({moo_literal(text)}, "NFC"))'), 100)
        assert_moo_raises(client, f'normalize({moo_literal(text)}, "NFKD")', 'E_QUOTA')


class TestCasefold:
    """casefold(str) (CF-001 onward)."""

    pytestmark = pytest.mark.usefixtures("requires_unitext")

    def test_cf_001_ascii(self, client):
        """CF-001: ASCII letters fold to lower case; the rest is unchanged."""
        result = assert_moo_success(client.eval(f'casefold({moo_literal(PRINTABLE_ASCII)})'))
        assert result == moo_literal(PRINTABLE_ASCII.lower())

    def test_cf_002_wrong_type(self, client):
        """CF-002: a non-string argument raises E_TYPE."""
        assert_moo_raises(client, 'casefold(1)', 'E_TYPE')


class TestCasefoldUnicode:
    """Full case folding on a Unicode server."""

    pytestmark = pytest.mark.usefixtures("requires_unitext", "requires_unicode")

    @pytest.mark.parametrize("text, expected", [
        pytest.param('Stra\u00DFe', 'strasse', id="sharp-s-expands"),
        pytest.param('\u1E9E', 'ss', id="capital-sharp-s"),
        pytest.param('\u039F\u0394\u03A5\u03A3\u03A3\u0395\u03A5\u03A3',
                     '\u03BF\u03B4\u03C5\u03C3\u03C3\u03B5\u03C5\u03C3', id="greek-sigma"),
        pytest.param('\u0130', 'i\u0307', id="dotted-capital-i"),
        pytest.param('\uFB01', 'fi', id="ligature"),
        pytest.param('\U0001F991 KRAKEN', '\U0001F991 kraken', id="emoji-unchanged"),
    ])
    def test_cf_010_full_folding(self, client, text, expected):
        """CF-010: folding uses the full mappings, which can change the length."""
        result = assert_moo_success(client.eval(f'casefold({moo_literal(text)})'))
        assert result == moo_literal(expected)

    def test_cf_011_matches_where_equality_does_not(self, client):
        """CF-011: == misses STRASSE vs Stra\u00DFe; casefold() makes them equal."""
        strasse = moo_literal('Stra\u00DFe')
        result = assert_moo_success(client.eval(
            f'{{"STRASSE" == {strasse}, casefold("STRASSE") == casefold({strasse})}}'))
        assert result == '{0, 1}'


class TestCharInfo:
    """char_category(ch) and char_script(ch) (CHR-001 onward)."""

    pytestmark = pytest.mark.usefixtures("requires_unitext")

    def test_chr_001_ascii_categories(self, client):
        """CHR-001: every printable ASCII character has its Unicode General Category."""
        calls = ', '.join(f'char_category({moo_literal(c)})' for c in PRINTABLE_ASCII)
        result = assert_moo_success(client.eval(f'tostr(@{{{calls}}})'))
        expected = ''.join(unicodedata.category(c) for c in PRINTABLE_ASCII)
        assert result == moo_literal(expected)

    def test_chr_002_ascii_scripts(self, client):
        """CHR-002: ASCII letters are Latin; digits, spaces and punctuation are Common."""
        for ch, script in (("A", "Latin"), ("z", "Latin"), ("7", "Common"),
                           (" ", "Common"), ("~", "Common")):
            assert assert_moo_success(client.eval(f'char_script({moo_literal(ch)})')) == moo_literal(script)

    def test_chr_003_tab(self, client):
        """CHR-003: tab is a control character in the Common script."""
        assert assert_moo_success(client.eval('char_category(tochar(9))')) == '"Cc"'
        assert assert_moo_success(client.eval('char_script(tochar(9))')) == '"Common"'

    @pytest.mark.parametrize("fn", ["char_category", "char_script"])
    def test_chr_004_one_character_only(self, client, fn):
        """CHR-004: anything but a one-character string raises E_INVARG or E_TYPE."""
        assert_moo_raises(client, f'{fn}("")', 'E_INVARG')
        assert_moo_raises(client, f'{fn}("ab")', 'E_INVARG')
        assert_moo_raises(client, f'{fn}(65)', 'E_TYPE')


class TestCharInfoUnicode:
    """Categories and scripts of non-ASCII characters."""

    pytestmark = pytest.mark.usefixtures("requires_unitext", "requires_unicode")

    @pytest.mark.parametrize("ch, category, script", [
        pytest.param('\u0430', 'Ll', 'Cyrillic', id="cyrillic-a"),
        pytest.param('\u0410', 'Lu', 'Cyrillic', id="cyrillic-capital-a"),
        pytest.param('\u03B1', 'Ll', 'Greek', id="greek-alpha"),
        pytest.param('\u4E2D', 'Lo', 'Han', id="han"),
        pytest.param('\u1D0B', 'Ll', 'Latin', id="small-capital-k"),
        pytest.param('\U0001F991', 'So', 'Common', id="emoji"),
        pytest.param('\u0301', 'Mn', 'Inherited', id="combining-acute"),
        pytest.param('\u200D', 'Cf', 'Inherited', id="zero-width-joiner"),
        pytest.param('\u0661', 'Nd', 'Arabic', id="arabic-indic-digit"),
        pytest.param('\uE000', 'Co', 'Unknown', id="private-use"),
    ])
    def test_chr_010_category_and_script(self, client, ch, category, script):
        """CHR-010: non-ASCII characters report their category and script."""
        assert assert_moo_success(client.eval(f'char_category({moo_literal(ch)})')) == moo_literal(category)
        assert assert_moo_success(client.eval(f'char_script({moo_literal(ch)})')) == moo_literal(script)

    def test_chr_011_spots_mixed_script_name(self, client):
        """CHR-011: a Cyrillic look-alike in a Latin name shows up in its scripts."""
        name = 'X\u0443thian'
        calls = ', '.join(f'char_script({moo_literal(c)})' for c in name)
        result = assert_moo_success(client.eval(f'{{{calls}}}'))
        assert result == '{"Latin", "Cyrillic", "Latin", "Latin", "Latin", "Latin", "Latin"}'


def moo_list(items) -> str:
    """Write a list of Python strings as a MOO list literal."""
    return '{' + ', '.join(moo_literal(i) for i in items) + '}'


SENTENCE = ("The squid surfaced beside the tent, and everyone in the living room "
            "agreed it was the best Halloween costume this year by a mile.")


class TestWrap:
    """wrap(str, width) (WRP-001 onward)."""

    pytestmark = pytest.mark.usefixtures("requires_unitext")

    @pytest.mark.parametrize("text, width, lines", [
        pytest.param('the quick brown fox', 10, ['the quick', 'brown fox'], id="words"),
        pytest.param('aaaa bbbb', 4, ['aaaa', 'bbbb'], id="exact-fit"),
        pytest.param('abcdefghij', 4, ['abcd', 'efgh', 'ij'], id="long-word"),
        pytest.param('aa    bb', 3, ['aa', 'bb'], id="spaces-dropped-at-break"),
        pytest.param('short', 80, ['short'], id="fits"),
        pytest.param('well-known', 6, ['well-', 'known'], id="after-hyphen"),
        pytest.param('a   ', 10, ['a'], id="trailing-spaces"),
        pytest.param('', 10, [], id="empty"),
        pytest.param('   ', 10, [], id="only-spaces"),
    ])
    def test_wrp_001_lines(self, client, text, width, lines):
        """WRP-001: lines break between words, or inside a word too long for a line."""
        result = assert_moo_success(client.eval(f'wrap({moo_literal(text)}, {width})'))
        assert result == moo_list(lines)

    @pytest.mark.parametrize("width", [10, 20, 33, 79])
    def test_wrp_002_widths_and_words_kept(self, client, width):
        """WRP-002: no line is wider than asked, and the words come back in order.

        Every width is at least as long as the longest word, so the lines are
        what a greedy fill of whole words gives.
        """
        lines = assert_moo_success(client.eval(f'wrap({moo_literal(SENTENCE)}, {width})'))
        expected = []
        for word in SENTENCE.split(' '):
            if expected and len(expected[-1]) + 1 + len(word) <= width:
                expected[-1] += ' ' + word
            else:
                expected.append(word)
        assert all(len(line) <= width for line in expected)
        assert lines == moo_list(expected)

    def test_wrp_003_bad_width(self, client):
        """WRP-003: a width below 1 raises E_INVARG."""
        assert_moo_raises(client, 'wrap("abc", 0)', 'E_INVARG')
        assert_moo_raises(client, 'wrap("abc", -5)', 'E_INVARG')

    def test_wrp_004_wrong_types(self, client):
        """WRP-004: wrap() takes a string and an integer."""
        assert_moo_raises(client, 'wrap(1, 10)', 'E_TYPE')
        assert_moo_raises(client, 'wrap("abc", "10")', 'E_TYPE')
        assert_moo_raises(client, 'wrap("abc")', 'E_ARGS')


class TestWrapUnicode:
    """wrap() measures display width and keeps graphemes whole."""

    pytestmark = pytest.mark.usefixtures("requires_unitext", "requires_unicode")

    @pytest.mark.parametrize("text, width, lines", [
        pytest.param('\U0001F991 KRAKEN attacks', 9, ['\U0001F991 KRAKEN', 'attacks'], id="emoji-is-two-columns"),
        pytest.param('\U0001F991 KRAKEN attacks', 8, ['\U0001F991', 'KRAKEN', 'attacks'], id="emoji-overflows"),
        pytest.param('\u4E2D\u6587\u4E2D\u6587', 4, ['\u4E2D\u6587', '\u4E2D\u6587'], id="cjk-breaks-between-ideographs"),
        pytest.param('ab\U0001F468\u200D\U0001F469\u200D\U0001F467', 3,
                     ['ab', '\U0001F468\u200D\U0001F469\u200D\U0001F467'], id="zwj-sequence-kept-whole"),
        pytest.param('\u4E2D', 1, ['\u4E2D'], id="wider-than-line"),
        pytest.param('caf\u00E9 cre\u0300me', 5, ['caf\u00E9', 'cre\u0300me'], id="combining-mark-zero-width"),
    ])
    def test_wrp_010_lines(self, client, text, width, lines):
        """WRP-010: wide characters count two columns and clusters are never split."""
        result = assert_moo_success(client.eval(f'wrap({moo_literal(text)}, {width})'))
        assert result == moo_list(lines)


class TestStringWidthAscii:
    """The extension on a server built without Unicode."""

    pytestmark = pytest.mark.usefixtures("requires_unitext", "requires_no_unicode")

    def test_wid_020_every_character_is_one_column(self, client):
        """WID-020: without Unicode, width always equals length()."""
        text = PRINTABLE_ASCII + "~F0~9F~A6~91"
        assert_moo_int(client.eval(f'string_width({moo_literal(text)})'), len(text))

    def test_wid_021_graphemes_are_characters(self, client):
        """WID-021: without Unicode, each byte of a ~-escape is its own grapheme."""
        assert assert_moo_success(client.eval('graphemes("~F0")')) == '{"~", "F", "0"}'

    def test_wid_022_normalize_is_identity(self, client):
        """WID-022: without Unicode, every form leaves the string alone."""
        assert assert_moo_success(client.eval('normalize("~C3~A9", "NFKD")')) == '"~C3~A9"'


class TestNoUnitext:
    """Servers built without the unitext extension."""

    pytestmark = pytest.mark.usefixtures("requires_no_unitext")

    @pytest.mark.parametrize("name", ["string_width", "graphemes", "normalize", "casefold",
                                      "char_category", "char_script", "wrap"])
    def test_wid_030_function_info_rejects_name(self, client, name):
        """WID-030: function_info() reports none of the extension's builtins."""
        assert_moo_raises(client, f'function_info("{name}")', 'E_INVARG')

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
