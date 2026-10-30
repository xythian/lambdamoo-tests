"""Session protocol: the Kaitai Struct description itself (SKS-001 through SKS-004).

lib/session_protocol.py is generated from tools/kaitai/session_protocol.ksy.
These check that it accepts what the reference edge sends and rejects what
the protocol forbids, so that its use on every frame in the other session
tests is a real check. They need no server.
"""

import struct

import pytest

from lib.session import (
    ACK, BIND, CLOSE, CONNECT, DETACH, DIR_OUTPUT, FAILED_DESTINATION, HELLO, LISTEN_FAILED,
    LISTEN_FAILED_CERTIFICATE, LISTENERS, MODE_CRASH, MODE_INITIAL, OUTPUT, WELCOME, Hello,
    ProtocolError, check_frame, describe_connection, encode_ack, encode_connect_failed,
    encode_fields, encode_frame, encode_input, encode_listen_failed,
)
from lib.session_protocol import SessionProtocol


def hello(**overrides) -> bytes:
    fields = overrides.pop('fields', encode_fields(describe_connection('tls', 7443, ('192.0.2.1', 4000))))
    return encode_frame(HELLO, Hello(bytes(16), bytes(16), 1, MODE_INITIAL, fields=fields,
                                 **overrides).encode())


def listen_entry(port, flags, certificate=b'', key=b'', acme=b'') -> bytes:
    return struct.pack('>HHHHH', port, flags, len(certificate), len(key), len(acme)) \
        + certificate + key + acme


VALID = {
    'hello': hello(),
    'welcome': encode_frame(WELCOME, struct.pack('>QB7xQQ', 1, MODE_INITIAL, 0, 0)),
    'input': encode_input(0, b'look\r\n'),
    'output': encode_frame(OUTPUT, struct.pack('>Q', 5) + b''),
    'ack': encode_ack(DIR_OUTPUT, 12),
    'detach': encode_frame(DETACH, struct.pack('>B7xQQ16s', MODE_CRASH, 1, 2, b'd' * 16)),
    'close': encode_frame(CLOSE),
    'bind': encode_frame(BIND, struct.pack('>qq', 3, 0)),
    'listeners': encode_frame(LISTENERS, struct.pack('>I', 1) + listen_entry(7777, 0)
                              + listen_entry(7443, 3, acme=b'moo.example.org')),
    'connect': encode_frame(CONNECT, struct.pack('>IHHIH2x', 9, 443, 1, 0, 11) + b'example.org'),
    'connect-failed': encode_connect_failed(9, FAILED_DESTINATION, 'refused'),
    'listen-failed': encode_listen_failed(7443, LISTEN_FAILED_CERTIFICATE, 'no certificate'),
}


class TestDescription:
    """The generated parser against hand-built frames."""

    @pytest.mark.parametrize('raw', list(VALID.values()), ids=list(VALID))
    def test_sks_001_valid_frames_parse(self, raw):
        """SKS-001: every frame type the protocol defines parses."""
        check_frame(raw)

    def test_sks_002_fields_are_decoded(self):
        """SKS-002: connection fields and listener entries come out typed."""
        frame = SessionProtocol.from_bytes(VALID['hello']).frames[0]
        fields = {f.name: (f.value.value if f.value_type.name == 'string' else f.value)
                  for f in frame.payload.fields.fields}
        assert fields == {'transport': 'tls', 'local-port': 7443,
                          'remote-address': '192.0.2.1', 'remote-port': 4000}
        entries = SessionProtocol.from_bytes(VALID['listeners']).frames[0].payload.entries
        assert [(e.port, e.tls, e.acme_requested, e.acme) for e in entries] == \
            [(7777, False, False, ''), (7443, True, True, 'moo.example.org')]

    def test_sks_003_several_frames_in_one_buffer(self):
        """SKS-003: a carrier's bytes are a sequence of whole frames."""
        frames = SessionProtocol.from_bytes(VALID['hello'] + VALID['input'] + VALID['close']).frames
        assert [f.frame_type.name for f in frames] == ['hello', 'input', 'close']

    @pytest.mark.parametrize('raw', [
        pytest.param(b'MSEX' + VALID['close'][4:], id='magic'),
        pytest.param(VALID['close'][:4] + b'\x02' + VALID['close'][5:], id='major-version'),
        pytest.param(VALID['close'][:6] + b'\x63' + VALID['close'][7:], id='unknown-type'),
        pytest.param(VALID['close'][:7] + b'\x01' + VALID['close'][8:], id='reserved-header-byte'),
        pytest.param(VALID['hello'][:-1], id='truncated'),
        pytest.param(hello(fields=b'\x01x\x03' + bytes(8)), id='unknown-field-type'),
        pytest.param(hello(fields=b'\x00\x01' + bytes(10)), id='empty-field-name'),
        pytest.param(encode_frame(WELCOME, struct.pack('>QB7xQQ', 1, 4, 0, 0)), id='unknown-mode'),
        pytest.param(encode_frame(WELCOME, struct.pack('>QBB6xQQ', 1, 1, 1, 0, 0)), id='reserved-payload-byte'),
        pytest.param(encode_frame(ACK, struct.pack('>B7xQ', 3, 0)), id='unknown-direction'),
        pytest.param(encode_frame(DETACH, struct.pack('>B7xQQ16s', MODE_INITIAL, 0, 0, bytes(16))),
                     id='initial-detach'),
        pytest.param(encode_frame(BIND, struct.pack('>qq', 3, 0) + b'x'), id='trailing-bytes'),
        pytest.param(encode_frame(LISTENERS, struct.pack('>I', 1) + listen_entry(0, 0)),
                     id='port-zero'),
        pytest.param(encode_frame(LISTENERS, struct.pack('>I', 1) + listen_entry(7777, 4)),
                     id='unknown-listen-flag'),
        pytest.param(encode_frame(LISTENERS, struct.pack('>I', 0)), id='listeners-serial-zero'),
        pytest.param(encode_frame(LISTEN_FAILED, struct.pack('>HBxI', 7443, 1, 0)),
                     id='listen-failed-serial-zero'),
        pytest.param(encode_frame(CONNECT, struct.pack('>IHHIH2x', 0, 443, 0, 0, 1) + b'h'),
                     id='request-zero'),
    ])
    def test_sks_004_invalid_frames_are_rejected(self, raw):
        """SKS-004: the description rejects layouts the protocol forbids."""
        with pytest.raises(ProtocolError):
            check_frame(raw)
