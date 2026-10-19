"""Session protocol 1.0 and a reference edge for the session network backend.

A server built with ``--enable-net=session`` accepts no TCP connections.
Clients reach it through an *edge*, which owns each client connection and
carries it to the server as a session over a Unix-domain socket. When the
server is replaced, the edge keeps the client connected and attaches the
session to the replacement. The protocol is specified in the server's
``Session_Protocol.md``; this module is written from that specification.

It provides:

- frame and payload codecs, and ``Carrier``, one attachment's connection to
  the server, for tests that speak the protocol directly;
- ``SessionEdge``, a reference edge that accepts TCP clients and bridges each
  to a session, reattaching after the server restarts, crashes or panics.
"""

import errno
import secrets
import select
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

MAGIC = 0x4D534553
VERSION_MAJOR = 1
VERSION_MINOR = 0

HELLO = 1
WELCOME = 2
INPUT = 3
OUTPUT = 4
ACK = 5
DETACH = 6
CLOSE = 7
ERROR = 8
BIND = 9

MODE_INITIAL = 1
MODE_GRACEFUL = 2
MODE_CRASH = 3

DIR_INPUT = 1
DIR_OUTPUT = 2

NO_PLAYER = -(2 ** 63)

MAX_CONTROL = 64 * 1024
MAX_DATA = 1024 * 1024

HEADER = struct.Struct('>IBBBBHI')
HELLO_FIXED = struct.Struct('>16s16sQB7xQQqqH')
WELCOME_PAYLOAD = struct.Struct('>QB7xQQ')
ACK_PAYLOAD = struct.Struct('>B7xQ')
DETACH_PAYLOAD = struct.Struct('>B7xQQ')
BIND_PAYLOAD = struct.Struct('>qq')
POSITION = struct.Struct('>Q')

_LENGTHS = {
    HELLO: (HELLO_FIXED.size, MAX_CONTROL),
    WELCOME: (WELCOME_PAYLOAD.size, WELCOME_PAYLOAD.size),
    INPUT: (POSITION.size, POSITION.size + MAX_DATA),
    OUTPUT: (POSITION.size, POSITION.size + MAX_DATA),
    ACK: (ACK_PAYLOAD.size, ACK_PAYLOAD.size),
    DETACH: (DETACH_PAYLOAD.size, DETACH_PAYLOAD.size),
    CLOSE: (0, MAX_CONTROL),
    ERROR: (0, MAX_CONTROL),
    BIND: (BIND_PAYLOAD.size, BIND_PAYLOAD.size),
}


class ProtocolError(Exception):
    """A peer sent something the protocol does not allow."""


class AttachRefused(Exception):
    """The server ended an attachment without accepting its HELLO."""


@dataclass
class Frame:
    """One protocol frame."""
    type: int
    payload: bytes = b''


def encode_frame(frame_type: int, payload: bytes = b'') -> bytes:
    """Return a frame's bytes: the 14-byte header followed by the payload."""
    return HEADER.pack(MAGIC, VERSION_MAJOR, VERSION_MINOR, frame_type, 0, 0, len(payload)) + payload


class FrameReader:
    """Reassembles frames from bytes read in arbitrary pieces."""

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data: bytes) -> List[Frame]:
        """Add bytes and return every frame they complete.

        Raises:
            ProtocolError: if a header is invalid.
        """
        self._buffer.extend(data)
        frames = []
        while len(self._buffer) >= HEADER.size:
            magic, major, minor, frame_type, reserved, flags, length = HEADER.unpack_from(self._buffer)
            if magic != MAGIC or major != VERSION_MAJOR or minor > VERSION_MINOR or reserved or flags:
                raise ProtocolError(f"invalid frame header {bytes(self._buffer[:HEADER.size]).hex()}")
            bounds = _LENGTHS.get(frame_type)
            if bounds is None or not bounds[0] <= length <= bounds[1]:
                raise ProtocolError(f"invalid length {length} for frame type {frame_type}")
            if len(self._buffer) < HEADER.size + length:
                break
            frames.append(Frame(frame_type, bytes(self._buffer[HEADER.size:HEADER.size + length])))
            del self._buffer[:HEADER.size + length]
        return frames


