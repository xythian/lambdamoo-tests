"""Object lifecycle builtins (OBJ-001 onward).

Covers create, recycle, move, chparent, renumber, reset_max_object,
max_object, set_player_flag and players, including the verbs those
builtins call (initialize, recycle, accept, exitfunc, enterfunc), the
ownership quota, and the permission checks a non-wizard programmer is
subject to.
"""

import pytest

from lib.assertions import (
    assert_moo_int,
    assert_moo_raises,
    assert_moo_success,
)
from lib.moocode import define_verb


def new(client, parent="#1", owner=None):
    """Create an object and return its reference, e.g. "#5"."""
    args = parent if owner is None else f"{parent}, {owner}"
    return assert_moo_success(client.eval(f"create({args})"))


@pytest.fixture
def log(client):
    """An object with a "log" list property that the hook verbs append to."""
    obj = new(client)
    assert_moo_success(client.eval(f'add_property({obj}, "log", {{}}, {{player, "rw"}})'))
    return obj


def hook(client, obj, name, log, returns=None):
    """Define obj:name to append {name, this, args} to log.log, then optionally return a value."""
    lines = [f'{log}.log = {{@{log}.log, {{"{name}", this, @args}}}};']
    if returns is not None:
        lines.append(f"return {returns};")
    define_verb(client, obj, name, lines)


class TestCreate:
    """create() and the initialize hook."""

    def test_obj_001_calls_initialize(self, client, log):
        """OBJ-001: create() calls :initialize on the new object, inherited from its parent."""
        parent = new(client)
        hook(client, parent, "initialize", log)
        child = new(client, parent)
        assert assert_moo_success(client.eval(f"{log}.log")) == f'{{{{"initialize", {child}}}}}'

    def test_obj_002_new_object_defaults(self, client):
        """OBJ-002: A new object is named "", owned by its creator, in #-1, with no contents or children."""
        obj = new(client)
        assert assert_moo_success(client.eval(
            f"{{{obj}.name, {obj}.owner, {obj}.location, {obj}.contents, children({obj}), parent({obj})}}"
        )) == '{"", #3, #-1, {}, {}, #1}'

    def test_obj_003_no_parent_and_self_owner(self, client):
        """OBJ-003: create(#-1, #-1) makes a parentless object that owns itself."""
        obj = new(client, "#-1", "#-1")
        assert assert_moo_success(client.eval(f"{{parent({obj}), {obj}.owner == {obj}}}")) == "{#-1, 1}"

    def test_obj_004_ids_increase(self, client):
        """OBJ-004: Each create() takes the next number after max_object()."""
        top = assert_moo_success(client.eval("max_object()"))
        obj = new(client)
        assert int(obj[1:]) == int(top[1:]) + 1
        assert assert_moo_success(client.eval("max_object()")) == obj

    def test_obj_005_invalid_parent(self, client):
        """OBJ-005: A recycled parent is E_PERM (it isn't valid and isn't #-1); a non-object is E_TYPE."""
        gone = new(client)
        assert_moo_success(client.eval(f"recycle({gone})"))
        assert_moo_raises(client, f"create({gone})", "E_PERM")
        assert_moo_raises(client, 'create("#1")', "E_TYPE")

    def test_obj_006_fertility(self, wizard_and_programmer):
        """OBJ-006: A programmer can create children only of fertile objects or its own."""
        wiz, prog = wizard_and_programmer
        parent = new(wiz)
        assert_moo_raises(prog, f"create({parent})", "E_PERM")
        assert_moo_success(wiz.eval(f"{parent}.f = 1"))
        child = new(prog, parent)
        assert assert_moo_success(prog.eval(f"{child}.owner")) == "#4"
        assert_moo_success(prog.eval(f"create({child})"))

    def test_obj_007_owner_argument_needs_wizard(self, wizard_and_programmer):
        """OBJ-007: Only a wizard may name an owner other than itself."""
        wiz, prog = wizard_and_programmer
        assert_moo_raises(prog, "create(#-1, #3)", "E_PERM")
        assert_moo_success(prog.eval("create(#-1, #4)"))
        obj = new(wiz, "#-1", "#4")
        assert assert_moo_success(wiz.eval(f"{obj}.owner")) == "#4"

    def test_obj_008_quota(self, client):
        """OBJ-008: An integer ownership_quota is spent by create() and refunded by recycle()."""
        assert_moo_success(client.eval('add_property(#3, "ownership_quota", 1, {#3, ""})'))
        obj = new(client)
        assert_moo_int(client.eval("#3.ownership_quota"), 0)
        assert_moo_raises(client, "create(#1)", "E_QUOTA")
        assert_moo_success(client.eval(f"recycle({obj})"))
        assert_moo_int(client.eval("#3.ownership_quota"), 1)
        new(client)

    def test_obj_009_non_integer_quota_is_unlimited(self, client):
        """OBJ-009: A quota property that isn't an integer doesn't limit creation."""
        assert_moo_success(client.eval('add_property(#3, "ownership_quota", "lots", {#3, ""})'))
        new(client)
        new(client)
        assert assert_moo_success(client.eval("#3.ownership_quota")) == '"lots"'


