"""AST builtins (AST-001 onward), in servers built with --enable-ast.

ast_parse() turns MOO source into the server's own syntax tree as nested
lists, ast_unparse() prints a tree back as verb_code() would, and
ast_info() describes every node kind.  The tree format is specified in
wp-lambdamoo's AST.md: every node is {kind, line, field, ...}.
"""

import pytest

from lib.assertions import assert_moo_raises, assert_moo_success
from lib.moocode import moo_string


def moo_lines(lines):
    """A MOO list literal of the given source lines."""
    return "{" + ", ".join(moo_string(line) for line in lines) + "}"


def parse(client, lines, options=None):
    """ast_parse() of LINES, as the MOO literal of {tree, diagnostics}."""
    opts = f", {options}" if options else ""
    return assert_moo_success(client.eval(f"ast_parse({moo_lines(lines)}{opts})"))


def tree_of(client, lines):
    """The tree for LINES, which must compile."""
    return assert_moo_success(client.eval(f"ast_parse({moo_lines(lines)})[1]"))


def stmt(client, line):
    """The first statement node of a one-line program."""
    return assert_moo_success(client.eval(f"ast_parse({moo_lines([line])})[1][3][1]"))


def expr(client, source):
    """The expression node of the statement `SOURCE;`."""
    return assert_moo_success(client.eval(f"ast_parse({moo_lines([source + ';'])})[1][3][1][3]"))


# Programs in verb_code() form, one per construct, for the round trip and
# the comparison with set_verb_code().
CORPUS = [
    ["return;"],
    ["x = 1;", "y = 2.5;", 'z = "a \\"quoted\\" string";', "o = #-1;", "e = E_PERM;"],
    ['"a string comment";', "return x;"],
    ["if (a)", "  b:c();", "elseif (c)", "  d = 1;", "elseif (e)", "else", "  f = 2;", "endif"],
    ["for x in ({1, 2, 3})", "  y = y + x;", "endfor"],
    ["for i in [1..10]", "  continue;", "endfor"],
    ["while (x < 10)", "  x = x + 1;", "endwhile"],
    ["while loop (1)", "  break loop;", "endwhile"],
    ["fork (5)", "  player:tell(\"hi\");", "endfork"],
    ["fork task (0)", "  return;", "endfork", "kill_task(task);"],
    ["try", "  x = 1 / 0;", "except e (E_DIV, E_TYPE)", "  return e;", "except (ANY)", "  raise(E_INVARG);", "endtry"],
    ["try", "  return 1;", "finally", "  x = 2;", "endtry"],
    ["{a, ?b, ?c = 3, @rest} = args;"],
    ["x = `y[1] ! E_RANGE => 0';", "z = `o:foo() ! ANY';"],
    ["return a ? b | c;"],
    ["x = l[$];", "y = l[2..$ - 1];", "l[1] = 2;", "l[1..2] = {};"],
    ["x = o.p;", "y = o.(\"two words\");", "o.(p) = 1;", "$foo.bar = 2;", "return #0.p;"],
    ["o:v(1, @args);", "o:(name)();", "$util:clamp(x, 10);", "#0:(\"x y\")();"],
    ["return {1, {}, @x, {@y, 2}};"],
    ["return length(args) + listappend({}, 1)[1];"],
    ["x = -y + !z;", "w = -(-1);", "return - -x;"],
    ["return (a + b) * c - d / e % f ^ g ^ h;"],
    ["return (a = b) + 1;"],
    ["return a && b || !(c == d) && e != f;"],
    ["return a < b && c <= d && e > f && g >= h && x in y;"],
    ["return 1 .p + 2.5;"],
]

BITWISE_CORPUS = [
    ["return a .|. b .^. c .&. ~d;"],
    ["return a << 1 >> 2 >>> 3;"],
]

# Snippets set_verb_code() rejects, and what it says.
BAD_CORPUS = [
    ["x = ;"],
    ["if (1)", "  x = 1;"],
    ["break;"],
    ["while (1)", "  continue nope;", "endwhile"],
    ["$ = 1;"],
    ["1 = 2;"],
    ["{} = x;"],
    ["{a, @b, @c} = x;"],
    ["{a, f(1)} = x;"],
    ["try", "  x;", "except (ANY)", "except (E_PERM)", "endtry"],
    ["x = 1;", "y = no_such_builtin_here(1);"],
    ['x = "unterminated;'],
    ["x = #;"],
    ["/* unterminated comment"],
    ["x = 99999999999999999999999999;"],
]


class TestAbsent:
    """Servers built without --enable-ast."""

    def test_ast_001_builtins_absent(self, client, requires_no_ast):
        """AST-001: Without the extension the builtins don't exist and "ast" is not a feature."""
        for name in ("ast_parse", "ast_unparse", "ast_info"):
            assert_moo_raises(client, f'function_info("{name}")', "E_INVARG")
        assert '"ast"' not in assert_moo_success(client.eval('server_version("features")'))


