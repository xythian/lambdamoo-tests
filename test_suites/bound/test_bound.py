"""Bound value tests (BOUND-001 onward).

wp-lambdamoo's experimental --enable-bound builds add one value type,
TYPE_BOUND (typeof() == 11), whose named subtypes come from compiled-in
providers.  Subtypes are looked up by name with bound_type(), which returns
a type handle; handle:new(@args) constructs an instance.  The providers
tested here are:

- bytes: an immutable octet sequence, compared and hashed by content
- stream: a mutable, owner-controlled byte accumulator that seal()s into bytes
- struct.cursor: a bounded reader that decodes primitives from a byte source

See README.Bound in the wp-lambdamoo branch for the full interface.
"""

import pytest

from lib.moocode import define_verb
from lib.assertions import (
    assert_moo_int,
    assert_moo_raises,
    assert_moo_string,
    assert_moo_success,
)

pytestmark = pytest.mark.bound

TYPE_BOUND = 11

BYTES = 'bound_type("bytes")'
STREAM = 'bound_type("stream")'
CURSOR = 'bound_type("struct.cursor")'


class TestBoundDetection:
    """The bound surface is present exactly when the server has it."""

    def test_bound_001_feature_and_builtins(self, client, requires_bound):
        """BOUND-001: A bound server lists "bound" in its features and has bound_type()/bound_types()."""
        ok, features = client.eval('server_version("features")')
        assert ok and '"bound"' in features, features
        for name in ("bound_type", "bound_types"):
            ok, info = client.eval(f'function_info("{name}")[1]')
            assert (ok, info) == (True, f'"{name}"')

    def test_bound_002_no_surface_without_bound(self, client, requires_no_bound):
        """BOUND-002: A server built without bound values has no bound_* builtins."""
        ok, features = client.eval('server_version("features")')
        assert ok and '"bound"' not in features, features
        assert_moo_raises(client, 'function_info("bound_type")', "E_INVARG")
        assert_moo_raises(client, 'function_info("bound_types")', "E_INVARG")


class TestTypeHandles:
    """bound_type(), bound_types() and the reflection on type handles."""

    @pytest.fixture(autouse=True)
    def _providers(self, requires_bound_type):
        requires_bound_type("bytes", "stream")

    def test_bound_010_lookup(self, client):
        """BOUND-010: bound_type() finds a subtype by name, case-insensitively."""
        assert_moo_int(client.eval(f"typeof({BYTES})"), TYPE_BOUND)
        assert_moo_string(client.eval(f"{BYTES}.name"), "bytes")
        assert_moo_string(client.eval('bound_type("BYTES").name'), "bytes")

    def test_bound_011_unknown_name(self, client):
        """BOUND-011: bound_type() raises E_INVARG for an unknown name and E_TYPE for a non-string."""
        assert_moo_raises(client, 'bound_type("no-such-type")', "E_INVARG")
        assert_moo_raises(client, "bound_type(1)", "E_TYPE")

    def test_bound_012_bound_types_lists_handles(self, run):
        """BOUND-012: bound_types() returns a handle for every registered subtype."""
        ok, names = run([
            'names = {};',
            'for h in (bound_types())',
            '  names = {@names, h.name};',
            'endfor',
            'return names;',
        ])
        assert ok, names
        for name in ('"bytes"', '"stream"'):
            assert name in names, names

    def test_bound_013_handle_reflection(self, client):
        """BOUND-013: A handle is owned by #0, is available, and its .class is a handle for the same subtype."""
        assert assert_moo_success(client.eval(f"{BYTES}.owner")) == "#0"
        assert_moo_int(client.eval(f"{BYTES}.available"), 1)
        assert_moo_string(client.eval(f"{BYTES}.class.name"), "bytes")

    def test_bound_014_handles_compare_by_subtype(self, client):
        """BOUND-014: Handles for one subtype are equal, so value.class == bound_type(name) tests a value's subtype."""
        assert_moo_int(client.eval(f"{BYTES} == {BYTES}"), 1)
        assert_moo_int(client.eval(f'bound_type("BYTES") == {BYTES}'), 1)
        assert_moo_int(client.eval(f"{BYTES}:new().class == {BYTES}"), 1)
        assert_moo_int(client.eval(f"{BYTES} == {STREAM}"), 0)
        assert_moo_int(client.eval(f"{STREAM}:new().class == {BYTES}"), 0)

    def test_bound_015_verbs_and_properties(self, client):
        """BOUND-015: handle:verbs() and handle:properties() list the instance interface."""
        assert assert_moo_success(client.eval(f"{BYTES}:verbs()")) == '{"binary_string", "string"}'
        assert assert_moo_success(client.eval(f"{BYTES}:properties()")) == '{"length"}'
        assert assert_moo_success(client.eval(f"{STREAM}:properties()")) == '{"length", "sealed"}'
        verbs = assert_moo_success(client.eval(f"{STREAM}:verbs()"))
        for verb in ("append_text", "append_binary", "append_bytes", "clear", "seal", "read"):
            assert f'"{verb}"' in verbs, verbs

    def test_bound_016_rendering(self, client):
        """BOUND-016: tostr() and toliteral() render instances and handles without their contents."""
        assert_moo_string(client.eval(f'tostr({BYTES}:new("hi"))'), "{bound bytes}")
        assert_moo_string(client.eval(f"tostr({BYTES})"), "{bound bytes class}")
        assert_moo_string(client.eval(f'toliteral({BYTES}:new("hi"))'), "[[bound bytes]]")
        assert_moo_string(client.eval(f'toliteral({{{BYTES}:new("hi")}})'), "{[[bound bytes]]}")

    def test_bound_017_unknown_members(self, client):
        """BOUND-017: Unknown properties and verbs raise E_PROPNF and E_VERBNF."""
        assert_moo_raises(client, f'{BYTES}:new("hi").nosuch', "E_PROPNF")
        assert_moo_raises(client, f'{BYTES}:new("hi"):nosuch()', "E_VERBNF")

    def test_bound_018_read_only_properties(self, run):
        """BOUND-018: Built-in instance properties can't be assigned."""
        assert run([
            f's = {STREAM}:new();',
            'return {`s.length = 1 ! ANY\', `s.owner = #1 ! ANY\'};',
        ]) == (True, "{E_PERM, E_PROPNF}")

    def test_bound_019_instances_are_false(self, client):
        """BOUND-019: Bound values are false in a condition, like objects and errors."""
        assert_moo_int(client.eval(f'{BYTES}:new("hi") ? 1 | 0'), 0)


