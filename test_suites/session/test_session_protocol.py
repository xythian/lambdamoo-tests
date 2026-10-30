"""Session backend: the wire protocol as the server implements it (SPR-001 through SPR-022).

These speak protocol 1.0 to the server directly, as an edge would, to check
the handshake, positions, acknowledgements and the server's refusal of frames
and attachments the specification does not allow.
"""

import secrets
import socket
import time

import pytest

from lib.session import (
    ACK, BIND, CLOSE, DIR_INPUT, HEADER, HELLO, KIND_CONTROL, LISTEN_FAILED_PORT, LISTENERS,
    MAGIC, MODE_CRASH, HELLO_FIXED, MODE_GRACEFUL, MODE_INITIAL, OUTPUT, WELCOME, Carrier, Hello,
    decode_ack, decode_bind, decode_data, decode_listeners, describe_connection, encode_fields,
    encode_frame, encode_input, encode_listen_failed,
)

CONNECTION = describe_connection('tcp', 7777, ('192.0.2.10', 40000))


def new_hello(mode=MODE_INITIAL, player=-(2 ** 63), listener=-(2 ** 63), fields=CONNECTION,
              database=bytes(16)):
    return Hello(secrets.token_bytes(16), secrets.token_bytes(16), 1, mode,
                 player=player, listener=listener, fields=encode_fields(fields),
                 database=database)


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

    def collect(self, until: bytes, timeout: float = 5.0, since: int = 0) -> bytes:
        """Read frames until the output from position since on contains until."""
        if until in self.output[since:]:
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
            if until in self.output[since:]:
                return self.output
        raise AssertionError(f"never received {until!r}; got {self.output!r}")

    def login(self) -> None:
        """Wait for the test database to log the new connection in as Wizard."""
        self.collect(b'*** Connected ***')

    def eval(self, expression: str) -> bytes:
        start = len(self.output)
        self.send(f';{expression}\n'.encode())
        self.collect(b'=>', since=start)
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

    def test_spr_012_initial_hello_with_database_is_refused(self, session_server):
        """SPR-012: only a resumed session names the database it was detached with."""
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(encode_frame(HELLO, new_hello(database=bytes(range(16))).encode()))
        assert carrier.is_closed()

    @pytest.mark.parametrize('positions', [(5, 0), (0, 5)], ids=['input', 'output'])
    def test_spr_021_initial_hello_with_positions_is_refused(self, session_server, positions):
        """SPR-021: a new session starts both streams at position 0."""
        hello = new_hello()
        hello.input_position, hello.output_position = positions
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(encode_frame(HELLO, hello.encode()))
        assert carrier.is_closed()

    def test_spr_013_resume_naming_other_database_is_refused(self, session_server):
        """SPR-013: a resumed session naming a database other than the one the
        server loaded is refused before its binding is considered."""
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(encode_frame(HELLO, new_hello(mode=MODE_GRACEFUL, player=3, listener=0,
                                                   database=bytes(range(16))).encode()))
        assert carrier.is_closed()
        assert 'SESSION REATTACHED' not in session_server.get_log_contents()

    @pytest.mark.parametrize('fields', [
        pytest.param(CONNECTION[:-1], id='missing-remote-port'),
        pytest.param(CONNECTION[1:], id='missing-transport'),
        pytest.param((('transport', 7),) + CONNECTION[1:], id='integer-transport'),
        pytest.param(CONNECTION + (('transport', 'tls'),), id='duplicate'),
        pytest.param(CONNECTION + (('direction', 'outbound'),), id='server-owned-name'),
        pytest.param(CONNECTION + (('Remote-Host', 'x'),), id='bad-name'),
        pytest.param(CONNECTION + (('remote-host', 'a\nb'),), id='control-character'),
        pytest.param(CONNECTION[:3] + (('remote-port', 70000),), id='port-out-of-range'),
    ])
    def test_spr_014_bad_connection_fields_are_refused(self, session_server, fields):
        """SPR-014: a client session must describe its connection with the
        required fields, each once, with the right types and printable values."""
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(encode_frame(HELLO, new_hello(fields=fields).encode()))
        assert carrier.is_closed()

    def test_spr_015_truncated_connection_field_is_refused(self, session_server):
        """SPR-015: connection fields must fill the HELLO exactly."""
        hello = new_hello()
        hello.fields = hello.fields[:-1]
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(encode_frame(HELLO, hello.encode()))
        assert carrier.is_closed()

    def test_spr_004_first_frame_must_be_hello(self, session_server):
        """SPR-004: any other first frame ends the attachment."""
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(encode_input(0, b'connect Wizard\n'))
        assert carrier.is_closed()