class TestPresent:
    """The feature is advertised and the builtins are registered."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_002_feature_listed(self, client):
        """AST-002: "ast" is in server_version("features")."""
        assert '"ast"' in assert_moo_success(client.eval('server_version("features")'))

    def test_ast_003_function_info(self, client):
        """AST-003: function_info() reports the arities and argument types."""
        assert assert_moo_success(client.eval('function_info("ast_parse")')) == '{"ast_parse", 1, 2, {-1, 4}}'
        assert assert_moo_success(client.eval('function_info("ast_unparse")')) == '{"ast_unparse", 1, 2, {4, 4}}'
        assert assert_moo_success(client.eval('function_info("ast_info")')) == '{"ast_info", 0, 0, {}}'


class TestStatementShapes:
    """One statement of each kind, compared exactly with the format."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_010_program(self, client):
        """AST-010: The root is {"program", 0, body}; an empty program has an empty body."""
        assert parse(client, []) == '{{"program", 0, {}}, {}}'
        assert parse(client, ["return;"]) == '{{"program", 0, {{"stmt_return", 1, 0}}}, {}}'

    def test_ast_011_stmt_expr_and_literals(self, client):
        """AST-011: Literals are expr_var with the value itself, of each literal type."""
        assert stmt(client, "1;") == '{"stmt_expr", 1, {"expr_var", 1, 1}}'
        assert expr(client, "2.5") == '{"expr_var", 1, 2.5}'
        assert expr(client, '"s"') == '{"expr_var", 1, "s"}'
        assert expr(client, "#12") == '{"expr_var", 1, #12}'
        assert expr(client, "E_PERM") == '{"expr_var", 1, E_PERM}'

    def test_ast_012_negative_literal_folded(self, client):
        """AST-012: A negated number literal is the negative literal, as the parser folds it."""
        assert expr(client, "-5") == '{"expr_var", 1, -5}'
        assert expr(client, "-x") == '{"expr_negate", 1, {"expr_id", 1, "x"}}'

    def test_ast_013_return(self, client):
        """AST-013: stmt_return holds its expression, or 0."""
        assert stmt(client, "return x;") == '{"stmt_return", 1, {"expr_id", 1, "x"}}'
        assert stmt(client, "return;") == '{"stmt_return", 1, 0}'

    def test_ast_014_cond(self, client):
        """AST-014: stmt_cond has a list of cond_arm and an otherwise body."""
        tree = tree_of(client, ["if (a)", "  b;", "elseif (c)", "else", "  d;", "endif"])
        assert tree == (
            '{"program", 0, {{"stmt_cond", 1, '
            '{{"cond_arm", 1, {"expr_id", 1, "a"}, {{"stmt_expr", 2, {"expr_id", 2, "b"}}}}, '
            '{"cond_arm", 3, {"expr_id", 3, "c"}, {}}}, '
            '{{"stmt_expr", 5, {"expr_id", 5, "d"}}}}}}')

    def test_ast_015_no_else_is_empty_otherwise(self, client):
        """AST-015: Without else, otherwise is an empty body."""
        assert stmt(client, "if (a) endif") == '{"stmt_cond", 1, {{"cond_arm", 1, {"expr_id", 1, "a"}, {}}}, {}}'

    def test_ast_016_for_list(self, client):
        """AST-016: stmt_list has the variable name, the list expression and the body."""
        assert stmt(client, "for x in (l) endfor") == '{"stmt_list", 1, "x", {"expr_id", 1, "l"}, {}}'

    def test_ast_017_for_range(self, client):
        """AST-017: stmt_range has the variable name, from, to and the body."""
        assert stmt(client, "for i in [1..n] endfor") == (
            '{"stmt_range", 1, "i", {"expr_var", 1, 1}, {"expr_id", 1, "n"}, {}}')

    def test_ast_018_while(self, client):
        """AST-018: stmt_while has the loop name or 0, the condition and the body."""
        assert stmt(client, "while (1) endwhile") == '{"stmt_while", 1, 0, {"expr_var", 1, 1}, {}}'
        assert stmt(client, "while lp (1) break lp; endwhile") == (
            '{"stmt_while", 1, "lp", {"expr_var", 1, 1}, {{"stmt_break", 1, "lp"}}}')

    def test_ast_019_fork(self, client):
        """AST-019: stmt_fork has the task variable name or 0, the delay and the body."""
        assert stmt(client, "fork (0) endfork") == '{"stmt_fork", 1, 0, {"expr_var", 1, 0}, {}}'
        assert stmt(client, "fork t (1) endfork") == '{"stmt_fork", 1, "t", {"expr_var", 1, 1}, {}}'

    def test_ast_020_break_continue(self, client):
        """AST-020: stmt_break and stmt_continue hold the loop name or 0."""
        tree = tree_of(client, ["while (1)", "  break;", "  continue;", "endwhile"])
        assert tree == (
            '{"program", 0, {{"stmt_while", 1, 0, {"expr_var", 1, 1}, '
            '{{"stmt_break", 2, 0}, {"stmt_continue", 3, 0}}}}}')

    def test_ast_021_try_except(self, client):
        """AST-021: stmt_try_except has a body and a list of except_arm; codes is 0 for ANY."""
        tree = tree_of(client, ["try", "  x;", "except e (E_PERM, @l)", "except (ANY)", "  y;", "endtry"])
        assert tree == (
            '{"program", 0, {{"stmt_try_except", 1, {{"stmt_expr", 2, {"expr_id", 2, "x"}}}, '
            '{{"except_arm", 3, "e", {{"expr_var", 3, E_PERM}, {"arg_splice", 3, {"expr_id", 3, "l"}}}, {}}, '
            '{"except_arm", 4, 0, 0, {{"stmt_expr", 5, {"expr_id", 5, "y"}}}}}}}}')

    def test_ast_022_try_finally(self, client):
        """AST-022: stmt_try_finally has a body and a handler body."""
        assert stmt(client, "try x; finally y; endtry") == (
            '{"stmt_try_finally", 1, {{"stmt_expr", 1, {"expr_id", 1, "x"}}}, '
            '{{"stmt_expr", 1, {"expr_id", 1, "y"}}}}')

    def test_ast_023_empty_statement_dropped(self, client):
        """AST-023: A bare `;` leaves nothing in the tree, as it leaves nothing in the verb."""
        assert parse(client, [";", ";"]) == '{{"program", 0, {}}, {}}'


