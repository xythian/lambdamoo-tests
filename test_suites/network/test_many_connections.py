"""Servers with more descriptors open than select() can handle (NET-100 onward).

select()'s fd_set holds descriptors below FD_SETSIZE, 1024 with glibc.  A
server that waits with select() and keeps more connections than that open
hands FD_SET() descriptors past the end of its sets; with glibc's fortify
checks the server aborts.  The server's descriptor limit is normally 1024,
which hides this, so the test raises it, opens more connections than
FD_SETSIZE, and checks that the server still accepts, reads from and writes
to them.
"""

import resource
import socket
import time

import pytest

FD_SETSIZE = 1024
CONNECTIONS = FD_SETSIZE + 100


@pytest.fixture
def many_fds():
    """Raise this process's descriptor limit, which the server inherits.

    Both the test (its client sockets) and the server (one descriptor per
    connection) need more than CONNECTIONS descriptors.
    """
    want = CONNECTIONS * 2 + 256
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if hard != resource.RLIM_INFINITY and hard < want:
        pytest.skip(f"RLIMIT_NOFILE hard limit {hard} is below {want}")
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, want), hard))
    yield
    resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def open_connections(instance, count: int) -> list:
    """Open count raw TCP connections to the server.

    Fails with the server's exit status if it dies part way.
    """
    socks = []
    for i in range(count):
        try:
            socks.append(socket.create_connection(('localhost', instance.port), timeout=10))
        except OSError:
            code = instance.process.poll()
            if code is not None:
                pytest.fail(f"server exited with status {code} after {i} connections")
            raise
    return socks


def wait_for_connection_count(admin, at_least: int, timeout: float = 60.0) -> int:
    """Wait until the server reports at least that many connections."""
    deadline = time.monotonic() + timeout
    count = 0
    while time.monotonic() < deadline:
        count = int(admin.eval_expect_success('length(connected_players(1))'))
        if count >= at_least:
            break
        time.sleep(0.5)
    return count


class TestManyConnections:
    """More than FD_SETSIZE simultaneous connections."""

    def test_net_100_serves_past_fd_setsize(self, many_fds, candidate_server, multiplayer_db):
        """NET-100: Connections above FD_SETSIZE are accepted, read and answered.

        The server must accept every connection, keep answering the ones it
        already had, read a command from the raw connection opened last, and
        let a new connection log in and run code.  (Opening this many
        connections takes a minute or two: the server accepts one per pass
        of its main loop and listens with a short backlog.)
        """
        if multiplayer_db is None:
            pytest.skip("Multiplayer database not available")
        instance = candidate_server.start(multiplayer_db, extra_args=['-N'])
        socks = []
        try:
            admin = candidate_server.connect(instance)
            admin.authenticate('Wizard')
            socks = open_connections(instance, CONNECTIONS)
            assert wait_for_connection_count(admin, CONNECTIONS + 1) >= CONNECTIONS + 1
            assert admin.eval_expect_success('1 + 1') == '2'

            high = socks[-1]
            high.sendall(b'connect Player3\r\n')
            reply = b''
            deadline = time.monotonic() + 10
            while b'\n' not in reply and time.monotonic() < deadline:
                chunk = high.recv(4096)
                if not chunk:
                    break
                reply += chunk
            assert reply, "no reply on the connection opened last"

            last = candidate_server.connect(instance)
            last.authenticate('Player2')
            assert last.eval_expect_success('6 * 7') == '42'
            assert instance.is_running()
        finally:
            for s in socks:
                s.close()
            candidate_server.stop(instance)
