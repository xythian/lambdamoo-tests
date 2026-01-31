"""Pytest configuration and fixtures for LambdaMOO test suite.

This module provides fixtures for testing MOO servers with support for:
- Persistence testing (write and read with same server)
- Upgrade testing (write with old server, read with new server)

Usage:
    # Persistence tests only (default)
    pytest --candidate=./moo

    # Include upgrade tests
    pytest --candidate=./moo --prior=waterpoint:../waterpoint/moo

    # Multiple prior versions
    pytest --candidate=./moo \
        --prior=waterpoint:../waterpoint/moo \
        --prior=toaststunt:../toaststunt/moo

Binary Resolution:
    The candidate binary is found in this order:
    1. --candidate CLI option
    2. MOO_BINARY environment variable
    3. Configuration file (moo_binary setting)
    4. Build cache (~/.cache/lambdamoo-tests/builds/)
    5. Local paths: ./moo, ./build/moo
"""

import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import Generator, Dict, List, Optional

import pytest

from lib.protocol import ServerConfig, ServerPair
from lib.moo_server import MooServer, MooClient
from harness.config import get_config


# ============================================================================
# Configuration
# ============================================================================

def pytest_addoption(parser):
    """Add custom command-line options."""
    parser.addoption(
        "--candidate",
        action="store",
        default=None,
        help="Path to the candidate MOO server binary to test"
    )
    parser.addoption(
        "--candidate-name",
        action="store",
        default="candidate",
        help="Name for the candidate server (default: candidate)"
    )
    parser.addoption(
        "--prior",
        action="append",
        default=[],
        help="Prior version in format 'name:path' (can be repeated)"
    )
    parser.addoption(
        "--keep-artifacts",
        action="store_true",
        default=False,
        help="Keep test artifacts (databases, logs) after test run"
    )
    parser.addoption(
        "--moo-trace",
        action="store_true",
        default=False,
        help="Enable network tracing (show all MOO protocol traffic)"
    )
    parser.addoption(
        "--moo-trace-on-failure",
        action="store_true",
        default=False,
        help="Show network transcript when a test fails"
    )
    parser.addoption(
        "--longrun",
        action="store_true",
        default=False,
        help="Include long-running tests (60+ seconds) that are skipped by default"
    )
    parser.addoption(
        "--candidate-features",
        action="store",
        default=None,
        help="Known features for candidate server (comma-separated: i64,unicode,xml,waifs,waif_dict)"
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "persistence: marks tests that test data persistence"
    )
    config.addinivalue_line(
        "markers", "upgrade: marks tests that test upgrade compatibility"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "unicode: marks tests that require Unicode support"
    )
    config.addinivalue_line(
        "markers", "waifs: marks tests that require Waif support"
    )
    config.addinivalue_line(
        "markers", "longrun: marks tests that take 60+ seconds (skipped unless --longrun)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip longrun tests unless --longrun is specified."""
    if config.getoption("--longrun"):
        # --longrun given: run all tests
        return

    skip_longrun = pytest.mark.skip(reason="longrun test: use --longrun to include")
    for item in items:
        if "longrun" in item.keywords:
            item.add_marker(skip_longrun)


# ============================================================================
# Server Binary Fixtures
# ============================================================================

def _find_default_binary(project_root: Path) -> Optional[Path]:
    """Find the default MOO binary using config system and common locations.

    Resolution order:
    1. MOO_BINARY environment variable
    2. Configuration file (moo_binary setting)
    3. Build cache
    4. Local paths relative to project_root
    """
    config = get_config()

    # Check environment variable
    if env_binary := os.environ.get("MOO_BINARY"):
        path = Path(env_binary).expanduser()
        if path.exists() and path.is_file():
            return path.resolve()

    # Check configured path
    if config.moo_binary and config.moo_binary.exists():
        return config.moo_binary.resolve()

    # Check build cache for any cached binaries
    if config.build_cache_dir.exists():
        for subdir in config.build_cache_dir.iterdir():
            if subdir.is_dir():
                binary = subdir / "moo"
                if binary.exists():
                    return binary.resolve()

    # Check local paths relative to project root
    candidates = [
        project_root / 'moo',
        project_root / 'build' / 'moo',
        project_root.parent / 'moo',
        project_root.parent / 'build' / 'moo',
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    return None


@pytest.fixture(scope='session')
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope='session')
def tests_dir() -> Path:
    """Return the tests directory."""
    return Path(__file__).parent


@pytest.fixture(scope='session')
def candidate_config(request, project_root) -> ServerConfig:
    """Get configuration for the candidate (new) server."""
    binary_path = request.config.getoption("--candidate")
    name = request.config.getoption("--candidate-name")
    features_opt = request.config.getoption("--candidate-features")

    if binary_path:
        binary_path = Path(binary_path).resolve()
    else:
        binary_path = _find_default_binary(project_root)

    if not binary_path or not binary_path.exists():
        pytest.skip(
            "Candidate binary not found. Options:\n"
            "  - Specify --candidate=<path>\n"
            "  - Set MOO_BINARY environment variable\n"
            "  - Build with: lmt build --repo lambdamoo\n"
            "  - Configure in ~/.config/lambdamoo-tests/config.toml"
        )

    # Parse known features if provided
    known_features = {}
    if features_opt:
        for feat in features_opt.split(','):
            feat = feat.strip()
            if feat:
                known_features[feat] = True

    return ServerConfig(
        binary=binary_path,
        name=name,
        version="unknown",  # Could query the binary
        features=known_features,
    )


@pytest.fixture(scope='session')
def prior_configs(request) -> Dict[str, ServerConfig]:
    """Get configurations for prior (old) server versions."""
    prior_args = request.config.getoption("--prior")
    configs = {}

    for prior_arg in prior_args:
        if ':' not in prior_arg:
            pytest.fail(f"Invalid --prior format: {prior_arg}. Use 'name:path'")

        name, path = prior_arg.split(':', 1)
        binary_path = Path(path).resolve()

        if not binary_path.exists():
            pytest.skip(f"Prior binary not found: {binary_path}")

        configs[name] = ServerConfig(
            binary=binary_path,
            name=name,
            version="unknown",
        )

    return configs


# ============================================================================
# Server Fixtures
# ============================================================================

@pytest.fixture(scope='session')
def candidate_server(candidate_config, request) -> Generator[MooServer, None, None]:
    """Provide a server manager for the candidate binary."""
    keep_artifacts = request.config.getoption("--keep-artifacts")
    trace = request.config.getoption("--moo-trace")
    work_dir = Path(tempfile.mkdtemp(prefix='moo_candidate_'))

    server = MooServer(candidate_config, work_dir, trace=trace)
    yield server
    server.stop_all()

    if not keep_artifacts:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.fixture(scope='session')
def prior_db_dirs(prior_configs, db_base_dir) -> Dict[str, Path]:
    """Return database directories for all prior servers."""
    dirs = {}
    for name in prior_configs:
        db_dir = _get_server_db_dir(db_base_dir, name)
        db_dir.mkdir(parents=True, exist_ok=True)
        dirs[name] = db_dir
    return dirs


@pytest.fixture(scope='session')
def prior_servers(prior_configs, request) -> Generator[Dict[str, MooServer], None, None]:
    """Provide server managers for all prior versions."""
    keep_artifacts = request.config.getoption("--keep-artifacts")
    trace = request.config.getoption("--moo-trace")
    servers = {}
    work_dirs = []

    for name, config in prior_configs.items():
        work_dir = Path(tempfile.mkdtemp(prefix=f'moo_{name}_'))
        work_dirs.append(work_dir)
        servers[name] = MooServer(config, work_dir, trace=trace)

    yield servers

    for server in servers.values():
        server.stop_all()

    if not keep_artifacts:
        for work_dir in work_dirs:
            shutil.rmtree(work_dir, ignore_errors=True)


# ============================================================================
# Server Pair Fixtures (for persistence/upgrade tests)
# ============================================================================

def _get_server_pair_params(prior_configs: Dict[str, ServerConfig]) -> List[str]:
    """Generate parameter IDs for server pairs."""
    params = ['persistence']
    for name in prior_configs:
        params.append(f'upgrade_from_{name}')
    return params


@pytest.fixture(scope='session')
def server_pair_ids(prior_configs) -> List[str]:
    """Get list of server pair test IDs."""
    return _get_server_pair_params(prior_configs)


@pytest.fixture
def server_pair(request, candidate_server, prior_servers, candidate_config, prior_configs,
                candidate_db_dir, prior_db_dirs) -> ServerPair:
    """Provide a (write_server, read_server) pair for testing.

    For persistence tests: write_server == read_server (candidate)
    For upgrade tests: write_server = prior, read_server = candidate

    Each pair includes the appropriate database directory for the write server.
    """
    param = request.param

    if param == 'persistence':
        return ServerPair(
            write_server=candidate_server,
            read_server=candidate_server,
            name='persistence',
            write_db_dir=candidate_db_dir,
        )
    elif param.startswith('upgrade_from_'):
        prior_name = param[len('upgrade_from_'):]
        if prior_name not in prior_servers:
            pytest.skip(f"Prior server '{prior_name}' not available")

        return ServerPair(
            write_server=prior_servers[prior_name],
            read_server=candidate_server,
            name=param,
            write_db_dir=prior_db_dirs.get(prior_name),
        )
    else:
        pytest.fail(f"Unknown server pair: {param}")


def pytest_generate_tests(metafunc):
    """Dynamically generate test parameters for server_pair fixture."""
    if 'server_pair' in metafunc.fixturenames:
        # Get prior configs from command line
        prior_args = metafunc.config.getoption("--prior") or []
        prior_names = []
        for prior_arg in prior_args:
            if ':' in prior_arg:
                name, _ = prior_arg.split(':', 1)
                prior_names.append(name)

        # Generate parameters
        params = ['persistence']
        for name in prior_names:
            params.append(f'upgrade_from_{name}')

        metafunc.parametrize('server_pair', params, indirect=True)


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture(scope='session')
def db_base_dir(request) -> Path:
    """Return base directory for server-scoped databases."""
    config = get_config()
    keep_artifacts = request.config.getoption("--keep-artifacts")

    # Use configured database_dir as base
    base_dir = config.database_dir
    base_dir.mkdir(parents=True, exist_ok=True)

    return base_dir


def _get_server_db_dir(db_base_dir: Path, server_name: str) -> Path:
    """Get database directory for a specific server."""
    return db_base_dir / server_name


@pytest.fixture(scope='session')
def candidate_db_dir(db_base_dir, candidate_config) -> Path:
    """Return database directory for candidate server."""
    db_dir = _get_server_db_dir(db_base_dir, candidate_config.name)
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir


@pytest.fixture(scope='session')
def minimal_db(candidate_db_dir, candidate_config) -> Path:
    """Return path to the test database for the candidate server.

    Auto-creates the database if it doesn't exist.
    """
    from lambdamoo_tests.setup import ensure_test_db, find_minimal_db

    db_path = ensure_test_db(candidate_config.binary, candidate_db_dir)
    if db_path and db_path.exists():
        return db_path

    # If auto-setup failed, check if Minimal.db is available for a better error
    minimal = find_minimal_db()
    if not minimal:
        pytest.skip(
            "Cannot create Test.db: Minimal.db not found.\n"
            "Options:\n"
            "  - Set MOO_MINIMAL_DB environment variable\n"
            "  - Clone a LambdaMOO repo (Minimal.db will be found in repo cache)"
        )
    else:
        pytest.skip(
            f"Failed to create Test.db for '{candidate_config.name}'.\n"
            "Check that the MOO binary works correctly."
        )


@pytest.fixture
def temp_db(minimal_db, tmp_path) -> Path:
    """Provide a temporary copy of the minimal database."""
    temp_db_path = tmp_path / 'test.db'
    shutil.copy(minimal_db, temp_db_path)
    return temp_db_path


@pytest.fixture(scope='session')
def multiplayer_db(candidate_db_dir, candidate_config) -> Optional[Path]:
    """Return path to multiplayer test database for the candidate server.

    Auto-creates the database if it doesn't exist.

    This database has:
    - #3 (Wizard)
    - #4 (Player2)
    - #5 (Player3)
    All players have programmer=1 and do_login_command supports name lookup.
    """
    from lambdamoo_tests.setup import ensure_multiplayer_db

    db_path = ensure_multiplayer_db(candidate_config.binary, candidate_db_dir)
    return db_path


@pytest.fixture
def write_server_db(server_pair) -> Path:
    """Return Test.db for the write_server in a server_pair.

    Auto-creates the database if it doesn't exist.
    """
    from lambdamoo_tests.setup import ensure_test_db, find_minimal_db

    if not server_pair.write_db_dir:
        pytest.skip("No database directory configured for write server")

    db_path = ensure_test_db(
        server_pair.write_server.config.binary,
        server_pair.write_db_dir
    )

    if db_path and db_path.exists():
        return db_path

    minimal = find_minimal_db()
    if not minimal:
        pytest.skip(
            "Cannot create Test.db: Minimal.db not found.\n"
            "Options:\n"
            "  - Set MOO_MINIMAL_DB environment variable\n"
            "  - Clone a LambdaMOO repo (Minimal.db will be found in repo cache)"
        )
    else:
        pytest.skip(
            f"Failed to create Test.db for write server.\n"
            "Check that the MOO binary works correctly."
        )


@pytest.fixture
def multiplayer_server(candidate_server, multiplayer_db) -> Generator:
    """Provide a running server with multiplayer database."""
    if not multiplayer_db:
        pytest.skip("Multiplayer.db not found - run setup_multiplayer_db.py")
    instance = candidate_server.start(database=multiplayer_db)
    yield instance
    candidate_server.stop(instance)


# ============================================================================
# Legacy Fixtures (for backward compatibility with existing tests)
# ============================================================================

@pytest.fixture(scope='session')
def moo_binary(candidate_config) -> Path:
    """Return path to the MOO binary (legacy compatibility)."""
    return candidate_config.binary


@pytest.fixture(scope='session')
def server_manager(candidate_server) -> MooServer:
    """Provide a server manager (legacy compatibility)."""
    return candidate_server


@pytest.fixture
def server(candidate_server, minimal_db) -> Generator:
    """Provide a running server instance (legacy compatibility)."""
    instance = candidate_server.start(database=minimal_db)
    yield instance
    candidate_server.stop(instance)


@pytest.fixture
def client(server, candidate_server, request) -> Generator[MooClient, None, None]:
    """Provide a connected client (legacy compatibility)."""
    trace = request.config.getoption("--moo-trace")
    client = candidate_server.connect(server, trace=trace)
    client.authenticate('Wizard')
    yield client
    client.close()


# ============================================================================
# Platform Detection
# ============================================================================

@pytest.fixture(scope='session')
def platform_config() -> dict:
    """Detect platform and return appropriate test configuration."""
    return {
        'system': platform.system(),
        'machine': platform.machine(),
        'word_size': 64 if platform.architecture()[0] == '64bit' else 32,
    }


# ============================================================================
# Feature Detection
# ============================================================================

from lib.features import ServerFeatures, detect_features


@pytest.fixture
def server_features(client) -> list:
    """Get the list of features enabled in the server."""
    success, result = client.eval('server_version("features")')
    if not success:
        return []

    features = []
    if result.startswith('{') and result.endswith('}'):
        content = result[1:-1]
        for item in content.split(','):
            item = item.strip().strip('"')
            if item:
                features.append(item)
    return features


@pytest.fixture
def detected_features(client, candidate_config) -> ServerFeatures:
    """Detect full server features using the features module.

    If candidate_config has known_features set (from --candidate-features),
    those override the detected values.
    """
    features = detect_features(client)

    # Apply known feature overrides from config
    known = candidate_config.features or {}
    if 'i64' in known:
        features.has_i64 = True
    if 'unicode' in known:
        features.has_unicode = True
    if 'xml' in known:
        features.has_xml = True
    if 'waifs' in known:
        features.has_waifs = True
    if 'waif_dict' in known:
        features.has_waif_dict = True
    if 'bitwise' in known:
        features.has_bitwise = True

    return features


@pytest.fixture
def requires_unicode(detected_features):
    """Skip if Unicode support is not enabled."""
    if not detected_features.has_unicode:
        pytest.skip("Test requires Unicode support")


@pytest.fixture
def requires_waifs(detected_features):
    """Skip if Waif support is not enabled."""
    if not detected_features.has_waifs:
        pytest.skip("Test requires Waif support")


@pytest.fixture
def requires_waif_dict(detected_features):
    """Skip if Waif dictionary syntax is not enabled."""
    if not detected_features.has_waif_dict:
        pytest.skip("Test requires Waif dictionary syntax")


@pytest.fixture
def requires_xml(detected_features):
    """Skip if XML support is not enabled."""
    if not detected_features.has_xml:
        pytest.skip("Test requires XML support")


@pytest.fixture
def requires_i64(detected_features):
    """Skip if 64-bit integers are not enabled."""
    if not detected_features.has_i64:
        pytest.skip("Test requires 64-bit integer support")


@pytest.fixture
def requires_no_i64(detected_features):
    """Skip if 64-bit integers ARE enabled (for testing 32-bit behavior)."""
    if detected_features.has_i64:
        pytest.skip("Test requires 32-bit integer server (no i64)")


@pytest.fixture
def requires_no_unicode(detected_features):
    """Skip if Unicode IS enabled (for testing non-Unicode behavior)."""
    if detected_features.has_unicode:
        pytest.skip("Test requires non-Unicode server")


@pytest.fixture
def requires_bitwise(detected_features):
    """Skip if bitwise operators are not enabled."""
    if not detected_features.has_bitwise:
        pytest.skip("Test requires BITWISE_OPERATORS support")


# ============================================================================
# Tracing and Debugging
# ============================================================================

@pytest.fixture
def traced_client(server, candidate_server) -> Generator[MooClient, None, None]:
    """Provide a connected client with tracing always enabled."""
    client = candidate_server.connect(server, trace=True)
    client.authenticate('Wizard')
    yield client
    client.close()


@pytest.fixture
def server_log(server) -> Generator[callable, None, None]:
    """Provide access to the server log contents.

    Usage:
        def test_something(server_log):
            # ... do things ...
            log = server_log()
            assert "some message" in log
    """
    def get_log():
        return server.get_log_contents()
    yield get_log


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to capture test results and display transcript on failure."""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        trace_on_failure = item.config.getoption("--moo-trace-on-failure", default=False)

        if trace_on_failure:
            # Try to get transcript from client fixture
            client = item.funcargs.get("client") or item.funcargs.get("traced_client")
            if client and hasattr(client, 'format_transcript'):
                transcript = client.format_transcript()
                if transcript:
                    report.longrepr = str(report.longrepr) + \
                        f"\n\n--- Network Transcript ---\n{transcript}\n"

            # Also try to get server log
            server_instance = item.funcargs.get("server")
            if server_instance and hasattr(server_instance, 'get_log_contents'):
                log = server_instance.get_log_contents()
                if log:
                    # Only show last 50 lines of log to avoid overwhelming output
                    log_lines = log.strip().split('\n')
                    if len(log_lines) > 50:
                        log = '\n'.join(['... (truncated) ...'] + log_lines[-50:])
                    report.longrepr = str(report.longrepr) + \
                        f"\n\n--- Server Log (last 50 lines) ---\n{log}\n"