class TestExpressionShapes:
    """One expression of each kind, compared exactly with the format."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_030_id(self, client):
        """AST-030: A variable is expr_id with its name; built-in variables too."""
        assert expr(client, "foo") == '{"expr_id", 1, "foo"}'
        assert expr(client, "player") == '{"expr_id", 1, "player"}'

    def test_ast_031_prop(self, client):
        """AST-031: o.p and o.("p") are the same expr_prop; o.(e) keeps its expression."""
        assert expr(client, "o.p") == '{"expr_prop", 1, {"expr_id", 1, "o"}, {"expr_var", 1, "p"}}'
        assert expr(client, 'o.("p")') == expr(client, "o.p")
        assert expr(client, "o.(e)") == '{"expr_prop", 1, {"expr_id", 1, "o"}, {"expr_id", 1, "e"}}'

    def test_ast_032_dollar_prop(self, client):
        """AST-032: $p is expr_prop on #0, like #0.p."""
        assert expr(client, "$p") == '{"expr_prop", 1, {"expr_var", 1, #0}, {"expr_var", 1, "p"}}'
        assert expr(client, "#0.p") == expr(client, "$p")

    def test_ast_033_verb(self, client):
        """AST-033: expr_verb has obj, verb and args; $v() is a verb on #0."""
        assert expr(client, "o:v(1)") == (
            '{"expr_verb", 1, {"expr_id", 1, "o"}, {"expr_var", 1, "v"}, {{"expr_var", 1, 1}}}')
        assert expr(client, "o:(n)()") == '{"expr_verb", 1, {"expr_id", 1, "o"}, {"expr_id", 1, "n"}, {}}'
        assert expr(client, "$v()") == '{"expr_verb", 1, {"expr_var", 1, #0}, {"expr_var", 1, "v"}, {}}'

    def test_ast_034_call(self, client):
        """AST-034: A builtin call is expr_call with the builtin's name."""
        assert expr(client, "length(x)") == '{"expr_call", 1, "length", {{"expr_id", 1, "x"}}}'
        assert expr(client, "LENGTH(x)") == expr(client, "length(x)")

    def test_ast_035_index_range_length(self, client):
        """AST-035: expr_index, expr_range and expr_length ($ inside an index)."""
        assert expr(client, "l[1]") == '{"expr_index", 1, {"expr_id", 1, "l"}, {"expr_var", 1, 1}}'
        assert expr(client, "l[2..$]") == (
            '{"expr_range", 1, {"expr_id", 1, "l"}, {"expr_var", 1, 2}, {"expr_length", 1}}')

    def test_ast_036_asgn(self, client):
        """AST-036: expr_asgn has lhs and rhs."""
        assert expr(client, "x = 1") == '{"expr_asgn", 1, {"expr_id", 1, "x"}, {"expr_var", 1, 1}}'

    def test_ast_037_scatter(self, client):
        """AST-037: A scattering assignment's lhs is expr_scatter, each target with id and expr."""
        assert expr(client, "{a, ?b, ?c = 1, @d} = x") == (
            '{"expr_asgn", 1, {"expr_scatter", 1, {{"scat_required", 1, "a", 0}, '
            '{"scat_optional", 1, "b", 0}, {"scat_optional", 1, "c", {"expr_var", 1, 1}}, '
            '{"scat_rest", 1, "d", 0}}}, {"expr_id", 1, "x"}}')

    def test_ast_038_list_and_splice(self, client):
        """AST-038: expr_list holds its arguments; @x is arg_splice."""
        assert expr(client, "{1, @x}") == (
            '{"expr_list", 1, {{"expr_var", 1, 1}, {"arg_splice", 1, {"expr_id", 1, "x"}}}}')
        assert expr(client, "{}") == '{"expr_list", 1, {}}'

    def test_ast_039_cond(self, client):
        """AST-039: expr_cond has condition, consequent and alternate."""
        assert expr(client, "a ? b | c") == (
            '{"expr_cond", 1, {"expr_id", 1, "a"}, {"expr_id", 1, "b"}, {"expr_id", 1, "c"}}')

    def test_ast_040_catch(self, client):
        """AST-040: expr_catch has try, codes (0 for ANY) and except (0 when absent)."""
        assert expr(client, "`x ! ANY'") == '{"expr_catch", 1, {"expr_id", 1, "x"}, 0, 0}'
        assert expr(client, "`x ! E_PERM => 1'") == (
            '{"expr_catch", 1, {"expr_id", 1, "x"}, {{"expr_var", 1, E_PERM}}, {"expr_var", 1, 1}}')

    @pytest.mark.parametrize("op,kind", [
        ("+", "expr_plus"), ("-", "expr_minus"), ("*", "expr_times"), ("/", "expr_divide"),
        ("%", "expr_mod"), ("^", "expr_exp"), ("==", "expr_eq"), ("!=", "expr_ne"),
        ("<", "expr_lt"), ("<=", "expr_le"), (">", "expr_gt"), (">=", "expr_ge"),
        ("in", "expr_in"), ("&&", "expr_and"), ("||", "expr_or"),
    ])
    def test_ast_041_binary(self, client, op, kind):
        """AST-041: Each binary operator is its own kind with lhs and rhs."""
        assert expr(client, f"a {op} b") == f'{{"{kind}", 1, {{"expr_id", 1, "a"}}, {{"expr_id", 1, "b"}}}}'

    @pytest.mark.parametrize("op,kind", [
        (".|.", "expr_bitor"), (".^.", "expr_bitxor"), (".&.", "expr_bitand"),
        ("<<", "expr_shl"), (">>", "expr_shr"), (">>>", "expr_lshr"),
    ])
    def test_ast_042_bitwise(self, client, requires_bitwise, op, kind):
        """AST-042: With bitwise operators, each is its own kind with lhs and rhs."""
        assert expr(client, f"a {op} b") == f'{{"{kind}", 1, {{"expr_id", 1, "a"}}, {{"expr_id", 1, "b"}}}}'

    def test_ast_043_unary(self, client):
        """AST-043: expr_negate and expr_not hold their operand."""
        assert expr(client, "!x") == '{"expr_not", 1, {"expr_id", 1, "x"}}'
        assert expr(client, "-(x)") == '{"expr_negate", 1, {"expr_id", 1, "x"}}'

    def test_ast_044_complement(self, client, requires_bitwise):
        """AST-044: With bitwise operators, ~x is expr_complement."""
        assert expr(client, "~x") == '{"expr_complement", 1, {"expr_id", 1, "x"}}'

    def test_ast_045_precedence_is_structure(self, client):
        """AST-045: Precedence and parentheses show only in the tree's shape."""
        assert expr(client, "a + b * c") == (
            '{"expr_plus", 1, {"expr_id", 1, "a"}, {"expr_times", 1, {"expr_id", 1, "b"}, {"expr_id", 1, "c"}}}')
        assert expr(client, "(a + b) * c") == (
            '{"expr_times", 1, {"expr_plus", 1, {"expr_id", 1, "a"}, {"expr_id", 1, "b"}}, {"expr_id", 1, "c"}}')
        assert expr(client, "a ^ b ^ c") == (
            '{"expr_exp", 1, {"expr_id", 1, "a"}, {"expr_exp", 1, {"expr_id", 1, "b"}, {"expr_id", 1, "c"}}}')


