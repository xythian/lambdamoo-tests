"""Test harness for building and testing MOO server versions.

This package provides utilities for:
- Building MOO server binaries from source or git refs
- Managing LambdaMOO source repositories
- Running the test suite against multiple server versions
- Generating test matrices for upgrade compatibility testing
- Configuration management for builds and tests
"""

from .build import build_server, build_from_source
from .repos import (
    get_or_clone_repo,
    clone_repo,
    update_repo,
    checkout_ref,
    list_known_repos,
    resolve_repo_url,
    KNOWN_REPOS,
)
from .config import get_config, load_config, Config
from .clean import clean_directory, list_cache_contents

__all__ = [
    # Build functions
    'build_server',
    'build_from_source',
    # Repository functions
    'get_or_clone_repo',
    'clone_repo',
    'update_repo',
    'checkout_ref',
    'list_known_repos',
    'resolve_repo_url',
    'KNOWN_REPOS',
    # Config functions
    'get_config',
    'load_config',
    'Config',
    # Clean functions
    'clean_directory',
    'list_cache_contents',
]
