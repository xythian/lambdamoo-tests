# LambdaMOO Test Suite TODO

## Checkpointing

- [ ] Basic checkpoint functionality (`dump_database()`)
- [ ] Checkpoint scheduling (`set_checkpoint_interval()`, automatic checkpoints)
- [ ] Checkpoint during active tasks (verify tasks survive)
- [ ] Checkpoint with pending network I/O
- [ ] Emergency checkpoint on shutdown signals
- [ ] Checkpoint file integrity verification

## Network - Port Listening

- [ ] `listen()` - create new listening port
- [ ] `unlisten()` - stop listening on port
- [ ] `listeners()` - list active listeners
- [ ] Multiple simultaneous listeners
- [ ] Listener with custom connection handlers
- [ ] Listener cleanup on object destruction

## Network - Connections

- [ ] `connection_name()` - get connection identifier
- [ ] `connection_option()` / `set_connection_option()` - connection settings
- [ ] `connected_players()` / `connected_seconds()` / `idle_seconds()`
- [ ] `notify()` - send output to connection
- [ ] `read()` - read input from connection
- [ ] `force_input()` - inject input into connection
- [ ] `boot_player()` - disconnect a player
- [ ] `open_network_connection()` - outbound connections (if enabled)

## Network - Buffering and Binary I/O

- [ ] Output buffering behavior
- [ ] `output_delimiters()` - line ending configuration
- [ ] `buffered_output_length()` - check buffer status
- [ ] `flush_input()` - discard pending input
- [ ] Binary mode connections
- [ ] Large data transfer handling
- [ ] Connection timeout behavior

## Waifs - Additional Coverage

- [ ] Waif garbage collection (verify cleanup when last reference dropped)
- [ ] Waif with recursive data structures (non-cyclic)
- [ ] Waif class deletion behavior
- [ ] Waif property permissions
- [ ] Waif verb permissions and `caller_perms()`

## Persistence - Upgrade Scenarios

- [ ] Upgrade from older database format versions
- [ ] Property type changes across upgrades
- [ ] Verb code compatibility across versions
- [ ] Object hierarchy changes during upgrade

## Builtins - Gaps

- [ ] `call_function()` - indirect function calls
- [ ] `function_info()` - builtin introspection
- [ ] `eval()` - dynamic code evaluation
- [ ] `raise()` - exception handling
- [ ] `callers()` - stack introspection
- [ ] Task management (`task_id()`, `queued_tasks()`, `kill_task()`, `resume()`, `suspend()`)
- [ ] `memory_usage()` - memory introspection
- [ ] `db_disk_size()` - database size

## Server Modes

- [ ] Emergency wizard mode (`-e` flag)
- [ ] Emergency wizard mode command restrictions
- [ ] Panic mode / recovery scenarios

## Quotas and Limits

- [ ] Object quota enforcement (`max_object()`)
- [ ] Tick/second limits for tasks
- [ ] Fork depth limits
- [ ] String length limits
- [ ] List size limits
- [ ] Stack depth limits
- [ ] Connection count limits
- [ ] Output buffer limits

## Test Infrastructure

- [ ] Parallel test execution (`pytest-xdist`) for performance
- [ ] Code coverage measurement and reporting
- [ ] Wrapper harness for running key scenario matrix:
  - Multiple server configurations (i32/i64, unicode, waifs, etc.)
  - Upgrade scenarios between versions
  - Cross-server compatibility testing
- [ ] GitHub Actions CI configuration
  - Build matrix for different server configs
  - Automated test runs on PR/push
  - Artifact collection for failures
  - Cache builds between runs
- [ ] Test result caching for unchanged code
- [ ] Performance regression testing

## Documentation

- [ ] Document test patterns and conventions
- [ ] Document fixture usage
- [ ] Document feature detection system
- [ ] Add examples for common test scenarios
