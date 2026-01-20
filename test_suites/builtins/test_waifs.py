"""Waif (Weak References to Objects) tests.

LambdaMOO supports waifs - lightweight objects that:
- Are created via new_waif() with caller() as the class
- Have properties defined by their class object (with ':' prefix)
- Have verbs defined by their class object (with ':' prefix)
- Are garbage collected when the last reference is dropped
- Have built-in pseudo-properties: .class, .owner, .wizard

Waifs require WAIF_CORE to be enabled at compile time.
The WAIF_DICT option additionally enables dictionary-style indexing
via :_index and :_set_index verbs.

Note: In production MOO, waif classes are typically set up as $waif
(a child of #1 stored in #0.waif). These tests create fresh waif
class objects to avoid modifying #0.
"""

import pytest

from lib.assertions import assert_moo_success, assert_moo_int, assert_moo_error


@pytest.fixture
def waif_class(client, requires_waifs):
    """Create a waif class object for testing.

    Returns the object number as a string (e.g., '#4').
    """
    # Create a new object to serve as the waif class
    result = client.eval('create(#1)')
    success, obj = result
    assert success, f"Failed to create waif class: {obj}"

    # Add a basic waif property so new_waif() will work
    client.eval(f'add_property({obj}, ":value", 0, {{{obj}, "rw"}})')

    # Add a verb to create waifs from this class
    client.eval(f'add_verb({obj}, {{{obj}, "xd", "new"}}, {{"this", "none", "this"}})')
    client.eval(f'set_verb_code({obj}, "new", {{"return new_waif();"}})')

    return obj


class TestWaifCreation:
    """Tests for new_waif() builtin."""

    def test_new_waif_basic(self, client, waif_class):
        """new_waif() creates a waif with caller as class."""
        result = client.eval(f'{waif_class}:new()')
        success, value = result
        assert success, f"new_waif() should succeed: {value}"
        # Waif should be represented as something like [[class waif]]
        assert 'waif' in value.lower() or value.startswith('[['), f"Expected waif, got: {value}"

    def test_new_waif_class_property(self, client, waif_class):
        """Waif .class returns the class object."""
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "get_class"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "get_class", {{"w = new_waif();", "return w.class;"}})')

        result = client.eval(f'{waif_class}:get_class()')
        success, value = result
        assert success, f"Getting waif.class should succeed: {value}"
        assert value == waif_class, f"Waif class should be {waif_class}, got: {value}"

    def test_new_waif_owner_property(self, client, waif_class):
        """Waif .owner returns the owner (programmer who created it)."""
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "get_owner"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "get_owner", {{"w = new_waif();", "return w.owner;"}})')

        result = client.eval(f'{waif_class}:get_owner()')
        success, value = result
        assert success, f"Getting waif.owner should succeed: {value}"
        # Owner should be the wizard running the code
        assert value.startswith('#'), f"Owner should be an object, got: {value}"

    def test_new_waif_wizard_property(self, client, waif_class):
        """Waif .wizard always returns 0."""
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "get_wizard"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "get_wizard", {{"w = new_waif();", "return w.wizard;"}})')

        result = client.eval(f'{waif_class}:get_wizard()')
        assert_moo_int(result, 0)

    def test_new_waif_requires_waif_property(self, client, requires_waifs):
        """new_waif() behavior on object without :properties.

        Note: Some implementations allow creating waifs from objects without
        waif properties, while others require at least one :property.
        This test documents the behavior.
        """
        # Create an object WITHOUT waif properties
        result = client.eval('create(#1)')
        success, obj = result
        assert success, f"create() should succeed: {obj}"

        # Add a verb to try new_waif()
        client.eval(f'add_verb({obj}, {{{obj}, "xd", "try_waif"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({obj}, "try_waif", {{"return new_waif();"}})')

        result = client.eval(f'{obj}:try_waif()')
        success, value = result
        # Behavior varies by implementation - just verify we get a result
        # Some implementations fail, others create an empty waif
        if success:
            # If it succeeds, verify we got a waif
            assert 'waif' in value.lower() or '[[' in value, f"Expected waif result: {value}"
        else:
            # If it fails, verify it's an appropriate error
            assert 'E_' in value or 'error' in value.lower(), f"Expected error: {value}"