@dataclass
class Hello:
    """The HELLO an edge sends to open an attachment."""
    session_id: bytes
    edge_id: bytes
    generation: int
    mode: int
    input_position: int = 0
    output_position: int = 0
    player: int = NO_PLAYER
    listener: int = NO_PLAYER
    origin: bytes = b''

    def encode(self) -> bytes:
        return HELLO_FIXED.pack(self.session_id, self.edge_id, self.generation, self.mode,
                                self.input_position, self.output_position, self.player,
                                self.listener, len(self.origin)) + self.origin


@dataclass
class Welcome:
    """The server's acceptance of a HELLO."""
    generation: int
    mode: int
    input_position: int
    output_position: int

    @classmethod
    def decode(cls, payload: bytes) -> 'Welcome':
        return cls(*WELCOME_PAYLOAD.unpack(payload))


def encode_input(position: int, data: bytes) -> bytes:
    """Return an INPUT frame carrying data that starts at position."""
    return encode_frame(INPUT, POSITION.pack(position) + data)


def encode_ack(direction: int, position: int) -> bytes:
    """Return an ACK frame."""
    return encode_frame(ACK, ACK_PAYLOAD.pack(direction, position))


def decode_data(payload: bytes) -> Tuple[int, bytes]:
    """Split an INPUT or OUTPUT payload into its position and data."""
    return POSITION.unpack_from(payload)[0], payload[POSITION.size:]


def decode_ack(payload: bytes) -> Tuple[int, int]:
    """Return an ACK's direction and position."""
    return ACK_PAYLOAD.unpack(payload)


def decode_detach(payload: bytes) -> Tuple[int, int, int]:
    """Return a DETACH's mode, input position and output position."""
    return DETACH_PAYLOAD.unpack(payload)


def decode_bind(payload: bytes) -> Tuple[int, int]:
    """Return a BIND's player and listener."""
    return BIND_PAYLOAD.unpack(payload)


def peer_pid(sock: socket.socket) -> Optional[int]:
    """Return the pid of the process at the other end of a Unix socket."""
    if not hasattr(socket, 'SO_PEERCRED'):
        return None
    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
    return struct.unpack('3i', creds)[0]


class Carrier:
    """One attachment's connection to the server's session socket."""

    def __init__(self, path: str, timeout: float = 5.0):
        """Connect to the server's socket.

        Raises:
            OSError: if nothing is listening at path.
        """
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.settimeout(timeout)
            self.sock.connect(path)
        except OSError:
            self.sock.close()
            raise
        self.reader = FrameReader()
        self._pending: List[Frame] = []
        self.pid = peer_pid(self.sock)

    def send(self, data: bytes) -> None:
        """Send encoded frames."""
        self.sock.sendall(data)

    def read_frame(self, timeout: Optional[float] = None) -> Optional[Frame]:
        """Return the next frame, or None if the server closed the carrier.

        Raises:
            socket.timeout: if no frame arrives in time.
            ProtocolError: if the server sent an invalid frame.
        """
        if timeout is not None:
            self.sock.settimeout(timeout)
        while not self._pending:
            try:
                data = self.sock.recv(65536)
            except ConnectionResetError:
                data = b''
            if not data:
                return None
            self._pending.extend(self.reader.feed(data))
        return self._pending.pop(0)

    def frames(self, timeout: float) -> Iterator[Frame]:
        """Yield frames until the carrier closes or none arrives within timeout."""
        while True:
            try:
                frame = self.read_frame(timeout)
            except socket.timeout:
                return
            if frame is None:
                return
            yield frame

    def is_closed(self, timeout: float = 2.0) -> bool:
        """Read and discard frames, reporting whether the server closed the carrier."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.read_frame(max(0.01, deadline - time.monotonic())) is None:
                    return True
            except socket.timeout:
                return False
            except ProtocolError:
                return False
        return False

    def hello(self, hello: Hello, timeout: float = 5.0) -> Welcome:
        """Send HELLO and wait for WELCOME.

        Raises:
            AttachRefused: if the server closes the carrier first.
            ProtocolError: if the server answers with anything else.
        """
        self.send(encode_frame(HELLO, hello.encode()))
        frame = self.read_frame(timeout)
        if frame is None:
            raise AttachRefused("server closed the carrier without WELCOME")
        if frame.type != WELCOME:
            raise ProtocolError(f"expected WELCOME, got frame type {frame.type}")
        welcome = Welcome.decode(frame.payload)
        if (welcome.generation, welcome.mode, welcome.input_position, welcome.output_position) != \
                (hello.generation, hello.mode, hello.input_position, hello.output_position):
            raise ProtocolError(f"WELCOME {welcome} does not match HELLO")
        return welcome

    def take_pending(self) -> List[Frame]:
        """Return frames already read from the socket but not yet returned."""
        pending, self._pending = self._pending, []
        return pending

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


@dataclass
class Session:
    """The edge's record of one session."""
    session_id: bytes
    origin: bytes
    generation: int = 0
    mode: int = MODE_INITIAL
    input_position: int = 0
    output_position: int = 0
    player: int = NO_PLAYER
    listener: int = NO_PLAYER
    attachments: List[int] = field(default_factory=list)
    closed_by_server: bool = False

    def hello(self, edge_id: bytes) -> Hello:
        return Hello(self.session_id, edge_id, self.generation, self.mode, self.input_position,
                     self.output_position, self.player, self.listener, self.origin)


