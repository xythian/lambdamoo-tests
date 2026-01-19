"""Persistence tests for MOO verbs.

These tests verify that verb code survives a write→checkpoint→read cycle.
When run with --prior options, they also test upgrade compatibility.
"""

import shutil
import pytest

from lib.protocol import ServerPair
from lib.assertions import assert_moo_success, assert_moo_int


@pytest.mark.persistence
class TestVerbPersistence:
    """Tests for verb persistence through checkpoint/upgrade."""

    def test_simple_verb(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Simple verb code survives write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_verb(#0, {#1, "rxd", "test_verb"}, {"this", "none", "this"})')
            write_client.eval('set_verb_code(#0, "test_verb", {"return 42;"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0:test_verb()')
            assert_moo_int(result, 42, "Verb should return 42")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_verb_with_arguments(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Verb with arguments survives write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_verb(#0, {#1, "rxd", "add_numbers"}, {"this", "none", "this"})')
            write_client.eval('set_verb_code(#0, "add_numbers", {"return args[1] + args[2];"})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0:add_numbers(10, 32)')
            assert_moo_int(result, 42, "Verb should return 10+32=42")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_verb_with_loop(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Verb with control structures survives write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_verb(#0, {#1, "rxd", "sum_to_n"}, {"this", "none", "this"})')
            code_lines = [
                '"n = args[1];"',
                '"sum = 0;"',
                '"for i in [1..n]"',
                '"  sum = sum + i;"',
                '"endfor"',
                '"return sum;"',
            ]
            write_client.eval(f'set_verb_code(#0, "sum_to_n", {{{", ".join(code_lines)}}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            # Sum of 1..10 = 55
            result = read_client.eval('#0:sum_to_n(10)')
            assert_moo_int(result, 55, "Verb should return sum 1..10 = 55")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_verb_with_conditionals(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Verb with if/else survives write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            write_client.eval('add_verb(#0, {#1, "rxd", "abs_value"}, {"this", "none", "this"})')
            code_lines = [
                '"n = args[1];"',
                '"if (n < 0)"',
                '"  return -n;"',
                '"else"',
                '"  return n;"',
                '"endif"',
            ]
            write_client.eval(f'set_verb_code(#0, "abs_value", {{{", ".join(code_lines)}}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0:abs_value(-42)')
            assert_moo_int(result, 42, "abs_value(-42) should be 42")

            result = read_client.eval('#0:abs_value(17)')
            assert_moo_int(result, 17, "abs_value(17) should be 17")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)


@pytest.mark.persistence
class TestPropertyPersistence:
    """Tests for property persistence through checkpoint/upgrade."""

    def test_property_with_permissions(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Property permissions survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Create object and add property with specific permissions
            result = write_client.eval('create(#1)')
            obj = assert_moo_success(result)

            write_client.eval(f'add_property({obj}, "secret", 42, {{#1, "r"}})')
            write_client.eval(f'add_property(#0, "test_obj", {obj}, {{#1, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.test_obj')
            obj = assert_moo_success(result)

            # Property value should be preserved
            result = read_client.eval(f'{obj}.secret')
            assert_moo_int(result, 42, "Property value not preserved")

            # Check permissions (property_info returns {owner, perms, name})
            result = read_client.eval(f'property_info({obj}, "secret")')
            info = assert_moo_success(result)
            assert '"r"' in info or "'r'" in info, f"Permission 'r' not preserved: {info}"
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)

    def test_inherited_property(self, server_pair: ServerPair, write_server_db, tmp_path):
        """Inherited properties survive write→read cycle."""
        db_path = tmp_path / "test.db"
        shutil.copy(write_server_db, db_path)

        # Phase 1: Write
        write_instance = server_pair.write_server.start(database=db_path)
        write_client = server_pair.write_server.connect(write_instance)
        write_client.authenticate('Wizard')

        try:
            # Create parent with property
            result = write_client.eval('create(#1)')
            parent = assert_moo_success(result)
            write_client.eval(f'add_property({parent}, "inherited_val", 100, {{#1, "rc"}})')

            # Create child
            result = write_client.eval(f'create({parent})')
            child = assert_moo_success(result)

            # Override in child
            write_client.eval(f'{child}.inherited_val = 200')

            write_client.eval(f'add_property(#0, "parent_obj", {parent}, {{#1, "rw"}})')
            write_client.eval(f'add_property(#0, "child_obj", {child}, {{#1, "rw"}})')
            write_client.checkpoint()
        finally:
            write_client.close()
            output_db = server_pair.write_server.stop(write_instance)

        # Phase 2: Read
        read_instance = server_pair.read_server.start(database=output_db)
        read_client = server_pair.read_server.connect(read_instance)
        read_client.authenticate('Wizard')

        try:
            result = read_client.eval('#0.parent_obj')
            parent = assert_moo_success(result)

            result = read_client.eval('#0.child_obj')
            child = assert_moo_success(result)

            # Parent's value
            result = read_client.eval(f'{parent}.inherited_val')
            assert_moo_int(result, 100, "Parent value not preserved")

            # Child's overridden value
            result = read_client.eval(f'{child}.inherited_val')
            assert_moo_int(result, 200, "Child override not preserved")
        finally:
            read_client.close()
            server_pair.read_server.stop(read_instance)