class TestCodeArgument:
    """What ast_parse() accepts as code."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_051_single_line_string(self, client):
        """AST-051: A string is a one-line program."""
        assert assert_moo_success(client.eval('ast_parse("return 1;")')) == parse(client, ["return 1;"])

    def test_ast_052_bad_code_type(self, client):
        """AST-052: Code that is neither a string nor a list of strings is E_TYPE."""
        assert_moo_raises(client, "ast_parse(1)", "E_TYPE")
        assert_moo_raises(client, 'ast_parse({"x;", 1})', "E_TYPE")


class TestRoundTrip:
    """ast_unparse(ast_parse(verb_code(o, v))[1]) is verb_code(o, v)."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def _set_corpus(self, client, program, corpus):
        obj = program.obj
        for i, lines in enumerate(corpus):
            name = f"c{i}"
            assert_moo_success(client.eval(f'add_verb({obj}, {{player, "rxd", "{name}"}}, {{"this", "none", "this"}})'))
            errors = assert_moo_success(client.eval(f'set_verb_code({obj}, "{name}", {moo_lines(lines)})'))
            assert errors == "{}", f"{lines}: {errors}"
        return obj

    ROUND_TRIP = [
        "bad = {};",
        "for o in [#0..max_object()]",
        "  if (valid(o))",
        "    for i in [1..length(verbs(o))]",
        "      for opt in ({{0, 1}, {1, 1}, {0, 0}, {1, 0}})",
        "        code = verb_code(o, i, @opt);",
        "        t = ast_parse(code)[1];",
        '        text = t ? ast_unparse(t, {{"parens", opt[1]}, {"indent", opt[2]}}) | 0;',
        "        if (text != code)",
        "          bad = {@bad, {o, i, opt, code, text}};",
        "        endif",
        "      endfor",
        "    endfor",
        "  endif",
        "endfor",
        "return bad;",
    ]

    def test_ast_060_corpus_round_trip(self, client, program):
        """AST-060: Every construct in the corpus prints back exactly, with each paren and indent option."""
        self._set_corpus(client, program, CORPUS)
        result, _ = program(self.ROUND_TRIP)
        assert assert_moo_success(result) == "{}"

    def test_ast_061_bitwise_round_trip(self, client, program, requires_bitwise):
        """AST-061: Bitwise operators print back exactly."""
        self._set_corpus(client, program, BITWISE_CORPUS)
        result, _ = program(self.ROUND_TRIP)
        assert assert_moo_success(result) == "{}"

    def test_ast_062_parsed_lines_match_verb_code(self, client, program):
        """AST-062: Parsing verb_code() output gives each statement its verb_code() line."""
        obj = self._set_corpus(client, program, [CORPUS[3]])
        code = assert_moo_success(client.eval(f'verb_code({obj}, "c0")'))
        assert code == '{"if (a)", "  b:c();", "elseif (c)", "  d = 1;", "elseif (e)", "else", "  f = 2;", "endif"}'
        tree = assert_moo_success(client.eval(f'ast_parse(verb_code({obj}, "c0"))[1][3][1]'))
        assert tree == (
            '{"stmt_cond", 1, {{"cond_arm", 1, {"expr_id", 1, "a"}, {{"stmt_expr", 2, {"expr_verb", 2, {"expr_id", 2, "b"}, {"expr_var", 2, "c"}, {}}}}}, '
            '{"cond_arm", 3, {"expr_id", 3, "c"}, {{"stmt_expr", 4, {"expr_asgn", 4, {"expr_id", 4, "d"}, {"expr_var", 4, 1}}}}}, '
            '{"cond_arm", 5, {"expr_id", 5, "e"}, {}}}, '
            '{{"stmt_expr", 7, {"expr_asgn", 7, {"expr_id", 7, "f"}, {"expr_var", 7, 2}}}}}')

    def test_ast_063_reformat_without_saving(self, client):
        """AST-063: Unparsing a parse reformats source as a save would, without a verb."""
        result = assert_moo_success(client.eval(
            f'ast_unparse(ast_parse({moo_lines(["if(x)y=((1+2))*3;/* gone */else", "z ;endif"])})[1])'))
        assert result == '{"if (x)", "  y = (1 + 2) * 3;", "else", "  z;", "endif"}'

    def test_ast_064_deepest_parse_round_trips(self, client, many_ticks):
        """AST-064: The most deeply nested expression the parser accepts prints back."""
        source = "{" * 9990 + "x" + "}" * 9990 + ";"
        result = assert_moo_success(client.eval(f'ast_unparse(ast_parse({{"{source}"}})[1]) == {{"{source}"}}'))
        assert result == "1"


