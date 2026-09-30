"""Realistic MOO workloads run cold and hot on a JIT server.

Each workload is ordinary MOO code split into helper verbs, operating on
lists of byte values so it stays within the JIT's integer tier.  Results
are checked against a Python reference both before warm-up (validating the
MOO code on the interpreter) and after warm-up and pool rotation (when the
helpers run as native code, with monomorphic calls stitched together).

Every input runs in its own task so each gets a full tick budget.
"""

import base64
import random
import zlib
from typing import Callable, Dict, List

import pytest

from lib.jit import JitHarness, moo_literal


pytestmark = pytest.mark.jit


def run_workload(jit: JitHarness, verbs: Dict[str, str], call: str, inputs: List,
                 reference: Callable, warm_input, native: List[str]) -> None:
    """Define verbs, check call(input) against reference cold, warm up, and check again hot.

    Args:
        jit: Harness on a JIT server.
        verbs: Verb name to MOO source.
        call: MOO expression template with {arg} for the MOO literal of an input.
        inputs: Inputs to check.
        reference: Python function giving the expected (parsed) result for an input.
        warm_input: Input used for warm-up calls.
        native: Verbs that must be running natively after warm-up.
    """
    for name, source in verbs.items():
        jit.define(name, source)
    expected = [reference(i) for i in inputs]

    cold = [jit.value(call.format(arg=moo_literal(i))) for i in inputs]
    assert cold == expected, "MOO workload disagrees with Python reference on the interpreter"

    jit.warm_and_rotate(call.format(arg=moo_literal(warm_input)))
    jit.assert_native(*native)

    hot = [jit.value(call.format(arg=moo_literal(i))) for i in inputs]
    for i, (h, e) in enumerate(zip(hot, expected)):
        assert h == e, f"hot result differs for input {inputs[i]!r}: {h!r} != {e!r}"


# ---------------------------------------------------------------------------
# HTTP/1.1 request parsing
# ---------------------------------------------------------------------------

def _bytes(s: str) -> List[int]:
    return list(s.encode('latin-1'))


CONTENT_LENGTH = _bytes('content-length')
TRANSFER_ENCODING = _bytes('transfer-encoding')
CHUNKED = _bytes('chunked')
HTTP_1_DOT = _bytes('HTTP/1.')
UINT_LIMIT = 134217727

