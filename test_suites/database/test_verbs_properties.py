"""Verb and property administration builtins (VP-001 onward).

Covers add_verb, verb_info, verb_args, set_verb_info, set_verb_args,
delete_verb, verb_code, set_verb_code, verbs, and the property equivalents,
including the permission checks a non-wizard programmer is subject to.
"""

import pytest

from lib.assertions import (
    assert_moo_int,
    assert_moo_raises,
    assert_moo_string,
    assert_moo_success,
)
from lib.moocode import moo_list


@pytest.fixture
def obj(client):
    """A fresh object, child of #1, owned by the wizard."""
    return assert_moo_success(client.eval("create(#1)"))


def add_verb(client, obj, names, perms="rx", args=("this", "none", "this"), owner="player"):
    """Add a verb and return its 1-based index."""
    spec = ", ".join(f'"{a}"' for a in args)
    return assert_moo_success(client.eval(f'add_verb({obj}, {{{owner}, "{perms}", "{names}"}}, {{{spec}}})'))


class TestVerbInfo:
    """add_verb, verb_info, set_verb_info, verbs and delete_verb."""

    def test_vp_001_add_and_read_back(self, client, obj):
        """VP-001: add_verb returns the verb's index and verb_info reads it back."""
        assert add_verb(client, obj, "foo b*ar", "rxd") == "1"
        assert add_verb(client, obj, "second") == "2"
        assert assert_moo_success(client.eval(f'verb_info({obj}, "foo")')) == '{#3, "rxd", "foo b*ar"}'
        assert assert_moo_success(client.eval(f"verbs({obj})")) == '{"foo b*ar", "second"}'

    def test_vp_002_names_match_with_wildcards(self, client, obj):
        """VP-002: A * in a verb name allows any abbreviation from that point."""
        add_verb(client, obj, "foo b*ar")
        for name in ("b", "ba", "bar"):
            assert_moo_success(client.eval(f'verb_info({obj}, "{name}")'))
        assert_moo_raises(client, f'verb_info({obj}, "bars")', "E_VERBNF")
        assert_moo_raises(client, f'verb_info({obj}, "fo")', "E_VERBNF")

    def test_vp_003_numeric_descriptor(self, client, obj):
        """VP-003: Verbs can be named by 1-based index; 0 and negatives are E_INVARG."""
        add_verb(client, obj, "only")
        assert assert_moo_success(client.eval(f"verb_info({obj}, 1)"))[-7:] == '"only"}'
        assert_moo_raises(client, f"verb_info({obj}, 0)", "E_INVARG")
        assert_moo_raises(client, f"verb_info({obj}, -1)", "E_INVARG")
        assert_moo_raises(client, f"verb_info({obj}, 2)", "E_VERBNF")
        assert_moo_raises(client, f"verb_info({obj}, 1.0)", "E_TYPE")

    def test_vp_004_set_verb_info(self, client, obj):
        """VP-004: set_verb_info replaces owner, flags and names; flags are case-insensitive."""
        add_verb(client, obj, "old")
        assert_moo_success(client.eval(f'set_verb_info({obj}, "old", {{#3, "RWXD", "new  names"}})'))
        assert assert_moo_success(client.eval(f"verb_info({obj}, 1)")) == '{#3, "rwxd", "new  names"}'
        assert_moo_raises(client, f'verb_info({obj}, "old")', "E_VERBNF")

    @pytest.mark.parametrize("info,error", [
        ('{#3, "rq", "x"}', "E_INVARG"),
        ('{#3, "r", "   "}', "E_INVARG"),
        ('{#-1, "r", "x"}', "E_INVARG"),
        ('{#3, "r"}', "E_TYPE"),
        ('{"#3", "r", "x"}', "E_TYPE"),
        ('"x"', "E_TYPE"),
    ])
    def test_vp_005_bad_verb_info(self, client, obj, info, error):
        """VP-005: add_verb and set_verb_info validate the info list the same way."""
        add_verb(client, obj, "v")
        assert_moo_raises(client, f"set_verb_info({obj}, 1, {info})", error)
        assert_moo_raises(client, f'add_verb({obj}, {info}, {{"this", "none", "this"}})', error)

    def test_vp_006_delete_verb(self, client, obj):
        """VP-006: delete_verb removes a verb; deleting it again is E_VERBNF."""
        add_verb(client, obj, "a")
        add_verb(client, obj, "b")
        assert_moo_success(client.eval(f'delete_verb({obj}, "a")'))
        assert assert_moo_success(client.eval(f"verbs({obj})")) == '{"b"}'
        assert_moo_raises(client, f'delete_verb({obj}, "a")', "E_VERBNF")
        assert_moo_raises(client, f"delete_verb({obj}, 0)", "E_INVARG")

    def test_vp_007_invalid_object(self, client):
        """VP-007: Every verb builtin rejects an invalid object with E_INVARG."""
        for expr in ("verbs(#-1)", "verb_info(#-1, 1)", "verb_args(#-1, 1)", "verb_code(#-1, 1)",
                     'delete_verb(#-1, "x")', 'set_verb_code(#-1, "x", {})',
                     'set_verb_info(#-1, 1, {#3, "r", "x"})', 'set_verb_args(#-1, 1, {"this", "none", "this"})',
                     'add_verb(#-1, {#3, "r", "x"}, {"this", "none", "this"})'):
            assert_moo_raises(client, expr, "E_INVARG")