class TestAgreesWithSave:
    """ast_parse() succeeds exactly when set_verb_code() does, with the same messages."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_070_good_corpus_compiles(self, client):
        """AST-070: Every good snippet parses with no diagnostics."""
        for lines in CORPUS:
            result = parse(client, lines)
            assert result.startswith('{{"program", 0,') and result.endswith(", {}}"), (lines, result)

    @pytest.mark.parametrize("lines", BAD_CORPUS, ids=[" / ".join(b) for b in BAD_CORPUS])
    def test_ast_071_bad_corpus_same_errors(self, client, program, lines):
        """AST-071: A snippet set_verb_code() rejects gives no tree and the same messages."""
        result, _ = program([
            f"code = {moo_lines(lines)};",
            'add_verb(this, {player, "rxd", "probe"}, {"this", "none", "this"});',
            'saved = set_verb_code(this, "probe", code);',
            "{tree, diags} = ast_parse(code);",
            "msgs = {};",
            "for d in (diags)",
            '  d[1] == "error" || raise(E_ASSERT, "warning in strict mode");',
            '  msgs = {@msgs, tostr("Line ", d[2], ":  ", d[3])};',
            "endfor",
            "return {tree, saved == msgs, saved, msgs};",
        ])
        value = assert_moo_success(result)
        assert value.startswith("{0, 1, "), value

    def test_ast_072_diagnostic_shape(self, client):
        """AST-072: A diagnostic is {severity, line, message} with eval()'s message text."""
        assert parse(client, ["x = 1;", "y = ;"]) == '{0, {{"error", 2, "syntax error"}}}'
        assert parse(client, ["x = 1;", "break;"]) == (
            '{0, {{"error", 2, "No enclosing loop for `break\' statement"}}}')

    def test_ast_073_several_errors(self, client):
        """AST-073: Semantic errors after the first are all reported."""
        assert parse(client, ["break;", "continue;"]) == (
            '{0, {{"error", 1, "No enclosing loop for `break\' statement"}, '
            '{"error", 2, "No enclosing loop for `continue\' statement"}}}')

    def test_ast_074_lines_count_comment_newlines(self, client):
        """AST-074: Lines inside a /* */ comment still count."""
        assert parse(client, ["/* one", "two */ x;"]) == '{{"program", 0, {{"stmt_expr", 2, {"expr_id", 2, "x"}}}}, {}}'
        assert parse(client, ["/* one", "two */ y = ;"]) == '{0, {{"error", 2, "syntax error"}}}'


