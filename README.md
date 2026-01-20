# LambdaMOO Test Suite

A standalone integration test suite for validating LambdaMOO server behavior,
database persistence, and upgrade compatibility across different server versions.

## Overview

This test suite operates at the network and database level rather than unit testing
individual C functions. Tests validate observable server behavior through the MOO
protocol, ensuring correctness of:

- Network connections and protocol handling
- Database persistence and object storage
- Task suspension and resumption through restart
- Builtin function behavior
- Database upgrade compatibility between versions

### Key Features

- **Standalone Operation**: Works independently of any LambdaMOO source tree
- **Multi-Version Testing**: Build and test multiple server versions for upgrade scenarios
- **Remote Repository Support**: Clone and build from GitHub repositories automatically
- **Build Caching**: Cached builds by commit hash and configure flags
- **Configuration System**: TOML-based configuration with environment variable overrides

## Requirements

- Python 3.8+
- Git (for cloning repositories)
- Build tools: autoconf, make, gcc (for building from source)
- [uv](https://docs.astral.sh/uv/) for Python package management (recommended)

## Installation

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the test suite
git clone https://github.com/xythian/lambdamoo-tests
cd lambdamoo-tests

# Install dependencies
uv sync
```

## Quick Start

### Simplest: Build and Test Automatically

```bash
# Build and test LambdaMOO with default config
lmt test --build lambdamoo

# Build with full feature set (i64, unicode, xml, waifs)
lmt test --build lambdamoo:full
```

Test databases are created automatically per-server when needed. Minimal.db is found
from the cloned repository cache.

### With Explicit Binary

```bash
# Test an existing binary
lmt test --candidate /path/to/moo

# Or build first, then test
lmt build --repo lambdamoo --config full --output ./builds/
lmt test --candidate ./builds/moo
```

### Manual Setup (Optional)

```bash
# Manually set up test databases if auto-setup doesn't work
lmt setup --moo-binary /path/to/moo --minimal-db /path/to/Minimal.db
```

## CLI Commands

The test suite provides a unified `lmt` command with subcommands:

```bash
lmt build    # Build MOO server from source or repository
lmt setup    # Set up test databases
lmt clean    # Clean cached repositories and builds
lmt test     # Run the test suite
```

**Global options:**

```bash
# Use a project-local cache directory instead of ~/.cache/lambdamoo-tests
lmt --cache-dir ./.lmt build --repo lambdamoo --config full
lmt -C ./.lmt test --build lambdamoo:full
```

### lmt build

Build MOO server binaries from source or remote repositories.

```bash
# Build from known repository with default config
lmt build --repo lambdamoo --output ./builds/

# Build with full feature set
lmt build --repo lambdamoo --config full --output ./builds/

# Build specific version/branch with specific config
lmt build --repo lambdamoo --ref v1.8.1 --config i64_unicode

# Build from wp-lambdamoo (uses custom build script)
lmt build --repo wp-lambdamoo --output ./builds/wp/

# Build from any git URL
lmt build --repo https://github.com/user/fork --ref feature-branch

# Build with explicit configure flags (overrides --config)
lmt build --repo lambdamoo --configure-flags="--enable-waifs --enable-sz=i64"

# Build from local source
lmt build --source /path/to/lambdamoo --output ./builds/local/

# List known repositories
lmt build --list-repos

# List available build configurations
lmt build --list-configs
```

**Known Repositories:**
- `lambdamoo` - https://github.com/wrog/lambdamoo (multiple build configs available)
- `wp-lambdamoo` - https://github.com/xythian/wp-lambdamoo (uses custom build script)

**Build Configurations:**

The main lambdamoo repo supports multiple build configurations via `./configure` flags.
Use `--config <name>` to select a predefined configuration:

| Config | Description | Configure Flags |
|--------|-------------|-----------------|
| `default` | Default build | (none) |
| `i32` | Explicit 32-bit integers | `--enable-sz=i32` |
| `i64` | 64-bit integers | `--enable-sz=i64` |
| `i64_unicode` | 64-bit + Unicode | `--enable-sz=i64 --enable-unicode` |
| `i64_xml` | 64-bit + XML | `--enable-sz=i64 --enable-xml` |
| `i64_waifs` | 64-bit + Waifs | `--enable-sz=i64 --enable-waifs=dict` |
| `i64_unicode_waifs` | 64-bit + Unicode + Waifs | `--enable-sz=i64 --enable-unicode --enable-waifs=dict` |
| `waterpoint` | Full feature set | `--enable-sz=i64 --enable-unicode --enable-xml --enable-waifs=dict` |
| `full` | Alias for waterpoint | (same as waterpoint) |

The `wp-lambdamoo` repository uses a custom `build.sh` script and has a single integrated
configuration equivalent to `full`. The `--config` flag is not needed for wp-lambdamoo.

### lmt setup

Set up test databases for the test suite.

```bash
# Auto-detect paths
lmt setup

# Specify paths explicitly
lmt setup --moo-binary ./builds/moo --minimal-db ./Minimal.db

# Build MOO if not found
lmt setup --build-if-missing --repo lambdamoo

# Create only specific database
lmt setup --only test        # Test.db only
lmt setup --only multiplayer # Multiplayer.db only

# Check prerequisites without creating databases
lmt setup --check-only
```

### lmt clean

Manage and clean up cached repositories and builds.

```bash
# Show what's in the caches
lmt clean --list

# Clean everything (with confirmation prompt)
lmt clean --all

# Clean only build cache
lmt clean --builds

# Clean only repository cache
lmt clean --repos

# Dry run - show what would be deleted
lmt clean --all --dry-run

# Force clean without confirmation
lmt clean --all --force
```

### lmt test

Run the test suite.

```bash
# Run with explicit binary path
lmt test --candidate ./builds/moo

# Build/find candidate from repo+config (uses cache if available)
lmt test --build lambdamoo
lmt test --build lambdamoo:full
lmt test --build lambdamoo:v1.8.1:i64_unicode

# Upgrade testing with explicit binaries
lmt test --candidate ./new-moo --prior old:./old-moo

# Upgrade testing with builds (e.g., test lambdamoo against prior wp-lambdamoo)
lmt test --build lambdamoo:full --prior-build wp=wp-lambdamoo

# Mix explicit binary and built priors
lmt test --candidate ./moo --prior-build old=lambdamoo:v1.8.0:i64

# Run specific tests by keyword
lmt test -k test_connection

# Run tests by marker
lmt test -m persistence

# Keep test artifacts for debugging
lmt test --keep-artifacts

# Pass additional pytest arguments
lmt test -- -v --tb=long
```

**Build spec format** (same for `--build` and after `=` in `--prior-build`):
- `repo` - Use repo's default config (name derived from repo)
- `repo:config` - Repo with build config (name derived)
- `repo:ref:config` - Repo with specific git ref and config
- `name=repo` - Explicit name with repo
- `name=repo:config` - Explicit name with config
- `name=repo:ref:config` - Explicit name with all components

**Examples:**
- `--build lambdamoo` - Default config, name defaults to "lambdamoo"
- `--build lambdamoo:full` - Full config, name defaults to "lambdamoo_full"
- `--build main=lambdamoo:full` - Explicit name "main"
- `--prior-build wp=wp-lambdamoo` - Prior named "wp" using wp-lambdamoo

## Upgrade Testing

Test database compatibility when upgrading between server versions:

```bash
# Test against a prior version
lmt test --build lambdamoo:full --prior-build old=lambdamoo:v1.8.0:i64

# Multiple prior versions
lmt test --build lambdamoo:full \
         --prior-build v1.8=lambdamoo:v1.8.0:i64 \
         --prior-build v1.7=lambdamoo:v1.7.0:i64

# Example: test lambdamoo against wp-lambdamoo (Waterpoint fork)
lmt test --build lambdamoo:full --prior-build wp=wp-lambdamoo

# Or manually build and use explicit paths
lmt build --repo lambdamoo --config full --output ./builds/main/
lmt build --repo lambdamoo --ref v1.8.0 --config i64 --output ./builds/old/

lmt test --candidate ./builds/main/moo \
         --prior old:./builds/old/moo
```

## Configuration

Configuration can be set via:
1. Environment variables (highest precedence)
2. Project config file: `.moo-tests.toml`
3. User config file: `~/.config/lambdamoo-tests/config.toml`

### Environment Variables

```bash
export MOO_BINARY=/path/to/moo
export MOO_MINIMAL_DB=/path/to/Minimal.db
export MOO_DATABASE_DIR=./databases
export MOO_REPO_CACHE_DIR=~/.cache/lambdamoo-tests/repos
export MOO_BUILD_CACHE_DIR=~/.cache/lambdamoo-tests/builds
export MOO_CONFIGURE_FLAGS="--enable-waifs"
export MOO_MAKE_JOBS=8
```

### Configuration File

Create `~/.config/lambdamoo-tests/config.toml` or `.moo-tests.toml`:

```toml
[paths]
repo_cache_dir = "~/.cache/lambdamoo-tests/repos"
build_cache_dir = "~/.cache/lambdamoo-tests/builds"
database_dir = "./databases"
minimal_db = "/path/to/Minimal.db"
moo_binary = "/path/to/moo"

[build]
configure_flags = ""
make_jobs = 4

[repos.lambdamoo]
url = "https://github.com/wrog/lambdamoo"
default_branch = "main"

[repos.wp-lambdamoo]
url = "https://github.com/xythian/wp-lambdamoo"
default_branch = "main"
build_script = "build.sh"  # Use custom build script instead of configure/make

# Add custom repos
[repos.my-fork]
url = "https://github.com/myuser/lambdamoo"
default_branch = "my-feature"
default_build_config = "i64_unicode"

# Add custom build configurations
[build_configs.my_custom]
configure_flags = ["--enable-sz=i64", "--enable-unicode", "--my-flag"]
description = "My custom build"
```

## Test Structure

```
lambdamoo-tests/
├── conftest.py              # Pytest configuration and fixtures
├── pyproject.toml           # Project metadata and dependencies
├── README.md                # This file
├── harness/                 # Build and test harness
│   ├── build.py            # Server build system
│   ├── repos.py            # Repository management
│   ├── config.py           # Configuration handling
│   └── clean.py            # Cache cleanup
├── lambdamoo_tests/         # CLI and tools
│   ├── cli.py              # Main lmt command
│   └── setup.py            # Database setup
├── lib/                     # Test support library
│   ├── protocol.py         # Protocol abstractions
│   ├── moo_server.py       # MOO server management
│   ├── client.py           # MOO network client
│   ├── assertions.py       # Custom assertions
│   └── features.py         # Feature detection
└── test_suites/
    ├── network/            # Network layer tests
    ├── database/           # Database persistence tests
    ├── builtins/           # Builtin function tests
    ├── persistence/        # Data persistence tests
    └── upgrade/            # Upgrade compatibility tests
```

## Test Categories

### Network Tests (`test_suites/network/`)
Validate TCP connection handling, line buffering, multiple connections,
and output ordering.

### Database Tests (`test_suites/database/`)
Validate object creation, destruction, hierarchy, properties, and verbs.

### Persistence Tests (`test_suites/persistence/`)
Validate that data survives write, checkpoint, and read cycles. Includes
tests for data types, verbs, and suspended/forked tasks.

### Builtin Tests (`test_suites/builtins/`)
Validate arithmetic operations, string functions, list operations, and
capability-dependent behavior.

### Upgrade Tests (`test_suites/upgrade/`)
Validate database compatibility when upgrading from older versions.

## Writing Tests

### Basic Test Pattern

```python
from lib.assertions import assert_moo_success, assert_moo_int

class TestMyFeature:
    def test_basic_operation(self, client):
        """Description of what this test validates."""
        result = client.eval('1 + 1')
        assert_moo_int(result, 2)
```

### Capability Tests (Positive and Negative)

To build confidence that tests are actually testing what they claim, write both positive
and negative tests that verify behavior varies correctly by server configuration:

```python
class TestIntegerCapabilities:
    def test_large_int_works_on_i64(self, client, requires_i64):
        """On i64 servers, large integers work correctly."""
        result = client.eval('9223372036854775807')
        value = assert_moo_success(result)
        assert value == '9223372036854775807'

    def test_large_int_fails_on_i32(self, client, requires_no_i64):
        """On i32 servers, large integers overflow or error."""
        result = client.eval('2147483647 + 1')
        success, value = result
        if success:
            # Should have wrapped, not equal 2147483648
            assert int(value) != 2147483648
```

Available capability fixtures:
- `requires_i64` / `requires_no_i64` - 64-bit integer support
- `requires_unicode` / `requires_no_unicode` - Unicode string support
- `requires_waifs` / `requires_waif_dict` - Waif object support
- `requires_xml` - XML parsing support

The `detected_features` fixture provides direct access to the `ServerFeatures` object
for more complex capability checks.

### Persistence Test Pattern

```python
def test_data_survives_restart(self, server_pair, minimal_db, tmp_path):
    """Data persists through checkpoint and restart."""
    import shutil
    db_path = tmp_path / "test.db"
    shutil.copy(minimal_db, db_path)

    # Write phase
    instance1 = server_pair.write_server.start(database=db_path)
    client1 = server_pair.write_server.connect(instance1)
    client1.authenticate('Wizard')
    client1.eval('add_property(#0, "test_value", 42, {#1, "rw"})')
    client1.checkpoint()
    client1.close()
    output_db = server_pair.write_server.stop(instance1)

    # Read phase
    instance2 = server_pair.read_server.start(database=output_db)
    client2 = server_pair.read_server.connect(instance2)
    client2.authenticate('Wizard')
    result = client2.eval('#0.test_value')
    assert result == (True, '42')
    client2.close()
    server_pair.read_server.stop(instance2)
```

## Markers

- `@pytest.mark.slow` - Long-running tests
- `@pytest.mark.unicode` - Requires Unicode support
- `@pytest.mark.waifs` - Requires WAIF support
- `@pytest.mark.xml` - Requires XML support
- `@pytest.mark.upgrade` - Database upgrade tests
- `@pytest.mark.persistence` - Data persistence tests
- `@pytest.mark.task_persistence` - Task persistence tests

## Build Caching

Builds are cached by commit hash and configure flags at:
`~/.cache/lambdamoo-tests/builds/<hash>/`

Each cached build includes:
- `moo` - The built binary
- `build-info.txt` - Build metadata (repo, commit, flags)

To disable caching: `lmt build --no-cache ...`

To clean caches: `lmt clean --all`

## Debugging Tests

### Network Tracing

To see all MOO protocol traffic during test execution:

```bash
# Show all network traffic in real-time
lmt test --build lambdamoo -- --moo-trace

# Show transcript only when tests fail
lmt test --build lambdamoo -- --moo-trace-on-failure
```

The `--moo-trace` option prints all send/receive operations with timestamps:
```
[14:32:05] >>> connect Wizard\n
[14:32:05] <<< *** Connected ***\n
[14:32:05] >>> ;1 + 1\n
[14:32:05] <<< #-1:  => 2\n
```

### Server Logs

Server logs are written to `server.log` in each instance's working directory. When using
`--keep-artifacts`, you can find logs in the temp directories printed at test completion.

To access server logs in a test:

```python
def test_something(server_log):
    # ... do things that might log ...
    log = server_log()
    assert "expected message" in log
```

### Using a Traced Client

For tests that need tracing regardless of command-line options:

```python
def test_with_trace(traced_client):
    """This test always shows network traffic."""
    result = traced_client.eval('1 + 1')
    # Trace output goes to stderr
```

### Keeping Test Artifacts

```bash
# Keep databases, logs, and temp files after test run
lmt test --build lambdamoo --keep-artifacts

# Artifacts are in temp directories like /tmp/moo_candidate_xxxxx/
```

## Troubleshooting

### "Candidate binary not found"

Options:
- Specify explicitly: `lmt test --candidate /path/to/moo`
- Set environment: `export MOO_BINARY=/path/to/moo`
- Build from source: `lmt build --repo lambdamoo`
- Configure in config file

### "Minimal.db not found"

Minimal.db is automatically found from the repository cache after building. If you haven't
built yet, run: `lmt build --repo lambdamoo`

For manual override: `export MOO_MINIMAL_DB=/path/to/Minimal.db`

### Build failures

- Ensure build dependencies are installed: `autoconf`, `make`, `gcc`
- Check configure output for missing dependencies
- Try building manually in the cached repo directory

### View cache contents

```bash
lmt clean --list
```

## Resources

- [LambdaMOO Home](https://wrog.net/moo/) - Main LambdaMOO site with downloads and documentation
- [LambdaMOO Programmer's Manual](https://wrog.net/moo/progman.html) - Complete reference for MOO programming

## License

Apache License 2.0 - see LICENSE file for details.

## Contributing

Contributions welcome! Please ensure tests pass before submitting PRs.
