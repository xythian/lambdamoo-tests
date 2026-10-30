"""Command parsing, dispatch and in-band commands (CMD-001 onward).

Lines that #0:do_command declines (the test database's do_command only
handles ";expr") go to the server's own parser, which looks for a matching
verb on the player, the player's location, the direct object and the
indirect object, then falls back to the location's :huh. Also covers the
intrinsic commands (.program, PREFIX, SUFFIX, OUTPUTPREFIX, OUTPUTSUFFIX),
the flush command and out-of-band commands.
"""

import pytest

from lib.assertions import assert_moo_int, assert_moo_success
from lib.moocode import define_verb

SHOW = 'notify(player, toliteral({"{tag}", verb, argstr, args, dobjstr, dobj, prepstr, iobjstr, iobj, this}));'


def show_verb(client, obj, names, tag, args=("any", "any", "any")):
    """Define a verb that echoes its tag and the parsed command variables."""
    define_verb(client, obj, names, [SHOW.replace("{tag}", tag)], args=args)


def command(client, line, timeout=1.0):
    """Send a command line and return everything the server prints in response."""
    client.send(line)
    return client.receive(timeout=timeout)


@pytest.fixture
def room(client):
    """A fresh room holding the wizard, a "red ball" and a "box"; returns (room, ball, box)."""
    room = assert_moo_success(client.eval("create(#1)"))
    ball = assert_moo_success(client.eval("create(#1)"))
    box = assert_moo_success(client.eval("create(#1)"))
    assert_moo_success(client.eval(f'{room}.name = "Test Room"'))
    assert_moo_success(client.eval(f'{ball}.name = "red ball"'))
    assert_moo_success(client.eval(f'{box}.name = "box"'))
    for obj in (ball, box):
        assert_moo_success(client.eval(f"move({obj}, {room})"))
    assert_moo_success(client.eval(f"move(player, {room})"))
    return room, ball, box


class TestParsing:
    """How a command line is split into verb, objects and preposition."""

    def test_cmd_001_bare_verb(self, client, room):
        """CMD-001: A verb alone has empty strings and #-1 objects."""
        show_verb(client, "#3", "show", "player")
        assert '{"player", "show", "", {}, "", #-1, "", "", #-1, #3}' in command(client, "show")

    def test_cmd_002_objects_and_preposition(self, client, room):
        """CMD-002: "verb dobj prep iobj" matches both objects by name in the room."""
        _, ball, box = room
        show_verb(client, "#3", "show", "player")
        out = command(client, "show red ball in box")
        assert (f'{{"player", "show", "red ball in box", {{"red", "ball", "in", "box"}}, '
                f'"red ball", {ball}, "in", "box", {box}, #3}}') in out

    def test_cmd_003_multi_word_preposition(self, client, room):
        """CMD-003: Multi-word prepositions like "on top of" are recognized."""
        _, _, box = room
        show_verb(client, "#3", "show", "player")
        assert f'"on top of", "box", {box}' in command(client, "show red on top of box")

    def test_cmd_004_quoting(self, client, room):
        """CMD-004: Double quotes group words into one argument and are removed."""
        show_verb(client, "#3", "show", "player")
        out = command(client, 'show "two words" here')
        assert '{"two words", "here"}, "two words here", #-3' in out

    def test_cmd_005_special_names(self, client, room):
        """CMD-005: "me" is the player, "here" the location, and "#N" an object number."""
        rm, _, box = room
        show_verb(client, "#3", "show", "player")
        assert f'"me", #3, "to", "here", {rm}' in command(client, "show me to here")
        assert f'"{box}", {box}, "", "", #-1' in command(client, f"show {box}")

    def test_cmd_006_failed_and_ambiguous_matches(self, client, room):
        """CMD-006: An unmatched name is #-3 ($failed_match); a name matching two objects is #-2."""
        rm = room[0]
        other = assert_moo_success(client.eval("create(#1)"))
        assert_moo_success(client.eval(f'{other}.name = "red box"'))
        assert_moo_success(client.eval(f"move({other}, {rm})"))
        show_verb(client, "#3", "show", "player")
        assert '"nothing", #-3' in command(client, "show nothing")
        assert '"red", #-2' in command(client, "show red")

    def test_cmd_007_verb_name_wildcards(self, client, room):
        """CMD-007: A verb named "sh*ow" answers to "sh", "sho" and "show" but not "s"."""
        show_verb(client, "#3", "sh*ow", "player")
        for typed in ("sh", "sho", "show"):
            assert f'{{"player", "{typed}",' in command(client, typed)
        assert "I couldn't understand that." in command(client, "s")


