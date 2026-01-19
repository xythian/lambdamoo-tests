"""Custom assertions for MOO testing."""

import re
from typing import Any, List, Set, Optional


def assert_moo_success(result: tuple, message: str = "") -> str:
    """
    Assert that a MOO evaluation was successful.

    Args:
        result: Tuple of (success, value_or_error) from MooClient.eval()
        message: Optional message to include on failure.

    Returns:
        The result value.

    Raises:
        AssertionError: If the evaluation failed.
    """
    success, value = result
    if not success:
        msg = f"MOO evaluation failed: {value}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)
    return value


def assert_moo_error(result: tuple, expected_error: Optional[str] = None, message: str = ""):
    """
    Assert that a MOO evaluation raised an error.

    Args:
        result: Tuple of (success, value_or_error) from MooClient.eval()
        expected_error: Expected error code (e.g., "E_TYPE", "E_PERM").
                       If None, any error is accepted.
        message: Optional message to include on failure.

    Raises:
        AssertionError: If the evaluation succeeded or wrong error was raised.
    """
    success, value = result
    if success:
        msg = f"Expected error but got success: {value}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)

    if expected_error and expected_error not in value:
        msg = f"Expected error {expected_error} but got: {value}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)


def assert_moo_value(actual: str, expected: str, message: str = ""):
    """
    Assert that a MOO value matches the expected value.

    Handles formatting differences in MOO output.

    Args:
        actual: The actual value from evaluation.
        expected: The expected value.
        message: Optional message to include on failure.

    Raises:
        AssertionError: If values don't match.
    """
    # Normalize whitespace
    actual_normalized = ' '.join(actual.split())
    expected_normalized = ' '.join(expected.split())

    if actual_normalized != expected_normalized:
        msg = f"Value mismatch:\n  Expected: {expected}\n  Actual: {actual}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)


def assert_moo_int(result: tuple, expected: int, message: str = ""):
    """
    Assert that a MOO evaluation returns a specific integer.

    Args:
        result: Tuple of (success, value) from MooClient.eval()
        expected: Expected integer value.
        message: Optional message on failure.
    """
    value = assert_moo_success(result, message)
    try:
        actual = int(value)
    except ValueError:
        raise AssertionError(f"Expected integer but got: {value}")

    if actual != expected:
        msg = f"Integer mismatch: expected {expected}, got {actual}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)


def assert_moo_float(result: tuple, expected: float, tolerance: float = 1e-9, message: str = ""):
    """
    Assert that a MOO evaluation returns a specific float.

    Args:
        result: Tuple of (success, value) from MooClient.eval()
        expected: Expected float value.
        tolerance: Acceptable difference.
        message: Optional message on failure.
    """
    value = assert_moo_success(result, message)
    try:
        actual = float(value)
    except ValueError:
        raise AssertionError(f"Expected float but got: {value}")

    if abs(actual - expected) > tolerance:
        msg = f"Float mismatch: expected {expected}, got {actual}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)


def assert_moo_string(result: tuple, expected: str, message: str = ""):
    """
    Assert that a MOO evaluation returns a specific string.

    Args:
        result: Tuple of (success, value) from MooClient.eval()
        expected: Expected string value (without quotes).
        message: Optional message on failure.
    """
    value = assert_moo_success(result, message)

    # MOO strings are returned with quotes
    expected_quoted = f'"{expected}"'
    if value != expected_quoted:
        msg = f"String mismatch: expected {expected_quoted}, got {value}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)


def assert_moo_list(result: tuple, expected_elements: List[Any], message: str = ""):
    """
    Assert that a MOO list contains expected elements (order-sensitive).

    Args:
        result: Tuple of (success, value) from MooClient.eval()
        expected_elements: List of expected elements as they would appear in MOO output.
        message: Optional message on failure.
    """
    value = assert_moo_success(result, message)

    # Parse the list - this is a simplified parser
    # Format: {elem1, elem2, ...}
    if not value.startswith('{') or not value.endswith('}'):
        raise AssertionError(f"Expected list but got: {value}")

    # Build expected list string
    expected_str = '{' + ', '.join(str(e) for e in expected_elements) + '}'

    # Normalize and compare
    actual_normalized = ' '.join(value.split())
    expected_normalized = ' '.join(expected_str.split())

    if actual_normalized != expected_normalized:
        msg = f"List mismatch:\n  Expected: {expected_str}\n  Actual: {value}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)


def assert_moo_list_contains(result: tuple, expected_element: str, message: str = ""):
    """
    Assert that a MOO list contains a specific element.

    Args:
        result: Tuple of (success, value) from MooClient.eval()
        expected_element: Element that should be in the list.
        message: Optional message on failure.
    """
    value = assert_moo_success(result, message)

    if expected_element not in value:
        msg = f"List {value} does not contain {expected_element}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)


def assert_moo_object(result: tuple, expected_objid: int, message: str = ""):
    """
    Assert that a MOO evaluation returns a specific object reference.

    Args:
        result: Tuple of (success, value) from MooClient.eval()
        expected_objid: Expected object ID (integer, e.g., 1 for #1).
        message: Optional message on failure.
    """
    value = assert_moo_success(result, message)

    expected_str = f"#{expected_objid}"
    if value != expected_str:
        msg = f"Object mismatch: expected {expected_str}, got {value}"
        if message:
            msg = f"{message}: {msg}"
        raise AssertionError(msg)


def assert_moo_type(result: tuple, expected_type: int, message: str = ""):
    """
    Assert that a value has a specific MOO type.

    Type constants:
        0 = INT
        1 = OBJ
        2 = STR
        3 = ERR
        4 = LIST
        5 = CLEAR (internal)
        9 = FLOAT

    Args:
        result: Tuple from eval('typeof(expr)')
        expected_type: Expected type constant.
        message: Optional message on failure.
    """
    assert_moo_int(result, expected_type, message or "Type mismatch")


# MOO type constants for convenience
TYPE_INT = 0
TYPE_OBJ = 1
TYPE_STR = 2
TYPE_ERR = 3
TYPE_LIST = 4
TYPE_FLOAT = 9