class TestWaifProperties:
    """Tests for waif property access."""

    def test_waif_property_get_default(self, client, waif_class):
        """Waif properties start with their default values."""
        # Add a waif property with a specific default value
        client.eval(f'add_property({waif_class}, ":answer", 42, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "get_answer"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "get_answer", {{"w = new_waif();", "return w.answer;"}})')

        result = client.eval(f'{waif_class}:get_answer()')
        assert_moo_int(result, 42)

    def test_waif_property_set(self, client, waif_class):
        """Waif properties can be set and retrieved."""
        client.eval(f'add_property({waif_class}, ":data", 0, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_set"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_set", {{"w = new_waif();", "w.data = 123;", "return w.data;"}})')

        result = client.eval(f'{waif_class}:test_set()')
        assert_moo_int(result, 123)

    def test_waif_property_independent(self, client, waif_class):
        """Each waif has independent property values."""
        client.eval(f'add_property({waif_class}, ":num", 0, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_indep"}}, {{"this", "none", "this"}})')
        code = '{"w1 = new_waif();", "w2 = new_waif();", "w1.num = 100;", "w2.num = 200;", "return {w1.num, w2.num};"}'
        client.eval(f'set_verb_code({waif_class}, "test_indep", {code})')

        result = client.eval(f'{waif_class}:test_indep()')
        success, value = result
        assert success, f"Property test should succeed: {value}"
        assert value == '{100, 200}', f"Properties should be independent: {value}"

    def test_waif_property_string(self, client, waif_class):
        """Waif properties can hold strings."""
        client.eval(f'add_property({waif_class}, ":name", "", {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_str"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_str", {{"w = new_waif();", "w.name = \\"hello\\";", "return w.name;"}})')

        result = client.eval(f'{waif_class}:test_str()')
        success, value = result
        assert success, f"String property should succeed: {value}"
        assert value == '"hello"', f"Expected string, got: {value}"

    def test_waif_property_list(self, client, waif_class):
        """Waif properties can hold lists."""
        client.eval(f'add_property({waif_class}, ":items", {{}}, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_list"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_list", {{"w = new_waif();", "w.items = {{1, 2, 3}};", "return w.items;"}})')

        result = client.eval(f'{waif_class}:test_list()')
        success, value = result
        assert success, f"List property should succeed: {value}"
        assert value == '{1, 2, 3}', f"Expected list, got: {value}"

    def test_waif_undefined_property_error(self, client, waif_class):
        """Accessing undefined waif property raises error."""
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_bad_prop"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_bad_prop", {{"w = new_waif();", "return w.nonexistent;"}})')

        result = client.eval(f'{waif_class}:test_bad_prop()')
        success, msg = result
        assert not success, f"Undefined property should fail: {msg}"
        assert 'E_PROPNF' in msg or 'Property not found' in msg, f"Expected property error, got: {msg}"


