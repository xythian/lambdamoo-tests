"""Input lines whose UTF-8 characters are split across TCP reads.

When a read ends partway through a multibyte character, the server holds the
partial bytes and prepends them to the next read.  It used to then drop that
many bytes from the end of the next read, which lost characters and, when
the newline was among them, left the command unprocessed.
"""

import socket
import time

import pytest


def send_in_pieces(client, pieces):
    """Send raw byte pieces with pauses so the server reads each separately."""
    sock = client._socket
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    for i, piece in enumerate(pieces):
        if i:
            time.sleep(0.3)
        sock.sendall(piece)


def read_result(client, timeout=5.0):
    """Read lines until an eval result arrives; return it or None on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = client.receive_line(timeout=max(0.1, deadline - time.monotonic()))
        if '=>' in line:
            return line.split('=>', 1)[1].strip()
        if line.startswith('**'):
            return line
    return None


@pytest.mark.unicode
@pytest.mark.parametrize("char,split", [
    ("é", 1),
    ("€", 1),
    ("€", 2),
    ("😀", 2),
    ("😀", 3),
], ids=["2byte-at-1", "3byte-at-1", "3byte-at-2", "4byte-at-2", "4byte-at-3"])
def test_character_split_across_reads(client, requires_unicode, char, split):
    """A character split across two reads arrives intact, along with the rest of the line."""
    head = ';{length("x'.encode() + char.encode()[:split]
    tail = char.encode()[split:] + 'y"), "x'.encode() + char.encode() + 'y"}\n'.encode()
    send_in_pieces(client, [head, tail])
    result = read_result(client)
    assert result is not None, "the command was never processed (its newline was lost)"
    assert result == '{3, "x%sy"}' % char
