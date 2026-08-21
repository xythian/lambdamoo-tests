"""Compatibility tests for MOO's match() and rmatch() builtins."""

import pytest

from lib.assertions import assert_moo_success


# The PCRE layer initializes absent byte offsets to (0, -1), then list.c runs
# both through utf_char_index().  The resulting public MOO sentinel is (1, 0).
NO_CAPTURE = (1, 0)


def moo_string(value):
    """Quote a Python string as a MOO string literal."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + escaped + '"'


def match_result(subject, start, end, *captures):
    """Render all four result elements, including all nine capture pairs."""
    captures = captures + (NO_CAPTURE,) * (9 - len(captures))
    pairs = ", ".join("{%d, %d}" % pair for pair in captures)
    return f"{{{start}, {end}, {{{pairs}}}, {moo_string(subject)}}}"


def assert_match(client, function, subject, pattern, expected, case_matters=None):
    args = [moo_string(subject), moo_string(pattern)]
    if case_matters is not None:
        args.append(str(case_matters))
    actual = assert_moo_success(client.eval(f"{function}({', '.join(args)})"))
    assert actual == expected


@pytest.mark.regexp
@pytest.mark.parametrize(
    "function,subject,pattern,expected",
    [
        ("match", "xxabcxx", "abc", match_result("xxabcxx", 3, 5)),
        ("rmatch", "abc abc", "abc", match_result("abc abc", 5, 7)),
        ("match", "abc", "z", "{}"),
        ("rmatch", "abc", "z", "{}"),
        ("match", "", "", match_result("", 1, 0)),
        ("rmatch", "", "", match_result("", 1, 0)),
        ("match", "abc", "", match_result("abc", 1, 0)),
        ("rmatch", "abc", "", match_result("abc", 4, 3)),
        ("match", "abc", "b*", match_result("abc", 1, 0)),
        ("rmatch", "abc", "b*", match_result("abc", 4, 3)),
        ("match", "axb", "a.b", match_result("axb", 1, 3)),
        ("match", "abbbc", "ab*c", match_result("abbbc", 1, 5)),
        ("match", "ac", "ab?c", match_result("ac", 1, 2)),
        ("match", "abbbc", "ab+c", match_result("abbbc", 1, 5)),
        ("match", "cat", "^cat$", match_result("cat", 1, 3)),
        ("match", "cat", "%<cat%>", match_result("cat", 1, 3)),
        ("match", "scat", "%<cat%>", "{}"),
        ("match", "x cat!", "%bcat%b", match_result("x cat!", 3, 5)),
        ("match", "ab", "a%Bb", match_result("ab", 1, 2)),
        ("match", "a_b", "%w+", match_result("a_b", 1, 1)),
        ("match", "a_b", "%W", match_result("a_b", 2, 2)),
        ("match", "abc-19", "[a-c0-9-]+", match_result("abc-19", 1, 6)),
        ("match", "ABC", "[^x]+", match_result("ABC", 1, 3)),
        ("match", "]-[", "[][-]+", match_result("]-[", 1, 3)),
        ("match", "a.c", "a%.c", match_result("a.c", 1, 3)),
        ("match", "a*c", "a%*c", match_result("a*c", 1, 3)),
        ("match", "a?c", "a%?c", match_result("a?c", 1, 3)),
        ("match", "a|b", "a|b", match_result("a|b", 1, 3)),
        ("match", "b", "a%|b", match_result("b", 1, 1)),
        ("match", "(a)", "(a)", match_result("(a)", 1, 3)),
        ("match", "a", "%(a%)", match_result("a", 1, 1, (1, 1))),
        ("match", "abab", "%(ab%)%1", match_result("abab", 1, 4, (1, 2))),
    ],
    ids=[
        "literal", "reverse-literal", "no-match", "reverse-no-match", "empty-both",
        "reverse-empty-both", "empty-pattern", "reverse-empty-pattern", "zero-length",
        "reverse-zero-length", "dot", "star", "optional", "plus", "anchors",
        "word-anchors", "word-start-negative", "word-boundaries", "non-boundary",
        "word-excludes-underscore", "nonword-includes-underscore", "class-range-hyphen",
        "negated-class", "class-literal-brackets", "escaped-dot", "escaped-star",
        "escaped-question", "plain-alternation-is-literal", "percent-alternation",
        "plain-parens-are-literal", "capture", "backreference",
    ],
)
def test_regex_operator_compatibility(client, requires_regexp, function, subject, pattern, expected):
    """Negative cases ensure translation bugs cannot pass as successful matches."""
    assert_match(client, function, subject, pattern, expected)


@pytest.mark.regexp
@pytest.mark.parametrize(
    "case_matters,expected",
    [(None, match_result("AbC", 1, 3)), (0, match_result("AbC", 1, 3)), (1, "{}"), (-1, "{}")],
    ids=["default-insensitive", "explicit-insensitive", "sensitive", "truthy-sensitive"],
)
def test_case_matters_argument(client, requires_regexp, case_matters, expected):
    assert_match(client, "match", "AbC", "abc", expected, case_matters)


@pytest.mark.regexp
def test_all_nine_capture_slots(client, requires_regexp):
    pattern = "".join(f"%({letter}%)" for letter in "abcdefghi")
    captures = tuple((i, i) for i in range(1, 10))
    assert_match(client, "match", "abcdefghi", pattern, match_result("abcdefghi", 1, 9, *captures))


@pytest.mark.regexp
@pytest.mark.parametrize("reference", range(1, 10), ids=lambda n: f"percent-{n}")
def test_percent_backreferences_one_through_nine(client, requires_regexp, reference):
    prefix = "abcdefghi"
    pattern = "".join(f"%({letter}%)" for letter in prefix) + f"%{reference}"
    subject = prefix + prefix[reference - 1]
    captures = tuple((i, i) for i in range(1, 10))
    assert_match(client, "match", subject, pattern, match_result(subject, 1, 10, *captures))


@pytest.mark.regexp
def test_more_than_nine_groups_are_truncated(client, requires_regexp):
    pattern = "".join(f"%({letter}%)" for letter in "abcdefghijk")
    captures = tuple((i, i) for i in range(1, 10))
    assert_match(client, "match", "abcdefghijk", pattern, match_result("abcdefghijk", 1, 11, *captures))


@pytest.mark.regexp
def test_optional_unmatched_and_repeated_captures(client, requires_regexp):
    assert_match(client, "match", "b", "%(a%)?%(b%)", match_result("b", 1, 1, NO_CAPTURE, (1, 1)))
    assert_match(client, "match", "foo", "%(o%)+", match_result("foo", 2, 3, (3, 3)))
    assert_match(client, "match", "foo", "%(%(o%)+%)", match_result("foo", 2, 3, (2, 3), (3, 3)))


@pytest.mark.regexp
def test_match_is_leftmost_and_uses_alternative_order(client, requires_regexp):
    assert_match(client, "match", "zaa", "a%|aa", match_result("zaa", 2, 2))
    assert_match(client, "match", "zaa", "aa%|a", match_result("zaa", 2, 3))


@pytest.mark.regexp
def test_rmatch_rightmost_endpoint_tie_and_selected_captures(client, requires_regexp):
    # The callout picks the greatest endpoint and, for a tie, the smallest start.
    assert_match(client, "rmatch", "ababa", "aba", match_result("ababa", 3, 5))
    assert_match(client, "rmatch", "zaa", "a%|aa", match_result("zaa", 2, 3))
    assert_match(client, "rmatch", "ab12cd34", "%([a-z]+%)%([0-9]+%)", match_result("ab12cd34", 5, 8, (5, 6), (7, 8)))


@pytest.mark.regexp
@pytest.mark.parametrize("pattern", ["[", "%(", "a%", "%(a", "a**"])
def test_invalid_patterns_raise_exact_moo_error(client, requires_regexp, pattern):
    success, error = client.eval(f"match(\"abc\", {moo_string(pattern)})")
    assert not success
    assert "Invalid argument" in error


@pytest.mark.regexp
@pytest.mark.timeout(2)
def test_match_limit_is_reported_as_quota_without_hanging(client, requires_regexp):
    subject = "a" * 64 + "X"
    success, error = client.eval(f"match({moo_string(subject)}, \"%(a+%)+$\")", timeout=1)
    assert not success
    assert "Resource limit exceeded" in error
    assert client.eval("1 + 1") == (True, "2")


@pytest.mark.regexp
@pytest.mark.timeout(3)
def test_recursive_match_depth_is_bounded_and_server_survives(client, requires_regexp):
    # Each optional capture iteration adds matcher stack depth.  The smaller
    # subject proves the pattern is otherwise valid; the larger one reaches
    # the server's recursion limit without requiring exponential backtracking.
    pattern = "^%(a?%)*$"
    assert_match(client, "match", "a" * 1000, pattern, match_result("a" * 1000, 1, 1000, (1001, 1000)))

    success, error = client.eval(f"match({moo_string('a' * 2000)}, {moo_string(pattern)})", timeout=2)
    assert not success
    assert "Resource limit exceeded" in error
    assert client.eval("1 + 1") == (True, "2")


@pytest.mark.regexp
@pytest.mark.unicode
@pytest.mark.parametrize(
    "function,subject,pattern,expected,case_matters",
    [
        ("match", "xxαβγyy", "αβγ", match_result("xxαβγyy", 3, 5), None),
        ("match", "甲乙丙", "乙", match_result("甲乙丙", 2, 2), None),
        ("match", "café", "é", match_result("café", 4, 4), None),
        ("match", "αβγ", "%(βγ%)", match_result("αβγ", 2, 3, (2, 3)), None),
        ("match", "😀x😀", "😀", match_result("😀x😀", 1, 1), None),
        ("rmatch", "😀x😀", "😀", match_result("😀x😀", 3, 3), None),
        ("rmatch", "αβαβ", "αβ", match_result("αβαβ", 3, 4), None),
        ("match", "É", "é", match_result("É", 1, 1), None),
        ("match", "É", "é", "{}", 1),
        ("match", "é", "%w", "{}", None),
        ("match", "éa", "%<a", match_result("éa", 2, 2), None),
        ("match", "e\u0301", "%(e\u0301%)", match_result("e\u0301", 1, 2, (1, 2)), None),
    ],
    ids=[
        "greek-codepoints-not-bytes", "cjk", "accented", "multibyte-capture",
        "supplementary-plane", "reverse-emoji", "reverse-greek", "nonascii-fold-default",
        "nonascii-sensitive", "moo-word-is-ascii", "boundary-after-nonascii", "combining-mark-capture",
    ],
)
def test_unicode_regex_compatibility(
    client, requires_regexp, requires_unicode, function, subject, pattern, expected, case_matters
):
    assert_match(client, function, subject, pattern, expected, case_matters)
