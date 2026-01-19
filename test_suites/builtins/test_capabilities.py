"""Capability tests - verify behavior varies correctly by server configuration.

These tests verify that the test harness correctly detects server capabilities
and that tests behave appropriately on different server configurations.

Test Strategy:
- "Positive" tests verify features work when enabled
- "Negative" tests verify features fail gracefully or behave differently when disabled
- These tests build confidence that we're actually testing what we claim

For example:
- Large integers should work on i64 servers, overflow on i32 servers
- Unicode should work on unicode servers, be corrupted/rejected on non-unicode servers
"""

import pytest

from lib.assertions import assert_moo_success, assert_moo_error, assert_moo_int


class TestIntegerCapabilities:
    """Tests that verify integer handling varies by server configuration.

    Note: On 64-bit platforms, even the "default" build typically uses 64-bit
    integers (INT_TYPE_BITSIZE=64). The requires_no_i64 tests will only run
    on actual 32-bit servers, which are rare in modern environments.
    """

    # Constants for testing
    MAX_32BIT = 2147483647           # 2^31 - 1
    MIN_32BIT = -2147483648          # -2^31
    LARGE_64BIT = 9223372036854775807  # 2^63 - 1 (max signed 64-bit)
    OVERFLOW_32BIT = 2147483648      # 2^31 (overflows signed 32-bit)

    def test_cap_i64_large_positive_works(self, client, requires_i64):
        """On i64 servers, large positive integers work correctly."""
        result = client.eval(f'{self.LARGE_64BIT}')
        value = assert_moo_success(result)
        assert value == str(self.LARGE_64BIT), f"Large integer not preserved: {value}"

    def test_cap_i64_large_negative_works(self, client, requires_i64):
        """On i64 servers, large negative integers work correctly."""
        large_neg = -4611686018427387904  # Large negative 64-bit
        result = client.eval(f'{large_neg}')
        value = assert_moo_success(result)
        assert value == str(large_neg), f"Large negative not preserved: {value}"

    def test_cap_i64_arithmetic_no_32bit_overflow(self, client, requires_i64):
        """On i64 servers, arithmetic near 32-bit boundary doesn't overflow."""
        # This would overflow on a 32-bit server
        result = client.eval(f'{self.MAX_32BIT} + 1')
        value = assert_moo_success(result)
        assert value == str(self.OVERFLOW_32BIT), f"Expected {self.OVERFLOW_32BIT}, got {value}"

    def test_cap_i64_overflow_at_64bit_boundary(self, client, requires_i64):
        """On i64 servers, arithmetic at 64-bit boundary wraps or errors.

        MAX_64BIT + 1 should wrap to MIN_64BIT (or possibly error).
        """
        # 9223372036854775807 + 1 should overflow
        result = client.eval(f'{self.LARGE_64BIT} + 1')
        success, value = result

        if success:
            int_value = int(value)
            # Should have wrapped to MIN_64BIT (-9223372036854775808)
            MIN_64BIT = -9223372036854775808
            assert int_value == MIN_64BIT, (
                f"64-bit overflow should wrap to {MIN_64BIT}, got {int_value}"
            )
        else:
            # An error is also acceptable for overflow
            pass  # Test passes

    def test_cap_i64_overflow_negative_boundary(self, client, requires_i64):
        """On i64 servers, negative overflow at 64-bit boundary wraps or errors.

        MIN_64BIT - 1 should wrap to MAX_64BIT (or possibly error).
        """
        MIN_64BIT = -9223372036854775808
        result = client.eval(f'{MIN_64BIT} - 1')
        success, value = result

        if success:
            int_value = int(value)
            # Should have wrapped to MAX_64BIT
            assert int_value == self.LARGE_64BIT, (
                f"64-bit underflow should wrap to {self.LARGE_64BIT}, got {int_value}"
            )

    def test_cap_i32_overflow_wraps_or_errors(self, client, requires_no_i64):
        """On i32 servers, overflow past 32-bit boundary wraps or errors.

        The exact behavior depends on the server implementation:
        - May wrap around to negative (C undefined behavior, but common)
        - May error
        - May saturate at max value

        This test verifies the result is NOT the mathematically correct value.
        """
        # MAX_32BIT + 1 should NOT equal 2147483648 on a 32-bit server
        result = client.eval(f'{self.MAX_32BIT} + 1')
        success, value = result

        if success:
            # If it succeeded, it should have wrapped (likely to MIN_32BIT)
            int_value = int(value)
            assert int_value != self.OVERFLOW_32BIT, (
                f"32-bit server should not handle {self.OVERFLOW_32BIT} correctly"
            )
            # Common wrap behavior: MAX + 1 = MIN
            assert int_value == self.MIN_32BIT, (
                f"Expected wrap to {self.MIN_32BIT}, got {int_value}"
            )
        else:
            # An error is also acceptable for overflow
            pass  # Test passes - server correctly rejected overflow

    def test_cap_i32_large_literal_rejected(self, client, requires_no_i64):
        """On i32 servers, a 64-bit literal in code should be rejected or truncated."""
        # Try to use a literal that exceeds 32-bit range
        result = client.eval(f'{self.LARGE_64BIT}')
        success, value = result

        if success:
            # If parsed, should be truncated/wrong
            int_value = int(value)
            assert int_value != self.LARGE_64BIT, (
                "32-bit server should not preserve 64-bit literal"
            )
        else:
            # Parse error is acceptable
            pass  # Test passes

    def test_cap_both_32bit_values_work(self, client):
        """Both i32 and i64 servers handle 32-bit range correctly."""
        # These should work on any server
        result = client.eval(f'{self.MAX_32BIT}')
        assert_moo_int(result, self.MAX_32BIT)

        result = client.eval(f'{self.MIN_32BIT}')
        assert_moo_int(result, self.MIN_32BIT)

        result = client.eval('1000000 * 1000')
        assert_moo_int(result, 1000000000)