class TestVerbArgs:
    """verb_args and set_verb_args."""

    def test_vp_010_prepositions_shown_in_full(self, client, obj):
        """VP-010: verb_args shows every alternative of the preposition."""
        add_verb(client, obj, "v", args=("this", "with", "any"))
        assert assert_moo_success(client.eval(f"verb_args({obj}, 1)")) == '{"this", "with/using", "any"}'

    def test_vp_011_set_verb_args(self, client, obj):
        """VP-011: set_verb_args accepts any one spelling of a preposition."""
        add_verb(client, obj, "v")
        assert_moo_success(client.eval(f'set_verb_args({obj}, 1, {{"any", "on top of", "none"}})'))
        assert assert_moo_success(client.eval(f"verb_args({obj}, 1)")) == \
            '{"any", "on top of/on/onto/upon", "none"}'
        assert_moo_success(client.eval(f'set_verb_args({obj}, 1, {{"NONE", "Any", "THIS"}})'))
        assert assert_moo_success(client.eval(f"verb_args({obj}, 1)")) == '{"none", "any", "this"}'

    @pytest.mark.parametrize("args,error", [
        ('{"any", "bogus", "none"}', "E_INVARG"),
        ('{"some", "none", "none"}', "E_INVARG"),
        ('{"any", "none"}', "E_TYPE"),
        ('{"any", 1, "none"}', "E_TYPE"),
    ])
    def test_vp_012_bad_args(self, client, obj, args, error):
        """VP-012: Unknown specs are E_INVARG; a malformed list is E_TYPE."""
        add_verb(client, obj, "v")
        assert_moo_raises(client, f"set_verb_args({obj}, 1, {args})", error)
        assert_moo_raises(client, f'add_verb({obj}, {{#3, "r", "w"}}, {args})', error)