class TestFrames:
    """Frame validation."""

    @pytest.mark.parametrize('header', [
        pytest.param(HEADER.pack(MAGIC ^ 1, 1, 0, HELLO, 0, 0, HELLO_FIXED.size), id='bad-magic'),
        pytest.param(HEADER.pack(MAGIC, 2, 0, HELLO, 0, 0, HELLO_FIXED.size), id='major-version'),
        pytest.param(HEADER.pack(MAGIC, 1, 1, HELLO, 0, 0, HELLO_FIXED.size), id='newer-minor-version'),
        pytest.param(HEADER.pack(MAGIC, 1, 0, HELLO, 1, 0, HELLO_FIXED.size), id='reserved-byte'),
        pytest.param(HEADER.pack(MAGIC, 1, 0, HELLO, 0, 1, HELLO_FIXED.size), id='flags'),
        pytest.param(HEADER.pack(MAGIC, 1, 0, 99, 0, 0, 0), id='unknown-type'),
        pytest.param(HEADER.pack(MAGIC, 1, 0, HELLO, 0, 0, HELLO_FIXED.size - 1), id='short-hello'),
    ])
    def test_spr_005_invalid_header_is_rejected(self, session_server, header):
        """SPR-005: the server ends an attachment whose frame header is invalid."""
        carrier = Carrier(str(session_server.socket_path))
        carrier.send(header + bytes(HELLO_FIXED.size))
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



class TestConnectionInfo:
    """What the server makes of a session's connection fields."""

    def test_spr_016_connection_name_uses_tcp_format(self, session_server):
        """SPR-016: connection_name() reads as the TCP backend's would, naming
        the remote host when the edge resolved one."""
        attached = Attached(session_server.socket_path)
        attached.login()
        assert b'=> "port 7777 from 192.0.2.10, port 40000"' in attached.eval('connection_name(player)')

        named = Attached(session_server.socket_path, new_hello(
            fields=describe_connection('tcp', 7777, ('192.0.2.10', 40000), 'client.example')))
        named.collect(b'***')
        assert b'=> "port 7777 from client.example, port 40000"' in named.eval('connection_name(player)')

    def test_spr_017_connection_info_lists_fields(self, session_server):
        """SPR-017: connection_info() lists the server's direction followed by
        every field the edge sent, extra ones included, with their types."""
        fields = describe_connection('tls', 7443, ('192.0.2.10', 40000), 'client.example') + \
            (('tls-server-name', 'moo.example'),)
        attached = Attached(session_server.socket_path, new_hello(fields=fields))
        attached.login()
        assert (b'=> {{"direction", "inbound"}, {"transport", "tls"}, {"local-port", 7443}, '
                b'{"remote-host", "client.example"}, {"remote-address", "192.0.2.10"}, '
                b'{"remote-port", 40000}, {"tls-server-name", "moo.example"}}') \
            in attached.eval('connection_info(player)')


