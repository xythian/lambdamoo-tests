"""Hashing, crypt() and MOO binary string builtins (HASH-001 onward).

MOO binary strings write a byte that is not printable ASCII as ~XX (two hex
digits) and a literal tilde as ~7E.  string_hash(), binary_hash() and
value_hash() return the MD5 digest of their input as 32 uppercase hex digits.
"""

import hashlib

import pytest

from lib.moocode import define_verb
from lib.assertions import (
    assert_moo_int,
    assert_moo_raises,
    assert_moo_string,
    assert_moo_success,
)


@pytest.fixture
def run(client):
    """Return a function that runs MOO statements as a verb on a fresh object and returns the eval result."""
    obj = assert_moo_success(client.eval('create(#1)'))
    counter = [0]

    def _run(lines):
        counter[0] += 1
        name = f"run{counter[0]}"
        define_verb(client, obj, name, lines)
        return client.eval(f'{obj}:{name}()')
    return _run


@pytest.fixture
def small_string_limit(client):
    """Lower max_string_concat to 2000 and make E_QUOTA catchable; returns the limit."""
    limit = 2000
    if '"server_options"' not in assert_moo_success(client.eval('properties(#0)')):
        assert_moo_success(client.eval('add_property(#0, "server_options", create(#1), {player, "r"})'))
    assert_moo_success(client.eval(f'add_property(#0.server_options, "max_string_concat", {limit}, {{player, "r"}})'))
    assert_moo_success(client.eval('add_property(#0.server_options, "max_concat_catchable", 1, {player, "r"})'))
    assert_moo_success(client.eval('add_property(#0.server_options, "fg_ticks", 10000000, {player, "r"})'))
    assert_moo_success(client.eval('load_server_options()'))
    return limit


def md5(data: bytes) -> str:
    """MD5 digest in the form the server returns."""
    return hashlib.md5(data).hexdigest().upper()