HTTP_VERBS = {
    'http_find_crlf': '''
        {b, i} = args;
        n = length(b);
        while (i < n)
          if (b[i] == 13 && b[i + 1] == 10)
            return i;
          endif
          i = i + 1;
        endwhile
        return 0;
    ''',
    'http_index': '''
        {l, c, i} = args;
        n = length(l);
        while (i <= n)
          if (l[i] == c)
            return i;
          endif
          i = i + 1;
        endwhile
        return 0;
    ''',
    'http_lower': '''
        r = {};
        for c in (args[1])
          r = {@r, (c >= 65 && c <= 90) ? c + 32 | c};
        endfor
        return r;
    ''',
    'http_trim': '''
        l = args[1];
        a = 1;
        z = length(l);
        while (a <= z && (l[a] == 32 || l[a] == 9))
          a = a + 1;
        endwhile
        while (z >= a && (l[z] == 32 || l[z] == 9))
          z = z - 1;
        endwhile
        return l[a..z];
    ''',
    'http_hexval': '''
        c = args[1];
        if (c >= 48 && c <= 57)
          return c - 48;
        elseif (c >= 97 && c <= 102)
          return c - 87;
        elseif (c >= 65 && c <= 70)
          return c - 55;
        endif
        return -1;
    ''',
    'http_parse_uint': f'''
        {{l, base}} = args;
        if (!l)
          return -1;
        endif
        v = 0;
        for c in (l)
          d = this:http_hexval(c);
          if (d < 0 || d >= base || v > {UINT_LIMIT})
            return -1;
          endif
          v = v * base + d;
        endfor
        return v;
    ''',
    'http_pct_decode': '''
        l = args[1];
        r = {};
        i = 1;
        n = length(l);
        while (i <= n)
          if (l[i] == 37)
            if (i + 2 > n)
              return {0};
            endif
            h = this:http_hexval(l[i + 1]);
            lo = this:http_hexval(l[i + 2]);
            if (h < 0 || lo < 0)
              return {0};
            endif
            r = {@r, h * 16 + lo};
            i = i + 3;
          else
            r = {@r, l[i]};
            i = i + 1;
          endif
        endwhile
        return {1, r};
    ''',
    'http_dechunk': '''
        {b, pos} = args;
        body = {};
        while (1)
          eol = this:http_find_crlf(b, pos);
          if (!eol)
            return {0};
          endif
          line = b[pos..eol - 1];
          semi = this:http_index(line, 59, 1);
          if (semi)
            line = line[1..semi - 1];
          endif
          size = this:http_parse_uint(this:http_trim(line), 16);
          if (size < 0)
            return {0};
          endif
          pos = eol + 2;
          if (size == 0)
            while (1)
              eol = this:http_find_crlf(b, pos);
              if (!eol)
                return {0};
              endif
              if (eol == pos)
                return {1, body};
              endif
              pos = eol + 2;
            endwhile
          endif
          if (pos + size + 1 > length(b))
            return {0};
          endif
          body = {@body, @b[pos..pos + size - 1]};
          pos = pos + size;
          if (b[pos] != 13 || b[pos + 1] != 10)
            return {0};
          endif
          pos = pos + 2;
        endwhile
    ''',
    'http_parse': f'''
        b = args[1];
        n = length(b);
        eol = this:http_find_crlf(b, 1);
        if (!eol)
          return {{0, 1}};
        endif
        line = b[1..eol - 1];
        sp1 = this:http_index(line, 32, 1);
        sp2 = sp1 ? this:http_index(line, 32, sp1 + 1) | 0;
        if (!sp2)
          return {{0, 2}};
        endif
        method = line[1..sp1 - 1];
        target = line[sp1 + 1..sp2 - 1];
        version = line[sp2 + 1..$];
        if (!method || !target)
          return {{0, 2}};
        endif
        for c in (method)
          if (c < 65 || c > 90)
            return {{0, 3}};
          endif
        endfor
        if (length(version) != 8 || version[1..7] != {moo_literal(HTTP_1_DOT)} || version[8] < 48 || version[8] > 57)
          return {{0, 4}};
        endif
        path = this:http_pct_decode(target);
        if (!path[1])
          return {{0, 5}};
        endif
        pos = eol + 2;
        headers = {{}};
        clen = -1;
        chunked = 0;
        while (1)
          eol = this:http_find_crlf(b, pos);
          if (!eol)
            return {{0, 6}};
          endif
          if (eol == pos)
            pos = pos + 2;
            break;
          endif
          hl = b[pos..eol - 1];
          colon = this:http_index(hl, 58, 1);
          if (colon < 2)
            return {{0, 7}};
          endif
          name = this:http_lower(hl[1..colon - 1]);
          for c in (name)
            if (c == 32 || c == 9)
              return {{0, 7}};
            endif
          endfor
          value = this:http_trim(hl[colon + 1..$]);
          headers = {{@headers, {{name, value}}}};
          if (name == {moo_literal(CONTENT_LENGTH)})
            v = this:http_parse_uint(value, 10);
            if (v < 0 || (clen >= 0 && clen != v))
              return {{0, 8}};
            endif
            clen = v;
          elseif (name == {moo_literal(TRANSFER_ENCODING)})
            if (this:http_lower(value) != {moo_literal(CHUNKED)})
              return {{0, 9}};
            endif
            chunked = 1;
          endif
          pos = eol + 2;
        endwhile
        if (chunked && clen >= 0)
          return {{0, 10}};
        endif
        if (chunked)
          body = this:http_dechunk(b, pos);
          if (!body[1])
            return {{0, 11}};
          endif
          body = body[2];
        elseif (clen >= 0)
          if (n - pos + 1 < clen)
            return {{0, 12}};
          endif
          body = b[pos..pos + clen - 1];
        else
          body = {{}};
        endif
        return {{1, method, path[2], version[8] - 48, headers, body}};
    ''',
}


def _find_crlf(b, i):
    """1-based index of the CR of the first CRLF at or after 1-based i, or 0."""
    j = bytes(b).find(b'\r\n', i - 1)
    return j + 1 if j >= 0 else 0


def _trim(b):
    return list(bytes(b).strip(b' \t'))


