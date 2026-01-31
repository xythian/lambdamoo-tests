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
5. See `AGENTS.md` for test validation guidelines

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

## Design Proposals

Design proposals and specifications live in `docs/rfcs/`. These documents describe formats, protocols, and architectural decisions that may be implemented in the future. RFCs go through draft, review, and accepted stages before implementation.
