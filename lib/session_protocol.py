# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO
from enum import IntEnum


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SessionProtocol(KaitaiStruct):
    """The byte layout of the frames a session server and an edge exchange over
    the server's Unix socket. A carrier is a stream of frames; this type
    describes such a stream, or any sequence of whole frames taken from one.
    
    This file is normative for byte layouts. Session_Protocol.md is normative
    for everything else: which side may send which frame on which attachment,
    positions and acknowledgements, the rules a HELLO's kind and mode impose on
    its other fields, which connection fields are required, and what each
    frame means.
    
    .. seealso::
       Session_Protocol.md
    """

    class ConnectFailure(IntEnum):
        destination = 1
        resources = 2

    class Direction(IntEnum):
        input = 1
        output = 2

    class FieldType(IntEnum):
        string = 1
        integer = 2

    class FrameType(IntEnum):
        hello = 1
        welcome = 2
        input = 3
        output = 4
        ack = 5
        detach = 6
        close = 7
        error = 8
        bind = 9
        listeners = 10
        connect = 11
        connect_failed = 12
        listen_failed = 13

    class Kind(IntEnum):
        client = 0
        outbound = 1
        control = 2

    class ListenFailure(IntEnum):
        port = 1
        certificate = 2

    class Mode(IntEnum):
        initial = 1
        graceful = 2
        crash = 3
    def __init__(self, _io, _parent=None, _root=None):
        super(SessionProtocol, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.frames = []
        i = 0
        while not self._io.is_eof():
            self.frames.append(SessionProtocol.Frame(self._io, self, self._root))
            i += 1



    def _fetch_instances(self):
        pass
        for i in range(len(self.frames)):
            pass
            self.frames[i]._fetch_instances()


    class Ack(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Ack, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.direction = KaitaiStream.resolve_enum(SessionProtocol.Direction, self._io.read_u1())
            if not  ((self.direction == SessionProtocol.Direction.input) or (self.direction == SessionProtocol.Direction.output)) :
                raise kaitaistruct.ValidationNotAnyOfError(self.direction, self._io, u"/types/ack/seq/0")
            self.reserved = self._io.read_bytes(7)
            if not self.reserved == b"\x00\x00\x00\x00\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00\x00\x00\x00\x00", self.reserved, self._io, u"/types/ack/seq/1")
            self.position = self._io.read_u8be()


        def _fetch_instances(self):
            pass


    class Bind(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Bind, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.player = self._io.read_s8be()
            self.listener = self._io.read_s8be()


        def _fetch_instances(self):
            pass


    class Connect(KaitaiStruct):
        """The server asking the edge for an outbound connection."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Connect, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.request = self._io.read_u4be()
            if not self.request >= 1:
                raise kaitaistruct.ValidationLessThanError(1, self.request, self._io, u"/types/connect/seq/0")
            self.port = self._io.read_u2be()
            self.flags = self._io.read_u2be()
            if not self.flags <= 1:
                raise kaitaistruct.ValidationGreaterThanError(1, self.flags, self._io, u"/types/connect/seq/2")
            self.timeout = self._io.read_u4be()
            self.host_length = self._io.read_u2be()
            if not self.host_length >= 1:
                raise kaitaistruct.ValidationLessThanError(1, self.host_length, self._io, u"/types/connect/seq/4")
            self.reserved = self._io.read_bytes(2)
            if not self.reserved == b"\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00", self.reserved, self._io, u"/types/connect/seq/5")
            self.host = (self._io.read_bytes(self.host_length)).decode(u"UTF-8")


        def _fetch_instances(self):
            pass

        @property
        def tls(self):
            if hasattr(self, '_m_tls'):
                return self._m_tls

            self._m_tls = self.flags & 1 != 0
            return getattr(self, '_m_tls', None)


    class ConnectFailed(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.ConnectFailed, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.request = self._io.read_u4be()
            if not self.request >= 1:
                raise kaitaistruct.ValidationLessThanError(1, self.request, self._io, u"/types/connect_failed/seq/0")
            self.reason = KaitaiStream.resolve_enum(SessionProtocol.ConnectFailure, self._io.read_u1())
            if not  ((self.reason == SessionProtocol.ConnectFailure.destination) or (self.reason == SessionProtocol.ConnectFailure.resources)) :
                raise kaitaistruct.ValidationNotAnyOfError(self.reason, self._io, u"/types/connect_failed/seq/1")
            self.reserved = self._io.read_bytes(3)
            if not self.reserved == b"\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00", self.reserved, self._io, u"/types/connect_failed/seq/2")
            self.diagnostic = (self._io.read_bytes_full()).decode(u"UTF-8")


        def _fetch_instances(self):
            pass


    class ConnectionField(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.ConnectionField, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.name_length = self._io.read_u1()
            if not self.name_length >= 1:
                raise kaitaistruct.ValidationLessThanError(1, self.name_length, self._io, u"/types/connection_field/seq/0")
            if not self.name_length <= 32:
                raise kaitaistruct.ValidationGreaterThanError(32, self.name_length, self._io, u"/types/connection_field/seq/0")
            self.name = (self._io.read_bytes(self.name_length)).decode(u"ASCII")
            self.value_type = KaitaiStream.resolve_enum(SessionProtocol.FieldType, self._io.read_u1())
            if not  ((self.value_type == SessionProtocol.FieldType.string) or (self.value_type == SessionProtocol.FieldType.integer)) :
                raise kaitaistruct.ValidationNotAnyOfError(self.value_type, self._io, u"/types/connection_field/seq/2")
            _on = self.value_type
            if _on == SessionProtocol.FieldType.integer:
                pass
                self.value = self._io.read_s8be()
            elif _on == SessionProtocol.FieldType.string:
                pass
                self.value = SessionProtocol.FieldString(self._io, self, self._root)


        def _fetch_instances(self):
            pass
            _on = self.value_type
            if _on == SessionProtocol.FieldType.integer:
                pass
            elif _on == SessionProtocol.FieldType.string:
                pass
                self.value._fetch_instances()


    class ConnectionFields(KaitaiStruct):
        """What the edge asserts about how the client reached it."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.ConnectionFields, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.fields = []
            i = 0
            while not self._io.is_eof():
                self.fields.append(SessionProtocol.ConnectionField(self._io, self, self._root))
                i += 1



        def _fetch_instances(self):
            pass
            for i in range(len(self.fields)):
                pass
                self.fields[i]._fetch_instances()



    class Data(KaitaiStruct):
        """INPUT from the edge, or OUTPUT from the server."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Data, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.position = self._io.read_u8be()
            self.data = self._io.read_bytes_full()


        def _fetch_instances(self):
            pass


    class Detach(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Detach, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.mode = KaitaiStream.resolve_enum(SessionProtocol.Mode, self._io.read_u1())
            if not  ((self.mode == SessionProtocol.Mode.graceful) or (self.mode == SessionProtocol.Mode.crash)) :
                raise kaitaistruct.ValidationNotAnyOfError(self.mode, self._io, u"/types/detach/seq/0")
            self.reserved = self._io.read_bytes(7)
            if not self.reserved == b"\x00\x00\x00\x00\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00\x00\x00\x00\x00", self.reserved, self._io, u"/types/detach/seq/1")
            self.input_position = self._io.read_u8be()
            self.output_position = self._io.read_u8be()
            self.database = self._io.read_bytes(16)


        def _fetch_instances(self):
            pass


    class Diagnostic(KaitaiStruct):
        """CLOSE or ERROR, with an optional diagnostic that isn't trusted data."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Diagnostic, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.text = (self._io.read_bytes_full()).decode(u"UTF-8")


        def _fetch_instances(self):
            pass


    class FieldString(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.FieldString, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.length = self._io.read_u2be()
            self.value = (self._io.read_bytes(self.length)).decode(u"ASCII")


        def _fetch_instances(self):
            pass


    class Frame(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Frame, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.magic = self._io.read_bytes(4)
            if not self.magic == b"\x4D\x53\x45\x53":
                raise kaitaistruct.ValidationNotEqualError(b"\x4D\x53\x45\x53", self.magic, self._io, u"/types/frame/seq/0")
            self.version_major = self._io.read_u1()
            if not self.version_major == 1:
                raise kaitaistruct.ValidationNotEqualError(1, self.version_major, self._io, u"/types/frame/seq/1")
            self.version_minor = self._io.read_u1()
            if not self.version_minor <= 0:
                raise kaitaistruct.ValidationGreaterThanError(0, self.version_minor, self._io, u"/types/frame/seq/2")
            self.frame_type = KaitaiStream.resolve_enum(SessionProtocol.FrameType, self._io.read_u1())
            if not  ((self.frame_type == SessionProtocol.FrameType.hello) or (self.frame_type == SessionProtocol.FrameType.welcome) or (self.frame_type == SessionProtocol.FrameType.input) or (self.frame_type == SessionProtocol.FrameType.output) or (self.frame_type == SessionProtocol.FrameType.ack) or (self.frame_type == SessionProtocol.FrameType.detach) or (self.frame_type == SessionProtocol.FrameType.close) or (self.frame_type == SessionProtocol.FrameType.error) or (self.frame_type == SessionProtocol.FrameType.bind) or (self.frame_type == SessionProtocol.FrameType.listeners) or (self.frame_type == SessionProtocol.FrameType.connect) or (self.frame_type == SessionProtocol.FrameType.connect_failed) or (self.frame_type == SessionProtocol.FrameType.listen_failed)) :
                raise kaitaistruct.ValidationNotAnyOfError(self.frame_type, self._io, u"/types/frame/seq/3")
            self.reserved = self._io.read_u1()
            if not self.reserved == 0:
                raise kaitaistruct.ValidationNotEqualError(0, self.reserved, self._io, u"/types/frame/seq/4")
            self.flags = self._io.read_u2be()
            if not self.flags == 0:
                raise kaitaistruct.ValidationNotEqualError(0, self.flags, self._io, u"/types/frame/seq/5")
            self.length = self._io.read_u4be()
            if not self.length <= 1048584:
                raise kaitaistruct.ValidationGreaterThanError(1048584, self.length, self._io, u"/types/frame/seq/6")
            _on = self.frame_type
            if _on == SessionProtocol.FrameType.ack:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Ack(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.bind:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Bind(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.close:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Diagnostic(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.connect:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Connect(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.connect_failed:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.ConnectFailed(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.detach:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Detach(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.error:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Diagnostic(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.hello:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Hello(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.input:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Data(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.listen_failed:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.ListenFailed(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.listeners:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Listeners(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.output:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Data(_io__raw_payload, self, self._root)
            elif _on == SessionProtocol.FrameType.welcome:
                pass
                self._raw_payload = self._io.read_bytes(self.length)
                _io__raw_payload = KaitaiStream(BytesIO(self._raw_payload))
                self.payload = SessionProtocol.Welcome(_io__raw_payload, self, self._root)
            else:
                pass
                self.payload = self._io.read_bytes(self.length)


        def _fetch_instances(self):
            pass
            _on = self.frame_type
            if _on == SessionProtocol.FrameType.ack:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.bind:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.close:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.connect:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.connect_failed:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.detach:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.error:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.hello:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.input:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.listen_failed:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.listeners:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.output:
                pass
                self.payload._fetch_instances()
            elif _on == SessionProtocol.FrameType.welcome:
                pass
                self.payload._fetch_instances()
            else:
                pass


    class Hello(KaitaiStruct):
        """The first frame on every attachment, from the edge."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Hello, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.session_id = self._io.read_bytes(16)
            self.edge_id = self._io.read_bytes(16)
            self.generation = self._io.read_u8be()
            self.mode = KaitaiStream.resolve_enum(SessionProtocol.Mode, self._io.read_u1())
            if not  ((self.mode == SessionProtocol.Mode.initial) or (self.mode == SessionProtocol.Mode.graceful) or (self.mode == SessionProtocol.Mode.crash)) :
                raise kaitaistruct.ValidationNotAnyOfError(self.mode, self._io, u"/types/hello/seq/3")
            self.kind = KaitaiStream.resolve_enum(SessionProtocol.Kind, self._io.read_u1())
            if not  ((self.kind == SessionProtocol.Kind.client) or (self.kind == SessionProtocol.Kind.outbound) or (self.kind == SessionProtocol.Kind.control)) :
                raise kaitaistruct.ValidationNotAnyOfError(self.kind, self._io, u"/types/hello/seq/4")
            self.listen_port = self._io.read_u2be()
            self.request = self._io.read_u4be()
            self.input_position = self._io.read_u8be()
            self.output_position = self._io.read_u8be()
            self.player = self._io.read_s8be()
            self.listener = self._io.read_s8be()
            self.database = self._io.read_bytes(16)
            self.fields_length = self._io.read_u2be()
            self._raw_fields = self._io.read_bytes(self.fields_length)
            _io__raw_fields = KaitaiStream(BytesIO(self._raw_fields))
            self.fields = SessionProtocol.ConnectionFields(_io__raw_fields, self, self._root)


        def _fetch_instances(self):
            pass
            self.fields._fetch_instances()


    class ListenEntry(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.ListenEntry, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.port = self._io.read_u2be()
            if not self.port >= 1:
                raise kaitaistruct.ValidationLessThanError(1, self.port, self._io, u"/types/listen_entry/seq/0")
            self.flags = self._io.read_u2be()
            if not self.flags <= 3:
                raise kaitaistruct.ValidationGreaterThanError(3, self.flags, self._io, u"/types/listen_entry/seq/1")
            self.certificate_length = self._io.read_u2be()
            self.key_length = self._io.read_u2be()
            self.acme_length = self._io.read_u2be()
            self.certificate = (self._io.read_bytes(self.certificate_length)).decode(u"UTF-8")
            self.key = (self._io.read_bytes(self.key_length)).decode(u"UTF-8")
            self.acme = (self._io.read_bytes(self.acme_length)).decode(u"UTF-8")


        def _fetch_instances(self):
            pass

        @property
        def acme_requested(self):
            if hasattr(self, '_m_acme_requested'):
                return self._m_acme_requested

            self._m_acme_requested = self.flags & 2 != 0
            return getattr(self, '_m_acme_requested', None)

        @property
        def tls(self):
            if hasattr(self, '_m_tls'):
                return self._m_tls

            self._m_tls = self.flags & 1 != 0
            return getattr(self, '_m_tls', None)


    class ListenFailed(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.ListenFailed, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.port = self._io.read_u2be()
            if not self.port >= 1:
                raise kaitaistruct.ValidationLessThanError(1, self.port, self._io, u"/types/listen_failed/seq/0")
            self.reason = KaitaiStream.resolve_enum(SessionProtocol.ListenFailure, self._io.read_u1())
            if not  ((self.reason == SessionProtocol.ListenFailure.port) or (self.reason == SessionProtocol.ListenFailure.certificate)) :
                raise kaitaistruct.ValidationNotAnyOfError(self.reason, self._io, u"/types/listen_failed/seq/1")
            self.reserved = self._io.read_bytes(5)
            if not self.reserved == b"\x00\x00\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00\x00\x00", self.reserved, self._io, u"/types/listen_failed/seq/2")
            self.diagnostic = (self._io.read_bytes_full()).decode(u"UTF-8")


        def _fetch_instances(self):
            pass


    class Listeners(KaitaiStruct):
        """The complete set of ports the server listens on through the edge."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Listeners, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.entries = []
            i = 0
            while not self._io.is_eof():
                self.entries.append(SessionProtocol.ListenEntry(self._io, self, self._root))
                i += 1



        def _fetch_instances(self):
            pass
            for i in range(len(self.entries)):
                pass
                self.entries[i]._fetch_instances()



    class Welcome(KaitaiStruct):
        """The server's acceptance of a HELLO."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SessionProtocol.Welcome, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.generation = self._io.read_u8be()
            self.mode = KaitaiStream.resolve_enum(SessionProtocol.Mode, self._io.read_u1())
            if not  ((self.mode == SessionProtocol.Mode.initial) or (self.mode == SessionProtocol.Mode.graceful) or (self.mode == SessionProtocol.Mode.crash)) :
                raise kaitaistruct.ValidationNotAnyOfError(self.mode, self._io, u"/types/welcome/seq/1")
            self.reserved = self._io.read_bytes(7)
            if not self.reserved == b"\x00\x00\x00\x00\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00\x00\x00\x00\x00", self.reserved, self._io, u"/types/welcome/seq/2")
            self.input_position = self._io.read_u8be()
            self.output_position = self._io.read_u8be()


        def _fetch_instances(self):
            pass



