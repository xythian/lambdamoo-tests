"""Non-ASCII characters in MOO code must be syntax errors, not server panics.

A Unicode server built without UNICODE_NUMBERS or UNICODE_IDENTIFIERS
classified each code point with the <ctype.h> isdigit()/isalpha()/isalnum(),
which are undefined above 255.  glibc indexes past the end of its table, so
some code points read as digits.  ``;𝟏`` (U+1D7CF MATHEMATICAL BOLD DIGIT ONE)
was lexed as the start of a number, parse_number() rejected it, and yylex()
called panic("parse_number ungot unexpected char."), taking the server down.
Which code points misfire depends on the libc build, so the sweep below tries
every one of them.
"""

import pytest

from lib.assertions import assert_moo_success


SWEEP_TIMEOUT = 300.0


def assert_server_alive(client):
    """The server must still answer after parsing the code."""
    assert assert_moo_success(client.eval('1 + 1')) == '2'


@pytest.fixture
def program(client):
    """Return a function that runs MOO statements as a verb and returns the result."""
    obj = assert_moo_success(client.eval('create(#1)'))
    counter = [0]

    def run(lines, timeout=None):
        counter[0] += 1
        name = f"run{counter[0]}"
        assert_moo_success(client.eval(f'add_verb({obj}, {{player, "rxd", "{name}"}}, {{"this", "none", "this"}})'))
        code = ", ".join('"' + line.replace('\\', '\\\\').replace('"', '\\"') + '"' for line in lines)
        assert assert_moo_success(client.eval(f'set_verb_code({obj}, "{name}", {{{code}}})')) == '{}'
        return client.eval(f'{obj}:{name}()', timeout=timeout)

    return run


CODE_POINTS = [
    pytest.param('\U0001D7CF', id="math-bold-digit-one"),
    pytest.param('１', id="fullwidth-digit-one"),
    pytest.param('١', id="arabic-indic-digit-one"),
    pytest.param('㍂', id="cjk-compat-square"),
    pytest.param('é', id="latin-e-acute"),
]


class TestNonAsciiInCode:
    """Non-ASCII outside string literals is a syntax error on a Unicode server."""

    def test_typed_eval_of_math_bold_digit(self, client, requires_unicode):
        """The exact command that crashed Waterpoint: ``;𝟏`` typed at the prompt."""
        success, output = client.eval('\U0001D7CF')
        assert not success
        assert 'syntax error' in output.lower()
        assert_server_alive(client)

    @pytest.mark.parametrize("ch", CODE_POINTS)
    @pytest.mark.parametrize("template", [
        "return {};", "return 1{};", "return x{};", "return .{};", "return #{};",
    ], ids=["alone", "after-digit", "after-identifier", "after-dot", "after-hash"])
    def test_eval_builtin_rejects_non_ascii(self, client, requires_unicode, ch, template):
        """eval() reports a parse error and the server keeps running."""
        result = assert_moo_success(client.eval(f'eval("{template.format(ch)}")'))
        assert result.startswith('{0, {"Line 1:  ')
        assert_server_alive(client)

    def test_every_code_point_parses_without_crashing(self, client, program, requires_unicode):
        """Every printable non-ASCII code point, alone and after a digit or identifier, parses safely."""
        result = program([
            "n = 0;",
            "for cp in [128..1114111]",
            "  if (cp < 55296 || cp > 57343)",
            "    chars = decode_chars(encode_chars({cp}, \"utf-8\"), \"utf-8\");",
            "    if (chars && typeof(ch = chars[1]) == STR)",
            "      for code in ({\"return \", \"return 1\", \"x = 1; return x\"})",
            "        eval(code + ch + \";\");",
            "      endfor",
            "      n = n + 1;",
            "    endif",
            "  endif",
            "  if (ticks_left() < 10000 || seconds_left() < 2)",
            "    suspend(0);",
            "  endif",
            "endfor",
            "return n;",
        ], timeout=SWEEP_TIMEOUT)
        assert int(assert_moo_success(result)) > 1000000
        assert_server_alive(client)
