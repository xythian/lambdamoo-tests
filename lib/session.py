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
  to a session, reattaching after the server restarts, crashes or panics. It
  also keeps a control attachment, through which it listens on the ports the
  server's ``listen()`` calls ask for and makes the outbound connections,
  optionally over TLS, that ``open_network_connection()`` asks for.
"""

import errno
import logging
import secrets
import select
import socket
import ssl
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Tuple, Union

import kaitaistruct
from kaitaistruct import KaitaiStruct

from lib.session_protocol import SessionProtocol

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
LISTENERS = 10
CONNECT = 11
CONNECT_FAILED = 12
LISTEN_FAILED = 13

KIND_CLIENT = 0
KIND_OUTBOUND = 1
KIND_CONTROL = 2

CONNECT_TLS = 1

LISTEN_TLS = 1
LISTEN_ACME = 2

FAILED_DESTINATION = 1
FAILED_RESOURCES = 2

LISTEN_FAILED_PORT = 1
LISTEN_FAILED_CERTIFICATE = 2

MODE_INITIAL = 1
MODE_GRACEFUL = 2
MODE_CRASH = 3

DIR_INPUT = 1
DIR_OUTPUT = 2

NO_PLAYER = -(2 ** 63)
NO_DATABASE = bytes(16)

MAX_CONTROL = 64 * 1024
MAX_DATA = 1024 * 1024
MAX_LISTENERS = 1024

HEADER = struct.Struct('>IBBBBHI')
HELLO_FIXED = struct.Struct('>16s16sQBBHIQQqq16sH')
WELCOME_PAYLOAD = struct.Struct('>QB7xQQ')
ACK_PAYLOAD = struct.Struct('>B7xQ')
DETACH_PAYLOAD = struct.Struct('>B7xQQ16s')
BIND_PAYLOAD = struct.Struct('>qq')
POSITION = struct.Struct('>Q')
CONNECT_FIXED = struct.Struct('>IHHIH2x')
CONNECT_FAILED_FIXED = struct.Struct('>IB3x')
LISTEN_FAILED_FIXED = struct.Struct('>HB5x')
LISTEN_FIXED = struct.Struct('>HHHHH')

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
    LISTENERS: (0, MAX_CONTROL),
    CONNECT: (CONNECT_FIXED.size + 1, MAX_CONTROL),
    CONNECT_FAILED: (CONNECT_FAILED_FIXED.size, MAX_CONTROL),
    LISTEN_FAILED: (LISTEN_FAILED_FIXED.size, MAX_CONTROL),
}

log = logging.getLogger(__name__)


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


def check_frame(raw: bytes) -> None:
    """Check one whole frame against the protocol's Kaitai Struct description.

    lib/session_protocol.py is generated from tools/kaitai/session_protocol.ksy,
    a copy of the server's normative description of the byte layout.

    Raises:
        ProtocolError: if the frame doesn't parse, or its payload has bytes
            the description doesn't account for.
    """
    try:
        parsed = SessionProtocol.from_bytes(raw)
    except (kaitaistruct.KaitaiStructError, EOFError, ValueError, UnicodeDecodeError) as error:
        raise ProtocolError(f"frame doesn't match session_protocol.ksy: {error}") from error
    for frame in parsed.frames:
        payload = frame.payload
        if isinstance(payload, KaitaiStruct) and not payload._io.is_eof():
            raise ProtocolError(f"{frame.frame_type.name} payload has trailing bytes")


class FrameReader:
    """Reassembles frames from bytes read in arbitrary pieces."""

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data: bytes) -> List[Frame]:
        """Add bytes and return every frame they complete.

        Raises:
            ProtocolError: if a frame is invalid.
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
            check_frame(bytes(self._buffer[:HEADER.size + length]))
            frames.append(Frame(frame_type, bytes(self._buffer[HEADER.size:HEADER.size + length])))
            del self._buffer[:HEADER.size + length]
        return frames