class TestRecycle:
    """recycle() and the recycle hook."""

    def test_obj_010_calls_recycle_verb(self, client, log):
        """OBJ-010: recycle() calls the object's :recycle verb before destroying it."""
        obj = new(client)
        hook(client, obj, "recycle", log)
        assert_moo_int(client.eval(f"recycle({obj})"), 0)
        assert assert_moo_success(client.eval(f"{log}.log")) == f'{{{{"recycle", {obj}}}}}'
        assert_moo_int(client.eval(f"valid({obj})"), 0)

    def test_obj_011_contents_move_to_nowhere(self, client, log):
        """OBJ-011: Recycling a container moves its contents to #-1, calling its :exitfunc for each."""
        box = new(client)
        hook(client, box, "exitfunc", log)
        items = [new(client), new(client)]
        for item in items:
            assert_moo_success(client.eval(f"move({item}, {box})"))
        assert_moo_success(client.eval(f"recycle({box})"))
        for item in items:
            assert assert_moo_success(client.eval(f"{item}.location")) == "#-1"
        assert_moo_int(client.eval(f"length({log}.log)"), 2)

    def test_obj_012_object_leaves_its_location(self, client):
        """OBJ-012: A recycled object is removed from its location's contents."""
        room = new(client)
        thing = new(client)
        assert_moo_success(client.eval(f"move({thing}, {room})"))
        assert_moo_success(client.eval(f"recycle({thing})"))
        assert assert_moo_success(client.eval(f"{room}.contents")) == "{}"

    def test_obj_013_children_move_up(self, client):
        """OBJ-013: Children of a recycled object are reparented to its parent and keep inherited properties."""
        grand = new(client)
        assert_moo_success(client.eval(f'add_property({grand}, "kept", 7, {{player, "r"}})'))
        middle = new(client, grand)
        assert_moo_success(client.eval(f'add_property({middle}, "lost", 8, {{player, "r"}})'))
        child = new(client, middle)
        assert_moo_success(client.eval(f"recycle({middle})"))
        assert assert_moo_success(client.eval(f"parent({child})")) == grand
        assert_moo_int(client.eval(f"{child}.kept"), 7)
        assert_moo_raises(client, f"{child}.lost", "E_PROPNF")

    def test_obj_014_invalid_and_permission(self, wizard_and_programmer):
        """OBJ-014: Recycling an invalid object is E_INVARG; someone else's is E_PERM."""
        wiz, prog = wizard_and_programmer
        theirs = new(wiz)
        assert_moo_raises(prog, f"recycle({theirs})", "E_PERM")
        assert_moo_success(wiz.eval(f"recycle({theirs})"))
        assert_moo_raises(wiz, f"recycle({theirs})", "E_INVARG")
        mine = new(wiz, "#-1", "#4")
        assert_moo_int(prog.eval(f"recycle({mine})"), 0)

    def test_obj_015_recycle_verb_can_recycle_itself(self, client):
        """OBJ-015: If :recycle recycles the object itself, the outer recycle() still succeeds."""
        obj = new(client)
        define_verb(client, obj, "recycle", ["recycle(this);"])
        assert_moo_int(client.eval(f"recycle({obj})"), 0)
        assert_moo_int(client.eval(f"valid({obj})"), 0)