class TestLenient:
    """The "builtins" option."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_080_strict_unknown_builtin(self, client):
        """AST-080: By default an unknown builtin is an error, as in set_verb_code()."""
        assert parse(client, ["frobnicate(1);"]) == '{0, {{"error", 1, "Unknown built-in function: frobnicate"}}}'
        assert parse(client, ["frobnicate(1);"], '{{"builtins", "strict"}}') == parse(client, ["frobnicate(1);"])

    def test_ast_081_lenient_keeps_name(self, client):
        """AST-081: Lenient mode makes it a warning and keeps the call with its name."""
        assert parse(client, ["frobnicate(1, @x);"], '{{"builtins", "lenient"}}') == (
            '{{"program", 0, {{"stmt_expr", 1, {"expr_call", 1, "frobnicate", '
            '{{"expr_var", 1, 1}, {"arg_splice", 1, {"expr_id", 1, "x"}}}}}}}, '
            '{{"warning", 1, "Unknown built-in function: frobnicate"}}}')

    def test_ast_082_lenient_unparses(self, client):
        """AST-082: A lenient tree prints the unknown builtin by name."""
        assert assert_moo_success(client.eval(
            'ast_unparse(ast_parse("return frobnicate(1);", {{"builtins", "lenient"}})[1])')) == '{"return frobnicate(1);"}'

    def test_ast_083_call_function_unchanged(self, client):
        """AST-083: An explicit call_function() call stays as written."""
        assert expr(client, 'call_function("length", x)') == (
            '{"expr_call", 1, "call_function", {{"expr_var", 1, "length"}, {"expr_id", 1, "x"}}}')

    def test_ast_084_lenient_other_errors(self, client):
        """AST-084: Lenient mode still fails on real errors."""
        assert parse(client, ["frobnicate(;"], '{{"builtins", "lenient"}}') == '{0, {{"error", 1, "syntax error"}}}'


class TestOptions:
    """Option lists."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    @pytest.mark.parametrize("options", [
        '{{"nope", 1}}', '{{"builtins", "sloppy"}}', '{{"builtins", 1}}', '{{"builtins"}}',
        '{"builtins"}', '{{1, 2}}', '{{"parens", 1}}',
    ])
    def test_ast_090_bad_parse_options(self, client, options):
        """AST-090: An unknown option or bad value for ast_parse() is E_INVARG."""
        assert_moo_raises(client, f'ast_parse("x;", {options})', "E_INVARG")

    @pytest.mark.parametrize("options", [
        '{{"nope", 1}}', '{{"parens", "yes"}}', '{{"indent", 1.0}}', '{{"builtins", "strict"}}', '{1}',
    ])
    def test_ast_091_bad_unparse_options(self, client, options):
        """AST-091: An unknown option or bad value for ast_unparse() is E_INVARG."""
        assert_moo_raises(client, f'ast_unparse(ast_parse("x;")[1], {options})', "E_INVARG")

    def test_ast_092_option_names_ignore_case(self, client):
        """AST-092: Option names and the builtins mode compare without case, as MOO strings do."""
        assert parse(client, ["f(1);"], '{{"BUILTINS", "Lenient"}}').startswith('{{"program"')

    def test_ast_093_parens_and_indent(self, client):
        """AST-093: "parens" and "indent" work as verb_code()'s third and fourth arguments."""
        tree = 'ast_parse({"if (a)", "x = a + b * c;", "endif"})[1]'
        assert assert_moo_success(client.eval(f"ast_unparse({tree})")) == '{"if (a)", "  x = a + b * c;", "endif"}'
        assert assert_moo_success(client.eval(f'ast_unparse({tree}, {{{{"parens", 1}}, {{"indent", 0}}}})')) == (
            '{"if (a)", "x = a + (b * c);", "endif"}')

    def test_ast_094_last_option_wins(self, client):
        """AST-094: When an option is given twice, the last one counts."""
        assert assert_moo_success(client.eval(
            'ast_unparse(ast_parse({"if (a)", "x;", "endif"})[1], {{"indent", 0}, {"indent", 1}})')) == (
            '{"if (a)", "  x;", "endif"}')


class TestTracebackLines:
    """Lines in ast_parse(verb_code(o, v)) are the traceback's lines."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_100_raising_statement_line(self, client, program):
        """AST-100: The statement a traceback names is at that line in the parsed verb_code()."""
        result, _ = program([
            "x = 1;",
            "if (x)",
            "  y = {1, 2};",
            "  while (x < 3)",
            "    x = x + 1;",
            "  endwhile",
            '  "comment";',
            "  z = y[x];",
            "endif",
        ])
        ok, message = result
        assert not ok
        line = int(message.split(", line ")[1].split(":")[0])
        assert line == 8
        found, _ = program([
            f'todo = {{ast_parse(verb_code(this, "run1"))[1]}};',
            "found = {};",
            "while (todo)",
            "  n = todo[1];",
            "  todo[1..1] = {};",
            "  if (typeof(n) == LIST)",
            f'    if (length(n) >= 2 && typeof(n[1]) == STR && index(n[1], "stmt_") == 1 && n[2] == {line})',
            "      found = {@found, n};",
            "    endif",
            "    todo = {@todo, @n};",
            "  endif",
            "endwhile",
            "return found;",
        ])
        assert assert_moo_success(found).startswith(
            '{{"stmt_expr", 8, {"expr_asgn", 8, {"expr_id", 8, "z"}, {"expr_index", 8,')


class TestUnparse:
    """ast_unparse() of hand-built trees."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_110_hand_built_tree(self, client):
        """AST-110: A hand-built tree prints, with parentheses where precedence needs them."""
        tree = ('{"program", 0, {{"stmt_expr", 0, {"expr_times", 0, '
                '{"expr_plus", 0, {"expr_id", 0, "a"}, {"expr_var", 0, 1}}, {"expr_var", 0, "s"}}}}}')
        assert assert_moo_success(client.eval(f"ast_unparse({tree})")) == '{"(a + 1) * \\"s\\";"}'

    def test_ast_111_kinds_ignore_case(self, client):
        """AST-111: Kinds compare without case, as MOO strings do."""
        tree = '{"PROGRAM", 0, {{"Stmt_Return", 0, {"EXPR_VAR", 0, 1}}}}'
        assert assert_moo_success(client.eval(f"ast_unparse({tree})")) == '{"return 1;"}'

    def test_ast_112_shape_not_semantics(self, client):
        """AST-112: A well-formed tree prints even if it would not compile; saving reports that."""
        tree = '{"program", 0, {{"stmt_break", 0, 0}}}'
        assert assert_moo_success(client.eval(f"ast_unparse({tree})")) == '{"break;"}'

    def test_ast_113_unknown_builtin_by_name(self, client):
        """AST-113: An expr_call to a builtin the server lacks prints by name."""
        tree = '{"program", 0, {{"stmt_expr", 0, {"expr_call", 0, "frobnicate", {{"expr_var", 0, 1}}}}}}'
        assert assert_moo_success(client.eval(f"ast_unparse({tree})")) == '{"frobnicate(1);"}'

    def test_ast_114_property_names(self, client):
        """AST-114: A property name that is not an identifier is printed in parentheses."""
        tree = ('{"program", 0, {{"stmt_expr", 0, {"expr_prop", 0, {"expr_id", 0, "o"}, '
                '{"expr_var", 0, "two words"}}}}}')
        assert assert_moo_success(client.eval(f"ast_unparse({tree})")) == '{"o.(\\"two words\\");"}'


