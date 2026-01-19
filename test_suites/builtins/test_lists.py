"""List builtin tests (LIST-001 through LIST-040)."""

import pytest

from lib.assertions import (
    assert_moo_success,
    assert_moo_error,
    assert_moo_int,
    assert_moo_list,
    assert_moo_list_contains,
)


class TestListBasics:
    """Tests for basic list operations."""

    def test_list_001_list_length(self, client):
        """LIST-001: length() returns correct list length."""
        result = client.eval('length({1, 2, 3})')
        assert_moo_int(result, 3)

        result = client.eval('length({})')
        assert_moo_int(result, 0)

    def test_list_002_list_indexing(self, client):
        """LIST-002: List indexing works correctly."""
        result = client.eval('{10, 20, 30}[1]')
        assert_moo_int(result, 10)

        result = client.eval('{10, 20, 30}[3]')
        assert_moo_int(result, 30)

    def test_list_003_list_range(self, client):
        """LIST-003: List range extraction works."""
        result = client.eval('{1, 2, 3, 4, 5}[2..4]')
        value = assert_moo_success(result)
        assert '2' in value and '3' in value and '4' in value

    def test_list_004_list_concatenation(self, client):
        """LIST-004: List concatenation via splice operator."""
        # MOO uses @ splice operator, not + for list concatenation
        result = client.eval('{@{1, 2}, @{3, 4}}')
        value = assert_moo_success(result)
        assert '1' in value and '4' in value

    def test_list_005_index_out_of_range(self, client):
        """LIST-005: Out of range indexing raises error."""
        result = client.eval('{1, 2, 3}[0]')
        success, msg = result
        assert not success, "Index 0 should fail"
        assert 'Range error' in msg or 'E_RANGE' in msg

        result = client.eval('{1, 2, 3}[10]')
        success, msg = result
        assert not success, "Index 10 should fail"
        assert 'Range error' in msg or 'E_RANGE' in msg

    def test_list_006_nested_lists(self, client):
        """LIST-006: Nested lists work correctly."""
        result = client.eval('{{1, 2}, {3, 4}}[1]')
        value = assert_moo_success(result)
        assert '1' in value and '2' in value

        result = client.eval('{{1, 2}, {3, 4}}[2][1]')
        assert_moo_int(result, 3)


class TestListFunctions:
    """Tests for list manipulation functions."""

    def test_list_010_listappend(self, client):
        """LIST-010: listappend() adds element at end."""
        result = client.eval('listappend({1, 2, 3}, 4)')
        value = assert_moo_success(result)
        assert value.endswith('4}') or ', 4}' in value

    def test_list_011_listinsert(self, client):
        """LIST-011: listinsert() inserts at position."""
        result = client.eval('listinsert({1, 2, 3}, 99, 2)')
        value = assert_moo_success(result)
        # Should be {1, 99, 2, 3}
        assert '99' in value

    def test_list_012_listdelete(self, client):
        """LIST-012: listdelete() removes element."""
        result = client.eval('listdelete({1, 2, 3}, 2)')
        value = assert_moo_success(result)
        # Should be {1, 3}
        assert '2' not in value or value == '{1, 3}'

    def test_list_013_listset(self, client):
        """LIST-013: listset() replaces element."""
        result = client.eval('listset({1, 2, 3}, 99, 2)')
        value = assert_moo_success(result)
        # Should be {1, 99, 3}
        assert '99' in value

    def test_list_014_setadd(self, client):
        """LIST-014: setadd() adds unique element."""
        result = client.eval('setadd({1, 2, 3}, 4)')
        value = assert_moo_success(result)
        assert '4' in value

        # Adding existing element should not duplicate
        result = client.eval('setadd({1, 2, 3}, 2)')
        value = assert_moo_success(result)
        # Count occurrences of '2' - should be 1
        assert value.count(', 2,') + value.count('{2,') + value.count(', 2}') <= 1

    def test_list_015_setremove(self, client):
        """LIST-015: setremove() removes element."""
        result = client.eval('setremove({1, 2, 3}, 2)')
        value = assert_moo_success(result)
        # Should remove 2
        assert value == '{1, 3}' or ('1' in value and '3' in value and value.count('2') == 0)


class TestListSearch:
    """Tests for list search functions."""

    def test_list_020_is_member(self, client):
        """LIST-020: is_member() finds element."""
        result = client.eval('is_member(2, {1, 2, 3})')
        value = assert_moo_success(result)
        assert int(value) > 0, "2 should be found in list"

        result = client.eval('is_member(5, {1, 2, 3})')
        assert_moo_int(result, 0)

    def test_list_021_index_in_list(self, client):
        """LIST-021: is_member() returns correct index."""
        result = client.eval('is_member("b", {"a", "b", "c"})')
        assert_moo_int(result, 2)


class TestListAssignment:
    """Tests for list modification functions."""

    def test_list_025_listset(self, client):
        """LIST-025: listset() modifies element."""
        # Use listset since indexed assignment requires verb context
        result = client.eval('listset({1, 2, 3}, 99, 2)')
        value = assert_moo_success(result)
        assert '99' in value
        assert value == '{1, 99, 3}'

    def test_list_026_range_extraction(self, client):
        """LIST-026: Range extraction works."""
        result = client.eval('{1, 2, 3, 4, 5}[2..4]')
        value = assert_moo_success(result)
        assert '2' in value and '3' in value and '4' in value

    def test_list_027_splice_operator(self, client):
        """LIST-027: Splice (@) operator works."""
        result = client.eval('{@{1, 2}, @{3, 4}}')
        value = assert_moo_success(result)
        # Should flatten to {1, 2, 3, 4}
        assert '1' in value and '4' in value


class TestScatterAssignment:
    """Tests for scatter (destructuring) assignment syntax."""

    def test_list_030_basic_scatter(self, client):
        """LIST-030: Basic scatter assignment syntax accepted."""
        # Note: variables don't persist across eval calls in this context
        # Just verify the syntax is accepted and returns the list
        result = client.eval('{a, b, c} = {1, 2, 3}')
        value = assert_moo_success(result)
        assert value == '{1, 2, 3}'

    def test_list_031_scatter_with_rest(self, client):
        """LIST-031: Scatter with @rest syntax accepted."""
        result = client.eval('{first, @rest} = {1, 2, 3, 4}')
        value = assert_moo_success(result)
        assert value == '{1, 2, 3, 4}'

    def test_list_032_scatter_optional(self, client):
        """LIST-032: Scatter with optional elements syntax accepted."""
        result = client.eval('{a, ?b = 99} = {1}')
        value = assert_moo_success(result)
        assert value == '{1}'


class TestListErrors:
    """Tests for list error conditions."""

    def test_list_035_type_error_non_list(self, client):
        """LIST-035: Operations on non-lists raise error."""
        result = client.eval('listappend(42, 1)')
        success, msg = result
        assert not success, "listappend on non-list should fail"
        assert 'Type mismatch' in msg or 'E_TYPE' in msg

    def test_list_036_scatter_length_mismatch(self, client):
        """LIST-036: Scatter with wrong length raises error."""
        result = client.eval('{a, b, c} = {1, 2}')
        success, msg = result
        assert not success, "Scatter with wrong length should fail"
        assert 'Incorrect number' in msg or 'E_ARGS' in msg
