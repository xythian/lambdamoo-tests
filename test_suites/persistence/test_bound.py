"""Persistence tests for bound values (experimental --enable-bound builds).

Bound values are written to the database as an envelope holding the
subtype name, schema version, owner, an opaque provider blob and a list of
referenced values.  These tests check that each provider's state survives a
checkpoint and restart, and that references to one value are still one
value afterwards.

Values are kept in properties of #0; a stream stored in two properties
must come back as one stream that both properties share.
"""

import shutil

import pytest

from lib.assertions import assert_moo_int, assert_moo_string, assert_moo_success
from lib.moocode import define_verb

pytestmark = [pytest.mark.bound, pytest.mark.persistence]

PROPS = ("b", "s", "s2", "sealed", "sealed_bytes", "c", "handle", "nested")


def write_then_read(candidate_server, minimal_db, tmp_path, setup_lines):
    """Run setup_lines as a wizard verb, checkpoint, restart, and return a client on the reloaded server.

    Args:
        candidate_server: The candidate MooServer.
        minimal_db: Test database to start from.
        tmp_path: Per-test temporary directory.
        setup_lines: Verb source that stores values in #0.bound_* properties.

    Returns:
        (client, instance) for the restarted server; the caller closes and stops them.
    """
    db_path = tmp_path / "test.db"
    shutil.copy(minimal_db, db_path)

    instance = candidate_server.start(database=db_path)
    client = candidate_server.connect(instance)
    client.authenticate("Wizard")
    try:
        for prop in PROPS:
            assert_moo_success(client.eval(f'add_property(#0, "bound_{prop}", 0, {{#3, "rw"}})'))
        define_verb(client, "#0", "bound_setup", setup_lines)
        assert_moo_success(client.eval("#0:bound_setup()"))
        assert client.checkpoint()
    finally:
        client.close()
        output_db = candidate_server.stop(instance)

    instance = candidate_server.start(database=output_db)
    client = candidate_server.connect(instance)
    client.authenticate("Wizard")
    return client, instance


@pytest.fixture
def reloaded(candidate_server, minimal_db, tmp_path, client, requires_bound):
    """A restarted server whose #0.bound_* properties were filled before a checkpoint."""
    for name in ("bytes", "stream", "struct.cursor"):
        ok, value = client.eval(f'`bound_type("{name}") ! ANY\'')
        if value == "E_INVARG":
            pytest.skip(f'Test requires the "{name}" bound type')
    reloaded_client, instance = write_then_read(candidate_server, minimal_db, tmp_path, [
        '#0.bound_b = bound_type("bytes"):new("~00~01~ff", "abc");',
        's = bound_type("stream"):new("UTF-16LE");',
        's:append_text("open");',
        '#0.bound_s = s;',
        '#0.bound_s2 = s;',
        't = bound_type("stream"):new();',
        't:append_text("done");',
        '#0.bound_sealed_bytes = t:seal();',
        '#0.bound_sealed = t;',
        'c = bound_type("struct.cursor"):new(bound_type("bytes"):new(9, 1, 2, 3, 4, 9), 1, 4);',
        'c:read("u1");',
        '#0.bound_c = c;',
        '#0.bound_handle = bound_type("bytes");',
        '#0.bound_nested = {1, {#0.bound_b}, {"k", s}};',
    ])
    yield reloaded_client
    reloaded_client.close()
    candidate_server.stop(instance)


class TestBoundPersistence:
    """Bound values survive checkpoint and restart."""

    def test_bytes_content_and_owner(self, reloaded):
        """bytes keeps its octets and owner."""
        assert_moo_string(reloaded.eval("#0.bound_b:binary_string()"), "~00~01~ffabc")
        assert_moo_int(reloaded.eval('#0.bound_b == bound_type("bytes"):new(0, 1, 255, "abc")'), 1)
        assert assert_moo_success(reloaded.eval("#0.bound_b.owner")) == "#3"

    def test_open_stream_keeps_contents_and_encoding(self, reloaded):
        """An open stream keeps its contents and default encoding and can still be appended to."""
        assert_moo_int(reloaded.eval("#0.bound_s.sealed"), 0)
        assert_moo_string(reloaded.eval("#0.bound_s:string()"), "open")
        assert_moo_int(reloaded.eval('#0.bound_s:append_text("!")'), 2)
        assert_moo_string(reloaded.eval("#0.bound_s:string()"), "open!")

    def test_stream_aliases_stay_one_stream(self, reloaded):
        """A stream stored in two properties is still one stream after reload."""
        assert_moo_success(reloaded.eval('#0.bound_s:append_text("+")'))
        assert_moo_string(reloaded.eval("#0.bound_s2:string()"), "open+")
        assert_moo_int(reloaded.eval("#0.bound_s == #0.bound_s2"), 1)

    def test_aliases_inside_lists(self, reloaded):
        """References inside nested lists resolve to the same values as the properties."""
        assert_moo_int(reloaded.eval("#0.bound_nested[2][1] == #0.bound_b"), 1)
        assert_moo_success(reloaded.eval('#0.bound_nested[3][2]:append_text("?")'))
        assert_moo_string(reloaded.eval("#0.bound_s:string()"), "open?")

    def test_sealed_stream_stays_sealed(self, reloaded):
        """A sealed stream is still sealed, and the bytes it returned keep their contents."""
        assert_moo_int(reloaded.eval("#0.bound_sealed.sealed"), 1)
        assert_moo_string(reloaded.eval("#0.bound_sealed:string()"), "done")
        assert_moo_string(reloaded.eval("#0.bound_sealed_bytes:string()"), "done")
        assert assert_moo_success(reloaded.eval('`#0.bound_sealed:append_text("x") ! ANY\'')) == "E_INVARG"

    def test_cursor_resumes_in_its_window(self, reloaded):
        """A cursor keeps its window and position and resumes reading where it stopped."""
        assert assert_moo_success(reloaded.eval("{#0.bound_c.length, #0.bound_c.position}")) == "{4, 1}"
        assert_moo_int(reloaded.eval('#0.bound_c:read("u2be")'), 0x0203)
        assert_moo_int(reloaded.eval('#0.bound_c:read("u1")'), 4)
        assert_moo_int(reloaded.eval("#0.bound_c.remaining"), 0)

    def test_type_handle(self, reloaded):
        """A stored type handle is still a handle for its subtype."""
        assert_moo_int(reloaded.eval('#0.bound_handle == bound_type("bytes")'), 1)
        assert_moo_string(reloaded.eval("tostr(#0.bound_handle)"), "{bound bytes class}")