FIELD_STRING = 1
FIELD_INTEGER = 2
MAX_FIELDS = 32

ConnectionField = Tuple[str, Union[str, int]]


def encode_fields(fields: Tuple[ConnectionField, ...]) -> bytes:
    """Encode connection fields for a HELLO.

    Each field is a name of [a-z0-9-], a type byte, then a u16-length string
    or an i64.
    """
    out = bytearray()
    for name, value in fields:
        raw = name.encode('ascii')
        out += struct.pack('>B', len(raw)) + raw
        if isinstance(value, int):
            out += struct.pack('>Bq', FIELD_INTEGER, value)
        else:
            data = value.encode()
            out += struct.pack('>BH', FIELD_STRING, len(data)) + data
    return bytes(out)


def describe_connection(transport: str, local_port: int, address: Tuple,
                        host: Optional[str] = None) -> Tuple[ConnectionField, ...]:
    """The connection fields for a client or outbound connection.

    Args:
        transport: How the connection arrived, such as "tcp" or "tls".
        local_port: The edge's port on this connection.
        address: The remote end's (address, port).
        host: The name the remote end is known by, if not just its address.
    """
    fields: List[ConnectionField] = [('transport', transport), ('local-port', local_port)]
    if host is not None and host != address[0]:
        fields.append(('remote-host', host))
    fields += [('remote-address', address[0]), ('remote-port', address[1])]
    return tuple(fields)


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
    fields: bytes = b''
    kind: int = KIND_CLIENT
    listen_port: int = 0
    request: int = 0
    database: bytes = NO_DATABASE

    def encode(self) -> bytes:
        return HELLO_FIXED.pack(self.session_id, self.edge_id, self.generation, self.mode,
                                self.kind, self.listen_port, self.request,
                                self.input_position, self.output_position, self.player,
                                self.listener, self.database, len(self.fields)) + self.fields


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


def decode_detach(payload: bytes) -> Tuple[int, int, int, bytes]:
    """Return a DETACH's mode, positions and the digest of the dump it names."""
    return DETACH_PAYLOAD.unpack(payload)


def decode_bind(payload: bytes) -> Tuple[int, int]:
    """Return a BIND's player and listener."""
    return BIND_PAYLOAD.unpack(payload)


@dataclass(frozen=True)
class Listen:
    """One port a LISTENERS frame asks the edge to accept clients on."""
    port: int
    tls: bool = False
    certificate: Optional[str] = None
    key: Optional[str] = None
    acme: Tuple[str, ...] = ()


def decode_listeners(payload: bytes) -> List[Listen]:
    """Return the ports a LISTENERS frame names.

    Raises:
        ProtocolError: an entry is truncated, repeats a port, sets an unknown
            flag, or gives paths or ACME names its flags don't allow.
    """
    listens: List[Listen] = []
    offset = 0
    while offset < len(payload):
        if offset + LISTEN_FIXED.size > len(payload):
            raise ProtocolError("truncated LISTENERS entry")
        port, flags, certificate_length, key_length, acme_length = \
            LISTEN_FIXED.unpack_from(payload, offset)
        offset += LISTEN_FIXED.size
        end = offset + certificate_length + key_length + acme_length
        tls, acme = bool(flags & LISTEN_TLS), bool(flags & LISTEN_ACME)
        if (end > len(payload) or not port or flags & ~(LISTEN_TLS | LISTEN_ACME)
                or any(listen.port == port for listen in listens)
                or (certificate_length or key_length or acme) and not tls
                or bool(certificate_length) != bool(key_length)
                or acme != bool(acme_length)
                or acme and certificate_length):
            raise ProtocolError("invalid LISTENERS entry")
        fields = payload[offset:end]
        certificate = fields[:certificate_length].decode() or None
        key = fields[certificate_length:certificate_length + key_length].decode() or None
        names = fields[certificate_length + key_length:].decode()
        listens.append(Listen(port, tls, certificate, key, tuple(names.split(',')) if names else ()))
        offset = end
    if len(listens) > MAX_LISTENERS:
        raise ProtocolError("too many LISTENERS entries")
    return listens


