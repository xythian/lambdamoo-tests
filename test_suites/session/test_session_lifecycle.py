"""Session backend: sessions surviving server replacement (SES-001 through SES-010).

These run only against servers built with --enable-net=session. Clients
connect over TCP to the reference edge in lib/session.py, which carries each
one to the server as a session, and the tests replace the server underneath
them: a graceful shutdown, a SIGKILL after a checkpoint, and a panic.
"""

import re
import signal
import socket
import time
from pathlib import Path

import pytest

from lib.moo_server import MooClient
from lib.session import MODE_CRASH, MODE_GRACEFUL, MODE_INITIAL, NO_PLAYER, SessionEdge

RECOVERED = "*** Session recovered from a server crash ***"


class SessionWorld:
    """A session server, the edge in front of it, and helpers to replace the server."""

    def __init__(self, candidate_server, database: Path, socket_path: Path, hold: float = 15.0):
        self.manager = candidate_server
        self.socket_path = socket_path
        self.instance = candidate_server.start(database=database, session_socket=socket_path)
        self.edge = SessionEdge(str(socket_path), hold=hold).start()
        self.clients = []

    def connect(self, login: bool = True) -> MooClient:
        client = MooClient(host='127.0.0.1', port=self.edge.port, timeout=5.0)
        client.connect()
        if login:
            client.authenticate('Wizard')
        self.clients.append(client)
        return client

    def session_for(self, client: MooClient):
        origin = f"tcp:127.0.0.1:{client._socket.getsockname()[1]}".encode()
        for session in self.edge.sessions.values():
            if session.origin == origin:
                return session
        raise AssertionError(f"edge has no session for {origin!r}")

    def wait_for_log(self, text: str, instance=None, timeout: float = 10.0) -> str:
        instance = instance or self.instance
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            log = instance.get_log_contents()
            if text in log:
                return log
            time.sleep(0.05)
        raise AssertionError(f"server log never showed {text!r}:\n{instance.get_log_contents()[-2000:]}")

    def checkpoint(self) -> None:
        self.instance.process.send_signal(signal.SIGUSR2)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if re.search(r"CHECKPOINTING on \S+ finished", self.instance.get_log_contents()):
                break
            time.sleep(0.05)
        assert self.instance.output_db.exists(), self.instance.get_log_contents()[-2000:]

    def restart_from(self, database: Path):
        self.instance = self.manager.start(database=database, session_socket=self.socket_path)
        return self.instance

    def graceful_restart(self):
        output = self.manager.stop(self.instance)
        return self.restart_from(output)

    def crash_restart(self):
        self.checkpoint()
        self.instance.process.kill()
        self.instance.process.wait()
        return self.restart_from(self.instance.output_db)

    def panic_restart(self):
        self.instance.process.send_signal(signal.SIGQUIT)
        self.instance.process.wait(timeout=10)
        panic_db = Path(f"{self.instance.output_db}.PANIC")
        assert panic_db.exists(), self.instance.get_log_contents()[-2000:]
        return self.restart_from(panic_db)

    def close(self) -> None:
        for client in self.clients:
            client.close()
        self.edge.close()
        if self.instance.is_running():
            self.manager.stop(self.instance)


def read_until(client: MooClient, text: str, timeout: float = 5.0) -> str:
    """Read client output until it contains text."""
    received = ''
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and text not in received:
        received += client.receive(timeout=0.1)
    assert text in received, f"never received {text!r}; got {received!r}"
    return received


def wait_for_eof(client: MooClient, timeout: float = 5.0) -> bool:
    """Report whether the edge closed the client's connection."""
    sock = client._socket
    sock.settimeout(timeout)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if sock.recv(4096) == b'':
                return True
    except socket.timeout:
        return False
    except ConnectionResetError:
        return True
    return False


@pytest.fixture
def world(requires_session, candidate_server, minimal_db, tmp_path):
    world = SessionWorld(candidate_server, minimal_db, tmp_path / "moo.sock")
    yield world
    world.close()


@pytest.fixture
def short_hold_world(requires_session, candidate_server, minimal_db, tmp_path):
    world = SessionWorld(candidate_server, minimal_db, tmp_path / "moo.sock", hold=1.0)
    yield world
    world.close()


