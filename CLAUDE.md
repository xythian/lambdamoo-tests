# Claude Guidelines for LambdaMOO Test Suite

## Getting Started

Read `README.md` first - it contains the project overview, architecture, and usage examples.

## Code Standards

### No Commented Code
Do not leave commented-out code in the codebase. Either:
- Delete code that's no longer needed
- Keep code that's still needed

No `# old implementation`, `# TODO: remove`, or vestigial commented blocks.

### No Redundant Comments
Avoid comments that merely restate what the code does:
```python
# Bad
i = i + 1  # increment i

# Good - explains why, not what
i = i + 1  # skip header row
```

### Docstrings
Use docstrings for modules, classes, and public functions. Include Args/Returns/Raises where helpful.

## Testing Workflow

### Running Commands
All commands should be run via `uv run` to use the project's virtual environment:

```bash
uv run lmt <command>    # Run lmt commands
uv run pytest <args>    # Run tests
```

### Before Completing Any Task
Always run the test suite to verify changes work:

```bash
# Quick smoke test (if you have a cached build)
uv run pytest -x -q

# Run full suite
uv run pytest

# Run specific test file
uv run pytest test_suites/builtins/test_capabilities.py -v
```

### If No MOO Binary Available
Build one first:
```bash
uv run lmt build --repo lambdamoo
```

### Building with Specific Features
```bash
# Build with waifs enabled
uv run lmt build --repo lambdamoo --config i64_waifs

# Build with bitwise operators
uv run lmt build --repo lambdamoo --config i64_bitwise

# See available configs
uv run lmt build --list-configs
```

### Test with Tracing (for debugging)
```bash
uv run pytest --moo-trace -k test_name
uv run pytest --moo-trace-on-failure
```

### Long-Running Tests
Tests that take 60+ seconds (e.g., waiting for automatic checkpoints) should be marked with `@pytest.mark.longrun`. These are skipped by default to keep the quick test cycle fast.

```bash
# Normal run - longrun tests are skipped
uv run pytest

# Include long-running tests
uv run pytest --longrun
```

Use the `longrun` marker when:
- Testing automatic scheduled behavior (dump_interval minimum is 60 seconds)
- Testing timeouts or delays that can't be shortened
- Any test that needs to wait for real time to pass

```python
@pytest.mark.longrun
def test_automatic_checkpoint_fires(self, ...):
    """This test waits 65 seconds for automatic checkpoint."""
    ...
```

## Project Structure

- `lib/` - Core library (MooServer, MooClient, assertions, feature detection)
- `harness/` - Build system and configuration
- `lambdamoo_tests/` - CLI tool (`lmt` command)
- `test_suites/` - Actual test files organized by category
- `conftest.py` - Pytest fixtures

## Key Patterns

### Adding New Tests
1. Put tests in appropriate `test_suites/` subdirectory
2. Use existing fixtures (`client`, `server`, `requires_unicode`, etc.)
3. Use assertion helpers from `lib.assertions`
4. Write clear docstrings describing what the test validates

### Validating New Tests
When writing new tests, explicitly verify they test what they claim to test:

1. **Explain the test logic** - Before writing, articulate why the test structure will prove the behavior. What would a false positive look like? What would a false negative look like?

2. **Beware of shutdown side effects** - The server checkpoints on SIGTERM shutdown. If testing that something "triggered a checkpoint", verify it happened DURING runtime (e.g., check file mtime or log messages before stopping the server), not just that data persisted after shutdown.

3. **Check server source when uncertain** - The LambdaMOO source is cached in `~/.cache/lambdamoo-tests/repos/`. When behavior is unclear, read the C source to understand actual semantics (e.g., `dump_interval` has a 60-second minimum - values below are ignored).

4. **Test the negative case** - If testing "X causes Y", also verify "not X causes not Y" where feasible. This catches tests that always pass regardless of the condition.

5. **Verify assertions actually fail** - Temporarily break the code or use wrong expected values to confirm the test would catch real failures.

Example of a subtle bug: A test that sets `dump_interval=3`, waits 5 seconds, stops the server, and checks data persisted will ALWAYS pass - because the server checkpoints on shutdown, not because automatic checkpointing worked.

### No Workarounds for Broken Behavior
Never adjust tests to skip or work around apparently broken server behavior. When a test fails:

1. **Investigate first** - The test itself may be wrong or not match expected semantics
2. **If the test is correct** - Let it fail; that documents the bug in the server
3. **If the test is wrong** - Fix the test to match correct expected behavior

Do NOT:
- Add `pytest.skip()` to avoid failing tests
- Change assertions to accept broken output
- Add conditionals to work around server bugs

The purpose of the test suite is to validate server behavior. Workarounds defeat this purpose and hide bugs. A failing test is valuable - it documents what needs to be fixed.

### Feature-Dependent Tests
```python
def test_unicode_feature(self, client, requires_unicode):
    """Test only runs on Unicode-enabled servers."""
    ...

def test_32bit_overflow(self, client, requires_no_i64):
    """Test only runs on 32-bit integer servers."""
    ...
```

### Capability Tests
When testing features that vary by server configuration, include both:
- Positive tests (feature works when enabled)
- Negative tests (feature behaves differently when disabled)

## Cache Locations

All caches go to `~/.cache/lambdamoo-tests/`:
- `repos/` - Cloned git repositories
- `builds/` - Compiled binaries (keyed by commit+flags)
- `databases/` - Auto-generated test databases

Use `uv run lmt clean --list` to inspect, `uv run lmt clean --all` to clear.