class TestMove:
    """move() and the accept, exitfunc and enterfunc hooks."""

    def test_obj_020_hooks_in_order(self, client, log):
        """OBJ-020: move() asks the destination's :accept, then calls the old :exitfunc and new :enterfunc."""
        source, dest, thing = new(client), new(client), new(client)
        assert_moo_success(client.eval(f"move({thing}, {source})"))
        hook(client, source, "exitfunc", log)
        hook(client, dest, "accept", log, returns=1)
        hook(client, dest, "enterfunc", log)
        assert_moo_int(client.eval(f"move({thing}, {dest})"), 0)
        assert assert_moo_success(client.eval(f"{log}.log")) == (
            f'{{{{"accept", {dest}, {thing}}}, {{"exitfunc", {source}, {thing}}}, {{"enterfunc", {dest}, {thing}}}}}')
        assert assert_moo_success(client.eval(f"{{{thing}.location, {dest}.contents, {source}.contents}}")) == (
            f"{{{dest}, {{{thing}}}, {{}}}}")

    def test_obj_021_refusal(self, wizard_and_programmer):
        """OBJ-021: A programmer's move is E_NACC when :accept is missing or false; wizards skip the check."""
        wiz, prog = wizard_and_programmer
        dest = new(wiz)
        thing = new(wiz, "#1", "#4")
        assert_moo_raises(prog, f"move({thing}, {dest})", "E_NACC")
        define_verb(wiz, dest, "accept", ["return 0;"])
        assert_moo_raises(prog, f"move({thing}, {dest})", "E_NACC")
        assert_moo_int(wiz.eval(f"move({thing}, {dest})"), 0)
        assert assert_moo_success(wiz.eval(f"{thing}.location")) == dest

    def test_obj_022_accept_true_lets_programmer_move(self, wizard_and_programmer):
        """OBJ-022: When :accept returns true a programmer can move its own object in."""
        wiz, prog = wizard_and_programmer
        dest = new(wiz)
        define_verb(wiz, dest, "accept", ["return 1;"])
        thing = new(wiz, "#1", "#4")
        assert_moo_int(prog.eval(f"move({thing}, {dest})"), 0)
        assert assert_moo_success(prog.eval(f"{thing}.location")) == dest

    def test_obj_023_move_needs_control(self, wizard_and_programmer):
        """OBJ-023: Moving an object the programmer doesn't own is E_PERM."""
        wiz, prog = wizard_and_programmer
        thing = new(wiz)
        assert_moo_raises(prog, f"move({thing}, #-1)", "E_PERM")

    def test_obj_024_recursive_move(self, client):
        """OBJ-024: Moving an object into itself or something it contains is E_RECMOVE."""
        outer, inner = new(client), new(client)
        assert_moo_success(client.eval(f"move({inner}, {outer})"))
        assert_moo_raises(client, f"move({outer}, {outer})", "E_RECMOVE")
        assert_moo_raises(client, f"move({outer}, {inner})", "E_RECMOVE")

    def test_obj_025_move_to_nowhere(self, client, log):
        """OBJ-025: Moving to #-1 needs no :accept and calls only the old location's :exitfunc."""
        room, thing = new(client), new(client)
        assert_moo_success(client.eval(f"move({thing}, {room})"))
        hook(client, room, "exitfunc", log)
        assert_moo_int(client.eval(f"move({thing}, #-1)"), 0)
        assert assert_moo_success(client.eval(f"{{{thing}.location, {room}.contents, {log}.log}}")) == (
            f'{{#-1, {{}}, {{{{"exitfunc", {room}, {thing}}}}}}}')

    def test_obj_026_move_in_place_is_a_no_op(self, client, log):
        """OBJ-026: Moving an object where it already is calls :accept but not :exitfunc or :enterfunc."""
        room, thing = new(client), new(client)
        assert_moo_success(client.eval(f"move({thing}, {room})"))
        hook(client, room, "accept", log, returns=1)
        hook(client, room, "exitfunc", log)
        hook(client, room, "enterfunc", log)
        assert_moo_success(client.eval(f"move({thing}, {room})"))
        assert assert_moo_success(client.eval(f"{log}.log")) == f'{{{{"accept", {room}, {thing}}}}}'

    def test_obj_027_invalid_arguments(self, client):
        """OBJ-027: An invalid object or destination is E_INVARG."""
        thing, gone = new(client), new(client)
        assert_moo_success(client.eval(f"recycle({gone})"))
        assert_moo_raises(client, f"move({gone}, #-1)", "E_INVARG")
        assert_moo_raises(client, f"move({thing}, {gone})", "E_INVARG")
        assert_moo_raises(client, f"move({thing}, 1)", "E_TYPE")

    def test_obj_028_exitfunc_can_move_it_elsewhere(self, client):
        """OBJ-028: If :exitfunc moves the object on, the destination's :enterfunc is skipped."""
        start, dest, elsewhere, thing = new(client), new(client), new(client), new(client)
        assert_moo_success(client.eval(f'add_property({dest}, "entered", 0, {{player, "rw"}})'))
        assert_moo_success(client.eval(f"move({thing}, {start})"))
        define_verb(client, start, "exitfunc", [f"move(args[1], {elsewhere});"])
        define_verb(client, dest, "enterfunc", ["this.entered = 1;"])
        assert_moo_success(client.eval(f"move({thing}, {dest})"))
        assert assert_moo_success(client.eval(f"{{{thing}.location, {dest}.entered}}")) == f"{{{elsewhere}, 0}}"