class TestNewSessions:
    """New sessions behave like ordinary connections."""

    def test_ses_001_connection_name_is_edge_origin(self, world):
        """SES-001: connection_name() reports the origin the edge asserted."""
        client = world.connect()
        port = client._socket.getsockname()[1]
        assert client.eval_expect_success('connection_name(player)') == f'"tcp:127.0.0.1:{port}"'

    def test_ses_002_login_binds_session(self, world):
        """SES-002: logging in sends BIND naming the player and listener."""
        client = world.connect()
        player = client.eval_expect_success('player')
        session = world.session_for(client)
        assert f"#{session.player}" == player
        assert session.listener == 0
        assert session.attachments == [MODE_INITIAL]

    def test_ses_003_client_disconnect_reaches_server(self, world):
        """SES-003: a client going away disconnects its player in the server."""
        client = world.connect()
        client.close()
        world.wait_for_log("CLIENT DISCONNECTED: Wizard")

    def test_ses_004_boot_closes_client(self, world):
        """SES-004: boot_player() closes the client and the session is not resumed."""
        client = world.connect()
        session = world.session_for(client)
        client.send(';boot_player(player)')
        assert wait_for_eof(client)
        assert session.closed_by_server
        assert session.attachments == [MODE_INITIAL]


class TestServerReplacement:
    """A logged-in player stays connected while the server is replaced."""

    def test_ses_005_graceful_restart_resumes(self, world):
        """SES-005: after a graceful shutdown and restart, the same player resumes."""
        client = world.connect()
        player = client.eval_expect_success('player')
        session = world.session_for(client)

        new = world.graceful_restart()
        world.wait_for_log(f"SESSION REATTACHED: {player}", instance=new)

        assert client.eval_expect_success('player') == player
        assert session.attachments == [MODE_INITIAL, MODE_GRACEFUL]

    def test_ses_006_crash_resumes_from_checkpoint(self, world):
        """SES-006: after SIGKILL, a restart from the checkpoint resumes the player."""
        client = world.connect()
        player = client.eval_expect_success('player')
        session = world.session_for(client)

        new = world.crash_restart()
        world.wait_for_log(f"SESSION RECOVERED: {player}", instance=new)
        read_until(client, RECOVERED)

        assert client.eval_expect_success('player') == player
        assert session.attachments == [MODE_INITIAL, MODE_CRASH]

    def test_ses_007_panic_resumes_with_state_up_to_panic(self, world):
        """SES-007: after a panic, a restart from the PANIC database resumes the
        player in crash mode, with changes made after the last checkpoint."""
        client = world.connect()
        player = client.eval_expect_success('player')
        client.eval_expect_success('add_property(#0, "ses_007", 42, {player, "rw"})')
        session = world.session_for(client)

        new = world.panic_restart()
        world.wait_for_log(f"SESSION RECOVERED: {player}", instance=new)
        read_until(client, RECOVERED)

        assert client.eval_expect_success('#0.ses_007') == '42'
        assert session.attachments == [MODE_INITIAL, MODE_CRASH]

    def test_ses_008_login_after_checkpoint_is_not_resumed(self, world):
        """SES-008: a crash rolls back to the checkpoint, so a player who logged
        in after it cannot resume and the edge closes their client."""
        world.checkpoint()
        client = world.connect()
        player = client.eval_expect_success('player')

        world.instance.process.kill()
        world.instance.process.wait()
        new = world.restart_from(world.instance.output_db)

        assert wait_for_eof(client)
        assert f"SESSION RECOVERED: {player}" not in new.get_log_contents()

    def test_ses_009_unbound_session_reattaches_as_new_connection(self, world):
        """SES-009: a client that had not logged in gets a fresh login prompt."""
        client = world.connect(login=False)
        session = world.session_for(client)

        new = world.graceful_restart()
        deadline = time.monotonic() + 10
        while len(session.attachments) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert session.attachments == [MODE_INITIAL, MODE_GRACEFUL]

        client.authenticate('Wizard')
        assert client.eval_expect_success('player').startswith('#')
        assert session.player != NO_PLAYER
        assert new.is_running()

    def test_ses_010_hold_expires_without_a_server(self, short_hold_world):
        """SES-010: if no server returns within the edge's hold, the client is closed."""
        client = short_hold_world.connect()
        short_hold_world.manager.stop(short_hold_world.instance)
        assert wait_for_eof(client, timeout=5.0)