class TestVerbCode:
    """set_verb_code and verb_code."""

    def test_vp_020_compile_errors_returned(self, client, obj):
        """VP-020: Compile errors come back as a list and leave the old code in place."""
        add_verb(client, obj, "v")
        assert assert_moo_success(client.eval(f'set_verb_code({obj}, 1, {{"return 5;"}})')) == "{}"
        errors = assert_moo_success(client.eval(f'set_verb_code({obj}, 1, {{"x = ;"}})'))
        assert "syntax error" in errors
        assert assert_moo_success(client.eval(f"verb_code({obj}, 1)")) == '{"return 5;"}'

    def test_vp_021_non_string_line(self, client, obj):
        """VP-021: A code line that is not a string is E_TYPE."""
        add_verb(client, obj, "v")
        assert_moo_raises(client, f'set_verb_code({obj}, 1, {{"return 1;", 2}})', "E_TYPE")

    def test_vp_022_indent_and_parens(self, client, obj):
        """VP-022: verb_code indents by default and fully parenthesizes on request."""
        add_verb(client, obj, "v")
        code = ["x = 1 + 2 * 3;", "if (x)", "  y = -x ^ 2;", "endif", "return a && b || c;"]
        assert_moo_success(client.eval(f"set_verb_code({obj}, 1, {moo_list(code)})"))
        assert assert_moo_success(client.eval(f"verb_code({obj}, 1)")) == moo_list(code)
        assert assert_moo_success(client.eval(f"verb_code({obj}, 1, 1)")) == moo_list(
            ["x = 1 + (2 * 3);", "if (x)", "  y = (-x) ^ 2;", "endif", "return (a && b) || c;"])
        assert assert_moo_success(client.eval(f"verb_code({obj}, 1, 0, 0)")) == moo_list(
            ["x = 1 + 2 * 3;", "if (x)", "y = -x ^ 2;", "endif", "return a && b || c;"])

    def test_vp_023_verb_runs_after_set(self, client, obj):
        """VP-023: Code set with set_verb_code is what the verb runs."""
        add_verb(client, obj, "v")
        assert_moo_success(client.eval(f'set_verb_code({obj}, 1, {{"return args[1] * 2;"}})'))
        assert_moo_int(client.eval(f"{obj}:v(21)"), 42)


# Source written in the form verb_code() prints, so it must round-trip
# unchanged.  It exercises every statement and expression form the
# decompiler has to rebuild from bytecode.
ROUND_TRIP = [
    "{a, ?b = 2, @rest} = args;",
    "x = {1, 2.5, \"three\", #4, E_PERM, {}};",
    "x[1] = x[2..$];",
    "x[1..2] = {@x, @args};",
    "y = x[1] + x[$];",
    "z = `x[10] ! E_RANGE => 0';",
    "w = `x[10] ! ANY';",
    "v = `1 / 0 ! E_DIV, E_TYPE';",
    "u = a ? b | c;",
    "t = !a && (b || c) && -d;",
    "s = 1 in x;",
    "r = a == b != c < d <= e > f >= g;",
    "q = a + b - c * d / e % f ^ g;",
    "p = this.name;",
    "o = this.(\"na\" + \"me\");",
    "n = $nothing;",
    "m = this:foo(1, @args);",
    "l = this:(\"fo\" + \"o\")();",
    "k = $sys_verb();",
    "j = length(x);",
    "if (a)",
    "  return 1;",
    "elseif (b)",
    "  return 2;",
    "else",
    "  return 3;",
    "endif",
    "for item in (x)",
    "  continue;",
    "endfor",
    "for i in [1..10]",
    "  break;",
    "endfor",
    "while outer (1)",
    "  while (0)",
    "    break outer;",
    "  endwhile",
    "  continue outer;",
    "endwhile",
    "while (a)",
    "  a = a - 1;",
    "endwhile",
    "fork (0)",
    "  return;",
    "endfork",
    "fork tid (5)",
    "  suspend(1);",
    "endfork",
    "try",
    "  raise(E_INVARG, \"message\", 5);",
    "except e (E_INVARG, E_PERM)",
    "  return e[1];",
    "except (ANY)",
    "  return 0;",
    "endtry",
    "try",
    "  x = 1;",
    "finally",
    "  x = 2;",
    "endtry",
    "return;",
]