def _parse_uint(b, base):
    if not b:
        return -1
    v = 0
    for c in b:
        ch = chr(c)
        d = int(ch, 16) if ch in '0123456789abcdefABCDEF' else -1
        if d < 0 or d >= base or v > UINT_LIMIT:
            return -1
        v = v * base + d
    return v


def _pct_decode(b):
    out, i = [], 0
    while i < len(b):
        if b[i] == 37:
            if i + 2 >= len(b):
                return None
            h, lo = _parse_uint(b[i + 1:i + 2], 16), _parse_uint(b[i + 2:i + 3], 16)
            if h < 0 or lo < 0:
                return None
            out.append(h * 16 + lo)
            i += 3
        else:
            out.append(b[i])
            i += 1
    return out


def _dechunk(b, pos):
    body = []
    while True:
        eol = _find_crlf(b, pos)
        if not eol:
            return None
        line = b[pos - 1:eol - 1]
        if 59 in line:
            line = line[:line.index(59)]
        size = _parse_uint(_trim(line), 16)
        if size < 0:
            return None
        pos = eol + 2
        if size == 0:
            while True:
                eol = _find_crlf(b, pos)
                if not eol:
                    return None
                if eol == pos:
                    return body
                pos = eol + 2
        if pos + size + 1 > len(b):
            return None
        body += b[pos - 1:pos - 1 + size]
        pos += size
        if b[pos - 1] != 13 or b[pos] != 10:
            return None
        pos += 2


def http_reference(b: List[int]):
    """Python mirror of #0:http_parse: {1, method, path, minor, headers, body} or {0, code}."""
    eol = _find_crlf(b, 1)
    if not eol:
        return [0, 1]
    line = b[:eol - 1]
    parts = bytes(line).split(b' ', 2)
    if len(parts) < 3 or not parts[0] or not parts[1]:
        return [0, 2]
    method, target, version = (list(p) for p in parts)
    if any(c < 65 or c > 90 for c in method):
        return [0, 3]
    if len(version) != 8 or version[:7] != HTTP_1_DOT or not 48 <= version[7] <= 57:
        return [0, 4]
    path = _pct_decode(target)
    if path is None:
        return [0, 5]
    pos, headers, clen, chunked = eol + 2, [], -1, False
    while True:
        eol = _find_crlf(b, pos)
        if not eol:
            return [0, 6]
        if eol == pos:
            pos += 2
            break
        hl = b[pos - 1:eol - 1]
        colon = hl.index(58) + 1 if 58 in hl else 0
        if colon < 2:
            return [0, 7]
        name = list(bytes(hl[:colon - 1]).lower())
        if 32 in name or 9 in name:
            return [0, 7]
        value = _trim(hl[colon:])
        headers.append([name, value])
        if name == CONTENT_LENGTH:
            v = _parse_uint(value, 10)
            if v < 0 or (clen >= 0 and clen != v):
                return [0, 8]
            clen = v
        elif name == TRANSFER_ENCODING:
            if list(bytes(value).lower()) != CHUNKED:
                return [0, 9]
            chunked = True
        pos = eol + 2
    if chunked and clen >= 0:
        return [0, 10]
    if chunked:
        body = _dechunk(b, pos)
        if body is None:
            return [0, 11]
    elif clen >= 0:
        if len(b) - pos + 1 < clen:
            return [0, 12]
        body = b[pos - 1:pos - 1 + clen]
    else:
        body = []
    return [1, method, path, version[7] - 48, headers, body]