# Malformed trees.  Each is wrapped as the expression of a statement or as a
# statement in a program unless it starts with "!".
BAD_EXPRS = [
    "1",
    '"expr_id"',
    "{}",
    '{"expr_id"}',
    '{"expr_id", 1}',
    '{"expr_id", "1", "x"}',
    '{"expr_id", 1, "x", "y"}',
    '{"expr_nope", 1, "x"}',
    '{"stmt_return", 1, 0}',
    '{"cond_arm", 1, {"expr_id", 1, "x"}, {}}',
    '{"expr_id", 1, 0}',
    '{"expr_id", 1, ""}',
    '{"expr_id", 1, "two words"}',
    '{"expr_id", 1, "1x"}',
    '{"expr_id", 1, "for"}',
    '{"expr_id", 1, "E_PERM"}',
    '{"expr_var", 1, {}}',
    '{"expr_var", 1, {1}}',
    '{"expr_plus", 1, {"expr_var", 1, 1}}',
    '{"expr_plus", 1, {"expr_var", 1, 1}, 0}',
    '{"expr_plus", 1, {"expr_var", 1, 1}, {"stmt_return", 1, 0}}',
    '{"expr_call", 1, "length", 0}',
    '{"expr_call", 1, 0, {}}',
    '{"expr_call", 1, "no such", {}}',
    '{"expr_list", 1, {1}}',
    '{"expr_list", 1, {{"arg_splice", 1}}}',
    '{"expr_list", 1, {{"scat_rest", 1, "x", 0}}}',
    '{"expr_scatter", 1, {}}',
    '{"expr_scatter", 1, {{"scat_required", 1, "x", {"expr_var", 1, 1}}}}',
    '{"expr_scatter", 1, {{"expr_id", 1, "x"}}}',
    '{"expr_catch", 1, {"expr_id", 1, "x"}, {}, 0}',
    '{"expr_catch", 1, {"expr_id", 1, "x"}, 1, 0}',
    '{"expr_length", 1, 0}',
    '{"expr_verb", 1, {"expr_id", 1, "o"}, {"expr_var", 1, "v"}}',
]

BAD_STMTS = [
    '{"stmt_cond", 1, {}, {}}',
    '{"stmt_cond", 1, {{"cond_arm", 1, {"expr_id", 1, "x"}, 0}}, {}}',
    '{"stmt_cond", 1, {{"cond_arm", 1, {"expr_id", 1, "x"}, {}}}, 0}',
    '{"stmt_cond", 1, {{"expr_id", 1, "x"}}, {}}',
    '{"stmt_list", 1, 0, {"expr_id", 1, "l"}, {}}',
    '{"stmt_while", 1, "", {"expr_var", 1, 1}, {}}',
    '{"stmt_while", 1, 0, {"expr_var", 1, 1}, {1}}',
    '{"stmt_while", 1, 0, {"expr_var", 1, 1}, {{"expr_id", 1, "x"}}}',
    '{"stmt_try_except", 1, {}, {}}',
    '{"stmt_try_except", 1, {}, {{"except_arm", 1, 0, {}, {}}}}',
    '{"stmt_try_finally", 1, {}}',
    '{"stmt_break", 1, 1}',
    '{"stmt_return", 1}',
    '{"program", 0, {}}',
]