@dataclass
class Connect:
    """A server's request that the edge open an outbound connection."""
    request: int
    port: int
    flags: int
    timeout: int
    host: str

    @classmethod
    def decode(cls, payload: bytes) -> 'Connect':
        request, port, flags, timeout, host_length = CONNECT_FIXED.unpack_from(payload)
        host = payload[CONNECT_FIXED.size:]
        if len(host) != host_length or not request or flags & ~CONNECT_TLS:
            raise ProtocolError("invalid CONNECT")
        return cls(request, port, flags, timeout, host.decode('utf-8', 'replace'))


def encode_connect_failed(request: int, code: int, reason: str) -> bytes:
    """Return a CONNECT_FAILED frame."""
    return encode_frame(CONNECT_FAILED, CONNECT_FAILED_FIXED.pack(request, code) + reason.encode()[:4096])


def encode_listen_failed(port: int, code: int, reason: str) -> bytes:
    """Return a LISTEN_FAILED frame."""
    return encode_frame(LISTEN_FAILED, LISTEN_FAILED_FIXED.pack(port, code) + reason.encode()[:4096])


def peer_pid(sock: socket.socket) -> Optional[int]:
    """Return the pid of the process at the other end of a Unix socket."""
    if not hasattr(socket, 'SO_PEERCRED'):
        return None
    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
    return struct.unpack('3i', creds)[0]


class Carrier:
    """One attachment's connection to the server's session socket."""

    def __init__(self, path: str, timeout: float = 5.0, check_sent: bool = False):
        """Connect to the server's socket.

        Args:
            path: the server's session socket.
            timeout: how long to wait for the connection.
            check_sent: check every frame sent against the protocol's
                description, as the reference edge does; tests that send
                malformed frames on purpose leave it off.

        Raises:
            OSError: if nothing is listening at path.
        """
        self.check_sent = check_sent
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
        if self.check_sent:
            check_frame(data)
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
    connection: Tuple[ConnectionField, ...]
    generation: int = 0
    mode: int = MODE_INITIAL
    input_position: int = 0
    output_position: int = 0
    player: int = NO_PLAYER
    listener: int = NO_PLAYER
    attachments: List[int] = field(default_factory=list)
    closed_by_server: bool = False
    kind: int = KIND_CLIENT
    listen_port: int = 0
    request: int = 0
    database: bytes = NO_DATABASE

    def hello(self, edge_id: bytes) -> Hello:
        return Hello(self.session_id, edge_id, self.generation, self.mode, self.input_position,
                     self.output_position, self.player, self.listener,
                     encode_fields(self.connection),
                     self.kind, self.listen_port, self.request, self.database)


@dataclass
class PortListener:
    """A port the edge accepts clients on, and how."""
    listen: Listen
    sock: socket.socket
    context: Optional[ssl.SSLContext] = None


def write_all(sock: socket.socket, data: bytes) -> None:
    """Send all of data, waiting while a non-blocking socket is full."""
    view = memoryview(data)
    while view:
        try:
            sent = sock.send(view)
        except (ssl.SSLWantWriteError, ssl.SSLWantReadError, BlockingIOError):
            select.select([], [sock], [], 1.0)
            continue
        view = view[sent:]