class TestDecompile:
    """Every syntax form survives compile, decompile and recompile."""

    def test_vp_030_round_trip(self, client, obj):
        """VP-030: verb_code returns the canonical source unchanged."""
        add_verb(client, obj, "v")
        assert assert_moo_success(client.eval(f"set_verb_code({obj}, 1, {moo_list(ROUND_TRIP)})")) == "{}"
        assert assert_moo_success(client.eval(f"verb_code({obj}, 1)")) == moo_list(ROUND_TRIP)

    def test_vp_031_recompile_is_a_fixed_point(self, client, obj):
        """VP-031: Recompiling verb_code's output gives the same code again."""
        add_verb(client, obj, "v")
        add_verb(client, obj, "w")
        assert_moo_success(client.eval(f"set_verb_code({obj}, 1, {moo_list(ROUND_TRIP)})"))
        assert assert_moo_success(client.eval(f"set_verb_code({obj}, 2, verb_code({obj}, 1))")) == "{}"
        assert assert_moo_success(client.eval(f"verb_code({obj}, 1) == verb_code({obj}, 2)")) == "1"

    def test_vp_032_canonicalizes_spacing_and_parens(self, client, obj):
        """VP-032: Redundant parentheses and odd spacing are normalized away."""
        add_verb(client, obj, "v")
        assert_moo_success(client.eval(
            f'set_verb_code({obj}, 1, {{"x=((1)+(2*3));", "if(x)return  x;endif"}})'))
        assert assert_moo_success(client.eval(f"verb_code({obj}, 1)")) == \
            moo_list(["x = 1 + 2 * 3;", "if (x)", "  return x;", "endif"])


class TestPropertyInfo:
    """add_property, property_info, set_property_info, delete_property, properties."""

    def test_vp_040_add_and_inherit(self, client, obj):
        """VP-040: A child inherits a new property's value and info."""
        assert_moo_success(client.eval(f'add_property({obj}, "color", "red", {{player, "rc"}})'))
        child = assert_moo_success(client.eval(f"create({obj})"))
        assert_moo_string(client.eval(f"{child}.color"), "red")
        assert assert_moo_success(client.eval(f'property_info({child}, "color")')) == '{#3, "rc"}'
        assert assert_moo_success(client.eval(f"properties({obj})")) == '{"color"}'
        assert assert_moo_success(client.eval(f"properties({child})")) == "{}"

    @pytest.mark.parametrize("name", ["color", "COLOR", "name", "owner"])
    def test_vp_041_duplicate_names(self, client, obj, name):
        """VP-041: A name already defined (in any case) or built in is E_INVARG."""
        assert_moo_success(client.eval(f'add_property({obj}, "color", 0, {{player, ""}})'))
        assert_moo_raises(client, f'add_property({obj}, "{name}", 0, {{player, ""}})', "E_INVARG")

    def test_vp_042_duplicate_in_descendant(self, client, obj):
        """VP-042: A name a descendant already defines is E_INVARG on the ancestor."""
        child = assert_moo_success(client.eval(f"create({obj})"))
        assert_moo_success(client.eval(f'add_property({child}, "mine", 0, {{player, ""}})'))
        assert_moo_raises(client, f'add_property({obj}, "mine", 0, {{player, ""}})', "E_INVARG")

    def test_vp_043_rename_and_change_flags(self, client, obj):
        """VP-043: set_property_info changes flags and, on the definer, the name."""
        assert_moo_success(client.eval(f'add_property({obj}, "color", "red", {{player, "r"}})'))
        child = assert_moo_success(client.eval(f"create({obj})"))
        assert_moo_success(client.eval(f'set_property_info({obj}, "color", {{player, "wc", "hue"}})'))
        assert assert_moo_success(client.eval(f'property_info({obj}, "hue")')) == '{#3, "wc"}'
        assert_moo_string(client.eval(f"{child}.hue"), "red")
        assert_moo_raises(client, f'property_info({obj}, "color")', "E_PROPNF")
        assert_moo_raises(client, f'set_property_info({child}, "hue", {{player, "r", "x"}})', "E_INVARG")

    @pytest.mark.parametrize("info,error", [
        ('{#3, "rq"}', "E_INVARG"),
        ('{#-1, "r"}', "E_INVARG"),
        ('{#3}', "E_TYPE"),
        ('{#3, "r", 5}', "E_TYPE"),
        ('{#3, 1}', "E_TYPE"),
    ])
    def test_vp_044_bad_property_info(self, client, obj, info, error):
        """VP-044: Property info lists are validated."""
        assert_moo_success(client.eval(f'add_property({obj}, "p", 0, {{player, ""}})'))
        assert_moo_raises(client, f'set_property_info({obj}, "p", {info})', error)

    def test_vp_045_add_property_with_new_name(self, client, obj):
        """VP-045: add_property's info may not carry a third (rename) element."""
        assert_moo_raises(client, f'add_property({obj}, "p", 0, {{player, "r", "x"}})', "E_TYPE")

    def test_vp_046_builtin_properties_have_no_info(self, client, obj):
        """VP-046: property_info on a built-in property is E_PROPNF."""
        assert_moo_raises(client, f'property_info({obj}, "name")', "E_PROPNF")
        assert_moo_raises(client, f'set_property_info({obj}, "owner", {{player, "r"}})', "E_PROPNF")

    def test_vp_047_delete_property(self, client, obj):
        """VP-047: delete_property works only on the definer and removes it from children."""
        assert_moo_success(client.eval(f'add_property({obj}, "p", 1, {{player, "r"}})'))
        child = assert_moo_success(client.eval(f"create({obj})"))
        assert_moo_raises(client, f'delete_property({child}, "p")', "E_PROPNF")
        assert_moo_success(client.eval(f'delete_property({obj}, "p")'))
        assert_moo_raises(client, f"{child}.p", "E_PROPNF")
        assert_moo_raises(client, f'delete_property({obj}, "p")', "E_PROPNF")

    def test_vp_048_invalid_object(self, client):
        """VP-048: Every property builtin rejects an invalid object with E_INVARG."""
        for expr in ("properties(#-1)", 'property_info(#-1, "p")', 'delete_property(#-1, "p")',
                     'clear_property(#-1, "p")', 'is_clear_property(#-1, "p")',
                     'set_property_info(#-1, "p", {#3, "r"})', 'add_property(#-1, "p", 0, {#3, "r"})'):
            assert_moo_raises(client, expr, "E_INVARG")