class SessionEdge:
    """A reference edge bridging TCP clients to the server's session socket.

    Each accepted client gets a session and its own thread. While a session is
    attached, client bytes go to the server as INPUT and OUTPUT goes to the
    client. When the attachment is lost, the edge stops reading the client and
    retries the socket until a server accepts the session, the server refuses
    it, or ``hold`` seconds pass; in the last two cases it closes the client.
    Input already sent to a server is never sent again.
    """

    def __init__(self, socket_path: str, host: str = '127.0.0.1', port: int = 0,
                 hold: float = 30.0, retry_interval: float = 0.05):
        self.socket_path = str(socket_path)
        self.hold = hold
        self.retry_interval = retry_interval
        self.edge_id = secrets.token_bytes(16)
        self.sessions: Dict[bytes, Session] = {}
        self._lock = threading.Lock()
        self._threads: List[threading.Thread] = []
        self._closing = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((host, port))
        self._listener.listen(64)
        self.port = self._listener.getsockname()[1]
        self._acceptor = threading.Thread(target=self._accept_loop, name='session-edge', daemon=True)

    def start(self) -> 'SessionEdge':
        self._acceptor.start()
        return self

    def close(self) -> None:
        """Stop accepting, close every client, and wait for session threads."""
        self._closing.set()
        try:
            self._listener.close()
        except OSError:
            pass
        self._acceptor.join(timeout=5)
        for thread in list(self._threads):
            thread.join(timeout=5)

    def __enter__(self) -> 'SessionEdge':
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    def _accept_loop(self) -> None:
        while not self._closing.is_set():
            try:
                readable, _, _ = select.select([self._listener], [], [], 0.1)
                if not readable:
                    continue
                client, address = self._listener.accept()
            except OSError:
                return
            session = Session(secrets.token_bytes(16), f"tcp:{address[0]}:{address[1]}".encode())
            with self._lock:
                self.sessions[session.session_id] = session
            thread = threading.Thread(target=self._serve, args=(client, session),
                                      name='session-edge-client', daemon=True)
            self._threads.append(thread)
            thread.start()

    def _attach(self, session: Session, previous_pid: Optional[int]) -> Optional[Carrier]:
        """Attach the session to whichever server is listening, or return None."""
        deadline = time.monotonic() + self.hold
        while not self._closing.is_set() and time.monotonic() < deadline:
            try:
                carrier = Carrier(self.socket_path)
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.ECONNREFUSED, errno.EAGAIN):
                    raise
                time.sleep(self.retry_interval)
                continue
            if previous_pid is not None and carrier.pid == previous_pid:
                # The server that just went away still has its listener open.
                carrier.close()
                time.sleep(self.retry_interval)
                continue
            session.generation += 1
            try:
                carrier.hello(session.hello(self.edge_id))
            except AttachRefused:
                carrier.close()
                return None
            session.attachments.append(session.mode)
            session.mode = MODE_CRASH
            return carrier
        return None

    def _serve(self, client: socket.socket, session: Session) -> None:
        carrier = None
        previous_pid = None
        try:
            while not self._closing.is_set():
                outcome = 'ok'
                if carrier is None:
                    carrier = self._attach(session, previous_pid)
                    if carrier is None:
                        return
                    # Frames that arrived with WELCOME
                    outcome = self._handle(client, carrier, session, carrier.take_pending())
                    readable = []
                else:
                    readable, _, _ = select.select([client, carrier.sock], [], [], 0.1)
                    if carrier.sock in readable:
                        outcome = self._from_server(client, carrier, session)
                if outcome == 'closed':
                    return
                if outcome == 'detached':
                    previous_pid = carrier.pid
                    carrier.close()
                    carrier = None
                    continue
                if client in readable:
                    data = client.recv(65536)
                    if not data:
                        try:
                            carrier.send(encode_frame(CLOSE))
                        except OSError:
                            pass
                        return
                    position = session.input_position
                    session.input_position += len(data)
                    try:
                        carrier.send(encode_input(position, data))
                    except OSError:
                        session.mode = MODE_CRASH
                        previous_pid = carrier.pid
                        carrier.close()
                        carrier = None
        finally:
            if carrier is not None:
                carrier.close()
            try:
                client.close()
            except OSError:
                pass

    def _from_server(self, client: socket.socket, carrier: Carrier, session: Session) -> str:
        """Handle what the server sent; return 'ok', 'detached' or 'closed'."""
        try:
            data = carrier.sock.recv(65536)
        except ConnectionResetError:
            data = b''
        if not data:
            session.mode = MODE_CRASH
            return 'detached'
        try:
            frames = carrier.reader.feed(data)
        except ProtocolError:
            session.mode = MODE_CRASH
            return 'detached'
        return self._handle(client, carrier, session, frames)

    def _handle(self, client: socket.socket, carrier: Carrier, session: Session,
                frames: List[Frame]) -> str:
        """Act on frames from the server; return 'ok', 'detached' or 'closed'."""
        for frame in frames:
            if frame.type == OUTPUT:
                position, payload = decode_data(frame.payload)
                if position != session.output_position:
                    session.mode = MODE_CRASH
                    return 'detached'
                try:
                    client.sendall(payload)
                except OSError:
                    try:
                        carrier.send(encode_frame(CLOSE))
                    except OSError:
                        pass
                    return 'closed'
                session.output_position += len(payload)
                try:
                    carrier.send(encode_ack(DIR_OUTPUT, session.output_position))
                except OSError:
                    # The server may already have gone; frames it sent before
                    # going, such as CLOSE, still need handling.
                    pass
            elif frame.type == BIND:
                session.player, session.listener = decode_bind(frame.payload)
            elif frame.type == DETACH:
                mode, input_position, output_position = decode_detach(frame.payload)
                if mode == MODE_GRACEFUL and (input_position, output_position) == \
                        (session.input_position, session.output_position):
                    session.mode = MODE_GRACEFUL
                else:
                    session.mode = MODE_CRASH
                return 'detached'
            elif frame.type == CLOSE:
                session.closed_by_server = True
                return 'closed'
            elif frame.type == ACK:
                direction, position = decode_ack(frame.payload)
                if direction != DIR_INPUT or position > session.input_position:
                    session.mode = MODE_CRASH
                    return 'detached'
            else:
                session.mode = MODE_CRASH
                return 'detached'
        return 'ok'