class TestChparent:
    """chparent() checks beyond the basics in test_objects."""

    def test_obj_030_needs_fertile_parent(self, wizard_and_programmer):
        """OBJ-030: A programmer can only reparent its objects onto fertile or owned parents."""
        wiz, prog = wizard_and_programmer
        mine = new(wiz, "#-1", "#4")
        theirs = new(wiz)
        assert_moo_raises(prog, f"chparent({mine}, {theirs})", "E_PERM")
        assert_moo_success(wiz.eval(f"{theirs}.f = 1"))
        assert_moo_int(prog.eval(f"chparent({mine}, {theirs})"), 0)
        assert_moo_raises(prog, f"chparent({theirs}, #-1)", "E_PERM")

    def test_obj_031_property_name_conflict(self, client):
        """OBJ-031: Reparenting is E_INVARG when the object defines a property the new ancestry also defines."""
        parent, obj = new(client), new(client)
        assert_moo_success(client.eval(f'add_property({parent}, "shared", 1, {{player, "r"}})'))
        assert_moo_success(client.eval(f'add_property({obj}, "shared", 2, {{player, "r"}})'))
        assert_moo_raises(client, f"chparent({obj}, {parent})", "E_INVARG")
        assert assert_moo_success(client.eval(f"parent({obj})")) == "#1"

    def test_obj_032_inherited_values_follow_new_parent(self, client):
        """OBJ-032: After chparent, properties from the old ancestry are gone and the new ones are inherited."""
        old, newp = new(client), new(client)
        assert_moo_success(client.eval(f'add_property({old}, "a", 1, {{player, "r"}})'))
        assert_moo_success(client.eval(f'add_property({newp}, "b", 2, {{player, "r"}})'))
        obj = new(client, old)
        assert_moo_success(client.eval(f"chparent({obj}, {newp})"))
        assert_moo_raises(client, f"{obj}.a", "E_PROPNF")
        assert_moo_int(client.eval(f"{obj}.b"), 2)
        assert assert_moo_success(client.eval(f"{{children({old}), children({newp})}}")) == f"{{{{}}, {{{obj}}}}}"