class TestClearProperties:
    """clear_property and is_clear_property."""

    def test_vp_050_inherited_value_is_clear(self, client, obj):
        """VP-050: A child's property is clear until set, and clear again after clear_property."""
        assert_moo_success(client.eval(f'add_property({obj}, "p", "parent", {{player, "r"}})'))
        child = assert_moo_success(client.eval(f"create({obj})"))
        assert_moo_int(client.eval(f'is_clear_property({child}, "p")'), 1)
        assert_moo_success(client.eval(f'{child}.p = "child"'))
        assert_moo_int(client.eval(f'is_clear_property({child}, "p")'), 0)
        assert_moo_success(client.eval(f'clear_property({child}, "p")'))
        assert_moo_int(client.eval(f'is_clear_property({child}, "p")'), 1)
        assert_moo_string(client.eval(f"{child}.p"), "parent")

    def test_vp_051_clear_follows_parent_changes(self, client, obj):
        """VP-051: A clear property shows the parent's current value."""
        assert_moo_success(client.eval(f'add_property({obj}, "p", 1, {{player, "r"}})'))
        child = assert_moo_success(client.eval(f"create({obj})"))
        assert_moo_success(client.eval(f"{obj}.p = 2"))
        assert_moo_int(client.eval(f"{child}.p"), 2)

    def test_vp_052_cannot_clear_on_definer(self, client, obj):
        """VP-052: clear_property on the defining object is E_INVARG."""
        assert_moo_success(client.eval(f'add_property({obj}, "p", 1, {{player, "r"}})'))
        assert_moo_raises(client, f'clear_property({obj}, "p")', "E_INVARG")
        assert_moo_int(client.eval(f'is_clear_property({obj}, "p")'), 0)

    def test_vp_053_builtin_properties(self, client, obj):
        """VP-053: Built-in properties are never clear and cannot be cleared."""
        assert_moo_int(client.eval(f'is_clear_property({obj}, "name")'), 0)
        assert_moo_raises(client, f'clear_property({obj}, "name")', "E_PERM")
        assert_moo_raises(client, f'is_clear_property({obj}, "nonesuch")', "E_PROPNF")
        assert_moo_raises(client, f'clear_property({obj}, "nonesuch")', "E_PROPNF")


