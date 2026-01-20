"""Persistence tests for waifs.

These tests verify that waifs survive a write→checkpoint→read cycle.
When run with --prior options, they also test upgrade compatibility.

Test coverage:
- Basic waif persistence (class, owner, properties)
- Waifs stored in object properties
- Waifs stored in lists
- Waif property values of various types
- Multiple waifs from the same class
"""

import shutil
import pytest

from lib.protocol import ServerPair
from lib.assertions import assert_moo_success, assert_moo_int


def setup_waif_class(client, class_obj):
    """Set up a waif class with standard properties and verbs.

    Args:
        client: Connected MooClient
        class_obj: Object number to use as waif class (e.g., '#4')

    Returns:
        The class object number
    """
    # Add waif properties (prefixed with :) - owned by #1 (wizard)
    client.eval(f'add_property({class_obj}, ":value", 0, {{#1, "rw"}})')
    client.eval(f'add_property({class_obj}, ":name", "", {{#1, "rw"}})')
    client.eval(f'add_property({class_obj}, ":data", {{}}, {{#1, "rw"}})')

    # Add verb to create waifs - owned by #1 for wizard permissions
    client.eval(f'add_verb({class_obj}, {{#1, "xd", "new"}}, {{"this", "none", "this"}})')
    client.eval(f'set_verb_code({class_obj}, "new", {{"return new_waif();"}})')

    return class_obj