class TestHashes:
    """string_hash(), binary_hash() and value_hash()."""

    @pytest.mark.parametrize("text", ["", "abc", "The quick brown fox", "x" * 1000])
    def test_hash_001_string_hash(self, client, text):
        """HASH-001: string_hash() is the MD5 of the string's bytes."""
        assert_moo_string(client.eval(f'string_hash("{text}")'), md5(text.encode()))

    def test_hash_002_string_hash_non_ascii(self, client, requires_unicode):
        """HASH-002: Non-ASCII characters are hashed as their UTF-8 bytes."""
        assert_moo_string(client.eval('string_hash("é")'), md5("é".encode()))

    def test_hash_003_binary_hash_decodes_escapes(self, client):
        """HASH-003: binary_hash() hashes the bytes the binary string stands for."""
        assert_moo_string(client.eval('binary_hash("A~42~0D~0A")'), md5(b"AB\r\n"))
        assert_moo_string(client.eval('binary_hash("~00~ff")'), md5(b"\x00\xff"))
        assert_moo_string(client.eval('binary_hash("~7e")'), md5(b"~"))

    @pytest.mark.parametrize("bad", ["~zz", "~4", "~", "a~g0"])
    def test_hash_004_binary_hash_rejects_bad_escapes(self, client, bad):
        """HASH-004: A malformed ~ escape raises E_INVARG."""
        assert_moo_raises(client, f'binary_hash("{bad}")', "E_INVARG")

    @pytest.mark.parametrize("value,literal", [
        ('{1, "a"}', '{1, "a"}'),
        ("#5", "#5"),
        ("E_PERM", "E_PERM"),
        ("1.5", "1.5"),
        ('{{}, {"x", {2}}}', '{{}, {"x", {2}}}'),
    ])
    def test_hash_005_value_hash(self, client, value, literal):
        """HASH-005: value_hash() is the MD5 of the value's literal form."""
        assert_moo_string(client.eval(f"value_hash({value})"), md5(literal.encode()))

    def test_hash_006_value_hash_matches_toliteral(self, client):
        """HASH-006: value_hash(v) == string_hash(toliteral(v))."""
        assert assert_moo_success(client.eval(
            'value_hash({1, "two", #3, {4.0}}) == string_hash(toliteral({1, "two", #3, {4.0}}))')) == "1"

    @pytest.mark.parametrize("build", [
        ['v = "say \\"hi\\" \\\\ back";'],
        ['v = {};', 'for i in [1..3000]', '  v = {@v, i, tostr("s", i), #-1, E_RANGE, 1.25, {}};', 'endfor'],
        ['v = {};', 's = "";', 'for i in [1..500]', '  s = s + "0123456789";', 'endfor',
         'v = {s, {s, {s}}, s};'],
        ['v = {1};', 'for i in [1..2000]', '  v = {i, v, "\\""};', 'endfor'],
        ['v = {-9, 0.5, 1e+30, -0.0, 3.0};'],
    ], ids=["escapes", "long-flat", "long-strings", "nested", "numbers"])
    def test_hash_008_value_hash_equals_hash_of_literal(self, run, build):
        """HASH-008: value_hash(v) is string_hash(toliteral(v)) for values larger than one hashing chunk."""
        assert run(build + ['return value_hash(v) == string_hash(toliteral(v));']) == (True, "1")

    def test_hash_009_value_hash_non_ascii(self, run, requires_unicode):
        """HASH-009: Non-ASCII characters inside lists hash as their UTF-8 bytes, as in toliteral()."""
        assert run(['v = {"é", {"日本"}, "\\"é\\""};',
                    'return value_hash(v) == string_hash(toliteral(v));']) == (True, "1")

    def test_hash_010_value_hash_waif(self, run, requires_waifs):
        """HASH-010: A waif inside a list hashes as its [[class = ..., owner = ...]] literal."""
        assert run(['add_property(this, ":x", 0, {player, "rw"});',
                    'add_verb(this, {player, "rxd", "mk"}, {"this", "none", "this"});',
                    'set_verb_code(this, "mk", {"return new_waif();"});',
                    'v = {1, this:mk(), {this:mk()}};',
                    'return value_hash(v) == string_hash(toliteral(v));']) == (True, "1")

    @pytest.mark.parametrize("extra", [-2, -1, 0, 1, 2])
    def test_hash_011_value_hash_space_limit(self, run, small_string_limit, extra):
        """HASH-011: value_hash() raises E_QUOTA exactly when toliteral() of the same value does."""
        # {"xxx...", "xxx..."} has a literal 8 longer than its two strings together
        n = small_string_limit - 8 + extra
        a, b = n // 2, n - n // 2
        assert run([
            'a = "";',
            f'for i in [1..{a}]',
            '  a = a + "x";',
            'endfor',
            'b = "";',
            f'for i in [1..{b}]',
            '  b = b + "x";',
            'endfor',
            'v = {a, b};',
            'lit = `toliteral(v) ! E_QUOTA => 0\';',
            'h = `value_hash(v) ! E_QUOTA => 0\';',
            'return {lit == 0, h == 0, lit == 0 || h == string_hash(lit)};',
        ]) == (True, "{1, 1, 1}" if extra > 0 else "{0, 0, 1}")

    def test_hash_007_argument_types(self, client):
        """HASH-007: string_hash and binary_hash need strings."""
        assert_moo_raises(client, "string_hash(1)", "E_TYPE")
        assert_moo_raises(client, "binary_hash({})", "E_TYPE")
        assert_moo_raises(client, "value_hash()", "E_ARGS")


class TestCrypt:
    """crypt(password [, salt])."""

    def test_hash_010_salted_crypt_is_deterministic(self, client):
        """HASH-010: The same password and salt give the same result, which starts with the salt."""
        first = assert_moo_success(client.eval('crypt("secret", "ab")'))
        second = assert_moo_success(client.eval('crypt("secret", "ab")'))
        assert first == second
        assert first.startswith('"ab')

    def test_hash_011_result_works_as_salt(self, client):
        """HASH-011: Crypting again with the stored result as salt reproduces it (password check)."""
        assert assert_moo_success(client.eval(
            'crypt("secret", crypt("secret", "xy")) == crypt("secret", "xy")')) == "1"
        assert assert_moo_success(client.eval(
            'crypt("wrong", crypt("secret", "xy")) == crypt("secret", "xy")')) == "0"

    def test_hash_012_random_salt(self, client):
        """HASH-012: Without a salt, or with one too short, a random two-character salt is used."""
        hashed = assert_moo_success(client.eval('crypt("secret")')).strip('"')
        assert len(hashed) >= 13
        assert assert_moo_success(client.eval(f'crypt("secret", "{hashed}") == "{hashed}"')) == "1"
        short = assert_moo_success(client.eval('crypt("secret", "a")')).strip('"')
        assert len(short) >= 13

    def test_hash_013_argument_types(self, client):
        """HASH-013: crypt takes strings."""
        assert_moo_raises(client, "crypt(1)", "E_TYPE")
        assert_moo_raises(client, 'crypt("a", 1)', "E_TYPE")


