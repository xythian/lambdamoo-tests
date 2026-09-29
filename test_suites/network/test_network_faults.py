"""Robustness of the server's network loop when descriptors or waits fail.

If a descriptor in the server's select()/poll() set is closed out from under
it, every wait fails immediately with EBADF.  Servers that just log the error
and try again never do any I/O, so the bad descriptor is never removed: the
server spins a full core and fills its log (and disk) with
"Waiting for network I/O: Bad file descriptor".  These tests inject such
faults with an LD_PRELOAD shim (lib/fault_shim.c) and check that the server
keeps serving, keeps its log bounded, and doesn't busy-loop.
"""

import os
import time
from pathlib import Path

import pytest

from lib.fault_shim import FaultInjector, build_fault_shim
from lib.moo_server import MooClient

WAIT_ERROR = 'Waiting for network I/O'


@pytest.fixture(scope='session')
def fault_shim(tmp_path_factory) -> Path:
    """Compile the fault-injection shim once per session."""
    shim = build_fault_shim(tmp_path_factory.mktemp('fault_shim'))
    if shim is None:
        pytest.skip("Fault injection requires Linux and a C compiler")
    return shim


@pytest.fixture
def faulty_server(candidate_server, multiplayer_db, fault_shim, tmp_path):
    """Start a multiplayer server with the fault-injection shim preloaded.

    Multiplayer.db is used so that new connections don't log in as (and
    redirect) the Wizard connection a test is driving.

    Yields:
        (instance, FaultInjector) tuple.
    """
    if multiplayer_db is None:
        pytest.skip("Multiplayer database not available")
    faults = FaultInjector(fault_shim, tmp_path / 'faults')
    instance = candidate_server.start(multiplayer_db, work_dir=tmp_path / 'server', env=faults.env)
    yield instance, faults
    candidate_server.stop(instance)


def count_log_lines(instance, text: str) -> int:
    """Count log lines containing text, streaming in case the log is huge."""
    with open(instance.log_file, errors='replace') as log:
        return sum(1 for line in log if text in line)


def cpu_seconds(pid: int) -> float:
    """Return user+system CPU time consumed so far by a process."""
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')


class TestNetworkFaultRecovery:
    """The network loop recovers from descriptor faults instead of spinning."""

    def test_closed_listener_and_connection_are_dropped(self, candidate_server, faulty_server):
        """A listener and a connection closed underneath the server are dropped.

        The rest of the server keeps working: existing connections still get
        answers, other listeners still accept, and the wait error is not
        logged over and over.
        """
        instance, faults = faulty_server
        admin = candidate_server.connect(instance)
        admin.authenticate('Wizard')
        try:
            victim_port = int(admin.eval_expect_success('listen(#0, 0)'))
            spare_port = int(admin.eval_expect_success('listen(#0, 0)'))

            trigger = faults.close_listener_on_next_accept(victim_port)
            candidate_server.connect(instance).close()
            time.sleep(1.0)
            assert not trigger.exists(), "Fault was never injected"

            assert admin.eval_expect_success('1 + 1') == '2'

            spare = MooClient(port=spare_port)
            spare.connect()
            try:
                spare.authenticate('Player2')
                time.sleep(0.5)
                assert '#4' in admin.eval_expect_success('connected_players()'), \
                    "Connection on the remaining listener was not served"
            finally:
                spare.close()
        finally:
            admin.close()

        assert count_log_lines(instance, WAIT_ERROR) <= 5, \
            "Network wait error was logged repeatedly"

    def test_persistent_wait_failure_is_throttled(self, candidate_server, faulty_server):
        """While every wait fails, the server neither spins nor floods its log.

        Once waits work again the server resumes serving existing connections.
        """
        instance, faults = faulty_server
        admin = candidate_server.connect(instance)
        admin.authenticate('Wizard')
        try:
            faults.fail_waits(True)
            cpu_before = cpu_seconds(instance.pid)
            time.sleep(3.0)
            cpu_used = cpu_seconds(instance.pid) - cpu_before
            faults.fail_waits(False)

            assert count_log_lines(instance, WAIT_ERROR) <= 3, \
                "Failing network wait was logged on every iteration"
            assert cpu_used < 1.0, \
                f"Server used {cpu_used:.1f}s of CPU in 3s while waits were failing"

            assert admin.eval_expect_success('1 + 1', timeout=5.0) == '2'
        finally:
            admin.close()
