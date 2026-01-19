"""Database object tests (DB-001 through DB-010)."""

import pytest

from lib.assertions import (
    assert_moo_success,
    assert_moo_error,
    assert_moo_int,
    assert_moo_object,
    TYPE_OBJ,
)


class TestObjectCreation:
    """Tests for object creation and destruction."""

    def test_db_001_create_object(self, client):
        """DB-001: create() returns a valid object."""
        # Create an object with #1 (wizard) as parent
        result = client.eval('create(#1)')
        value = assert_moo_success(result)

        # Should return an object reference
        assert value.startswith('#'), f"Expected object reference, got: {value}"

        # The object should be valid
        objid = value
        result = client.eval(f'valid({objid})')
        assert_moo_int(result, 1, "Created object should be valid")

    def test_db_002_destroy_object(self, client):
        """DB-002: recycle() removes object."""
        # Create an object
        result = client.eval('create(#1)')
        objid = assert_moo_success(result)

        # Verify it's valid
        result = client.eval(f'valid({objid})')
        assert_moo_int(result, 1)

        # Recycle it
        result = client.eval(f'recycle({objid})')
        assert_moo_success(result)

        # Should no longer be valid
        result = client.eval(f'valid({objid})')
        assert_moo_int(result, 0, "Recycled object should be invalid")

    def test_db_003_object_validity(self, client):
        """DB-003: valid() returns correct state."""
        # #0 should be valid (system object)
        result = client.eval('valid(#0)')
        assert_moo_int(result, 1, "#0 should be valid")

        # #1 should be valid (wizard)
        result = client.eval('valid(#1)')
        assert_moo_int(result, 1, "#1 should be valid")

        # A very high object number should be invalid
        result = client.eval('valid(#999999)')
        assert_moo_int(result, 0, "Non-existent object should be invalid")

        # #-1 should be invalid
        result = client.eval('valid(#-1)')
        assert_moo_int(result, 0, "#-1 should be invalid")

    def test_db_004_object_parent(self, client):
        """DB-004: parent() returns correct hierarchy."""
        # Create object with #1 as parent
        result = client.eval('create(#1)')
        objid = assert_moo_success(result)

        # Parent should be #1
        result = client.eval(f'parent({objid})')
        value = assert_moo_success(result)
        assert value == '#1', f"Expected parent #1, got {value}"

        # Clean up
        client.eval(f'recycle({objid})')

    def test_db_005_object_children(self, client):
        """DB-005: children() lists correctly."""
        # Get initial children of #1
        result = client.eval('children(#1)')
        initial_children = assert_moo_success(result)

        # Create a new child
        result = client.eval('create(#1)')
        new_obj = assert_moo_success(result)

        # Children list should now include the new object
        result = client.eval('children(#1)')
        new_children = assert_moo_success(result)

        assert new_obj in new_children, \
            f"New object {new_obj} should be in children list: {new_children}"

        # Clean up
        client.eval(f'recycle({new_obj})')