class TestBinaryStrings:
    """decode_binary() and encode_binary()."""

    def test_hash_020_decode_groups_printable_runs(self, client):
        """HASH-020: Printable runs become strings; other bytes become integers."""
        result = assert_moo_success(client.eval('decode_binary("ab~0D~0Acd~FF")'))
        assert result == '{"ab", 13, 10, "cd", 255}'

    def test_hash_021_decode_fully(self, client):
        """HASH-021: With a true second argument every byte is an integer."""
        assert assert_moo_success(client.eval('decode_binary("ab~0D~0A", 1)')) == "{97, 98, 13, 10}"
        assert assert_moo_success(client.eval('decode_binary("", 1)')) == "{}"

    def test_hash_022_decode_tab_and_tilde(self, client):
        """HASH-022: Tab counts as printable, and ~7E decodes to a tilde."""
        result = assert_moo_success(client.eval('decode_binary("a~09b~7E")'))
        assert result == '{"a\tb~"}'

    def test_hash_023_decode_rejects_bad_escapes(self, client):
        """HASH-023: decode_binary of a malformed binary string raises E_INVARG."""
        assert_moo_raises(client, 'decode_binary("~q1")', "E_INVARG")

    def test_hash_024_encode(self, client):
        """HASH-024: encode_binary flattens strings, bytes and nested lists."""
        assert_moo_string(client.eval('encode_binary("ab", 13, 10, {"c", 255})'), "ab~0d~0ac~ff")
        assert_moo_string(client.eval('encode_binary("~")'), "~7e")
        assert_moo_string(client.eval("encode_binary()"), "")

    @pytest.mark.parametrize("bad", ["256", "-1", "1.0", "#1", "{300}"])
    def test_hash_025_encode_rejects_non_bytes(self, client, bad):
        """HASH-025: Integers outside 0..255 and other types raise E_INVARG."""
        assert_moo_raises(client, f"encode_binary({bad})", "E_INVARG")

    def test_hash_026_round_trip(self, client):
        """HASH-026: decode_binary(encode_binary(...)) gives back the bytes."""
        assert assert_moo_success(client.eval(
            'decode_binary(encode_binary("hi", 0, 127, 128, 255, "~"), 1)')) == \
            "{104, 105, 0, 127, 128, 255, 126}"

    def test_hash_027_non_ascii_is_utf8_bytes(self, client, requires_unicode):
        """HASH-027: A non-ASCII character in a binary string stands for its UTF-8 bytes."""
        assert assert_moo_success(client.eval('decode_binary("é")')) == "{195, 169}"
        assert_moo_string(client.eval('encode_binary("é")'), "~c3~a9")


class TestValueSizes:
    """value_bytes() and object_bytes()."""

    def test_hash_030_value_bytes_grows_with_size(self, client):
        """HASH-030: Longer strings and lists report more bytes."""
        short = int(assert_moo_success(client.eval('value_bytes("a")')))
        long_ = int(assert_moo_success(client.eval('value_bytes("' + "a" * 100 + '")')))
        assert long_ >= short + 99
        empty = int(assert_moo_success(client.eval("value_bytes({})")))
        three = int(assert_moo_success(client.eval("value_bytes({1, 2, 3})")))
        assert three > empty

    def test_hash_031_object_bytes(self, client):
        """HASH-031: object_bytes() grows when a property is added; an invalid object raises E_INVIND."""
        obj = assert_moo_success(client.eval("create(#1)"))
        before = int(assert_moo_success(client.eval(f"object_bytes({obj})")))
        assert_moo_success(client.eval(f'add_property({obj}, "blob", "' + "z" * 200 + '", {player, "r"})'))
        after = int(assert_moo_success(client.eval(f"object_bytes({obj})")))
        assert after >= before + 200
        assert_moo_raises(client, "object_bytes(#-1)", "E_INVIND")
        assert_moo_int(client.eval("typeof(object_bytes(#0))"), 0)