class TestDispatch:
    """Which object's verb runs for a command."""

    def test_cmd_010_search_order(self, client, room):
        """CMD-010: The player is searched first, then the location, then dobj, then iobj."""
        rm, ball, box = room
        show_verb(client, box, "poke", "iobj", args=("any", "with", "this"))
        assert '{"iobj"' in command(client, "poke red with box")
        show_verb(client, ball, "poke", "dobj", args=("this", "with", "any"))
        assert '{"dobj"' in command(client, "poke red with box")
        show_verb(client, rm, "poke", "room")
        assert '{"room"' in command(client, "poke red with box")
        show_verb(client, "#3", "poke", "player")
        assert '{"player"' in command(client, "poke red with box")

    def test_cmd_011_argument_specifiers(self, client, room):
        """CMD-011: A verb is only a candidate when its dobj/prep/iobj specifiers fit the command."""
        _, ball, _ = room
        show_verb(client, ball, "kick", "this-none-none", args=("this", "none", "none"))
        assert '{"this-none-none"' in command(client, "kick red")
        assert "I couldn't understand that." in command(client, "kick red at box")
        assert "I couldn't understand that." in command(client, "kick")

    def test_cmd_012_preposition_specifier(self, client, room):
        """CMD-012: A verb for one preposition doesn't match a command using another."""
        _, _, box = room
        show_verb(client, box, "put", "put-in", args=("any", "in/inside/into", "this"))
        assert '{"put-in"' in command(client, "put red into box")
        assert "I couldn't understand that." in command(client, "put red on box")

    def test_cmd_013_huh_fallback(self, client, room):
        """CMD-013: With no matching verb, the location's :huh runs with the parsed command."""
        rm = room[0]
        show_verb(client, rm, "huh", "huh")
        assert '{"huh", "frobnicate", "the box"' in command(client, "frobnicate the box")

    def test_cmd_014_not_understood(self, client, room):
        """CMD-014: With no verb and no :huh the player is told the command wasn't understood."""
        assert "I couldn't understand that." in command(client, "frobnicate")

    def test_cmd_015_commands_ignore_x_flag(self, client, room):
        """CMD-015: A verb without the x flag still runs as a command, though it can't be called with ":"."""
        define_verb(client, "#3", "quiet", ['notify(player, "ran");'], perms="rd", args=("none", "none", "none"))
        assert "ran" in command(client, "quiet")
        success, text = client.eval("#3:quiet()")
        assert not success and "Verb not found" in text

    def test_cmd_016_do_command_can_claim_the_line(self, client, room):
        """CMD-016: When #0:do_command returns true the server does no parsing of its own."""
        show_verb(client, "#3", "show", "player")
        code = assert_moo_success(client.eval('verb_code(#0, "do_command")'))
        assert_moo_success(client.eval(
            'set_verb_code(#0, "do_command", {"if (args && args[1] == \\"show\\")", '
            '"  notify(player, \\"claimed\\");", "  return 1;", "endif", @' + code + "})"))
        out = command(client, "show")
        assert "claimed" in out
        assert '{"player"' not in out


