"""clear_property() and is_clear_property() on waifs.

A waif property is clear until the waif assigns it, and while clear it
reads as the class's current value for the property.  Servers that
extend clear_property() and is_clear_property() to waifs let MOO code
inspect and reset that state the same way it can for an object's
inherited properties.

The semantics follow the object built-ins:
- is_clear_property() needs read permission and is 0 for the built-in
  pseudo-properties .owner, .class and .wizard.
- clear_property() needs the property's owner (the waif's owner for a +c
  property) or a wizard, regardless of +w, and is E_PERM on a built-in.
- Neither reports E_INVARG for a defining object, since a waif never
  defines its own properties.

Servers without this support reject a waif argument with E_TYPE; these
tests detect that and skip.
"""

import pytest

from lib.assertions import (
    assert_moo_success, assert_moo_int, assert_moo_string, assert_moo_raises,
)

# More waif properties than any WAIF_MAPSZ can map (6 or 8 words of 32 bits),
# so the last ones are stored in always-allocated slots.
MANY_PROPS = 260


def skip_unless_supported(client, waif):
    """Skip unless the server accepts a waif in is_clear_property().

    Servers without the support reject the waif argument with E_TYPE.
    """
    probe = assert_moo_success(client.eval(f'`is_clear_property({waif}, "value") ! ANY\''))
    if probe == "E_TYPE":
        pytest.skip("Server does not support clear_property() on waifs")


@pytest.fixture
def waif_class(client, requires_waifs):
    """A waif class with a ':value' property and a 'held' slot holding one of its waifs.

    Returns the class object number; '{cls}.held' is the waif.
    """
    cls = assert_moo_success(client.eval('create(#1)'))
    assert_moo_success(client.eval(f'add_property({cls}, ":value", "default", {{player, "rw"}})'))
    assert_moo_success(client.eval(f'add_property({cls}, "held", 0, {{player, "rw"}})'))
    assert_moo_success(client.eval(f'add_verb({cls}, {{player, "xd", "new"}}, {{"this", "none", "this"}})'))
    assert_moo_success(client.eval(f'set_verb_code({cls}, "new", {{"return new_waif();"}})'))
    assert_moo_success(client.eval(f'{cls}.held = {cls}:new()'))
    return cls


@pytest.fixture
def waif(client, waif_class):
    """An expression for a waif whose server supports clear properties on waifs."""
    expr = f'{waif_class}.held'
    skip_unless_supported(client, expr)
    return expr


