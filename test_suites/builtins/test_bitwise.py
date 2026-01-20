"""Bitwise operator tests.

LambdaMOO supports bitwise operations on integers using operator syntax:
- a .|. b  - bitwise OR
- a .&. b  - bitwise AND
- a .^. b  - bitwise XOR
- ~a       - bitwise NOT (one's complement)
- a << b   - left shift by b bits
- a >> b   - arithmetic right shift (sign-extended)
- a >>> b  - logical right shift (zero-extended)

These operators require BITWISE_OPERATORS to be enabled at compile time.

Note: The dot syntax for AND/OR/XOR requires spaces around integer literals
to avoid confusion with floating-point numbers (e.g., "2 .|. 5" not "2.|.5").
"""

import pytest

from lib.assertions import assert_moo_success, assert_moo_int


class TestBitwiseOr:
    """Tests for .|. (bitwise OR)."""

    def test_bitor_basic(self, client, requires_bitwise):
        """Bitwise OR performs OR on each bit."""
        # 0b0101 | 0b0011 = 0b0111
        result = client.eval('5 .|. 3')
        assert_moo_int(result, 7)

    def test_bitor_zero(self, client, requires_bitwise):
        """Bitwise OR with zero returns the other operand."""
        result = client.eval('42 .|. 0')
        assert_moo_int(result, 42)

        result = client.eval('0 .|. 42')
        assert_moo_int(result, 42)

    def test_bitor_same(self, client, requires_bitwise):
        """Bitwise OR of identical values returns that value."""
        result = client.eval('255 .|. 255')
        assert_moo_int(result, 255)

    def test_bitor_all_ones(self, client, requires_bitwise):
        """Bitwise OR with all ones returns all ones."""
        result = client.eval('255 .|. 170')
        assert_moo_int(result, 255)

    def test_bitor_negative(self, client, requires_bitwise):
        """Bitwise OR works with negative numbers."""
        # -1 in two's complement is all ones
        result = client.eval('-1 .|. 42')
        assert_moo_int(result, -1)


class TestBitwiseAnd:
    """Tests for .&. (bitwise AND)."""

    def test_bitand_basic(self, client, requires_bitwise):
        """Bitwise AND performs AND on each bit."""
        # 0b0101 & 0b0011 = 0b0001
        result = client.eval('5 .&. 3')
        assert_moo_int(result, 1)

    def test_bitand_zero(self, client, requires_bitwise):
        """Bitwise AND with zero returns zero."""
        result = client.eval('42 .&. 0')
        assert_moo_int(result, 0)

        result = client.eval('0 .&. 42')
        assert_moo_int(result, 0)

    def test_bitand_same(self, client, requires_bitwise):
        """Bitwise AND of identical values returns that value."""
        result = client.eval('255 .&. 255')
        assert_moo_int(result, 255)

    def test_bitand_mask(self, client, requires_bitwise):
        """Bitwise AND can mask off bits."""
        # 0xFF & 0x0F = 0x0F
        result = client.eval('255 .&. 15')
        assert_moo_int(result, 15)

    def test_bitand_negative(self, client, requires_bitwise):
        """Bitwise AND works with negative numbers."""
        # -1 & 255 = 255 (masking off sign extension)
        result = client.eval('-1 .&. 255')
        assert_moo_int(result, 255)


class TestBitwiseXor:
    """Tests for .^. (bitwise XOR)."""

    def test_bitxor_basic(self, client, requires_bitwise):
        """Bitwise XOR performs XOR on each bit."""
        # 0b0101 ^ 0b0011 = 0b0110
        result = client.eval('5 .^. 3')
        assert_moo_int(result, 6)

    def test_bitxor_zero(self, client, requires_bitwise):
        """Bitwise XOR with zero returns the other operand."""
        result = client.eval('42 .^. 0')
        assert_moo_int(result, 42)

        result = client.eval('0 .^. 42')
        assert_moo_int(result, 42)

    def test_bitxor_same(self, client, requires_bitwise):
        """Bitwise XOR of identical values returns zero."""
        result = client.eval('255 .^. 255')
        assert_moo_int(result, 0)

    def test_bitxor_double(self, client, requires_bitwise):
        """Bitwise XOR twice returns original value."""
        result = client.eval('(42 .^. 123) .^. 123')
        assert_moo_int(result, 42)

    def test_bitxor_negative(self, client, requires_bitwise):
        """Bitwise XOR works with negative numbers."""
        result = client.eval('-1 .^. 0')
        assert_moo_int(result, -1)