class TestWaifVerbs:
    """Tests for waif verb calls."""

    def test_waif_verb_call(self, client, waif_class):
        """Waif verbs can be called."""
        # Add a waif verb (prefixed with :)
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", ":greet"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, ":greet", {{"return \\"hello from waif\\";"}})')

        # Create a verb to test calling the waif verb
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_verb"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_verb", {{"w = new_waif();", "return w:greet();"}})')

        result = client.eval(f'{waif_class}:test_verb()')
        success, value = result
        assert success, f"Waif verb call should succeed: {value}"
        assert 'hello from waif' in value, f"Expected greeting, got: {value}"

    def test_waif_verb_with_args(self, client, waif_class):
        """Waif verbs receive arguments."""
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", ":add"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, ":add", {{"return args[1] + args[2];"}})')

        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_args"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_args", {{"w = new_waif();", "return w:add(10, 32);"}})')

        result = client.eval(f'{waif_class}:test_args()')
        assert_moo_int(result, 42)

    def test_waif_verb_access_property(self, client, waif_class):
        """Waif verbs can access waif properties via this.prop."""
        client.eval(f'add_property({waif_class}, ":counter", 0, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", ":increment"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, ":increment", {{"this.counter = this.counter + 1;", "return this.counter;"}})')

        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_counter"}}, {{"this", "none", "this"}})')
        code = '{"w = new_waif();", "w:increment();", "w:increment();", "return w:increment();"}'
        client.eval(f'set_verb_code({waif_class}, "test_counter", {code})')

        result = client.eval(f'{waif_class}:test_counter()')
        assert_moo_int(result, 3)

    def test_waif_undefined_verb_error(self, client, waif_class):
        """Calling undefined waif verb raises error."""
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_bad_verb"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_bad_verb", {{"w = new_waif();", "return w:nonexistent();"}})')

        result = client.eval(f'{waif_class}:test_bad_verb()')
        success, msg = result
        assert not success, f"Undefined verb should fail: {msg}"
        assert 'E_VERBNF' in msg or 'Verb not found' in msg, f"Expected verb error, got: {msg}"


class TestWaifLifecycle:
    """Tests for waif creation and garbage collection."""

    def test_waif_stored_in_variable(self, client, waif_class):
        """Waifs can be stored in variables and accessed later."""
        client.eval(f'add_property({waif_class}, ":data", 0, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_store"}}, {{"this", "none", "this"}})')
        code = '{"w = new_waif();", "w.data = 999;", "x = w;", "return x.data;"}'
        client.eval(f'set_verb_code({waif_class}, "test_store", {code})')

        result = client.eval(f'{waif_class}:test_store()')
        assert_moo_int(result, 999)

    def test_waif_stored_in_list(self, client, waif_class):
        """Waifs can be stored in lists."""
        client.eval(f'add_property({waif_class}, ":id", 0, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_list"}}, {{"this", "none", "this"}})')
        code = '{"w1 = new_waif();", "w1.id = 1;", "w2 = new_waif();", "w2.id = 2;", "lst = {w1, w2};", "return lst[1].id + lst[2].id;"}'
        client.eval(f'set_verb_code({waif_class}, "test_list", {code})')

        result = client.eval(f'{waif_class}:test_list()')
        assert_moo_int(result, 3)

    def test_waif_self_reference_error(self, client, waif_class):
        """Waifs cannot contain self-references (E_RECMOVE)."""
        client.eval(f'add_property({waif_class}, ":self_ref", 0, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_self_ref"}}, {{"this", "none", "this"}})')
        code = '{"w = new_waif();", "w.self_ref = w;", "return 1;"}'
        client.eval(f'set_verb_code({waif_class}, "test_self_ref", {code})')

        result = client.eval(f'{waif_class}:test_self_ref()')
        success, msg = result
        assert not success, f"Self-reference should fail: {msg}"
        assert 'E_RECMOVE' in msg or 'Recursive' in msg, f"Expected recursive move error, got: {msg}"

    def test_waif_indirect_self_reference_error(self, client, waif_class):
        """Waifs cannot contain indirect self-references."""
        client.eval(f'add_property({waif_class}, ":indirect", 0, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_indirect"}}, {{"this", "none", "this"}})')
        code = '{"w = new_waif();", "w.indirect = {w};", "return 1;"}'
        client.eval(f'set_verb_code({waif_class}, "test_indirect", {code})')

        result = client.eval(f'{waif_class}:test_indirect()')
        success, msg = result
        assert not success, f"Indirect self-reference should fail: {msg}"
        assert 'E_RECMOVE' in msg or 'Recursive' in msg, f"Expected recursive move error, got: {msg}"