class TestObjectHierarchy:
    """Tests for object hierarchy operations."""

    def test_db_006_object_location(self, client):
        """DB-006: move() changes location."""
        # Create two objects
        result = client.eval('create(#1)')
        container = assert_moo_success(result)

        result = client.eval('create(#1)')
        item = assert_moo_success(result)

        try:
            # Initially, location should be #-1 (nowhere)
            # Note: location is a built-in property, not a function
            result = client.eval(f'{item}.location')
            value = assert_moo_success(result)
            assert value == '#-1', f"Initial location should be #-1, got {value}"

            # Move item into container
            result = client.eval(f'move({item}, {container})')
            assert_moo_success(result)

            # Location should now be the container
            result = client.eval(f'{item}.location')
            value = assert_moo_success(result)
            assert value == container, f"Location should be {container}, got {value}"

        finally:
            client.eval(f'recycle({item})')
            client.eval(f'recycle({container})')

    def test_db_007_object_contents(self, client):
        """DB-007: .contents lists contained objects."""
        # Create container and items
        result = client.eval('create(#1)')
        container = assert_moo_success(result)

        result = client.eval('create(#1)')
        item1 = assert_moo_success(result)

        result = client.eval('create(#1)')
        item2 = assert_moo_success(result)

        try:
            # Initially empty
            # Note: contents is a built-in property, not a function
            result = client.eval(f'{container}.contents')
            value = assert_moo_success(result)
            assert value == '{}', f"Initial contents should be empty, got {value}"

            # Move items into container
            client.eval(f'move({item1}, {container})')
            client.eval(f'move({item2}, {container})')

            # Contents should include both items
            result = client.eval(f'{container}.contents')
            contents = assert_moo_success(result)
            assert item1 in contents, f"{item1} should be in contents: {contents}"
            assert item2 in contents, f"{item2} should be in contents: {contents}"

        finally:
            client.eval(f'recycle({item1})')
            client.eval(f'recycle({item2})')
            client.eval(f'recycle({container})')

    def test_db_008_chparent(self, client):
        """DB-008: Changing parent works."""
        # Create two potential parents and a child
        result = client.eval('create(#1)')
        parent1 = assert_moo_success(result)

        result = client.eval('create(#1)')
        parent2 = assert_moo_success(result)

        result = client.eval(f'create({parent1})')
        child = assert_moo_success(result)

        try:
            # Initial parent
            result = client.eval(f'parent({child})')
            assert assert_moo_success(result) == parent1

            # Change parent
            result = client.eval(f'chparent({child}, {parent2})')
            assert_moo_success(result)

            # Verify new parent
            result = client.eval(f'parent({child})')
            assert assert_moo_success(result) == parent2

        finally:
            client.eval(f'recycle({child})')
            client.eval(f'recycle({parent2})')
            client.eval(f'recycle({parent1})')

    def test_db_009_circular_parent_rejected(self, client):
        """DB-009: Circular parent relationships are rejected."""
        # Create parent-child chain
        result = client.eval('create(#1)')
        obj1 = assert_moo_success(result)

        result = client.eval(f'create({obj1})')
        obj2 = assert_moo_success(result)

        try:
            # Try to make obj1's parent be obj2 (creating a cycle)
            result = client.eval(f'chparent({obj1}, {obj2})')
            # This should fail with E_RECMOVE (server returns "Recursive move" message)
            assert_moo_error(result, 'Recursive')

        finally:
            client.eval(f'recycle({obj2})')
            client.eval(f'recycle({obj1})')


class TestObjectProperties:
    """Tests for basic property operations on objects."""

    def test_db_020_define_property(self, client):
        """DB-020: add_property() works."""
        result = client.eval('create(#1)')
        obj = assert_moo_success(result)

        try:
            # Add a property
            result = client.eval(f'add_property({obj}, "test_prop", 42, {{#1, "rw"}})')
            assert_moo_success(result)

            # Read it back
            result = client.eval(f'{obj}.test_prop')
            assert_moo_int(result, 42)

        finally:
            client.eval(f'recycle({obj})')

    def test_db_021_read_property(self, client):
        """DB-021: Property access works."""
        result = client.eval('create(#1)')
        obj = assert_moo_success(result)

        try:
            # Add and read property
            client.eval(f'add_property({obj}, "value", "hello", {{#1, "rw"}})')

            result = client.eval(f'{obj}.value')
            value = assert_moo_success(result)
            assert value == '"hello"', f"Expected \"hello\", got {value}"

        finally:
            client.eval(f'recycle({obj})')

    def test_db_022_write_property(self, client):
        """DB-022: Property assignment works."""
        result = client.eval('create(#1)')
        obj = assert_moo_success(result)

        try:
            client.eval(f'add_property({obj}, "counter", 0, {{#1, "rw"}})')

            # Write new value
            client.eval(f'{obj}.counter = 100')

            # Verify
            result = client.eval(f'{obj}.counter')
            assert_moo_int(result, 100)

        finally:
            client.eval(f'recycle({obj})')

    def test_db_023_delete_property(self, client):
        """DB-023: delete_property() works."""
        result = client.eval('create(#1)')
        obj = assert_moo_success(result)

        try:
            # Add property
            client.eval(f'add_property({obj}, "temp_prop", 1, {{#1, "rw"}})')

            # Verify it exists
            result = client.eval(f'{obj}.temp_prop')
            assert_moo_success(result)

            # Delete it
            result = client.eval(f'delete_property({obj}, "temp_prop")')
            assert_moo_success(result)

            # Accessing it should now fail (server returns "Property not found" message)
            result = client.eval(f'{obj}.temp_prop')
            assert_moo_error(result, 'Property not found')

        finally:
            client.eval(f'recycle({obj})')