class TestRenumber:
    """renumber(), reset_max_object() and max_object()."""

    def test_obj_040_renumber_moves_to_lowest_free(self, client):
        """OBJ-040: renumber() gives an object the lowest free number and keeps its verbs and properties."""
        low, high = new(client), new(client)
        assert_moo_success(client.eval(f'add_property({high}, "p", "kept", {{player, "r"}})'))
        define_verb(client, high, "v", ['return "verb";'])
        assert_moo_success(client.eval(f"recycle({low})"))
        assert assert_moo_success(client.eval(f"renumber({high})")) == low
        assert assert_moo_success(client.eval(f'{{valid({high}), {low}.p, {low}:v()}}')) == '{0, "kept", "verb"}'

    def test_obj_041_renumber_updates_references(self, client):
        """OBJ-041: renumber() updates the object's parent, children, location and contents links."""
        low, parent = new(client), new(client)
        obj = new(client, parent)
        child = new(client, obj)
        thing = new(client)
        assert_moo_success(client.eval(f"move({thing}, {obj})"))
        assert_moo_success(client.eval(f"recycle({low})"))
        moved = assert_moo_success(client.eval(f"renumber({obj})"))
        assert moved == low
        assert assert_moo_success(client.eval(
            f"{{children({parent}), parent({child}), {thing}.location, {moved}.contents}}"
        )) == f"{{{{{moved}}}, {moved}, {moved}, {{{thing}}}}}"

    def test_obj_042_renumber_without_gap(self, client):
        """OBJ-042: With no lower free number, renumber() leaves the object where it is."""
        assert assert_moo_success(client.eval("renumber(#1)")) == "#1"

    def test_obj_043_renumber_errors(self, wizard_and_programmer):
        """OBJ-043: renumber() of an invalid object is E_INVARG; for a programmer it is E_PERM."""
        wiz, prog = wizard_and_programmer
        assert_moo_raises(wiz, "renumber(#999999)", "E_INVARG")
        mine = new(wiz, "#-1", "#4")
        assert_moo_raises(prog, f"renumber({mine})", "E_PERM")

    def test_obj_044_reset_max_object(self, client):
        """OBJ-044: reset_max_object() lowers max_object() past recycled objects at the top, so their numbers are reused."""
        before = assert_moo_success(client.eval("max_object()"))
        first, second = new(client), new(client)
        assert_moo_success(client.eval(f"recycle({second})"))
        assert_moo_success(client.eval(f"recycle({first})"))
        assert assert_moo_success(client.eval("max_object()")) == second
        assert_moo_int(client.eval("reset_max_object()"), 0)
        assert assert_moo_success(client.eval("max_object()")) == before
        assert new(client) == first

    def test_obj_045_reset_max_object_keeps_live_top(self, client):
        """OBJ-045: reset_max_object() stops at the highest valid object."""
        gap, top = new(client), new(client)
        assert_moo_success(client.eval(f"recycle({gap})"))
        client.eval("reset_max_object()")
        assert assert_moo_success(client.eval("max_object()")) == top

    def test_obj_046_reset_max_object_needs_wizard(self, wizard_and_programmer):
        """OBJ-046: reset_max_object() is wizard-only."""
        _, prog = wizard_and_programmer
        assert_moo_raises(prog, "reset_max_object()", "E_PERM")


class TestPlayerFlag:
    """set_player_flag(), is_player() and players()."""

    def test_obj_050_set_and_clear(self, client):
        """OBJ-050: set_player_flag adds an object to players() and clearing it removes it."""
        obj = new(client)
        assert_moo_int(client.eval(f"is_player({obj})"), 0)
        assert_moo_int(client.eval(f"set_player_flag({obj}, 1)"), 0)
        assert assert_moo_success(client.eval(f"{{is_player({obj}), {obj} in players() > 0}}")) == "{1, 1}"
        assert_moo_int(client.eval(f'set_player_flag({obj}, "")'), 0)
        assert assert_moo_success(client.eval(f"{{is_player({obj}), {obj} in players()}}")) == "{0, 0}"

    def test_obj_051_errors(self, wizard_and_programmer):
        """OBJ-051: set_player_flag is wizard-only and needs a valid object."""
        wiz, prog = wizard_and_programmer
        mine = new(wiz, "#-1", "#4")
        assert_moo_raises(prog, f"set_player_flag({mine}, 1)", "E_PERM")
        assert_moo_raises(wiz, "set_player_flag(#999999, 1)", "E_INVARG")
        assert_moo_raises(wiz, "is_player(#999999)", "E_INVARG")

    def test_obj_052_clearing_boots_connected_player(self, wizard_and_programmer):
        """OBJ-052: Clearing the flag of a connected player disconnects it."""
        wiz, prog = wizard_and_programmer
        assert_moo_int(wiz.eval("#4 in connected_players() > 0"), 1)
        assert_moo_int(wiz.eval("set_player_flag(#4, 0)"), 0)
        assert_moo_int(wiz.eval("#4 in connected_players()"), 0)