class TestWaifClearProperties:
    """is_clear_property() and clear_property() on a waif's own properties."""

    def test_new_waif_property_is_clear(self, client, waif):
        """A property the waif has never assigned is clear."""
        assert_moo_int(client.eval(f'is_clear_property({waif}, "value")'), 1)

    def test_assigned_property_is_not_clear(self, client, waif):
        """Assigning a property makes it not clear, even to the class's value."""
        assert_moo_success(client.eval(f'{waif}.value = "default"'))
        assert_moo_int(client.eval(f'is_clear_property({waif}, "value")'), 0)

    def test_clear_restores_class_value(self, client, waif):
        """clear_property() makes the property clear and read as the class's value again."""
        assert_moo_success(client.eval(f'{waif}.value = "mine"'))
        assert_moo_success(client.eval(f'clear_property({waif}, "value")'))
        assert_moo_int(client.eval(f'is_clear_property({waif}, "value")'), 1)
        assert_moo_string(client.eval(f'{waif}.value'), "default")

    def test_cleared_property_follows_class(self, client, waif, waif_class):
        """A cleared property reads the class's current value, not a copy."""
        assert_moo_success(client.eval(f'{waif}.value = "mine"'))
        assert_moo_success(client.eval(f'clear_property({waif}, "value")'))
        assert_moo_success(client.eval(f'{waif_class}.(":value") = "changed"'))
        assert_moo_string(client.eval(f'{waif}.value'), "changed")

    def test_clear_returns_zero(self, client, waif):
        """clear_property() on a waif returns 0, like on an object."""
        assert_moo_success(client.eval(f'{waif}.value = "mine"'))
        assert_moo_int(client.eval(f'clear_property({waif}, "value")'), 0)

    def test_clear_already_clear_property(self, client, waif):
        """Clearing a property that is already clear succeeds and leaves it clear."""
        assert_moo_success(client.eval(f'clear_property({waif}, "value")'))
        assert_moo_int(client.eval(f'is_clear_property({waif}, "value")'), 1)
        assert_moo_string(client.eval(f'{waif}.value'), "default")

    def test_property_can_be_set_after_clear(self, client, waif):
        """A cleared property can be assigned again."""
        assert_moo_success(client.eval(f'{waif}.value = "first"'))
        assert_moo_success(client.eval(f'clear_property({waif}, "value")'))
        assert_moo_success(client.eval(f'{waif}.value = "second"'))
        assert_moo_int(client.eval(f'is_clear_property({waif}, "value")'), 0)
        assert_moo_string(client.eval(f'{waif}.value'), "second")

    def test_clear_affects_only_that_waif(self, client, waif, waif_class):
        """Clearing one waif's property leaves another waif of the class alone."""
        assert_moo_success(client.eval(f'add_property({waif_class}, "other", 0, {{player, "rw"}})'))
        other = f'{waif_class}.other'
        assert_moo_success(client.eval(f'{other} = {waif_class}:new()'))
        assert_moo_success(client.eval(f'{waif}.value = "one"'))
        assert_moo_success(client.eval(f'{other}.value = "two"'))
        assert_moo_success(client.eval(f'clear_property({waif}, "value")'))
        assert_moo_string(client.eval(f'{other}.value'), "two")
        assert_moo_int(client.eval(f'is_clear_property({other}, "value")'), 0)

    def test_clear_leaves_other_properties(self, client, waif, waif_class):
        """Clearing one property keeps the values of the properties around it."""
        for name in ("a", "b", "c", "d"):
            assert_moo_success(client.eval(f'add_property({waif_class}, ":{name}", 0, {{player, "rw"}})'))
        for i, name in enumerate(("a", "b", "c", "d"), 1):
            assert_moo_success(client.eval(f'{waif}.{name} = {i}'))
        assert_moo_success(client.eval(f'clear_property({waif}, "b")'))
        assert_moo_int(client.eval(f'is_clear_property({waif}, "b")'), 1)
        assert_moo_int(client.eval(f'{waif}.b'), 0)
        for i, name in ((1, "a"), (3, "c"), (4, "d")):
            assert_moo_int(client.eval(f'{waif}.{name}'), i)
            assert_moo_int(client.eval(f'is_clear_property({waif}, "{name}")'), 0)

    def test_property_added_to_class_is_clear(self, client, waif, waif_class):
        """A property added to the class after the waif was made is clear on it."""
        assert_moo_success(client.eval(f'add_property({waif_class}, ":late", "class", {{player, "rw"}})'))
        assert_moo_int(client.eval(f'is_clear_property({waif}, "late")'), 1)
        assert_moo_string(client.eval(f'{waif}.late'), "class")

    def test_many_properties(self, client, waif, waif_class, program):
        """Properties beyond the waif's property map clear like the rest."""
        assert_moo_success(program([
            f'for i in [1..{MANY_PROPS}]',
            f'  add_property({waif_class}, ":p" + tostr(i), i, {{player, "rw"}});',
            'endfor',
            'return 1;',
        ])[0])
        first, last = "p1", f"p{MANY_PROPS}"
        for name in (first, last):
            assert_moo_success(client.eval(f'{waif}.{name} = "set"'))
            assert_moo_int(client.eval(f'is_clear_property({waif}, "{name}")'), 0)
        assert_moo_success(client.eval(f'clear_property({waif}, "{last}")'))
        assert_moo_int(client.eval(f'is_clear_property({waif}, "{last}")'), 1)
        assert_moo_int(client.eval(f'{waif}.{last}'), MANY_PROPS)
        assert_moo_string(client.eval(f'{waif}.{first}'), "set")
        assert_moo_success(client.eval(f'clear_property({waif}, "{first}")'))
        assert_moo_int(client.eval(f'{waif}.{first}'), 1)