class TestBitwiseNot:
    """Tests for ~ (bitwise NOT / one's complement)."""

    def test_bitnot_zero(self, client, requires_bitwise):
        """~0 returns -1 (all ones in two's complement)."""
        result = client.eval('~0')
        assert_moo_int(result, -1)

    def test_bitnot_minus_one(self, client, requires_bitwise):
        """~(-1) returns 0."""
        result = client.eval('~(-1)')
        assert_moo_int(result, 0)

    def test_bitnot_double(self, client, requires_bitwise):
        """Double complement returns original value."""
        result = client.eval('~~42')
        assert_moo_int(result, 42)

    def test_bitnot_positive(self, client, requires_bitwise):
        """Complement of positive number is negative."""
        # ~n = -(n+1) in two's complement
        result = client.eval('~42')
        assert_moo_int(result, -43)

    def test_bitnot_identity(self, client, requires_bitwise):
        """a .^. ~a = -1 (all ones)."""
        result = client.eval('42 .^. ~42')
        assert_moo_int(result, -1)


class TestShiftLeft:
    """Tests for << (left shift)."""

    def test_shl_basic(self, client, requires_bitwise):
        """Left shift moves bits left."""
        # 1 << 4 = 16
        result = client.eval('1 << 4')
        assert_moo_int(result, 16)

    def test_shl_zero_shift(self, client, requires_bitwise):
        """Left shift by zero returns original value."""
        result = client.eval('42 << 0')
        assert_moo_int(result, 42)

    def test_shl_multiply(self, client, requires_bitwise):
        """Left shift by 1 is equivalent to multiply by 2."""
        result = client.eval('21 << 1')
        assert_moo_int(result, 42)

    def test_shl_large(self, client, requires_bitwise):
        """Left shift can create large numbers."""
        # 1 << 30 = 1073741824
        result = client.eval('1 << 30')
        assert_moo_int(result, 1073741824)

    def test_shl_negative_shift_error(self, client, requires_bitwise):
        """Left shift by negative amount raises E_INVARG."""
        result = client.eval('5 << -1')
        success, msg = result
        assert not success, "Negative shift should fail"
        assert 'E_INVARG' in msg or 'Invalid' in msg


class TestArithmeticShiftRight:
    """Tests for >> (arithmetic right shift, sign-extended)."""

    def test_shr_basic(self, client, requires_bitwise):
        """Arithmetic right shift moves bits right."""
        # 16 >> 4 = 1
        result = client.eval('16 >> 4')
        assert_moo_int(result, 1)

    def test_shr_zero_shift(self, client, requires_bitwise):
        """Right shift by zero returns original value."""
        result = client.eval('42 >> 0')
        assert_moo_int(result, 42)

    def test_shr_divide(self, client, requires_bitwise):
        """Right shift by 1 is like integer divide by 2."""
        result = client.eval('42 >> 1')
        assert_moo_int(result, 21)

    def test_shr_truncates(self, client, requires_bitwise):
        """Right shift truncates low bits."""
        # 7 >> 1 = 3 (not 3.5)
        result = client.eval('7 >> 1')
        assert_moo_int(result, 3)

    def test_shr_negative_preserves_sign(self, client, requires_bitwise):
        """Arithmetic right shift preserves sign (sign-extended)."""
        # -8 >> 2 = -2 (sign bits shifted in)
        result = client.eval('-8 >> 2')
        assert_moo_int(result, -2)

    def test_shr_negative_shift_error(self, client, requires_bitwise):
        """Right shift by negative amount raises E_INVARG."""
        result = client.eval('5 >> -1')
        success, msg = result
        assert not success, "Negative shift should fail"


