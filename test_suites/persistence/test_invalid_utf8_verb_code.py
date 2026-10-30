"""Invalid UTF-8 in verb code read from the database.

Verb code is parsed straight from the database file's bytes, so it can hold
UTF-8 that network input and MOO strings never do.  The parser's decoder
subtracted 0x80 from each continuation byte before checking it, which let a
byte below 0x80 (ASCII, or EOF) through as a negative value.  The decoder then
shifted that into the code point, so a lead byte followed by ASCII swallowed
the ASCII byte into a bogus character: ``"\\xc3A"`` became U+0081, and
``"\\xc3"`` ate its closing quote.  A bad sequence must decode as U+FFFD with
the byte after it left alone.
"""

import pytest

from lib.assertions import assert_moo_success


PLACEHOLDER = b'"QQQ"'

CODE = 's = "QQQ"; r = {}; for i in [1..length(s)] r = {@r, ord(s[i])}; endfor return r;'


def code_points_after_reload(candidate_server, temp_db, tmp_path, literal):
    """Store a verb whose string literal is the raw bytes `literal`, reload, and run it.

    Returns the eval result of the verb, which lists the code points of the
    string the parser built from `literal`.
    """
    instance = candidate_server.start(database=temp_db)
    client = candidate_server.connect(instance)
    client.authenticate('Wizard')
    try:
        assert_moo_success(client.eval('add_verb(#0, {#1, "rxd", "utf_probe"}, {"this", "none", "this"})'))
        code = CODE.replace('"', '\\"')
        assert assert_moo_success(client.eval(f'set_verb_code(#0, "utf_probe", {{"{code}"}})')) == '{}'
        client.checkpoint()
    finally:
        client.close()
        saved = candidate_server.stop(instance)

    data = saved.read_bytes()
    assert data.count(PLACEHOLDER) == 1, "verb code not found in the saved database"
    patched = tmp_path / 'patched.db'
    patched.write_bytes(data.replace(PLACEHOLDER, b'"' + literal + b'"'))

    instance = candidate_server.start(database=patched)
    client = candidate_server.connect(instance)
    client.authenticate('Wizard')
    try:
        return client.eval('#0:utf_probe()')
    finally:
        client.close()
        candidate_server.stop(instance)


@pytest.mark.unicode
@pytest.mark.persistence
@pytest.mark.parametrize("literal,expected", [
    pytest.param(b'\xc3\xa9', '{233}', id="valid-two-byte"),
    pytest.param(b'\xc3A', '{65533, 65}', id="two-byte-lead-then-ascii"),
    pytest.param(b'x\xe3\x80A', '{120, 65533, 65}', id="three-byte-lead-then-ascii"),
    pytest.param(b'\xf0\x9f\x98', '{65533}', id="truncated-four-byte-at-quote"),
    pytest.param(b'\xc3', '{65533}', id="two-byte-lead-at-quote"),
])
def test_invalid_continuation_in_verb_code(candidate_server, temp_db, tmp_path, requires_unicode,
                                           literal, expected):
    """A lead byte followed by a non-continuation byte decodes as U+FFFD and keeps that byte."""
    result = code_points_after_reload(candidate_server, temp_db, tmp_path, literal)
    assert assert_moo_success(result) == expected
