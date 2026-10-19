"""Session backend: the wire protocol as the server implements it (SPR-001 through SPR-011).

These speak protocol 1.0 to the server directly, as an edge would, to check
the handshake, positions, acknowledgements and the server's refusal of frames
and attachments the specification does not allow.
"""

import secrets
import time

import pytest

from lib.session import (
    ACK, BIND, CLOSE, DIR_INPUT, HEADER, HELLO, MAGIC, MODE_CRASH,
    MODE_GRACEFUL, MODE_INITIAL, OUTPUT, WELCOME, Carrier, Hello, decode_ack,
    decode_bind, decode_data, encode_frame, encode_input,
)


def new_hello(mode=MODE_INITIAL, player=-(2 ** 63), listener=-(2 ** 63), origin=b'test:origin'):
    return Hello(secrets.token_bytes(16), secrets.token_bytes(16), 1, mode,
                 player=player, listener=listener, origin=origin)


class Attached:
    """An attached carrier that collects the session's output."""

    def __init__(self, socket_path, hello=None):
        self.carrier = Carrier(str(socket_path))
        self.welcome = self.carrier.hello(hello or new_hello())
        self.output = b''
        self.input_position = 0
        self.input_acked = 0
        self.binds = []

    def send(self, data: bytes) -> None:
        self.carrier.send(encode_input(self.input_position, data))
        self.input_position += len(data)

    def collect(self, until: bytes, timeout: float = 5.0) -> bytes:
        """Read frames until the output contains until."""
        if until in self.output:
            return self.output
        for frame in self.carrier.frames(timeout):
            if frame.type == OUTPUT:
                position, data = decode_data(frame.payload)
                assert position == len(self.output), "OUTPUT position skipped or repeated"
                self.output += data
            elif frame.type == ACK:
                direction, position = decode_ack(frame.payload)
                assert direction == DIR_INPUT
                assert self.input_acked <= position <= self.input_position
                self.input_acked = position
            elif frame.type == BIND:
                self.binds.append(decode_bind(frame.payload))
            if until in self.output:
                return self.output
        raise AssertionError(f"never received {until!r}; got {self.output!r}")

    def login(self) -> None:
        """Wait for the test database to log the new connection in as Wizard."""
        self.collect(b'*** Connected ***')

    def eval(self, expression: str) -> bytes:
        start = len(self.output)
        self.send(f';{expression}\n'.encode())
        self.collect(b'=>')
        return self.output[start:]


@pytest.fixture
def session_server(requires_session, candidate_server, minimal_db, tmp_path):
    socket_path = tmp_path / "moo.sock"
    instance = candidate_server.start(database=minimal_db, session_socket=socket_path)
    yield instance
    candidate_server.stop(instance)


class TestHandshake:
    """HELLO and WELCOME."""

    def test_spr_001_welcome_echoes_hello(self, session_server):
        """SPR-001: WELCOME echoes the generation, mode and positions of an initial HELLO."""
        attached = Attached(session_server.socket_path)
        welcome = attached.welcome
        assert (welcome.generation, welcome.mode, welcome.input_position, welcome.output_position) == \
            (1, MODE_INITIAL, 0, 0)

    def test_spr_002_initial_hello_with_binding_is_refused(self, session_server):
        """SPR-002: an initial HELLO may not claim a player."""
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(encode_frame(HELLO, new_hello(player=3, listener=0).encode()))
        assert carrier.is_closed()

    @pytest.mark.parametrize('mode', [MODE_GRACEFUL, MODE_CRASH])
    def test_spr_003_resume_not_in_database_is_refused(self, session_server, mode):
        """SPR-003: a server resumes only players its loaded database records as connected."""
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(encode_frame(HELLO, new_hello(mode=mode, player=3, listener=0).encode()))
        assert carrier.is_closed()

    def test_spr_004_first_frame_must_be_hello(self, session_server):
        """SPR-004: any other first frame ends the attachment."""
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(encode_input(0, b'connect Wizard\n'))
        assert carrier.is_closed()


class TestFrames:
    """Frame validation."""

    @pytest.mark.parametrize('header', [
        pytest.param(HEADER.pack(MAGIC ^ 1, 1, 0, HELLO, 0, 0, 82), id='bad-magic'),
        pytest.param(HEADER.pack(MAGIC, 2, 0, HELLO, 0, 0, 82), id='major-version'),
        pytest.param(HEADER.pack(MAGIC, 1, 1, HELLO, 0, 0, 82), id='newer-minor-version'),
        pytest.param(HEADER.pack(MAGIC, 1, 0, HELLO, 1, 0, 82), id='reserved-byte'),
        pytest.param(HEADER.pack(MAGIC, 1, 0, HELLO, 0, 1, 82), id='flags'),
        pytest.param(HEADER.pack(MAGIC, 1, 0, 99, 0, 0, 0), id='unknown-type'),
        pytest.param(HEADER.pack(MAGIC, 1, 0, HELLO, 0, 0, 81), id='short-hello'),
    ])
    def test_spr_005_invalid_header_is_rejected(self, session_server, header):
        """SPR-005: the server ends an attachment whose frame header is invalid."""
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(header + bytes(82))
        assert carrier.is_closed()

    def test_spr_006_frames_split_across_writes(self, session_server):
        """SPR-006: the server reassembles frames from arbitrarily small writes."""
        carrier = Carrier(str(session_server.socket_path))
        frame = encode_frame(HELLO, new_hello().encode())
        for i in range(len(frame)):
            carrier.send(frame[i:i + 1])
        first = carrier.read_frame(5.0)
        assert first is not None and first.type == WELCOME

    def test_spr_007_input_position_gap_is_rejected(self, session_server):
        """SPR-007: INPUT must start at the next input position."""
        attached = Attached(session_server.socket_path)
        attached.carrier.send(encode_input(5, b'connect Wizard\n'))
        assert attached.carrier.is_closed()


class TestData:
    """Input, output and acknowledgement."""

    def test_spr_008_input_is_acknowledged_and_output_positioned(self, session_server):
        """SPR-008: the server acknowledges input up to what it has read, and
        output positions run on without gaps."""
        attached = Attached(session_server.socket_path)
        attached.login()
        assert b'=> 2' in attached.eval('1 + 1')
        assert attached.input_acked == attached.input_position

    def test_spr_009_login_sends_bind(self, session_server):
        """SPR-009: logging in sends BIND with the player and listener."""
        attached = Attached(session_server.socket_path)
        attached.login()
        player = attached.eval('player').split(b'=>')[1].strip()
        assert attached.binds and f"#{attached.binds[-1][0]}".encode() == player
        assert attached.binds[-1][1] == 0

    def test_spr_010_utf8_split_across_input_frames(self, session_server, requires_unicode):
        """SPR-010: a UTF-8 character split between INPUT frames arrives whole."""
        attached = Attached(session_server.socket_path)
        attached.login()
        command = ';"café"\n'.encode()
        cut = command.index(b'\xc3') + 1
        attached.send(command[:cut])
        attached.send(command[cut:])
        assert '=> "café"'.encode() in attached.collect(b'=>')

    def test_spr_011_close_ends_the_connection(self, session_server):
        """SPR-011: CLOSE from the edge disconnects the player in the server."""
        attached = Attached(session_server.socket_path)
        attached.login()
        attached.carrier.send(encode_frame(CLOSE))
        assert attached.carrier.is_closed()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if "CLIENT DISCONNECTED: Wizard" in session_server.get_log_contents():
                break
            time.sleep(0.05)
        assert "CLIENT DISCONNECTED: Wizard" in session_server.get_log_contents()

