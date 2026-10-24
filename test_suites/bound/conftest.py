"""Fixtures for bound value tests."""

import itertools

import pytest

from lib.moocode import define_verb


_verb_names = itertools.count(1)


@pytest.fixture
def run(client, requires_bound):
    """Run MOO statements as a verb on #0 and return the eval result.

    Bound values can't be written as literals, so most tests need several
    statements; running them as a verb (rather than nested eval()) lets
    errors propagate with their usual codes.

    Returns:
        A function taking a list of source lines and returning the
        (success, value) tuple from calling the verb.
    """
    def _run(lines):
        name = f"bound_test_{next(_verb_names)}"
        define_verb(client, "#0", name, lines)
        return client.eval(f"#0:{name}()")
    return _run


@pytest.fixture
def requires_bound_type(client, requires_bound):
    """Return a function that skips the test unless a bound subtype is registered.

    --enable-bound=core builds have no providers and =stream builds have
    no struct.cursor, so each test names the subtypes it needs.
    """
    def _require(*names):
        for name in names:
            ok, value = client.eval(f'`bound_type("{name}") ! ANY\'')
            if not ok or value == "E_INVARG":
                pytest.skip(f'Test requires the "{name}" bound type')
    return _require
