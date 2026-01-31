# Guidelines for Coding Agents

These guidelines apply to all coding agents working on this codebase.

## Long-Running Tests

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

## Validating New Tests

When writing new tests, explicitly verify they test what they claim to test:

1. **Explain the test logic** - Before writing, articulate why the test structure will prove the behavior. What would a false positive look like? What would a false negative look like?

2. **Beware of shutdown side effects** - The server checkpoints on SIGTERM shutdown. If testing that something "triggered a checkpoint", verify it happened DURING runtime (e.g., check file mtime or log messages before stopping the server), not just that data persisted after shutdown.

3. **Check server source when uncertain** - The LambdaMOO source is cached in `~/.cache/lambdamoo-tests/repos/`. When behavior is unclear, read the C source to understand actual semantics (e.g., `dump_interval` has a 60-second minimum - values below are ignored).

4. **Test the negative case** - If testing "X causes Y", also verify "not X causes not Y" where feasible. This catches tests that always pass regardless of the condition.

5. **Verify assertions actually fail** - Temporarily break the code or use wrong expected values to confirm the test would catch real failures.

Example of a subtle bug: A test that sets `dump_interval=3`, waits 5 seconds, stops the server, and checks data persisted will ALWAYS pass - because the server checkpoints on shutdown, not because automatic checkpointing worked.