HTTP_REQUESTS = [
    'GET /index.html HTTP/1.1\r\nHost: example.com\r\nAccept: */*\r\n\r\n',
    'GET / HTTP/1.0\r\n\r\n',
    'POST /submit HTTP/1.1\r\nHost: x\r\nContent-Type: text/plain\r\nContent-Length: 11\r\n\r\nhello world',
    'PUT /a%20b/%E2%9C%93?q=%41 HTTP/1.1\r\nHOST:   spaced.example  \r\nX-Tab:\tvalue\t\r\n\r\n',
    'POST /c HTTP/1.1\r\nTransfer-Encoding: Chunked\r\n\r\n'
    '5;ext=1\r\nhello\r\n1A\r\nabcdefghijklmnopqrstuvwxyz\r\n0\r\nTrailer: t\r\n\r\n',
    'POST /c HTTP/1.1\r\ntransfer-encoding: chunked\r\n\r\n0\r\n\r\n',
    'DELETE /x HTTP/1.1\r\ncontent-length: 3\r\nContent-Length: 3\r\n\r\nabcEXTRA',
    'GET /x HTTP/1.1',
    'GET /x\r\n\r\n',
    'get /x HTTP/1.1\r\n\r\n',
    'GET /x HTTP/2.0\r\n\r\n',
    'GET /x%zz HTTP/1.1\r\n\r\n',
    'GET /x%4 HTTP/1.1\r\n\r\n',
    'GET /x HTTP/1.1\r\nHost: x\r\n',
    'GET /x HTTP/1.1\r\nNoColon\r\n\r\n',
    'GET /x HTTP/1.1\r\nBad Name: v\r\n\r\n',
    'POST /x HTTP/1.1\r\nContent-Length: 12a\r\n\r\n',
    'POST /x HTTP/1.1\r\nContent-Length: 99999999999\r\n\r\n',
    'POST /x HTTP/1.1\r\nContent-Length: 3\r\nContent-Length: 4\r\n\r\nabcd',
    'POST /x HTTP/1.1\r\nTransfer-Encoding: gzip\r\n\r\n',
    'POST /x HTTP/1.1\r\nTransfer-Encoding: chunked\r\nContent-Length: 5\r\n\r\n0\r\n\r\n',
    'POST /x HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\nZZ\r\n',
    'POST /x HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhel',
    'POST /x HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabcXY0\r\n\r\n',
    'POST /x HTTP/1.1\r\nContent-Length: 10\r\n\r\nshort',
    ' / HTTP/1.1\r\n\r\n',
]


def test_http_request_parser(jit):
    """An HTTP/1.1 request parser (request line, headers, Content-Length, chunked, %-decoding)."""
    run_workload(
        jit, HTTP_VERBS, '#0:http_parse({arg})',
        [_bytes(r) for r in HTTP_REQUESTS], http_reference,
        warm_input=_bytes(HTTP_REQUESTS[2]),
        native=['http_find_crlf', 'http_index', 'http_trim', 'http_hexval', 'http_parse_uint'],
    )


# ---------------------------------------------------------------------------
# UTF-8 decoding and validation
# ---------------------------------------------------------------------------

UTF8_VERBS = {
    'utf8_decode': '''
        b = args[1];
        n = length(b);
        i = 1;
        r = {};
        while (i <= n)
          c = b[i];
          if (c < 128)
            r = {@r, c};
            i = i + 1;
            continue;
          elseif (c >= 194 && c <= 223)
            need = 1;
            cp = c .&. 31;
            lo = 128;
            hi = 191;
          elseif (c >= 224 && c <= 239)
            need = 2;
            cp = c .&. 15;
            lo = c == 224 ? 160 | 128;
            hi = c == 237 ? 159 | 191;
          elseif (c >= 240 && c <= 244)
            need = 3;
            cp = c .&. 7;
            lo = c == 240 ? 144 | 128;
            hi = c == 244 ? 143 | 191;
          else
            return {0, i};
          endif
          if (i + need > n)
            return {0, i};
          endif
          for k in [1..need]
            d = b[i + k];
            if (d < (k == 1 ? lo | 128) || d > (k == 1 ? hi | 191))
              return {0, i};
            endif
            cp = (cp << 6) .|. (d .&. 63);
          endfor
          r = {@r, cp};
          i = i + need + 1;
        endwhile
        return {1, r};
    ''',
}


def utf8_reference(b: List[int]):
    """{1, codepoints} or {0, 1-based index of the first invalid sequence}."""
    try:
        return [1, [ord(ch) for ch in bytes(b).decode('utf-8')]]
    except UnicodeDecodeError as e:
        return [0, e.start + 1]


UTF8_INPUTS = [
    'plain ascii'.encode(),
    'héllo wörld'.encode(),
    'Ελληνικά 中文 日本語'.encode(),
    '😀🎉 supplementary'.encode(),
    '߿ࠀ￿\U00010000\U0010ffff'.encode(),
    b'',
    b'\xc0\xaf',              # overlong
    b'\xe0\x80\xaf',          # overlong three-byte
    b'\xed\xa0\x80',          # surrogate
    b'\xf4\x90\x80\x80',      # above U+10FFFF
    b'\xf5\x80\x80\x80',      # invalid lead
    b'ok\x80',                # stray continuation
    b'ok\xe2\x82',            # truncated at end
    b'ok\xe2\x28\xa1',        # bad continuation
    b'abc\xff',
]


