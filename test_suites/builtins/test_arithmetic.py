"""Arithmetic builtin tests (ARITH-001 through ARITH-020)."""

import pytest

from lib.assertions import (
    assert_moo_success,
    assert_moo_error,
    assert_moo_int,
    assert_moo_float,
)


class TestBasicArithmetic:
    """Tests for basic arithmetic operations."""

    def test_arith_001_integer_addition(self, client):
        """ARITH-001: Integer addition works correctly."""
        result = client.eval('1 + 2')
        assert_moo_int(result, 3)

    def test_arith_002_integer_subtraction(self, client):
        """ARITH-002: Integer subtraction works correctly."""
        result = client.eval('10 - 3')
        assert_moo_int(result, 7)

    def test_arith_003_integer_multiplication(self, client):
        """ARITH-003: Integer multiplication works correctly."""
        result = client.eval('6 * 7')
        assert_moo_int(result, 42)

    def test_arith_004_integer_division(self, client):
        """ARITH-004: Integer division works correctly."""
        result = client.eval('20 / 4')
        assert_moo_int(result, 5)

    def test_arith_005_integer_modulo(self, client):
        """ARITH-005: Integer modulo works correctly."""
        result = client.eval('17 % 5')
        assert_moo_int(result, 2)

    def test_arith_006_negative_numbers(self, client):
        """ARITH-006: Negative numbers work correctly."""
        result = client.eval('-5 + 3')
        assert_moo_int(result, -2)

        result = client.eval('-5 * -3')
        assert_moo_int(result, 15)

    def test_arith_007_division_truncation(self, client):
        """ARITH-007: Integer division truncates toward zero."""
        result = client.eval('7 / 3')
        assert_moo_int(result, 2)

        result = client.eval('-7 / 3')
        assert_moo_int(result, -2)


class TestFloatArithmetic:
    """Tests for floating-point arithmetic."""

    def test_arith_010_float_addition(self, client):
        """ARITH-010: Float addition works correctly."""
        result = client.eval('1.5 + 2.5')
        assert_moo_float(result, 4.0)

    def test_arith_011_float_subtraction(self, client):
        """ARITH-011: Float subtraction works correctly."""
        result = client.eval('5.0 - 2.25')
        assert_moo_float(result, 2.75)

    def test_arith_012_float_multiplication(self, client):
        """ARITH-012: Float multiplication works correctly."""
        result = client.eval('2.5 * 4.0')
        assert_moo_float(result, 10.0)

    def test_arith_013_float_division(self, client):
        """ARITH-013: Float division works correctly."""
        result = client.eval('7.5 / 2.5')
        assert_moo_float(result, 3.0)

    def test_arith_014_mixed_int_float_requires_conversion(self, client):
        """ARITH-014: Mixed integer/float arithmetic requires type conversion."""
        # LambdaMOO does not allow mixed int/float arithmetic directly
        result = client.eval('5 + 2.5')
        success, msg = result
        assert not success, "Mixed int+float should fail"

        # Must convert explicitly
        result = client.eval('5.0 + 2.5')
        assert_moo_float(result, 7.5)

        result = client.eval('tofloat(5) + 2.5')
        assert_moo_float(result, 7.5)


class TestArithmeticErrors:
    """Tests for arithmetic error conditions."""

    def test_arith_020_division_by_zero(self, client):
        """ARITH-020: Division by zero raises error."""
        result = client.eval('5 / 0')
        success, msg = result
        assert not success, "Division by zero should fail"
        assert 'Division by zero' in msg or 'E_DIV' in msg

    def test_arith_021_modulo_by_zero(self, client):
        """ARITH-021: Modulo by zero raises error."""
        result = client.eval('5 % 0')
        success, msg = result
        assert not success, "Modulo by zero should fail"
        assert 'Division by zero' in msg or 'E_DIV' in msg

    def test_arith_022_float_division_by_zero(self, client):
        """ARITH-022: Float division by zero raises error."""
        result = client.eval('5.0 / 0.0')
        success, msg = result
        assert not success, "Float division by zero should fail"
        assert 'Division by zero' in msg or 'E_DIV' in msg


class TestMathFunctions:
    """Tests for math builtin functions."""

    def test_arith_030_abs(self, client):
        """ARITH-030: abs() works correctly."""
        result = client.eval('abs(-5)')
        assert_moo_int(result, 5)

        result = client.eval('abs(5)')
        assert_moo_int(result, 5)

        result = client.eval('abs(-3.5)')
        assert_moo_float(result, 3.5)

    def test_arith_031_min_max(self, client):
        """ARITH-031: min() and max() work correctly."""
        result = client.eval('min(1, 5)')
        assert_moo_int(result, 1)

        result = client.eval('max(1, 5)')
        assert_moo_int(result, 5)

    def test_arith_032_sqrt(self, client):
        """ARITH-032: sqrt() works correctly."""
        result = client.eval('sqrt(16.0)')
        assert_moo_float(result, 4.0)

        result = client.eval('sqrt(2.0)')
        assert_moo_float(result, 1.41421356, tolerance=0.00001)

    def test_arith_033_sqrt_negative_raises_error(self, client):
        """ARITH-033: sqrt() of negative number raises error."""
        result = client.eval('sqrt(-1.0)')
        success, msg = result
        assert not success, "sqrt of negative should fail"
        assert 'Invalid argument' in msg or 'E_INVARG' in msg

    def test_arith_034_floor_ceil(self, client):
        """ARITH-034: floor() and ceil() work correctly."""
        # Note: floor/ceil return floats, not integers
        result = client.eval('floor(3.7)')
        assert_moo_float(result, 3.0)

        result = client.eval('ceil(3.2)')
        assert_moo_float(result, 4.0)

        result = client.eval('floor(-3.2)')
        assert_moo_float(result, -4.0)

        result = client.eval('ceil(-3.7)')
        assert_moo_float(result, -3.0)

    def test_arith_035_trunc(self, client):
        """ARITH-035: trunc() truncates toward zero."""
        # Note: trunc returns float, not integer
        result = client.eval('trunc(3.7)')
        assert_moo_float(result, 3.0)

        result = client.eval('trunc(-3.7)')
        assert_moo_float(result, -3.0)


@pytest.mark.slow
class TestLargeNumbers:
    """Tests for large number handling (requires 64-bit integers)."""

    def test_arith_040_large_integers(self, client):
        """ARITH-040: Large integers are handled correctly."""
        # Test beyond 32-bit range
        result = client.eval('2147483647 + 1')
        assert_moo_int(result, 2147483648)

        result = client.eval('4294967296 * 2')
        assert_moo_int(result, 8589934592)

    def test_arith_041_very_large_integers(self, client):
        """ARITH-041: Very large integers work (64-bit)."""
        # Near 64-bit limit
        result = client.eval('9000000000000000000 + 1')
        assert_moo_int(result, 9000000000000000001)