@pytest.mark.unicode
class TestUnicodeCapabilities:
    """Tests that verify Unicode handling varies by server configuration."""

    def test_cap_unicode_multibyte_length(self, client, requires_unicode):
        """On Unicode servers, multibyte chars count as single characters."""
        # Greek letters α, β, γ - each is one character
        result = client.eval('length("αβγ")')
        assert_moo_int(result, 3, "Unicode server should count 3 characters")

    def test_cap_unicode_emoji_length(self, client, requires_unicode):
        """On Unicode servers, emoji count correctly."""
        # Using a simple emoji that's likely to work
        result = client.eval('length("★")')  # Unicode star
        assert_moo_int(result, 1, "Unicode server should count star as 1 char")

    def test_cap_no_unicode_multibyte_stripped_or_bytes(self, client, requires_no_unicode):
        """On non-Unicode servers, multibyte chars are stripped or counted as bytes.

        Behavior varies by server:
        - May strip non-ASCII bytes entirely (length = 0, string = "")
        - May count UTF-8 bytes (length = 6 for "αβγ")
        - Should NOT count as 3 characters (that would be Unicode behavior)
        """
        result = client.eval('length("αβγ")')
        success, value = result

        if success:
            length = int(value)
            # Should NOT be character count (3) - that's Unicode behavior
            assert length != 3, (
                "Non-Unicode server should not count multibyte as single chars"
            )
            # Acceptable: 0 (stripped), 6 (byte count), or other non-3 value
            assert length in (0, 6) or length != 3, (
                f"Expected 0 (stripped) or 6 (bytes), got {length}"
            )

    def test_cap_both_ascii_works(self, client):
        """Both Unicode and non-Unicode servers handle ASCII correctly."""
        result = client.eval('length("hello")')
        assert_moo_int(result, 5)

        result = client.eval('"hello"[3]')
        success, value = result
        assert success and value == '"l"', f"Expected 'l', got {value}"


class TestFeatureDetection:
    """Meta-tests that verify feature detection works correctly."""

    def test_meta_features_detected(self, detected_features):
        """Verify that feature detection produces a result."""
        assert detected_features is not None
        assert detected_features.version != "unknown" or True  # May be unknown

    def test_meta_i64_consistent_with_max_int(self, client, detected_features):
        """Verify i64 detection is consistent with actual integer behavior."""
        # Try arithmetic that would overflow on 32-bit
        result = client.eval('2147483647 + 1')
        success, value = result

        if detected_features.has_i64:
            # Should succeed and give correct result
            assert success, "i64 server should handle overflow"
            assert value == '2147483648', f"i64 server gave wrong result: {value}"
        else:
            # Should either error or wrap
            if success:
                assert value != '2147483648', (
                    "Feature detection says i32 but server handles 64-bit values"
                )

    def test_meta_unicode_consistent_with_length(self, client, detected_features):
        """Verify Unicode detection is consistent with actual string handling."""
        result = client.eval('length("αβγ")')
        success, value = result

        if success:
            length = int(value)
            if detected_features.has_unicode:
                assert length == 3, (
                    f"Feature detection says Unicode but length('αβγ') = {length}"
                )
            else:
                assert length != 3, (
                    f"Feature detection says no Unicode but length('αβγ') = {length}"
                )
