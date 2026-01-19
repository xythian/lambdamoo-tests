"""Persistence tests for MOO data types.

These tests verify that data survives a write→checkpoint→read cycle.
When run with --prior options, they also test upgrade compatibility.

Test coverage:
- Integers (including 64-bit)
- Floats
- Strings (including Unicode)
- Lists
- Objects references
"""

import shutil
import pytest

from lib.protocol import ServerPair
from lib.assertions import assert_moo_success, assert_moo_int


@pytest.mark.persistence
class TestIntegerPersistence:
    """Tests for integer persistence through checkpoint/upgrade."""

    def test_small_integers(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Small integers survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write with write_server
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_property(#0, "small_pos", 42, {#1, "rw"})')
            write_client.eval('add_property(#0, "small_neg", -17, {#1, "rw"})')
            write_client.eval('add_property(#0, "zero", 0, {#1, "rw"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read with read_server
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.small_pos')
            assert_moo_int(result, 42, "Positive integer not preserved")

            result = read_client.eval('#0.small_neg')
            assert_moo_int(result, -17, "Negative integer not preserved")

            result = read_client.eval('#0.zero')
            assert_moo_int(result, 0, "Zero not preserved")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_large_integers_64bit(self, server_pair: ServerPair, write_server_db, tmp_path):
        """64-bit integers survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        large_pos = 9223372036854775807   # Max signed 64-bit
        large_neg = -4611686018427387904  # Large negative

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval(f'add_property(#0, "large_pos", {large_pos}, {{#1, "rw"}})')
            write_client.eval(f'add_property(#0, "large_neg", {large_neg}, {{#1, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.large_pos')
            value = assert_moo_success(result)
            assert value == str(large_pos), f"Large positive not preserved: {value}"

            result = read_client.eval('#0.large_neg')
            value = assert_moo_success(result)
            assert value == str(large_neg), f"Large negative not preserved: {value}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestStringPersistence:
    """Tests for string persistence through checkpoint/upgrade."""

    def test_ascii_strings(self, server_pair: ServerPair, write_server_db, tmp_path):
        """ASCII strings survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_property(#0, "greeting", "Hello, World!", {#1, "rw"})')
            write_client.eval('add_property(#0, "empty", "", {#1, "rw"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.greeting')
            value = assert_moo_success(result)
            assert value == '"Hello, World!"', f"String not preserved: {value}"

            result = read_client.eval('#0.empty')
            value = assert_moo_success(result)
            assert value == '""', f"Empty string not preserved: {value}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    @pytest.mark.unicode
    def test_unicode_strings(self, server_pair: ServerPair, write_server_db, tmp_path,
                             requires_unicode):
        """Unicode strings survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Use actual UTF-8 characters (MOO doesn't support \u escape syntax)
            # "αβγ" = 3 Greek letters
            write_client.eval('add_property(#0, "greek", "αβγ", {#1, "rw"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('length(#0.greek)')
            assert_moo_int(result, 3, "Unicode string length should be 3")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestListPersistence:
    """Tests for list persistence through checkpoint/upgrade."""

    def test_simple_lists(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Simple lists survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_property(#0, "numbers", {1, 2, 3, 4, 5}, {#1, "rw"})')
            write_client.eval('add_property(#0, "empty_list", {}, {#1, "rw"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('length(#0.numbers)')
            assert_moo_int(result, 5, "List length should be 5")

            result = read_client.eval('#0.numbers[3]')
            assert_moo_int(result, 3, "Third element should be 3")

            result = read_client.eval('#0.empty_list')
            value = assert_moo_success(result)
            assert value == '{}', f"Empty list not preserved: {value}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_nested_lists(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Nested lists survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_property(#0, "nested", {{1, 2}, {3, 4}}, {#1, "rw"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('length(#0.nested)')
            assert_moo_int(result, 2, "Outer list length should be 2")

            result = read_client.eval('#0.nested[1][2]')
            assert_moo_int(result, 2, "Nested element should be 2")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestObjectPersistence:
    """Tests for object persistence through checkpoint/upgrade."""

    def test_object_creation(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Created objects survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            new_obj = assert_moo_success(result)

            # Store the object reference
            write_client.eval(f'add_property(#0, "created_obj", {new_obj}, {{#1, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.created_obj')
            stored_obj = assert_moo_success(result)

            # Object should still be valid
            result = read_client.eval(f'valid({stored_obj})')
            assert_moo_int(result, 1, "Created object should still be valid")

            # Parent should be preserved
            result = read_client.eval(f'parent({stored_obj})')
            value = assert_moo_success(result)
            assert value == '#1', f"Parent should be #1, got {value}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_object_hierarchy(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Object parent-child relationships survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            parent = assert_moo_success(result)

            result = write_client.eval(f'create({parent})')
            child = assert_moo_success(result)

            write_client.eval(f'add_property(#0, "test_parent", {parent}, {{#1, "rw"}})')
            write_client.eval(f'add_property(#0, "test_child", {child}, {{#1, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.test_parent')
            parent = assert_moo_success(result)

            result = read_client.eval('#0.test_child')
            child = assert_moo_success(result)

            # Verify hierarchy
            result = read_client.eval(f'parent({child})')
            actual_parent = assert_moo_success(result)
            assert actual_parent == parent, f"Parent not preserved: {actual_parent}"

            result = read_client.eval(f'children({parent})')
            children = assert_moo_success(result)
            assert child in children, f"Child not in children list: {children}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_object_location(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Object location/contents survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            result = write_client.eval('create(#1)')
            container = assert_moo_success(result)

            result = write_client.eval('create(#1)')
            item = assert_moo_success(result)

            write_client.eval(f'move({item}, {container})')

            write_client.eval(f'add_property(#0, "container", {container}, {{#1, "rw"}})')
            write_client.eval(f'add_property(#0, "item", {item}, {{#1, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.container')
            container = assert_moo_success(result)

            result = read_client.eval('#0.item')
            item = assert_moo_success(result)

            # Verify location
            result = read_client.eval(f'{item}.location')
            location = assert_moo_success(result)
            assert location == container, f"Location not preserved: {location}"

            # Verify contents
            result = read_client.eval(f'{container}.contents')
            contents = assert_moo_success(result)
            assert item in contents, f"Item not in contents: {contents}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)