class TestIntrinsicCommands:
    """PREFIX/SUFFIX, .program and the flush command."""

    def test_cmd_020_prefix_and_suffix(self, client):
        """CMD-020: PREFIX and SUFFIX lines wrap each command's output and show in output_delimiters()."""
        client.send("PREFIX <<start>>")
        client.send("SUFFIX <<end>>")
        out = command(client, ";output_delimiters(player)")
        lines = [line for line in out.splitlines() if line]
        assert lines == ["<<start>>", '#-1:  => {"<<start>>", "<<end>>"}', "<<end>>"]

    def test_cmd_021_output_aliases_and_clearing(self, client):
        """CMD-021: OUTPUTPREFIX and OUTPUTSUFFIX are synonyms; an empty value clears the delimiter."""
        client.send("OUTPUTPREFIX [[")
        client.send("OUTPUTSUFFIX ]]")
        assert '{"[[", "]]"}' in command(client, ";output_delimiters(player)")
        client.send("PREFIX")
        client.send("SUFFIX")
        assert assert_moo_success(client.eval("output_delimiters(player)")) == '{"", ""}'

    def test_cmd_022_program_verb(self, client):
        """CMD-022: ".program obj:verb" reads source lines up to "." and compiles them into the verb."""
        obj = assert_moo_success(client.eval("create(#1)"))
        define_verb(client, obj, "target", ["return 1;"])
        assert 'Now programming' in command(client, f".program {obj}:target")
        client.send('x = "programmed";')
        client.send("return x;")
        out = command(client, ".")
        assert "0 error(s)." in out and "Verb programmed." in out
        assert assert_moo_success(client.eval(f"{obj}:target()")) == '"programmed"'

    def test_cmd_023_program_syntax_error(self, client):
        """CMD-023: A program with errors is reported and leaves the verb unchanged."""
        obj = assert_moo_success(client.eval("create(#1)"))
        define_verb(client, obj, "target", ["return 1;"])
        command(client, f".program {obj}:target")
        client.send("return (;")
        out = command(client, ".")
        assert "1 error(s)." in out and "Verb not programmed." in out
        assert_moo_int(client.eval(f"{obj}:target()"), 1)

    def test_cmd_024_program_errors(self, client):
        """CMD-024: .program reports usage errors and missing objects or verbs."""
        obj = assert_moo_success(client.eval("create(#1)"))
        assert "Usage:  .program object:verb" in command(client, ".program")
        assert "That object does not have that verb definition." in command(client, f".program {obj}:nope")
        assert 'I don\'t see "nosuchthing" here.' in command(client, ".program nosuchthing:verb")
        assert 'I don\'t see "#999999" here.' in command(client, ".program #999999:verb")
        assert "You must specify a verb" in command(client, f".program {obj}")

    def test_cmd_025_program_needs_programmer(self, wizard_and_programmer):
        """CMD-025: For a non-programmer, .program is not an intrinsic command."""
        wiz, prog = wizard_and_programmer
        obj = assert_moo_success(wiz.eval("create(#1, #4)"))
        define_verb(wiz, obj, "target", ["return 1;"], owner="#4")
        assert_moo_success(wiz.eval("#4.programmer = 0"))
        out = command(prog, f".program {obj}:target")
        assert "Now programming" not in out
        assert "I couldn't understand that." in out

    def test_cmd_026_flush_command(self, client):
        """CMD-026: The flush command (".flush" by default) discards input queued behind a running task."""
        assert assert_moo_success(client.eval('connection_option(player, "flush-command")')) == '".flush"'
        client.send(";suspend(1)")
        client.send(';notify(player, "QUEUED")')
        client.send(".flush")
        out = client.receive(timeout=2.5)
        assert ">> Flushing the following pending input:" in out
        assert "QUEUED" not in [line.strip() for line in out.splitlines()]

    def test_cmd_027_custom_flush_command(self, client):
        """CMD-027: set_connection_option changes the flush command; "" disables it."""
        assert_moo_int(client.eval('set_connection_option(player, "flush-command", "!!!")'), 0)
        assert assert_moo_success(client.eval('connection_option(player, "flush-command")')) == '"!!!"'
        assert_moo_int(client.eval('set_connection_option(player, "flush-command", "")'), 0)
        assert assert_moo_success(client.eval('connection_option(player, "flush-command")')) == '""'


class TestOutOfBand:
    """Out-of-band lines starting with #$#."""

    def test_cmd_030_out_of_band_handler(self, client):
        """CMD-030: A line starting with "#$#" goes to #0:do_out_of_band_command, not the parser."""
        define_verb(client, "#0", "do_out_of_band_command", ['notify(player, "oob: " + argstr);'])
        assert "oob: #$#mcp hello" in command(client, "#$#mcp hello")

    def test_cmd_031_out_of_band_quote(self, client):
        """CMD-031: A line starting with '#$"' is an ordinary command with that prefix removed."""
        define_verb(client, "#0", "do_out_of_band_command", ['notify(player, "oob: " + argstr);'])
        out = command(client, '#$";notify(player, "quoted ok")')
        assert "quoted ok" in out
        assert "oob:" not in out

    def test_cmd_032_disable_oob(self, client):
        """CMD-032: With the disable-oob option set, "#$#" lines are ordinary commands."""
        define_verb(client, "#0", "do_out_of_band_command", ['notify(player, "oob: " + argstr);'])
        assert_moo_int(client.eval('set_connection_option(player, "disable-oob", 1)'), 0)
        out = command(client, "#$#mcp hello")
        assert "oob:" not in out