class TestBytes:
    """The immutable bytes subtype."""

    @pytest.fixture(autouse=True)
    def _providers(self, requires_bound_type):
        requires_bound_type("bytes")

    @pytest.mark.parametrize("args", ['0, 1, 255', '"~00~01~ff"', '{0, {1, 255}}', '0, "~01", {255}'])
    def test_bound_030_constructor_forms(self, client, args):
        """BOUND-030: The constructor takes integers, MOO binary strings and nested lists of them."""
        assert_moo_string(client.eval(f"{BYTES}:new({args}):binary_string()"), "~00~01~ff")

    def test_bound_031_empty(self, client):
        """BOUND-031: bytes:new() with no arguments is empty."""
        assert_moo_int(client.eval(f"{BYTES}:new().length"), 0)
        assert_moo_string(client.eval(f"{BYTES}:new():binary_string()"), "")

    @pytest.mark.parametrize("arg, error", [
        ("-1", "E_INVARG"),
        ("256", "E_INVARG"),
        ("1.0", "E_TYPE"),
        ("#1", "E_TYPE"),
    ])
    def test_bound_032_constructor_rejects(self, client, arg, error):
        """BOUND-032: Integers outside 0..255 and non-byte values are rejected."""
        assert_moo_raises(client, f"{BYTES}:new({arg})", error)

    def test_bound_033_length(self, client):
        """BOUND-033: .length is the raw octet count, not the binary-string length."""
        assert_moo_int(client.eval(f'{BYTES}:new("~00~01~ff").length'), 3)
        assert_moo_int(client.eval(f'{BYTES}:new("abc", {{1, 2}}).length'), 5)

    def test_bound_034_string_decodes_utf8(self, client, requires_unicode):
        """BOUND-034: string() decodes the octets as UTF-8 by default."""
        assert_moo_string(client.eval(f'{BYTES}:new("caf~c3~a9"):string()'), "café")

    def test_bound_035_string_with_encoding(self, client, requires_unicode):
        """BOUND-035: string(encoding) decodes with the named encoding."""
        assert_moo_string(client.eval(f'{BYTES}:new("h~00i~00"):string("UTF-16LE")'), "hi")
        assert_moo_string(client.eval(f'{BYTES}:new(233):string("ISO-8859-1")'), "é")

    @pytest.mark.parametrize("args, encoding", [
        ("255", ""),
        ("104, 0, 105", ""),
        ('"hi"', '"no-such-encoding"'),
    ])
    def test_bound_036_string_rejects(self, client, args, encoding):
        """BOUND-036: string() raises E_INVARG for malformed input, a NUL in the result, or an unknown encoding."""
        assert_moo_raises(client, f"{BYTES}:new({args}):string({encoding})", "E_INVARG")

    def test_bound_037_equality_by_content(self, client):
        """BOUND-037: Distinct bytes values are equal exactly when their octets are."""
        assert_moo_int(client.eval(f'{BYTES}:new("hi") == {BYTES}:new(104, 105)'), 1)
        assert_moo_int(client.eval(f'{BYTES}:new("hi") == {BYTES}:new("ho")'), 0)
        assert_moo_int(client.eval(f'{BYTES}:new("hi") == "hi"'), 0)
        assert_moo_int(client.eval(f'{BYTES}:new("hi") in {{1, {BYTES}:new("hi")}}'), 2)

    def test_bound_038_value_hash_by_content(self, client):
        """BOUND-038: value_hash() agrees with equality: same octets, same hash; different octets, different hash."""
        assert_moo_int(client.eval(f'value_hash({BYTES}:new("hi")) == value_hash({BYTES}:new(104, 105))'), 1)
        assert_moo_int(client.eval(f'value_hash({BYTES}:new("hi")) == value_hash({BYTES}:new("ho"))'), 0)

    def test_bound_039_owner_is_constructor(self, client):
        """BOUND-039: A new value is owned by the programmer that constructed it."""
        assert assert_moo_success(client.eval(f"{BYTES}:new().owner")) == \
            assert_moo_success(client.eval("player"))

    def test_bound_040_immutable(self, client):
        """BOUND-040: bytes has no mutating verbs and its length can't be assigned."""
        assert_moo_raises(client, f'{BYTES}:new("hi"):append_text("x")', "E_VERBNF")
        assert_moo_raises(client, f'({BYTES}:new("hi").length = 3)', "E_PERM")