@pytest.mark.persistence
class TestWaifPersistence:
    """Tests for basic waif persistence through checkpoint/upgrade."""

    def test_waif_survives_checkpoint(self, server_pair: ServerPair, write_server_db,
                                       tmp_path, requires_waifs):
        """A waif stored in a property survives write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write with write_server
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Create waif class
            result = write_client.eval('create(#1)')
            waif_class = assert_moo_success(result)
            setup_waif_class(write_client, waif_class)

            # Store class reference first
            write_client.eval(f'add_property(#0, "waif_class", {waif_class}, {{#1, "rw"}})')
            # Create property to hold waif (with 0 as placeholder)
            write_client.eval('add_property(#0, "test_waif", 0, {#1, "rw"})')

            # Create a waif and store it in a single verb (so we have the actual waif, not string repr)
            write_client.eval(f'add_verb({waif_class}, {{#1, "xd", "setup_and_store"}}, {{"this", "none", "this"}})')
            code = '{"w = new_waif();", "w.value = 42;", "w.name = \\"test\\";", "#0.test_waif = w;", "return 1;"}'
            write_client.eval(f'set_verb_code({waif_class}, "setup_and_store", {code})')

            result = write_client.eval(f'{waif_class}:setup_and_store()')
            assert_moo_success(result)

            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read with read_server
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # Get the stored waif
            result = read_client.eval('#0.test_waif')
            success, value = result
            assert success, f"Failed to get stored waif: {value}"
            assert '[[' in value or 'waif' in value.lower(), f"Expected waif, got: {value}"

            # Verify waif properties survived
            result = read_client.eval('#0.test_waif.value')
            assert_moo_int(result, 42, "Waif .value not preserved")

            result = read_client.eval('#0.test_waif.name')
            value = assert_moo_success(result)
            assert value == '"test"', f"Waif .name not preserved: {value}"

            # Verify waif class reference
            result = read_client.eval('#0.test_waif.class')
            waif_class = assert_moo_success(result)
            result = read_client.eval('#0.waif_class')
            expected_class = assert_moo_success(result)
            assert waif_class == expected_class, f"Waif class changed: {waif_class} != {expected_class}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_waif_with_list_property(self, server_pair: ServerPair, write_server_db,
                                      tmp_path, requires_waifs):
        """Waif with list property survives write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            waif_class = assert_moo_success(result)
            setup_waif_class(write_client, waif_class)

            # Pre-create property to hold waif (with 0 as placeholder)
            write_client.eval('add_property(#0, "test_waif", 0, {#1, "rw"})')

            # Create waif with list data and store it
            write_client.eval(f'add_verb({waif_class}, {{#1, "xd", "setup_and_store"}}, {{"this", "none", "this"}})')
            code = '{"w = new_waif();", "w.data = {1, 2, 3, \\"four\\"};", "#0.test_waif = w;", "return 1;"}'
            write_client.eval(f'set_verb_code({waif_class}, "setup_and_store", {code})')

            result = write_client.eval(f'{waif_class}:setup_and_store()')
            assert_moo_success(result)

            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('length(#0.test_waif.data)')
            assert_moo_int(result, 4, "Waif list property length not preserved")

            result = read_client.eval('#0.test_waif.data[4]')
            value = assert_moo_success(result)
            assert value == '"four"', f"Waif list element not preserved: {value}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_multiple_waifs_same_class(self, server_pair: ServerPair, write_server_db,
                                        tmp_path, requires_waifs):
        """Multiple waifs from same class survive independently."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            waif_class = assert_moo_success(result)
            setup_waif_class(write_client, waif_class)

            # Pre-create property to hold waif pair (with {} as placeholder)
            write_client.eval('add_property(#0, "waif_pair", {}, {#1, "rw"})')

            # Create two waifs with different values and store them
            write_client.eval(f'add_verb({waif_class}, {{#1, "xd", "make_and_store"}}, {{"this", "none", "this"}})')
            code = '{"w1 = new_waif();", "w1.value = 100;", "w2 = new_waif();", "w2.value = 200;", "#0.waif_pair = {w1, w2};", "return 1;"}'
            write_client.eval(f'set_verb_code({waif_class}, "make_and_store", {code})')

            result = write_client.eval(f'{waif_class}:make_and_store()')
            assert_moo_success(result)

            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('length(#0.waif_pair)')
            assert_moo_int(result, 2, "Waif pair list length wrong")

            result = read_client.eval('#0.waif_pair[1].value')
            assert_moo_int(result, 100, "First waif value not preserved")

            result = read_client.eval('#0.waif_pair[2].value')
            assert_moo_int(result, 200, "Second waif value not preserved")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_waif_owner_preserved(self, server_pair: ServerPair, write_server_db,
                                   tmp_path, requires_waifs):
        """Waif .owner is preserved through checkpoint."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            waif_class = assert_moo_success(result)
            setup_waif_class(write_client, waif_class)

            # Pre-create property to hold waif info (with {} as placeholder)
            write_client.eval('add_property(#0, "waif_info", {}, {#1, "rw"})')

            # Create waif and store it along with its owner
            write_client.eval(f'add_verb({waif_class}, {{#1, "xd", "setup_and_store"}}, {{"this", "none", "this"}})')
            code = '{"w = new_waif();", "#0.waif_info = {w, w.owner};", "return 1;"}'
            write_client.eval(f'set_verb_code({waif_class}, "setup_and_store", {code})')

            result = write_client.eval(f'{waif_class}:setup_and_store()')
            assert_moo_success(result)

            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # Get original owner from saved info
            result = read_client.eval('#0.waif_info[2]')
            original_owner = assert_moo_success(result)

            # Get current waif owner
            result = read_client.eval('#0.waif_info[1].owner')
            current_owner = assert_moo_success(result)

            assert current_owner == original_owner, f"Owner changed: {current_owner} != {original_owner}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestWaifClassPersistence:
    """Tests for waif class object persistence."""

    def test_waif_class_properties_preserved(self, server_pair: ServerPair, write_server_db,
                                              tmp_path, requires_waifs):
        """Waif class :properties survive checkpoint."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            waif_class = assert_moo_success(result)

            # Add multiple waif properties with different defaults
            write_client.eval(f'add_property({waif_class}, ":prop_int", 123, {{{waif_class}, "rw"}})')
            write_client.eval(f'add_property({waif_class}, ":prop_str", "default", {{{waif_class}, "rw"}})')
            write_client.eval(f'add_property({waif_class}, ":prop_list", {{1, 2}}, {{{waif_class}, "rw"}})')

            write_client.eval(f'add_property(#0, "waif_class", {waif_class}, {{#1, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.waif_class')
            waif_class = assert_moo_success(result)

            # Verify properties exist by checking properties list
            result = read_client.eval(f'properties({waif_class})')
            props = assert_moo_success(result)
            assert ':prop_int' in props, f":prop_int not in properties: {props}"
            assert ':prop_str' in props, f":prop_str not in properties: {props}"
            assert ':prop_list' in props, f":prop_list not in properties: {props}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_waif_class_verbs_preserved(self, server_pair: ServerPair, write_server_db,
                                         tmp_path, requires_waifs):
        """Waif class :verbs survive checkpoint."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            waif_class = assert_moo_success(result)

            # Add waif property and verb
            write_client.eval(f'add_property({waif_class}, ":counter", 0, {{{waif_class}, "rw"}})')
            write_client.eval(f'add_verb({waif_class}, {{#1, "xd", "new"}}, {{"this", "none", "this"}})')
            write_client.eval(f'set_verb_code({waif_class}, "new", {{"return new_waif();"}})')

            write_client.eval(f'add_verb({waif_class}, {{#1, "xd", ":increment"}}, {{"this", "none", "this"}})')
            write_client.eval(f'set_verb_code({waif_class}, ":increment", {{"this.counter = this.counter + 1;", "return this.counter;"}})')

            write_client.eval(f'add_property(#0, "waif_class", {waif_class}, {{#1, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.waif_class')
            waif_class = assert_moo_success(result)

            # Verify verbs exist
            result = read_client.eval(f'verbs({waif_class})')
            verbs = assert_moo_success(result)
            assert ':increment' in verbs, f":increment not in verbs: {verbs}"

            # Verify waif verb actually works after restore
            # Create a verb to test this properly (eval has parsing issues with multiple statements)
            read_client.eval(f'add_verb({waif_class}, {{#1, "xd", "test_increment"}}, {{"this", "none", "this"}})')
            read_client.eval(f'set_verb_code({waif_class}, "test_increment", {{"w = new_waif();", "return w:increment();"}})')
            result = read_client.eval(f'{waif_class}:test_increment()')
            assert_moo_int(result, 1, "Waif verb not functional after restore")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestWaifEdgeCases:
    """Tests for edge cases in waif persistence."""

    def test_waif_in_nested_list(self, server_pair: ServerPair, write_server_db,
                                  tmp_path, requires_waifs):
        """Waif inside nested list structure survives checkpoint."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            waif_class = assert_moo_success(result)
            setup_waif_class(write_client, waif_class)

            # Pre-create property to hold nested structure (with {} as placeholder)
            write_client.eval('add_property(#0, "nested_waif", {}, {#1, "rw"})')

            # Create waif inside nested structure and store it
            write_client.eval(f'add_verb({waif_class}, {{#1, "xd", "setup_and_store"}}, {{"this", "none", "this"}})')
            code = '{"w = new_waif();", "w.value = 999;", "#0.nested_waif = {{\\"key\\", {w}}};", "return 1;"}'
            write_client.eval(f'set_verb_code({waif_class}, "setup_and_store", {code})')

            result = write_client.eval(f'{waif_class}:setup_and_store()')
            assert_moo_success(result)

            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # Navigate to nested waif: #0.nested_waif[1][2][1]
            # Structure is {{"key", {waif}}}
            result = read_client.eval('#0.nested_waif[1][2][1].value')
            assert_moo_int(result, 999, "Nested waif value not preserved")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_waif_default_property_values(self, server_pair: ServerPair, write_server_db,
                                           tmp_path, requires_waifs):
        """New waifs get correct default property values after restore."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write - set up class with specific defaults
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            waif_class = assert_moo_success(result)

            # Set up class with specific default values
            write_client.eval(f'add_property({waif_class}, ":default_val", 12345, {{{waif_class}, "rw"}})')
            write_client.eval(f'add_verb({waif_class}, {{#1, "xd", "new"}}, {{"this", "none", "this"}})')
            write_client.eval(f'set_verb_code({waif_class}, "new", {{"return new_waif();"}})')

            write_client.eval(f'add_property(#0, "waif_class", {waif_class}, {{#1, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read - create NEW waif and check defaults
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.waif_class')
            waif_class = assert_moo_success(result)

            # Create a new waif after restore and check default value
            # Use a verb to avoid eval parsing issues
            read_client.eval(f'add_verb({waif_class}, {{#1, "xd", "test_default"}}, {{"this", "none", "this"}})')
            read_client.eval(f'set_verb_code({waif_class}, "test_default", {{"w = new_waif();", "return w.default_val;"}})')
            result = read_client.eval(f'{waif_class}:test_default()')
            assert_moo_int(result, 12345, "Default property value not preserved for new waifs")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)