class TestProgrammerPermissions:
    """What a non-wizard programmer (#4, Player2) may and may not do."""

    def test_vp_060_cannot_add_verb_to_others_object(self, wizard_and_programmer):
        """VP-060: Adding a verb needs write permission on the object."""
        wiz, prog = wizard_and_programmer
        theirs = assert_moo_success(wiz.eval("create(#1)"))
        assert_moo_raises(prog, f'add_verb({theirs}, {{player, "rx", "v"}}, {{"this", "none", "this"}})', "E_PERM")
        assert_moo_success(wiz.eval(f"{theirs}.w = 1"))
        assert_moo_success(prog.eval(f'add_verb({theirs}, {{player, "rx", "v"}}, {{"this", "none", "this"}})'))

    def test_vp_061_cannot_give_verb_to_someone_else(self, wizard_and_programmer):
        """VP-061: A programmer may only add or reassign verbs owned by themselves."""
        wiz, prog = wizard_and_programmer
        mine = assert_moo_success(wiz.eval("create(#1, #4)"))
        assert_moo_raises(prog, f'add_verb({mine}, {{#3, "rx", "v"}}, {{"this", "none", "this"}})', "E_PERM")
        assert_moo_success(prog.eval(f'add_verb({mine}, {{player, "rx", "v"}}, {{"this", "none", "this"}})'))
        assert_moo_raises(prog, f'set_verb_info({mine}, 1, {{#3, "rx", "v"}})', "E_PERM")
        assert_moo_success(prog.eval(f'set_verb_info({mine}, 1, {{player, "rxd", "v2"}})'))

    def test_vp_062_unreadable_verb(self, wizard_and_programmer):
        """VP-062: A verb without the r flag hides its info, args and code from non-owners."""
        wiz, prog = wizard_and_programmer
        theirs = assert_moo_success(wiz.eval("create(#1)"))
        assert_moo_success(wiz.eval(f'add_verb({theirs}, {{player, "x", "secret"}}, {{"this", "none", "this"}})'))
        for expr in ("verb_info({o}, 1)", "verb_args({o}, 1)", "verb_code({o}, 1)"):
            assert_moo_raises(prog, expr.format(o=theirs), "E_PERM")
        assert_moo_success(wiz.eval(f'set_verb_info({theirs}, 1, {{player, "rx", "secret"}})'))
        assert_moo_success(prog.eval(f"verb_code({theirs}, 1)"))

    def test_vp_063_unwritable_verb(self, wizard_and_programmer):
        """VP-063: Without the w flag a non-owner cannot change a verb's code, args or info."""
        wiz, prog = wizard_and_programmer
        theirs = assert_moo_success(wiz.eval("create(#1)"))
        assert_moo_success(wiz.eval(f"{theirs}.w = 1"))
        assert_moo_success(wiz.eval(f'add_verb({theirs}, {{player, "rx", "v"}}, {{"this", "none", "this"}})'))
        assert_moo_raises(prog, f'set_verb_code({theirs}, 1, {{"return 1;"}})', "E_PERM")
        assert_moo_raises(prog, f'set_verb_args({theirs}, 1, {{"any", "any", "any"}})', "E_PERM")
        assert_moo_raises(prog, f'set_verb_info({theirs}, 1, {{#3, "rxw", "v"}})', "E_PERM")

    def test_vp_064_unreadable_object(self, wizard_and_programmer):
        """VP-064: verbs() and properties() need read permission on the object."""
        wiz, prog = wizard_and_programmer
        theirs = assert_moo_success(wiz.eval("create(#1)"))
        assert_moo_raises(prog, f"verbs({theirs})", "E_PERM")
        assert_moo_raises(prog, f"properties({theirs})", "E_PERM")
        assert_moo_success(wiz.eval(f"{theirs}.r = 1"))
        assert_moo_success(prog.eval(f"verbs({theirs})"))
        assert_moo_success(prog.eval(f"properties({theirs})"))

    def test_vp_065_property_ownership(self, wizard_and_programmer):
        """VP-065: A programmer may only add or reassign properties owned by themselves."""
        wiz, prog = wizard_and_programmer
        mine = assert_moo_success(wiz.eval("create(#1, #4)"))
        assert_moo_raises(prog, f'add_property({mine}, "p", 0, {{#3, "r"}})', "E_PERM")
        assert_moo_success(prog.eval(f'add_property({mine}, "p", 0, {{player, "r"}})'))
        assert_moo_raises(prog, f'set_property_info({mine}, "p", {{#3, "r"}})', "E_PERM")
        assert_moo_success(prog.eval(f'set_property_info({mine}, "p", {{player, "rw"}})'))

    def test_vp_066_unreadable_property(self, wizard_and_programmer):
        """VP-066: Without the r flag, property_info and is_clear_property are E_PERM."""
        wiz, prog = wizard_and_programmer
        theirs = assert_moo_success(wiz.eval("create(#1)"))
        assert_moo_success(wiz.eval(f'add_property({theirs}, "hidden", 1, {{player, ""}})'))
        assert_moo_raises(prog, f'property_info({theirs}, "hidden")', "E_PERM")
        assert_moo_raises(prog, f'is_clear_property({theirs}, "hidden")', "E_PERM")
        assert_moo_raises(prog, f"{theirs}.hidden", "E_PERM")

    def test_vp_067_clear_needs_ownership(self, wizard_and_programmer):
        """VP-067: Only the property's owner (or a wizard) may clear it."""
        wiz, prog = wizard_and_programmer
        parent = assert_moo_success(wiz.eval("create(#1)"))
        assert_moo_success(wiz.eval(f'add_property({parent}, "p", 1, {{player, "rw"}})'))
        assert_moo_success(wiz.eval(f"{parent}.f = 1"))
        child = assert_moo_success(prog.eval(f"create({parent})"))
        assert_moo_raises(prog, f'clear_property({child}, "p")', "E_PERM")
        assert_moo_success(wiz.eval(f'clear_property({child}, "p")'))

    def test_vp_068_delete_needs_write(self, wizard_and_programmer):
        """VP-068: delete_verb and delete_property need write permission on the object."""
        wiz, prog = wizard_and_programmer
        theirs = assert_moo_success(wiz.eval("create(#1)"))
        assert_moo_success(wiz.eval(f'add_verb({theirs}, {{player, "rxw", "v"}}, {{"this", "none", "this"}})'))
        assert_moo_success(wiz.eval(f'add_property({theirs}, "p", 0, {{player, "rw"}})'))
        assert_moo_raises(prog, f'delete_verb({theirs}, "v")', "E_PERM")
        assert_moo_raises(prog, f'delete_property({theirs}, "p")', "E_PERM")

    def test_vp_069_non_programmer_cannot_set_code(self, wizard_and_programmer):
        """VP-069: set_verb_code needs the programmer bit even on one's own verb."""
        wiz, prog = wizard_and_programmer
        mine = assert_moo_success(wiz.eval("create(#1, #4)"))
        assert_moo_success(prog.eval(f'add_verb({mine}, {{player, "rxw", "v"}}, {{"this", "none", "this"}})'))
        as_player2 = f'eval("set_task_perms(#4); return set_verb_code({mine}, 1, {{\\"return 1;\\"}});")'
        assert assert_moo_success(wiz.eval(as_player2)) == "{1, {}}"
        assert_moo_success(wiz.eval("#4.programmer = 0"))
        assert_moo_raises(wiz, as_player2, "E_PERM")