class SessionEdge:
    """A reference edge bridging TCP clients to the server's session socket.

    Each accepted client gets a session and its own thread. While a session is
    attached, client bytes go to the server as INPUT and OUTPUT goes to the
    client. When the attachment is lost, the edge stops reading the client and
    retries the socket until a server accepts the session, the server refuses
    it, or ``hold`` seconds pass; in the last two cases it closes the client.
    Input already sent to a server is never sent again.

    A control attachment, reopened whenever it ends, carries the server's
    LISTENERS and CONNECT requests. Ports the server listens on stay open
    while no server is attached, so clients that arrive then are held too.
    The edge terminates TLS on ports the server asks for with TLS, so the
    server only ever sees plain bytes.
    """

    def __init__(self, socket_path: str, host: str = '127.0.0.1', port: int = 0,
                 hold: float = 30.0, retry_interval: float = 0.05,
                 tls_context: Optional[ssl.SSLContext] = None,
                 certificate: Optional[str] = None, key: Optional[str] = None,
                 acme: Optional[Callable[[Tuple[str, ...]], Tuple[str, str]]] = None):
        """Listen for clients on host:port, the server's main listener.

        Args:
            tls_context: verifies outbound TLS connections; defaults to the
                system's trusted certificates.
            certificate: the edge's own certificate chain file, for TLS ports
                the server asks for without naming one.
            key: the private key file for certificate.
            acme: given the names of a port the server asks to have an ACME
                certificate for, returns the certificate chain and key files
                to accept TLS with. The reference edge has no ACME client of
                its own, so without this it doesn't open such ports.
        """
        self.socket_path = str(socket_path)
        self.host = host
        self.hold = hold
        self.retry_interval = retry_interval
        self.tls_context = tls_context or ssl.create_default_context()
        self.certificate = certificate
        self.key = key
        self.acme = acme
        self.requested: List[Listen] = []
        self.seen: Dict[int, Listen] = {}  # every port the server has asked for, latest spec
        self.edge_id = secrets.token_bytes(16)
        self.sessions: Dict[bytes, Session] = {}
        self._lock = threading.Lock()
        self._threads: List[threading.Thread] = []
        self._closing = threading.Event()
        self._listener = self._bind(port)
        self.port = self._listener.getsockname()[1]
        self._ports: Dict[int, PortListener] = {}
        self._control: Optional[Carrier] = None
        self._control_lock = threading.Lock()
        self._acceptor = threading.Thread(target=self._accept_loop, name='session-edge', daemon=True)
        self._controller = threading.Thread(target=self._control_loop, name='session-edge-control',
                                            daemon=True)

    def _bind(self, port: int) -> socket.socket:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, port))
            listener.listen(64)
        except OSError:
            listener.close()
            raise
        return listener

    def start(self) -> 'SessionEdge':
        self._acceptor.start()
        self._controller.start()
        return self

    @property
    def listening_ports(self) -> List[int]:
        """The ports the edge listens on for the server, besides its own."""
        with self._lock:
            return sorted(self._ports)

    def close(self) -> None:
        """Stop accepting, close every client, and wait for session threads."""
        self._closing.set()
        with self._lock:
            listeners = [self._listener, *(p.sock for p in self._ports.values())]
            self._ports.clear()
        for listener in listeners:
            try:
                listener.close()
            except OSError:
                pass
        with self._control_lock:
            if self._control is not None:
                self._control.close()
        self._acceptor.join(timeout=5)
        self._controller.join(timeout=5)
        for thread in list(self._threads):
            thread.join(timeout=5)

    def __enter__(self) -> 'SessionEdge':
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    def _accept_loop(self) -> None:
        while not self._closing.is_set():
            with self._lock:
                listeners = {self._listener: PortListener(Listen(0), self._listener),
                             **{p.sock: p for p in self._ports.values()}}
            try:
                readable, _, _ = select.select(list(listeners), [], [], 0.1)
            except (OSError, ValueError):
                if self._listener.fileno() < 0:
                    return
                continue
            for listener in readable:
                try:
                    client, address = listener.accept()
                except OSError:
                    continue
                port = listeners[listener]
                transport = 'tls' if port.context else 'tcp'
                session = Session(secrets.token_bytes(16),
                                  describe_connection(transport, client.getsockname()[1],
                                                      address),
                                  listen_port=port.listen.port)
                thread = threading.Thread(target=self._serve_accepted,
                                          args=(client, session, port.context),
                                          name='session-edge-client', daemon=True)
                self._threads.append(thread)
                thread.start()

    def _serve_accepted(self, client: socket.socket, session: Session,
                        context: Optional[ssl.SSLContext]) -> None:
        """Finish the TLS handshake, if the port has one, then serve the client."""
        if context is not None:
            try:
                client.settimeout(10.0)
                client = context.wrap_socket(client, server_side=True)
                client.setblocking(False)
            except (OSError, ssl.SSLError) as error:
                log.info("TLS handshake failed: %s", error)
                client.close()
                return
        with self._lock:
            self.sessions[session.session_id] = session
        self._serve(client, session)

    def _control_loop(self) -> None:
        """Keep a control attachment open and act on what arrives on it."""
        previous_pid = None
        while not self._closing.is_set():
            carrier = self._connect(previous_pid, deadline=None)
            if carrier is None:
                return
            hello = Hello(secrets.token_bytes(16), self.edge_id, 1, MODE_INITIAL,
                          kind=KIND_CONTROL)
            try:
                carrier.hello(hello)
            except (AttachRefused, ProtocolError, OSError) as error:
                log.warning("control attachment refused: %s", error)
                carrier.close()
                previous_pid = carrier.pid
                time.sleep(self.retry_interval)
                continue
            with self._control_lock:
                self._control = carrier
            try:
                self._control_frames(carrier, carrier.take_pending())
                while not self._closing.is_set():
                    try:
                        frame = carrier.read_frame(0.1)
                    except socket.timeout:
                        continue
                    if frame is None:
                        break
                    self._control_frames(carrier, [frame])
            except (OSError, ProtocolError):
                pass
            finally:
                with self._control_lock:
                    self._control = None
                previous_pid = carrier.pid
                carrier.close()

    def _control_frames(self, carrier: Carrier, frames: List[Frame]) -> None:
        for frame in frames:
            if frame.type == LISTENERS:
                self._set_ports(decode_listeners(frame.payload))
            elif frame.type == CONNECT:
                request = Connect.decode(frame.payload)
                thread = threading.Thread(target=self._connect_outbound, args=(request,),
                                          name='session-edge-connect', daemon=True)
                self._threads.append(thread)
                thread.start()
            else:
                raise ProtocolError(f"unexpected frame type {frame.type} on control attachment")

    def _server_context(self, listen: Listen) -> Optional[ssl.SSLContext]:
        """Return the context to accept TLS with on a port, or None for plain TCP.

        Raises:
            ValueError: the port wants TLS but there is no certificate for it.
            OSError, ssl.SSLError: the certificate or key cannot be loaded.
        """
        if not listen.tls:
            return None
        if listen.acme:
            if self.acme is None:
                raise ValueError("ACME requested, but the edge has no ACME client")
            certificate, key = self.acme(listen.acme)
        else:
            certificate, key = listen.certificate or self.certificate, listen.key or self.key
        if not certificate:
            raise ValueError("TLS requested, but the edge has no certificate")
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certificate, key)
        return context

    def _set_ports(self, listens: List[Listen]) -> None:
        """Listen on exactly the given ports, besides the edge's own.

        A port whose settings changed is opened again with the new ones.
        """
        self.requested = listens
        self.seen.update((listen.port, listen) for listen in listens)
        wanted = {listen.port: listen for listen in listens}
        with self._lock:
            for port in [p for p, current in self._ports.items() if wanted.get(p) != current.listen]:
                self._ports.pop(port).sock.close()
            missing = [listen for port, listen in wanted.items() if port not in self._ports]
        for listen in missing:
            try:
                context = self._server_context(listen)
            except (OSError, ValueError, ssl.SSLError) as error:
                self._listen_failed(listen.port, LISTEN_FAILED_CERTIFICATE, error)
                continue
            try:
                listener = self._bind(listen.port)
            except OSError as error:
                self._listen_failed(listen.port, LISTEN_FAILED_PORT, error)
                continue
            with self._lock:
                self._ports[listen.port] = PortListener(listen, listener, context)

    def _listen_failed(self, port: int, code: int, error: Exception) -> None:
        """Log that the edge can't serve PORT and tell the server."""
        log.warning("cannot listen on port %d: %s", port, error)
        with self._control_lock:
            if self._control is not None:
                try:
                    self._control.send(encode_listen_failed(port, code, str(error)))
                except OSError:
                    pass

    def _connect_outbound(self, request: Connect) -> None:
        scheme = 'tls' if request.flags & CONNECT_TLS else 'tcp'
        try:
            remote = socket.create_connection((request.host, request.port),
                                              timeout=request.timeout or None)
            if request.flags & CONNECT_TLS:
                remote = self.tls_context.wrap_socket(remote, server_hostname=request.host)
                # A TLS record may carry no application data (a session
                # ticket, say), so a blocking read could wait indefinitely.
                remote.setblocking(False)
            else:
                remote.settimeout(None)
        except (OSError, ssl.SSLError) as error:
            code = FAILED_RESOURCES if isinstance(error, OSError) and error.errno in (
                errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM) else FAILED_DESTINATION
            with self._control_lock:
                if self._control is not None:
                    try:
                        self._control.send(encode_connect_failed(request.request, code, str(error)))
                    except OSError:
                        pass
            return
        session = Session(secrets.token_bytes(16),
                          describe_connection(scheme, remote.getsockname()[1],
                                              remote.getpeername()[:2], request.host),
                          kind=KIND_OUTBOUND, request=request.request)
        with self._lock:
            self.sessions[session.session_id] = session
        self._serve(remote, session)

    def _connect(self, previous_pid: Optional[int], deadline: Optional[float]) -> Optional[Carrier]:
        """Connect to whichever server is listening, other than previous_pid."""
        while not self._closing.is_set() and (deadline is None or time.monotonic() < deadline):
            try:
                carrier = Carrier(self.socket_path, check_sent=True)
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
            return carrier
        return None

    def _attach(self, session: Session, previous_pid: Optional[int]) -> Optional[Carrier]:
        """Attach the session to whichever server is listening, or return None."""
        carrier = self._connect(previous_pid, time.monotonic() + self.hold)
        if carrier is None:
            return None
        session.generation += 1
        try:
            carrier.hello(session.hello(self.edge_id))
        except AttachRefused:
            carrier.close()
            return None
        session.attachments.append(session.mode)
        # Until a DETACH names a dump, losing this server leaves nothing
        # the session can be resumed from.
        session.mode = MODE_CRASH
        session.database = NO_DATABASE
        session.request = 0
        return carrier

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
                    if isinstance(client, ssl.SSLSocket) and client.pending() and client not in readable:
                        readable.append(client)
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
                    try:
                        data = client.recv(65536)
                    except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                        continue
                    except (ConnectionResetError, ssl.SSLError):
                        data = b''
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
                    write_all(client, payload)
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
                mode, input_position, output_position, database = \
                    decode_detach(frame.payload)
                if output_position != session.output_position or \
                        input_position > session.input_position or \
                        mode == MODE_GRACEFUL and input_position != session.input_position:
                    database = NO_DATABASE
                session.mode = mode
                session.database = database
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
    parser.add_argument('--tls-cert', help='certificate chain for TLS ports the server opens')
    parser.add_argument('--tls-key', help='private key for --tls-cert')
    args = parser.parse_args(argv)

    return serve(args.socket, args.host, args.port, args.hold, args.tls_cert, args.tls_key)


def serve(socket_path: str, host: str, port: int, hold: float,
          certificate: Optional[str] = None, key: Optional[str] = None) -> int:
    """Run an edge in the foreground until interrupted."""
    edge = SessionEdge(socket_path, host, port, hold, certificate=certificate, key=key).start()
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
    'NO_DATABASE',
]