class TestOutputBound:
    """A session whose edge isn't reading keeps a bounded output queue."""

    LINE = 's = "x"; while (length(s) < 1000) s = s + s; endwhile; '

    @staticmethod
    def run(attached, program: str) -> int:
        """Run PROGRAM through eval() without reading output until it has
        finished, and return the integer it returns."""
        start = len(attached.output)
        literal = '"' + program.replace('\\', '\\\\').replace('"', '\\"') + '"'
        attached.send(f';eval({literal})[2]\n'.encode())
        time.sleep(1.0)
        attached.collect(b'=> ', timeout=20.0)
        output = attached.collect(b'\r\n', timeout=5.0)[start:]
        return output, int(output.rsplit(b'=> ', 1)[1].split(b'\r\n')[0])

    def test_spr_018_overflow_drops_oldest_output(self, session_server):
        """SPR-018: when output outruns the edge, the server drops the oldest
        unsent lines and says so, as the TCP backend does, and positions run
        on without a gap."""
        attached = Attached(session_server.socket_path)
        attached.login()
        output, queued = self.run(attached, self.LINE +
                                  'for i in [1..2000] notify(player, tostr(i, " ", s)); endfor '
                                  'return buffered_output_length(player);')
        assert b'>> Network buffer overflow: ' in output
        assert b'2000 xx' in output
        assert queued < 200000

    def test_spr_019_no_flush_notify_fails_when_full(self, session_server):
        """SPR-019: notify() with no-flush returns 0 rather than drop output
        when the queue is full."""
        attached = Attached(session_server.socket_path)
        attached.login()
        output, returned = self.run(attached, self.LINE +
                                    'for i in [1..2000] if (!notify(player, s, 1)) return i; endif '
                                    'endfor return 0;')
        assert 0 < returned < 2000
        assert b'Network buffer overflow' not in output


class TestInputFlowControl:
    """The server's only input flow control is to stop reading the carrier."""

    def test_spr_020_held_input_stops_carrier_reads(self, session_server):
        """SPR-020: once a connection's queued input passes the limit, the
        server stops reading its carrier, so an edge writing more blocks
        instead of the server buffering it."""
        attached = Attached(session_server.socket_path)
        attached.login()
        attached.eval('set_connection_option(player, "hold-input", 1)')
        line = b'say ' + b'x' * 1000 + b'\n'
        attached.carrier.sock.settimeout(3.0)
        sent = 0
        with pytest.raises(socket.timeout):
            while sent < 64 * 1024 * 1024:
                attached.send(line * 64)
                sent += len(line) * 64
        assert sent < 16 * 1024 * 1024
        assert session_server.is_running()


class TestControl:
    """The control attachment, spoken to directly."""

    @staticmethod
    def next_listeners(control: Carrier):
        for frame in control.frames(5.0):
            if frame.type == LISTENERS:
                return decode_listeners(frame.payload)
        raise AssertionError("no LISTENERS arrived")

    def test_spr_022_stale_listen_failed_is_ignored(self, session_server):
        """SPR-022: a LISTEN_FAILED answering a LISTENERS sent before the port
        was last listened on doesn't drop the listener; one answering a
        LISTENERS that named it does."""
        control = Carrier(str(session_server.socket_path), check_sent=True)
        control.hello(Hello(secrets.token_bytes(16), secrets.token_bytes(16), 1, MODE_INITIAL,
                            kind=KIND_CONTROL))
        first, ports = self.next_listeners(control)
        assert ports == []
        wizard = Attached(session_server.socket_path)
        wizard.login()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        wizard.eval(f'listen(#0, {port})')
        second, ports = self.next_listeners(control)
        assert second > first and [listen.port for listen in ports] == [port]

        control.send(encode_listen_failed(port, LISTEN_FAILED_PORT, 'stale', first))
        assert f', {port}, '.encode() in wizard.eval('listeners()')
        control.send(encode_listen_failed(port, LISTEN_FAILED_PORT, 'in use', second))
        third, ports = self.next_listeners(control)
        assert third > second and ports == []
        assert f', {port}, '.encode() not in wizard.eval('listeners()')
