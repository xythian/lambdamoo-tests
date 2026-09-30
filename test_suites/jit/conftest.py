"""Fixtures for JIT tests."""

import pytest

from lib.jit import JitHarness


@pytest.fixture
def jit(client, server, requires_jit) -> JitHarness:
    """A JitHarness on a fresh JIT-enabled server."""
    return JitHarness(client, log_file=server.log_file)