class TestWaifTypeChecks:
    """Tests for typeof() and other type operations on waifs."""

    def test_typeof_waif(self, client, waif_class):
        """typeof(waif) returns appropriate type code."""
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_typeof"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_typeof", {{"w = new_waif();", "return typeof(w);"}})')

        result = client.eval(f'{waif_class}:test_typeof()')
        success, value = result
        assert success, f"typeof should succeed: {value}"
        # TYPE_WAIF is typically 10 (after the standard types)
        int_value = int(value)
        assert int_value > 0, f"typeof(waif) should return positive type code: {value}"

    def test_waif_tostr(self, client, waif_class):
        """tostr(waif) produces a string representation."""
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_tostr"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_tostr", {{"w = new_waif();", "return tostr(w);"}})')

        result = client.eval(f'{waif_class}:test_tostr()')
        success, value = result
        assert success, f"tostr should succeed: {value}"
        # String representation typically includes class and some identifier
        assert 'waif' in value.lower() or '#' in value, f"Expected waif string, got: {value}"

    def test_waif_equality(self, client, waif_class):
        """Waif equality comparison works correctly."""
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_eq"}}, {{"this", "none", "this"}})')
        code = '{"w1 = new_waif();", "w2 = w1;", "w3 = new_waif();", "return {w1 == w2, w1 == w3};"}'
        client.eval(f'set_verb_code({waif_class}, "test_eq", {code})')

        result = client.eval(f'{waif_class}:test_eq()')
        success, value = result
        assert success, f"Equality test should succeed: {value}"
        assert value == '{1, 0}', f"w1==w2 should be true, w1==w3 should be false: {value}"


class TestWaifValidObject:
    """Tests for valid() and type checking on waifs."""

    def test_waif_is_not_object(self, client, waif_class):
        """Waifs are distinct from objects."""
        # Waifs have a different type than objects
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_type"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_type", {{"w = new_waif();", "return typeof(w) != typeof(#0);"}})')

        result = client.eval(f'{waif_class}:test_type()')
        # Waif type should be different from object type
        assert_moo_int(result, 1)


class TestWaifDict:
    """Tests for WAIF_DICT dictionary syntax (optional feature)."""

    def test_waif_index_read(self, client, waif_class, requires_waif_dict):
        """Waif dictionary read via :_index verb."""
        # Add :_index that returns the value property
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", ":_index"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, ":_index", {{"return args[1] * 10;"}})')

        # Test reading with integer key - w[5] should call :_index(5) and return 50
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_read"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_read", {{"w = new_waif();", "return w[5];"}})')

        result = client.eval(f'{waif_class}:test_read()')
        assert_moo_int(result, 50)

    def test_waif_set_index_verb(self, client, waif_class, requires_waif_dict):
        """Waif dictionary write via w[key] = value syntax.

        The w[key] = value syntax calls :_set_index(key, value) on the waif.
        IMPORTANT: The return value of :_set_index replaces the variable, so
        :_set_index must return the waif (typically `this` or a new waif) for
        the variable to remain usable as a waif. This enables immutable-style
        updates where :_set_index returns a new waif with the updated value.
        """
        # Add :_index that returns the value property
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", ":_index"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, ":_index", {{"return this.value;"}})')

        # :_set_index stores the value and returns THIS (not the value!)
        # The return value replaces the variable, so we must return the waif
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", ":_set_index"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, ":_set_index", {{"this.value = args[2];", "return this;"}})')

        # Test w[key] = value syntax - should call :_set_index and allow w[key] to retrieve it
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_set"}}, {{"this", "none", "this"}})')
        code = '{"w = new_waif();", "w[1] = 42;", "return w[1];"}'
        client.eval(f'set_verb_code({waif_class}, "test_set", {code})')

        result = client.eval(f'{waif_class}:test_set()')
        assert_moo_int(result, 42)