class TestStream:
    """The mutable stream subtype and seal()."""

    @pytest.fixture(autouse=True)
    def _providers(self, requires_bound_type):
        requires_bound_type("bytes", "stream")

    def test_bound_050_new_stream_is_empty(self, client):
        """BOUND-050: A new stream is empty and open."""
        assert assert_moo_success(client.eval(f"{{{STREAM}:new().length, {STREAM}:new().sealed}}")) == "{0, 0}"

    def test_bound_051_appends_return_byte_counts(self, run):
        """BOUND-051: append_binary(), append_bytes() and append_text() return the octets each added."""
        assert run([
            f's = {STREAM}:new();',
            'a = s:append_binary("~00~ff");',
            'b = s:append_bytes(1, {2, "~03"});',
            'c = s:append_text({104, "i"});',
            'return {a, b, c, s.length, s:binary_string()};',
        ]) == (True, '{2, 3, 2, 7, "~00~ff~01~02~03hi"}')

    def test_bound_052_append_text_encodes(self, run, requires_unicode):
        """BOUND-052: append_text() encodes with the stream's default encoding or the one given."""
        assert run([
            f's = {STREAM}:new("UTF-16LE");',
            'a = s:append_text("hi");',
            'b = s:append_text("é", "UTF-8");',
            'return {a, b, s:binary_string()};',
        ]) == (True, '{4, 2, "h~00i~00~c3~a9"}')

    def test_bound_053_string_uses_default_encoding(self, run, requires_unicode):
        """BOUND-053: string() decodes with the stream's default encoding unless one is given."""
        assert run([
            f's = {STREAM}:new("UTF-16LE");',
            's:append_text("hi");',
            'return {s:string(), `s:string("UTF-8") ! ANY\'};',
        ]) == (True, '{"hi", E_INVARG}')

    def test_bound_054_failed_append_changes_nothing(self, run):
        """BOUND-054: An append that fails part way leaves the stream unchanged."""
        assert run([
            f's = {STREAM}:new();',
            's:append_text("ab");',
            'r = `s:append_bytes(1, 256) ! ANY\';',
            'return {r, s.length, s:binary_string()};',
        ]) == (True, '{E_INVARG, 2, "ab"}')

    def test_bound_055_clear(self, run):
        """BOUND-055: clear() empties an open stream."""
        assert run([
            f's = {STREAM}:new();',
            's:append_text("abc");',
            's:clear();',
            'return {s.length, s.sealed};',
        ]) == (True, "{0, 0}")

    def test_bound_056_aliases_share_state(self, run):
        """BOUND-056: Assigning a stream copies the reference, not the contents."""
        assert run([
            f's = {STREAM}:new();',
            't = s;',
            't:append_text("ab");',
            'return {s.length, s == t};',
        ]) == (True, "{2, 1}")

    def test_bound_057_streams_compare_by_identity(self, run):
        """BOUND-057: Two distinct streams are unequal even with the same contents."""
        assert run([
            f'a = {STREAM}:new();',
            f'b = {STREAM}:new();',
            'return {a == b, a == a};',
        ]) == (True, "{0, 1}")

    def test_bound_058_seal_returns_bytes(self, run):
        """BOUND-058: seal() marks the stream sealed and returns bytes with its contents and owner."""
        assert run([
            f's = {STREAM}:new();',
            's:append_text("hello");',
            'b = s:seal();',
            f'return {{s.sealed, s.length, b.class == {BYTES}, b == {BYTES}:new("hello"), b.owner == s.owner}};',
        ]) == (True, "{1, 5, 1, 1, 1}")

    def test_bound_059_sealed_stream_is_read_only(self, run):
        """BOUND-059: After seal(), the stream stays readable but every mutation raises E_INVARG."""
        assert run([
            f's = {STREAM}:new();',
            's:append_text("x");',
            't = s;',
            's:seal();',
            'return {t.sealed, t:string(), `t:append_text("y") ! ANY\', `t:append_binary("y") ! ANY\','
            ' `t:append_bytes(1) ! ANY\', `t:clear() ! ANY\', t.length};',
        ]) == (True, '{1, "x", E_INVARG, E_INVARG, E_INVARG, E_INVARG, 1}')

    def test_bound_060_seal_is_idempotent(self, run):
        """BOUND-060: Sealing again returns equal bytes."""
        assert run([
            f's = {STREAM}:new();',
            's:append_text("x");',
            'a = s:seal();',
            'b = s:seal();',
            'return {a == b, b:string()};',
        ]) == (True, '{1, "x"}')

    def test_bound_061_read_appends_input(self, client, requires_bound):
        """BOUND-061: stream:read(player) appends the next input line and returns its byte count."""
        define_verb(client, "#0", "bound_read_line", [
            f's = {STREAM}:new();',
            'n = s:read(player);',
            'return {n, s:string()};',
        ])
        client.send(";#0:bound_read_line()")
        client.send("hello there")
        response = client.receive(timeout=2.0)
        assert '=> {11, "hello there"}' in response, response