class TestBadTrees:
    """ast_unparse() rejects malformed trees with E_INVARG and stays up."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    @pytest.mark.parametrize("bad", BAD_EXPRS)
    def test_ast_120_bad_expression(self, client, bad):
        """AST-120: A malformed expression anywhere in the tree is E_INVARG."""
        assert_moo_raises(client, f'ast_unparse({{"program", 0, {{{{"stmt_expr", 1, {bad}}}}}}})', "E_INVARG")

    @pytest.mark.parametrize("bad", BAD_STMTS)
    def test_ast_121_bad_statement(self, client, bad):
        """AST-121: A malformed statement is E_INVARG."""
        assert_moo_raises(client, f'ast_unparse({{"program", 0, {{{bad}}}}})', "E_INVARG")

    @pytest.mark.parametrize("bad", [
        "{}", '{"program"}', '{"program", 0}', '{"program", 0, 0}', '{"program", 0, {}, {}}',
        '{"stmt_return", 1, 0}', '{"program", "0", {}}',
    ])
    def test_ast_122_bad_root(self, client, bad):
        """AST-122: The root must be a program node."""
        assert_moo_raises(client, f"ast_unparse({bad})", "E_INVARG")

    def test_ast_123_server_stays_up(self, client):
        """AST-123: After every rejected tree the server still answers."""
        for bad in BAD_EXPRS:
            client.eval(f'`ast_unparse({{"program", 0, {{{{"stmt_expr", 1, {bad}}}}}}}) ! ANY\'')
        assert assert_moo_success(client.eval("1 + 1")) == "2"


@pytest.fixture
def many_ticks(client):
    """Raise the foreground limits, and make running out of string space catchable."""
    if '"server_options"' not in assert_moo_success(client.eval('properties(#0)')):
        assert_moo_success(client.eval('add_property(#0, "server_options", create(#1), {player, "r"})'))
    for name, value in (("fg_ticks", 100000000), ("fg_seconds", 120), ("max_concat_catchable", 1)):
        assert_moo_success(client.eval(f'add_property(#0.server_options, "{name}", {value}, {{player, "r"}})'))
    assert_moo_success(client.eval('load_server_options()'))


class TestLimits:
    """Depth, size and permissions."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_130_too_deep(self, client, program, many_ticks):
        """AST-130: Nesting deeper than any parsed tree is E_INVARG, even when each node is well formed."""
        result, _ = program([
            "e = {\"expr_var\", 1, 1};",
            "for i in [1..20010]",
            '  e = {"expr_not", 1, e};',
            "endfor",
            'return `ast_unparse({"program", 0, {{"stmt_expr", 1, e}}}) ! ANY\';',
        ])
        assert assert_moo_success(result) == "E_INVARG"
        assert assert_moo_success(client.eval("1 + 1")) == "2"

    def test_ast_131_deep_but_allowed(self, client, program, many_ticks):
        """AST-131: A chain as deep as the parser allows prints."""
        result, _ = program([
            "e = {\"expr_id\", 1, \"x\"};",
            "for i in [1..9000]",
            '  e = {"expr_not", 1, e};',
            "endfor",
            'r = ast_unparse({"program", 0, {{"stmt_expr", 1, e}}});',
            "return {length(r), length(r[1])};",
        ])
        assert assert_moo_success(result) == "{1, 9002}"

    def test_ast_132_shared_sublists(self, client, program, many_ticks):
        """AST-132: A tree that shares a sublist so often it would print enormous is E_QUOTA."""
        result, _ = program([
            'e = {"expr_var", 1, "xxxxxxxxxxxxxxxx"};',
            "for i in [1..64]",
            '  e = {"expr_plus", 1, e, e};',
            "endfor",
            'return `ast_unparse({"program", 0, {{"stmt_expr", 1, e}}}) ! ANY\';',
        ])
        assert assert_moo_success(result) == "E_QUOTA"
        assert assert_moo_success(client.eval("1 + 1")) == "2"

    def test_ast_133_programmer_required(self, client, program):
        """AST-133: ast_parse() and ast_unparse() need a programmer; ast_info() does not."""
        owner = assert_moo_success(client.eval("create(#1)"))
        assert_moo_success(client.eval(f"{owner}.programmer = 0"))
        obj = program.obj
        assert_moo_success(client.eval(f'add_verb({obj}, {{{owner}, "rxd", "noprog"}}, {{"this", "none", "this"}})'))
        code = moo_lines([
            'return {`ast_parse("x;") ! ANY\', '
            '`ast_unparse({"program", 0, {}}) ! ANY\', `ast_info()[1] ! ANY\'};',
        ])
        assert assert_moo_success(client.eval(f'set_verb_code({obj}, "noprog", {code})')) == "{}"
        assert assert_moo_success(client.eval(f"{obj}:noprog()")) == "{E_PERM, E_PERM, 1}"


class TestInfo:
    """ast_info()."""

    pytestmark = pytest.mark.usefixtures("requires_ast")

    def test_ast_140_version(self, client):
        """AST-140: The format version is 1."""
        assert assert_moo_success(client.eval("ast_info()[1]")) == "1"

    def test_ast_141_entry_shape(self, client):
        """AST-141: Each entry is {kind, class, fields, operator}."""
        assert assert_moo_success(client.eval("ast_info()[2][1]")) == '{"program", "program", {{"body", "body"}}, 0}'

    def test_ast_142_operators(self, program):
        """AST-142: Operators carry spelling, precedence and associativity."""
        result, _ = program([
            "ops = {};",
            "for k in (ast_info()[2])",
            '  if (k[1] in {"expr_plus", "expr_times", "expr_exp", "expr_asgn", "expr_not", "expr_or", "expr_and"})',
            "    ops = {@ops, {k[1], k[4]}};",
            "  endif",
            "endfor",
            "return ops;",
        ])
        assert assert_moo_success(result) == (
            '{{"expr_asgn", {"=", 1, "right"}}, {"expr_or", {"||", 3, "left"}}, {"expr_and", {"&&", 3, "left"}}, '
            '{"expr_plus", {"+", 9, "left"}}, {"expr_times", {"*", 10, "left"}}, '
            '{"expr_exp", {"^", 11, "right"}}, {"expr_not", {"!", 12, "prefix"}}}')

    def test_ast_143_schema_matches_trees(self, client, program):
        """AST-143: Every kind the corpus produces is listed, with its field count."""
        corpus = CORPUS + [["frobnicate();"]]
        result, _ = program([
            "kinds = {};",
            "for k in (ast_info()[2])",
            "  kinds = {@kinds, {k[1], length(k[3])}};",
            "endfor",
            f"todo = {{{', '.join('ast_parse(' + moo_lines(c) + ', {{\"builtins\", \"lenient\"}})[1]' for c in corpus)}}};",
            "seen = {};",
            "bad = {};",
            "while (todo)",
            "  n = todo[$];",
            "  todo[$..$] = {};",
            "  if (typeof(n) == LIST && length(n) >= 2 && typeof(n[1]) == STR && typeof(n[2]) == INT)",
            "    entry = {n[1], length(n) - 2};",
            "    entry in kinds || (bad = {@bad, entry});",
            "    n[1] in seen || (seen = {@seen, n[1]});",
            "    todo = {@todo, @n[3..$]};",
            "  elseif (typeof(n) == LIST)",
            "    todo = {@todo, @n};",
            "  endif",
            "endwhile",
            "return {bad, length(seen)};",
        ])
        value = assert_moo_success(result)
        assert value.startswith("{{}, "), value

    def test_ast_144_bitwise_kinds_follow_build(self, client, detected_features):
        """AST-144: The bitwise kinds are listed exactly when the server has bitwise operators."""
        listed = assert_moo_success(client.eval("ast_info()[2]"))
        assert ('"expr_bitor"' in listed) == detected_features.has_bitwise
        assert ('"expr_complement"' in listed) == detected_features.has_bitwise