class TestWaifClassProperty:
    """Tests for waif .class property."""

    def test_class_property_of_waif(self, client, waif_class):
        """waif.class returns the waif's class object."""
        # This is already tested in test_new_waif_class_property
        # Just verify it matches when accessed differently
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "test_class2"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, "test_class2", {{"w = new_waif();", "return w.class;"}})')

        result = client.eval(f'{waif_class}:test_class2()')
        success, value = result
        assert success, f"w.class should succeed: {value}"
        assert value == waif_class, f"w.class should be {waif_class}, got: {value}"


class TestWaifSpecialCases:
    """Tests for edge cases and special behaviors."""

    def test_waif_in_object_property(self, client, waif_class):
        """Waifs can be stored in object properties."""
        client.eval(f'add_property({waif_class}, ":data", 0, {{{waif_class}, "rw"}})')
        client.eval(f'add_property({waif_class}, "stored_waif", 0, {{{waif_class}, "rw"}})')
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", "store_waif"}}, {{"this", "none", "this"}})')
        code = '{"w = new_waif();", "w.data = 12345;", "this.stored_waif = w;", "return this.stored_waif.data;"}'
        client.eval(f'set_verb_code({waif_class}, "store_waif", {code})')

        result = client.eval(f'{waif_class}:store_waif()')
        assert_moo_int(result, 12345)

    def test_multiple_waif_classes(self, client, requires_waifs):
        """Waifs can be created from different class objects."""
        # Create two waif classes
        result = client.eval('create(#1)')
        success, class1 = result
        assert success

        result = client.eval('create(#1)')
        success, class2 = result
        assert success

        # Set up first class
        client.eval(f'add_property({class1}, ":origin", "class1", {{{class1}, "rw"}})')
        client.eval(f'add_verb({class1}, {{{class1}, "xd", "new"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({class1}, "new", {{"return new_waif();"}})')

        # Set up second class
        client.eval(f'add_property({class2}, ":origin", "class2", {{{class2}, "rw"}})')
        client.eval(f'add_verb({class2}, {{{class2}, "xd", "new"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({class2}, "new", {{"return new_waif();"}})')

        # Test that waifs from different classes have different values
        client.eval(f'add_verb({class1}, {{{class1}, "xd", "test_multi"}}, {{"this", "none", "this"}})')
        code = '{' + f'"w1 = {class1}:new();", "w2 = {class2}:new();", "return {{w1.origin, w2.origin}};"' + '}'
        client.eval(f'set_verb_code({class1}, "test_multi", {code})')

        result = client.eval(f'{class1}:test_multi()')
        success, value = result
        assert success, f"Multi-class test should succeed: {value}"
        assert 'class1' in value and 'class2' in value, f"Expected both class origins: {value}"

    def test_waif_properties_on_class(self, client, waif_class):
        """Waif class object has the waif properties defined."""
        # Note: properties(waif) doesn't work - use properties(waif.class) instead
        client.eval(f'add_property({waif_class}, ":prop_a", 1, {{{waif_class}, "rw"}})')
        client.eval(f'add_property({waif_class}, ":prop_b", 2, {{{waif_class}, "rw"}})')

        # Get properties from the class object
        result = client.eval(f'properties({waif_class})')
        success, value = result
        assert success, f"properties() should succeed: {value}"
        # Should include the waif properties (prefixed with :)
        assert ':prop_a' in value or 'prop_a' in value, f"Expected waif properties: {value}"

    def test_waif_verbs_on_class(self, client, waif_class):
        """Waif class object has the waif verbs defined."""
        # Note: verbs(waif) doesn't work - use verbs(waif.class) instead
        client.eval(f'add_verb({waif_class}, {{{waif_class}, "xd", ":verb_a"}}, {{"this", "none", "this"}})')
        client.eval(f'set_verb_code({waif_class}, ":verb_a", {{"return 1;"}})')

        # Get verbs from the class object
        result = client.eval(f'verbs({waif_class})')
        success, value = result
        assert success, f"verbs() should succeed: {value}"
        # Should include the :verb_a verb
        assert ':verb_a' in value or 'verb_a' in value, f"Expected verb_a in verbs: {value}"
