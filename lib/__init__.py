"""LambdaMOO Test Suite Library.

This module provides:
- MooServer: Server lifecycle management (start/stop/connect)
- MooClient: Network client for MOO protocol (from moo_server, used with MooServer)
- StandaloneMooClient: Auto-connecting client for direct use (from client module)
- Assertions: Test assertion helpers
"""

from .moo_server import MooServer, MooServerInstance, MooClient
from .client import MooClient as StandaloneMooClient
from .assertions import (
    assert_moo_value,
    assert_moo_error,
    assert_moo_list,
    assert_moo_success,
)

__all__ = [
    'MooServer',
    'MooServerInstance',
    'MooClient',
    'StandaloneMooClient',
    'assert_moo_value',
    'assert_moo_error',
    'assert_moo_list',
    'assert_moo_success',
]