class TestNotify:
    """Sending bound values to a connection."""

    @pytest.fixture(autouse=True)
    def _providers(self, requires_bound_type):
        requires_bound_type("bytes")

    def test_bound_070_notify_sends_bytes_as_a_line(self, client):
        """BOUND-070: notify() of bytes on a text connection sends the octets followed by a line end."""
        client.send(f';notify(player, {BYTES}:new("bytes line"))')
        response = client.receive(timeout=1.0)
        assert "bytes line\r\n" in response or "bytes line\n" in response, repr(response)

    def test_bound_071_notify_rejects_streams(self, client, requires_bound_type):
        """BOUND-071: notify() raises E_TYPE for a bound value without an output view, such as a stream."""
        requires_bound_type("stream")
        assert_moo_raises(client, f"notify(player, {STREAM}:new())", "E_TYPE")


class TestStructCursor:
    """struct.cursor: a bounded reader over a bytes source."""

    @pytest.fixture(autouse=True)
    def _providers(self, requires_bound_type):
        requires_bound_type("bytes", "struct.cursor")

    def cursor(self, *octets):
        return f"{CURSOR}:new({BYTES}:new({', '.join(str(o) for o in octets)}))"

    def test_bound_080_integer_codecs(self, run):
        """BOUND-080: Integer codecs decode with their width, sign and byte order, and advance the position."""
        assert run([
            f'c = {self.cursor(1, 2, 3, 4, 255, 255, 254)};',
            'return {c:read("u2be"), c.position, c:read("u2le"), c:read("i2be"), c:read("i1"), c.remaining};',
        ]) == (True, "{258, 2, 1027, -1, -2, 0}")

    def test_bound_081_eight_byte_limits(self, run, requires_i64):
        """BOUND-081: i8 reaches the full 64-bit range; a u8 above the server's maximum raises E_RANGE."""
        assert run([
            f'c = {self.cursor(255, 255, 255, 255, 255, 255, 255, 127, 128, 0, 0, 0, 0, 0, 0, 0)};',
            'a = c:read("i8le");',
            'b = c:read("i8be");',
            'c:seek(0);',
            'd = c:read("u8le");',
            'c:seek(0);',
            'c:skip(8);',
            'return {a, b, d, c.position, `c:read("u8be") ! ANY\', c.position};',
        ]) == (True, "{9223372036854775807, -9223372036854775808, 9223372036854775807, 8, E_RANGE, 8}")

    def test_bound_082_float_codecs(self, run):
        """BOUND-082: f8le/f4be decode IEEE 754 values."""
        assert run([
            f'c = {self.cursor(0, 0, 0, 0, 0, 0, 240, 63, 64, 32, 0, 0)};',
            'return {c:read("f8le"), c:read("f4be")};',
        ]) == (True, "{1.0, 2.5}")

    def test_bound_083_errors_leave_position(self, run):
        """BOUND-083: Exhausted input, bad codecs and bad seeks raise an error without moving the cursor."""
        assert run([
            f'c = {self.cursor(1, 2, 3)};',
            'c:read("u1");',
            'return {`c:read("u4be") ! ANY\', `c:read("u3") ! ANY\', `c:read("u2") ! ANY\','
            ' `c:seek(4) ! ANY\', c.position};',
        ]) == (True, "{E_RANGE, E_INVARG, E_INVARG, E_RANGE, 1}")

    def test_bound_084_seek_skip_bytes(self, run):
        """BOUND-084: seek(), skip() and bytes(n) move through the source; bytes(n) copies into a bytes value."""
        assert run([
            f'c = {self.cursor(10, 11, 12, 13, 14)};',
            'c:seek(3);',
            'c:skip(-2);',
            'b = c:bytes(3);',
            f'return {{b == {BYTES}:new(11, 12, 13), c.position, c.remaining}};',
        ]) == (True, "{1, 4, 1}")

    def test_bound_085_window(self, run):
        """BOUND-085: new(source, start, length) reads only that window, with positions relative to it."""
        assert run([
            f'src = {BYTES}:new(9, 9, 1, 2, 3, 9);',
            f'c = {CURSOR}:new(src, 2, 3);',
            'return {c.length, c:read("u1"), c:read("u2be"), c.remaining, `c:read("u1") ! ANY\','
            f' `{CURSOR}:new(src, 5, 3) ! ANY\'}};',
        ]) == (True, "{3, 1, 515, 0, E_RANGE, E_RANGE}")

    def test_bound_086_align_and_subcursor(self, run):
        """BOUND-086: align() rounds the position up; subcursor(n) makes a bounded child and skips past it."""
        assert run([
            f'c = {self.cursor(1, 2, 3, 4, 5, 6)};',
            'c:read("u1");',
            'c:align(4);',
            'p = c.position;',
            'c:seek(1);',
            'sub = c:subcursor(2);',
            'return {p, c.position, sub.length, sub:read("u2be"), sub.remaining, c:read("u1")};',
        ]) == (True, "{4, 3, 2, 515, 0, 4}")

    def test_bound_087_source_must_be_bytes(self, client, requires_bound_type):
        """BOUND-087: The source must be a bound value with an immutable byte source."""
        requires_bound_type("stream")
        assert_moo_raises(client, f'{CURSOR}:new("not bound")', "E_TYPE")
        assert_moo_raises(client, f"{CURSOR}:new({STREAM}:new())", "E_INVARG")


class TestPermissions:
    """Owner-only operations on bound values."""

    def test_bound_090_stream_mutation_is_owner_only(self, wizard_and_programmer, requires_bound_type):
        """BOUND-090: Only a stream's owner or a wizard can append to it; anyone can read it."""
        requires_bound_type("stream")
        wiz, prog = wizard_and_programmer
        assert_moo_success(wiz.eval('add_property(#0, "bound_perm_stream", 0, {#3, "rw"})'))
        assert_moo_success(wiz.eval(f"#0.bound_perm_stream = {STREAM}:new()"))
        assert_moo_success(wiz.eval('#0.bound_perm_stream:append_text("ok")'))
        assert_moo_raises(prog, '#0.bound_perm_stream:append_text("no")', "E_PERM")
        assert_moo_raises(prog, "#0.bound_perm_stream:seal()", "E_PERM")
        assert_moo_string(prog.eval("#0.bound_perm_stream:string()"), "ok")
        assert_moo_int(prog.eval("#0.bound_perm_stream.length"), 2)