def test_utf8_decoder(jit, requires_bitwise):
    """A UTF-8 decoder that rejects overlongs, surrogates, out-of-range and truncated sequences."""
    run_workload(
        jit, UTF8_VERBS, '#0:utf8_decode({arg})',
        [list(b) for b in UTF8_INPUTS], utf8_reference,
        warm_input=list('Ελληνικά 中文 😀'.encode()),
        native=['utf8_decode'],
    )


# ---------------------------------------------------------------------------
# Base64
# ---------------------------------------------------------------------------

B64_ALPHABET = list(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/')

BASE64_VERBS = {
    'b64_encode': f'''
        b = args[1];
        n = length(b);
        alphabet = {moo_literal(B64_ALPHABET)};
        r = {{}};
        i = 1;
        while (i + 2 <= n)
          v = (b[i] << 16) .|. (b[i + 1] << 8) .|. b[i + 2];
          r = {{@r, alphabet[(v >> 18) + 1], alphabet[((v >> 12) .&. 63) + 1], alphabet[((v >> 6) .&. 63) + 1], alphabet[(v .&. 63) + 1]}};
          i = i + 3;
        endwhile
        left = n - i + 1;
        if (left == 1)
          v = b[i] << 16;
          r = {{@r, alphabet[(v >> 18) + 1], alphabet[((v >> 12) .&. 63) + 1], 61, 61}};
        elseif (left == 2)
          v = (b[i] << 16) .|. (b[i + 1] << 8);
          r = {{@r, alphabet[(v >> 18) + 1], alphabet[((v >> 12) .&. 63) + 1], alphabet[((v >> 6) .&. 63) + 1], 61}};
        endif
        return r;
    ''',
    'b64_val': '''
        c = args[1];
        if (c >= 65 && c <= 90)
          return c - 65;
        elseif (c >= 97 && c <= 122)
          return c - 71;
        elseif (c >= 48 && c <= 57)
          return c + 4;
        elseif (c == 43)
          return 62;
        elseif (c == 47)
          return 63;
        endif
        return -1;
    ''',
    'b64_decode': '''
        s = args[1];
        n = length(s);
        if (n % 4)
          return {0};
        endif
        r = {};
        i = 1;
        while (i <= n)
          a = this:b64_val(s[i]);
          b = this:b64_val(s[i + 1]);
          if (a < 0 || b < 0)
            return {0};
          endif
          if (s[i + 2] == 61)
            if (i + 3 != n || s[i + 3] != 61)
              return {0};
            endif
            return {1, {@r, (a << 2) .|. (b >> 4)}};
          endif
          c = this:b64_val(s[i + 2]);
          if (c < 0)
            return {0};
          endif
          if (s[i + 3] == 61)
            if (i + 3 != n)
              return {0};
            endif
            return {1, {@r, (a << 2) .|. (b >> 4), ((b .&. 15) << 4) .|. (c >> 2)}};
          endif
          d = this:b64_val(s[i + 3]);
          if (d < 0)
            return {0};
          endif
          r = {@r, (a << 2) .|. (b >> 4), ((b .&. 15) << 4) .|. (c >> 2), ((c .&. 3) << 6) .|. d};
          i = i + 4;
        endwhile
        return {1, r};
    ''',
    'b64_roundtrip': 'e = this:b64_encode(args[1]); return {e, this:b64_decode(e)};',
}


def _random_bytes(seed: int, n: int) -> List[int]:
    rng = random.Random(seed)
    return [rng.randrange(256) for _ in range(n)]


BASE64_INPUTS = [[], list(b'f'), list(b'fo'), list(b'foo'), list(b'foob'), list(b'fooba'),
                 list(b'foobar'), list(range(256)), _random_bytes(1, 97), _random_bytes(2, 200)]

BASE64_INVALID = [list(b'Zm9'), list(b'Zm9v!A=='), list(b'Zg==Zg=='), list(b'Z==='),
                  list(b'Zm=v'), list(b'====')]


def test_base64(jit, requires_bitwise):
    """Base64 encode/decode round trips match Python's base64 module."""
    run_workload(
        jit, BASE64_VERBS, '#0:b64_roundtrip({arg})', BASE64_INPUTS,
        lambda b: [list(base64.b64encode(bytes(b))), [1, b]],
        warm_input=_random_bytes(3, 60),
        native=['b64_encode', 'b64_decode', 'b64_val'],
    )
    for bad in BASE64_INVALID:
        assert jit.value(f'#0:b64_decode({moo_literal(bad)})') == [0], bytes(bad)


# ---------------------------------------------------------------------------
# CRC-32
# ---------------------------------------------------------------------------

CRC_VERBS = {
    'crc_byte': '''
        crc = args[1];
        for k in [1..8]
          if (crc .&. 1)
            crc = (crc >> 1) .^. 3988292384;
          else
            crc = crc >> 1;
          endif
        endfor
        return crc;
    ''',
    'crc32_bitwise': '''
        crc = 4294967295;
        for c in (args[1])
          crc = this:crc_byte(crc .^. c);
        endfor
        return crc .^. 4294967295;
    ''',
    'crc_table': '''
        t = {};
        for i in [0..255]
          t = {@t, this:crc_byte(i)};
        endfor
        return t;
    ''',
    'crc32_table': '''
        {b, t} = args;
        crc = 4294967295;
        for c in (b)
          crc = (crc >> 8) .^. t[((crc .^. c) .&. 255) + 1];
        endfor
        return crc .^. 4294967295;
    ''',
    'crc32_both': 'return {this:crc32_bitwise(args[1]), this:crc32_table(args[1], this:crc_table())};',
}

CRC_INPUTS = [[], list(b'a'), list(b'123456789'), list(b'The quick brown fox jumps over the lazy dog'),
              list(range(256)), _random_bytes(4, 150)]


def test_crc32(jit, requires_bitwise):
    """Bitwise and table-driven CRC-32 match zlib.crc32."""
    run_workload(
        jit, CRC_VERBS, '#0:crc32_both({arg})', CRC_INPUTS,
        lambda b: [zlib.crc32(bytes(b))] * 2,
        warm_input=_random_bytes(5, 40),
        native=['crc_byte', 'crc32_bitwise', 'crc32_table'],
    )


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

SORT_VERBS = {
    'msort': '''
        l = args[1];
        n = length(l);
        if (n < 2)
          return l;
        endif
        mid = n / 2;
        return this:msort_merge(this:msort(l[1..mid]), this:msort(l[mid + 1..n]));
    ''',
    'msort_merge': '''
        {a, b} = args;
        r = {};
        i = 1;
        j = 1;
        na = length(a);
        nb = length(b);
        while (i <= na && j <= nb)
          if (b[j] < a[i])
            r = {@r, b[j]};
            j = j + 1;
          else
            r = {@r, a[i]};
            i = i + 1;
          endif
        endwhile
        return {@r, @a[i..na], @b[j..nb]};
    ''',
    'isort': '''
        l = args[1];
        for i in [2..length(l)]
          v = l[i];
          j = i - 1;
          while (j >= 1 && l[j] > v)
            l[j + 1] = l[j];
            j = j - 1;
          endwhile
          l[j + 1] = v;
        endfor
        return l;
    ''',
    'both_sorts': 'return {this:msort(args[1]), this:isort(args[1])};',
}


def _random_ints(seed: int, n: int, lo: int, hi: int) -> List[int]:
    rng = random.Random(seed)
    return [rng.randint(lo, hi) for _ in range(n)]


SORT_INPUTS = [[], [1], [2, 1], list(range(30, 0, -1)), [5] * 10,
               [2**63 - 1, -2**63, 0, -1, 1, 2**63 - 1, -2**63],
               _random_ints(6, 60, -1000, 1000), _random_ints(7, 80, 0, 3)]


def test_sorting(jit):
    """Recursive mergesort and in-place insertion sort match sorted()."""
    run_workload(
        jit, SORT_VERBS, '#0:both_sorts({arg})', SORT_INPUTS,
        lambda values: [sorted(values)] * 2,
        warm_input=_random_ints(8, 20, -50, 50),
        native=['msort', 'msort_merge', 'isort'],
    )
