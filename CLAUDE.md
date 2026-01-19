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

### Before Completing Any Task
Always run the test suite to verify changes work:

```bash
# Quick smoke test (if you have a cached build)
pytest -x -q

# Run full suite
pytest

# Run specific test file
pytest test_suites/builtins/test_capabilities.py -v
```

### If No MOO Binary Available
Build one first:
```bash
lmt build --repo lambdamoo --config waterpoint
```

### Test with Tracing (for debugging)
```bash
pytest --moo-trace -k test_name
pytest --moo-trace-on-failure
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
4. Add test ID prefix (e.g., "ARITH-042") for traceability

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

Use `lmt clean --list` to inspect, `lmt clean --all` to clear.