class TestLogicalShiftRight:
    """Tests for >>> (logical right shift, zero-extended)."""

    def test_lshr_basic(self, client, requires_bitwise):
        """Logical right shift moves bits right."""
        result = client.eval('16 >>> 4')
        assert_moo_int(result, 1)

    def test_lshr_zero_shift(self, client, requires_bitwise):
        """Logical right shift by zero returns original value."""
        result = client.eval('42 >>> 0')
        assert_moo_int(result, 42)

    def test_lshr_positive_same_as_shr(self, client, requires_bitwise):
        """For positive numbers, >>> and >> behave the same."""
        result1 = client.eval('1000 >> 3')
        result2 = client.eval('1000 >>> 3')
        assert result1 == result2

    def test_lshr_negative_differs_from_shr(self, client, requires_bitwise):
        """For negative numbers, >>> fills with zeros (becomes positive)."""
        result = client.eval('-8 >>> 2')
        success, value = result
        assert success, f"Logical shift failed: {value}"
        # Should be positive (large number) because zeros shifted in
        int_value = int(value)
        assert int_value > 0, f"Logical shift of negative should be positive, got {int_value}"

    def test_lshr_negative_shift_error(self, client, requires_bitwise):
        """Logical right shift by negative amount raises E_INVARG."""
        result = client.eval('5 >>> -1')
        success, msg = result
        assert not success, "Negative shift should fail"


class TestBitwiseCombinations:
    """Tests combining multiple bitwise operations."""

    def test_and_or_combination(self, client, requires_bitwise):
        """Test combining AND and OR operations."""
        # (5 | 2) & 7 = 7 & 7 = 7
        result = client.eval('(5 .|. 2) .&. 7')
        assert_moo_int(result, 7)

    def test_xor_not_identity(self, client, requires_bitwise):
        """XOR with NOT gives all ones."""
        # a ^ ~a = -1 (all ones)
        result = client.eval('42 .^. ~42')
        assert_moo_int(result, -1)

    def test_shift_round_trip(self, client, requires_bitwise):
        """Shift left then right recovers original (for small values)."""
        result = client.eval('(42 << 8) >> 8')
        assert_moo_int(result, 42)

    def test_mask_extraction(self, client, requires_bitwise):
        """Extract bits using shift and mask."""
        # Extract bits 4-7 from 0xAB (171)
        # (171 >> 4) & 0xF = 10
        result = client.eval('(171 >> 4) .&. 15')
        assert_moo_int(result, 10)

    def test_set_bit(self, client, requires_bitwise):
        """Set a specific bit using OR."""
        # Set bit 3 (value 8) in 0
        result = client.eval('0 .|. (1 << 3)')
        assert_moo_int(result, 8)

    def test_clear_bit(self, client, requires_bitwise):
        """Clear a specific bit using AND and NOT."""
        # Clear bit 1 (value 2) from 7 (0b111)
        result = client.eval('7 .&. ~(1 << 1)')
        assert_moo_int(result, 5)

    def test_toggle_bit(self, client, requires_bitwise):
        """Toggle a specific bit using XOR."""
        # Toggle bit 0 in 5 (0b101) -> 4 (0b100)
        result = client.eval('5 .^. 1')
        assert_moo_int(result, 4)

        # Toggle again -> back to 5
        result = client.eval('4 .^. 1')
        assert_moo_int(result, 5)


class TestBitwiseTypeErrors:
    """Tests for bitwise operation type checking."""

    def test_bitor_type_error(self, client, requires_bitwise):
        """Bitwise OR with non-integer raises E_TYPE."""
        result = client.eval('"5" .|. 3')
        success, msg = result
        assert not success, "bitor with string should fail"
        assert 'E_TYPE' in msg or 'Type' in msg

    def test_bitand_type_error(self, client, requires_bitwise):
        """Bitwise AND with non-integer raises E_TYPE."""
        result = client.eval('5 .&. "3"')
        success, msg = result
        assert not success, "bitand with string should fail"

    def test_bitxor_type_error(self, client, requires_bitwise):
        """Bitwise XOR with non-integer raises E_TYPE."""
        result = client.eval('5 .^. 3.0')
        success, msg = result
        assert not success, "bitxor with float should fail"

    def test_bitnot_type_error(self, client, requires_bitwise):
        """Bitwise NOT with non-integer raises E_TYPE."""
        result = client.eval('~"hello"')
        success, msg = result
        assert not success, "bitnot with string should fail"

    def test_shl_type_error(self, client, requires_bitwise):
        """Left shift with non-integer raises E_TYPE."""
        result = client.eval('5 << 1.5')
        success, msg = result
        assert not success, "shl with float should fail"

    def test_shr_type_error(self, client, requires_bitwise):
        """Right shift with non-integer raises E_TYPE."""
        result = client.eval('"5" >> 1')
        success, msg = result
        assert not success, "shr with string should fail"