def main(argv: Optional[List[str]] = None) -> int:
    """Run the reference edge until interrupted."""
    import argparse

    parser = argparse.ArgumentParser(description='Reference edge for the session network backend')
    parser.add_argument('socket', help="the server's session socket")
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7777)
    parser.add_argument('--hold', type=float, default=30.0,
                        help='seconds to hold a client while no server accepts its session')
    args = parser.parse_args(argv)

    return serve(args.socket, args.host, args.port, args.hold)


def serve(socket_path: str, host: str, port: int, hold: float) -> int:
    """Run an edge in the foreground until interrupted."""
    edge = SessionEdge(socket_path, host, port, hold).start()
    print(f"edge listening on {host}:{edge.port}, server socket {socket_path}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        edge.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


__all__ = [
    'Carrier', 'FrameReader', 'Frame', 'Hello', 'Welcome', 'Session', 'SessionEdge',
    'AttachRefused', 'ProtocolError', 'encode_frame', 'encode_input', 'encode_ack',
    'decode_data', 'decode_ack', 'decode_detach', 'decode_bind',
    'HELLO', 'WELCOME', 'INPUT', 'OUTPUT', 'ACK', 'DETACH', 'CLOSE', 'ERROR', 'BIND',
    'MODE_INITIAL', 'MODE_GRACEFUL', 'MODE_CRASH', 'DIR_INPUT', 'DIR_OUTPUT', 'NO_PLAYER',
]