class TestWaifClearPropertyErrors:
    """Built-in pseudo-properties, missing properties and bad arguments."""

    @pytest.mark.parametrize("name", ["owner", "class", "wizard"])
    def test_builtin_properties(self, client, waif, name):
        """The pseudo-properties are never clear and cannot be cleared."""
        assert_moo_int(client.eval(f'is_clear_property({waif}, "{name}")'), 0)
        assert_moo_raises(client, f'clear_property({waif}, "{name}")', "E_PERM")

    def test_missing_property(self, client, waif):
        """A property the class does not define is E_PROPNF."""
        assert_moo_raises(client, f'is_clear_property({waif}, "nonesuch")', "E_PROPNF")
        assert_moo_raises(client, f'clear_property({waif}, "nonesuch")', "E_PROPNF")

    def test_prefix_is_not_part_of_name(self, client, waif):
        """The name is given without the ':' prefix, as in waif.value."""
        assert_moo_raises(client, f'is_clear_property({waif}, ":value")', "E_PROPNF")

    def test_deleted_class_property(self, client, waif, waif_class):
        """A property deleted from the class is gone from the waif."""
        assert_moo_success(client.eval(f'{waif}.value = "mine"'))
        assert_moo_success(client.eval(f'delete_property({waif_class}, ":value")'))
        assert_moo_raises(client, f'is_clear_property({waif}, "value")', "E_PROPNF")
        assert_moo_raises(client, f'clear_property({waif}, "value")', "E_PROPNF")

    def test_recycled_class(self, client, waif, waif_class):
        """A waif whose class was recycled is E_INVIND, as for property access."""
        assert_moo_success(client.eval(f'add_property(#0, "orphan", {waif}, {{player, "rw"}})'))
        assert_moo_success(client.eval(f'recycle({waif_class})'))
        assert_moo_raises(client, '#0.orphan.value', "E_INVIND")
        assert_moo_raises(client, 'is_clear_property(#0.orphan, "value")', "E_INVIND")
        assert_moo_raises(client, 'clear_property(#0.orphan, "value")', "E_INVIND")


class TestClearPropertyArgumentTypes:
    """Values that are neither objects nor waifs."""

    @pytest.mark.parametrize("value", ['"#1"', "1", "{#1}"])
    def test_non_object_argument(self, client, value):
        """clear_property() and is_clear_property() reject non-object values with E_TYPE."""
        assert_moo_raises(client, f'is_clear_property({value}, "name")', "E_TYPE")
        assert_moo_raises(client, f'clear_property({value}, "name")', "E_TYPE")


class TestWaifClearPropertyPermissions:
    """What a non-wizard programmer (#4, Player2) may do to a waif it owns."""

    @pytest.fixture
    def setup(self, wizard_and_programmer, requires_waifs):
        """A wizard-owned class whose 'held' property holds a waif owned by #4.

        ':plain' is owned by the wizard; ':chown' is +c, so #4 owns it on
        #4's waifs; ':hidden' is unreadable.
        """
        wiz, prog = wizard_and_programmer
        cls = assert_moo_success(wiz.eval('create(#1)'))
        for name, flags in (("value", "r"), ("plain", "rw"), ("chown", "rwc"), ("hidden", "")):
            assert_moo_success(wiz.eval(f'add_property({cls}, ":{name}", 0, {{player, "{flags}"}})'))
        assert_moo_success(wiz.eval(f'add_property({cls}, "held", 0, {{#4, "rw"}})'))
        assert_moo_success(wiz.eval(f'add_verb({cls}, {{#4, "xd", "new"}}, {{"this", "none", "this"}})'))
        assert_moo_success(wiz.eval(f'set_verb_code({cls}, "new", {{"return new_waif();"}})'))
        assert_moo_success(wiz.eval(f'{cls}.held = {cls}:new()'))
        held = f'{cls}.held'
        skip_unless_supported(wiz, held)
        assert_moo_success(wiz.eval(f'{held}.plain = 1'))
        assert_moo_success(wiz.eval(f'{held}.chown = 1'))
        return wiz, prog, held

    def test_waif_owned_by_programmer(self, setup):
        """The waif made by #4's verb is owned by #4."""
        wiz, _, held = setup
        assert assert_moo_success(wiz.eval(f'{held}.owner')) == "#4"

    def test_cannot_clear_others_property(self, setup):
        """Write permission is not enough: clearing needs the property's owner."""
        _, prog, held = setup
        assert_moo_raises(prog, f'clear_property({held}, "plain")', "E_PERM")
        assert_moo_int(prog.eval(f'is_clear_property({held}, "plain")'), 0)

    def test_can_clear_chown_property_on_own_waif(self, setup):
        """For a +c property the waif's owner is the property's owner."""
        _, prog, held = setup
        assert_moo_success(prog.eval(f'clear_property({held}, "chown")'))
        assert_moo_int(prog.eval(f'is_clear_property({held}, "chown")'), 1)

    def test_wizard_can_clear(self, setup):
        """A wizard can clear any waif property."""
        wiz, _, held = setup
        assert_moo_success(wiz.eval(f'clear_property({held}, "plain")'))
        assert_moo_int(wiz.eval(f'is_clear_property({held}, "plain")'), 1)

    def test_unreadable_property(self, setup):
        """is_clear_property() needs read permission."""
        _, prog, held = setup
        assert_moo_raises(prog, f'is_clear_property({held}, "hidden")', "E_PERM")
