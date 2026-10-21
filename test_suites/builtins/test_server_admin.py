"""Server administration builtins (ADMIN-001 onward).

Covers listen, unlisten, listeners, server_log, shutdown, db_disk_size,
memory_usage, verb_cache_stats, log_cache_stats, buffered_output_length,
output_delimiters, flush_input and disassemble, including the wizard-only
checks.
"""

import re
import socket
import time

import pytest

from lib.assertions import (
    assert_moo_int,
    assert_moo_raises,
    assert_moo_success,
)
from lib.moocode import define_verb


def wait_for_log(server, text, timeout=3.0):
    """Wait until text appears in the server log; return whether it did."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if text in server.get_log_contents():
            return True
        time.sleep(0.05)
    return False


def read_until(sock, text, timeout=3.0):
    """Read from a socket until text is seen or the timeout passes; return what was read."""
    sock.settimeout(0.1)
    data = b""
    deadline = time.monotonic() + timeout
    while text.encode() not in data and time.monotonic() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            break
        data += chunk
    return data.decode(errors="replace")


class TestListeners:
    """listen(), unlisten() and listeners()."""

    def test_admin_001_listen_on_ephemeral_port(self, client):
        """ADMIN-001: listen(obj, 0) picks a free port, returns it, and listeners() shows it."""
        obj = assert_moo_success(client.eval("create(#1)"))
        port = int(assert_moo_success(client.eval(f"listen({obj}, 0)")))
        assert port > 0
        assert_moo_int(client.eval(f"{{{obj}, {port}, 0}} in listeners() > 0"), 1)
        assert_moo_int(client.eval(f"unlisten({port})"), 0)
        assert_moo_int(client.eval(f"{{{obj}, {port}, 0}} in listeners()"), 0)

    def test_admin_002_listener_uses_its_object(self, client):
        """ADMIN-002: Connections to a listener are handled by the listening object's do_login_command."""
        obj = assert_moo_success(client.eval("create(#1)"))
        define_verb(client, obj, "do_login_command", ['notify(player, "via listener: " + argstr);'])
        port = int(assert_moo_success(client.eval(f"listen({obj}, 0)")))
        with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
            sock.sendall(b"hello there\r\n")
            assert "via listener: hello there" in read_until(sock, "hello there")

    def test_admin_003_print_messages_flag(self, client):
        """ADMIN-003: The third argument is recorded; only with it set does the server send "*** Connected ***"."""
        obj = assert_moo_success(client.eval("create(#1)"))
        guest = assert_moo_success(client.eval("create(#1)"))
        assert_moo_success(client.eval(f"set_player_flag({guest}, 1)"))
        define_verb(client, obj, "do_login_command", [f"return {guest};"])
        quiet = int(assert_moo_success(client.eval(f"listen({obj}, 0)")))
        loud = int(assert_moo_success(client.eval(f"listen({obj}, 0, 1)")))
        assert_moo_int(client.eval(f"{{{obj}, {loud}, 1}} in listeners() > 0"), 1)
        with socket.create_connection(("127.0.0.1", loud), timeout=3) as sock:
            sock.sendall(b"connect\r\n")
            assert "*** Connected ***" in read_until(sock, "***")
            assert_moo_int(client.eval(f"{guest} in connected_players() > 0"), 1)
        with socket.create_connection(("127.0.0.1", quiet), timeout=3) as sock:
            sock.sendall(b"connect\r\n")
            assert "***" not in read_until(sock, "***", timeout=0.5)
            assert_moo_int(client.eval(f"{guest} in connected_players() > 0"), 1)

    def test_admin_004_unlisten_closes_port(self, client):
        """ADMIN-004: After unlisten() the port refuses connections."""
        obj = assert_moo_success(client.eval("create(#1)"))
        port = int(assert_moo_success(client.eval(f"listen({obj}, 0)")))
        assert_moo_success(client.eval(f"unlisten({port})"))
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()

    def test_admin_005_listen_errors(self, client):
        """ADMIN-005: An invalid object or a port already listened on is E_INVARG; unlisten of an unknown port too."""
        obj = assert_moo_success(client.eval("create(#1)"))
        port = assert_moo_success(client.eval(f"listen({obj}, 0)"))
        assert_moo_raises(client, f"listen({obj}, {port})", "E_INVARG")
        assert_moo_raises(client, "listen(#999999, 0)", "E_INVARG")
        assert_moo_raises(client, f'listen({obj}, "port")', "E_TYPE")
        assert_moo_raises(client, "unlisten(1)", "E_INVARG")

    def test_admin_006_wizard_only(self, wizard_and_programmer):
        """ADMIN-006: listen and unlisten are wizard-only; listeners() is not."""
        wiz, prog = wizard_and_programmer
        mine = assert_moo_success(wiz.eval("create(#1, #4)"))
        assert_moo_raises(prog, f"listen({mine}, 0)", "E_PERM")
        port = assert_moo_success(wiz.eval("listeners()[1][2]"))
        assert_moo_raises(prog, f"unlisten({port})", "E_PERM")
        assert_moo_success(prog.eval("listeners()"))


class TestLogging:
    """server_log() and log_cache_stats()."""

    def test_admin_010_server_log(self, client, server):
        """ADMIN-010: server_log writes a "> " line to the log, marked as an error when asked."""
        assert_moo_int(client.eval('server_log("plain log line")'), 0)
        assert_moo_int(client.eval('server_log("error log line", 1)'), 0)
        assert wait_for_log(server, "> error log line")
        log = server.get_log_contents()
        assert re.search(r"^\S.*: > plain log line$", log, re.M)
        assert re.search(r"^\S.*: \*\*\* > error log line$", log, re.M)

    def test_admin_011_log_cache_stats(self, client, server):
        """ADMIN-011: log_cache_stats() writes the verb cache summary to the log."""
        assert_moo_int(client.eval("log_cache_stats()"), 0)
        assert wait_for_log(server, "cache")

    def test_admin_012_wizard_only(self, wizard_and_programmer):
        """ADMIN-012: The logging and cache statistics builtins are wizard-only."""
        _, prog = wizard_and_programmer
        for expr in ('server_log("x")', "log_cache_stats()", "verb_cache_stats()"):
            assert_moo_raises(prog, expr, "E_PERM")


class TestStatistics:
    """db_disk_size(), memory_usage() and verb_cache_stats()."""

    def test_admin_020_db_disk_size(self, client):
        """ADMIN-020: db_disk_size() is the size of the database file read at startup, in bytes."""
        assert_moo_int(client.eval("db_disk_size() > 100"), 1)

    def test_admin_021_memory_usage(self, client):
        """ADMIN-021: memory_usage() is a list (empty when the allocator doesn't report)."""
        assert_moo_int(client.eval("typeof(memory_usage()) == LIST"), 1)

    def test_admin_022_verb_cache_stats(self, client):
        """ADMIN-022: verb_cache_stats() is {hits, negative hits, misses, generations, histogram}."""
        stats = assert_moo_success(client.eval(
            "{length(verb_cache_stats()), typeof(verb_cache_stats()[5]), length(verb_cache_stats()[5])}"))
        assert stats == "{5, 4, 17}"

    def test_admin_023_verb_cache_hits_grow(self, client):
        """ADMIN-023: Calling the same verb again counts as a cache hit."""
        obj = assert_moo_success(client.eval("create(#1)"))
        define_verb(client, obj, "v", ["return 1;"])
        client.eval(f"{obj}:v()")
        before = int(assert_moo_success(client.eval("verb_cache_stats()[1]")))
        client.eval(f"{{{obj}:v(), {obj}:v(), {obj}:v()}}")
        assert int(assert_moo_success(client.eval("verb_cache_stats()[1]"))) >= before + 3


class TestConnectionBuffers:
    """buffered_output_length(), output_delimiters() and flush_input()."""

    def test_admin_030_buffered_output_length(self, client):
        """ADMIN-030: With no argument it is the buffer limit; for a connection, the bytes waiting to be sent."""
        assert_moo_int(client.eval("buffered_output_length() > 0"), 1)
        assert_moo_int(client.eval("buffered_output_length(player) >= 0"), 1)

    def test_admin_031_buffered_output_length_errors(self, wizard_and_programmer):
        """ADMIN-031: A non-connection is E_INVARG; another player's connection is E_PERM for a programmer."""
        wiz, prog = wizard_and_programmer
        assert_moo_raises(wiz, "buffered_output_length(#1)", "E_INVARG")
        assert_moo_raises(prog, "buffered_output_length(#3)", "E_PERM")
        assert_moo_int(prog.eval("buffered_output_length(#4) >= 0"), 1)

    def test_admin_032_output_delimiters_default(self, client):
        """ADMIN-032: Without PREFIX or SUFFIX commands the delimiters are empty."""
        assert assert_moo_success(client.eval("output_delimiters(player)")) == '{"", ""}'

    def test_admin_033_output_delimiters_errors(self, wizard_and_programmer):
        """ADMIN-033: Another player's delimiters are E_PERM; a player not connected is E_INVARG."""
        wiz, prog = wizard_and_programmer
        assert_moo_raises(prog, "output_delimiters(#3)", "E_PERM")
        assert_moo_raises(wiz, "output_delimiters(#5)", "E_INVARG")

    def test_admin_034_flush_input_discards_pending(self, client):
        """ADMIN-034: flush_input discards input queued behind the running task."""
        result = client.eval('{force_input(player, ";notify(player, \\"SHOULD NOT RUN\\")"), flush_input(player)}')
        assert assert_moo_success(result) == "{0, 0}"
        assert "SHOULD NOT RUN" not in client.receive(timeout=0.5)

    def test_admin_035_flush_input_messages(self, client):
        """ADMIN-035: flush_input(conn, 1) tells the player which lines were thrown away."""
        client.send(';{force_input(player, "discarded line"), flush_input(player, 1)}')
        text = client.receive(timeout=1.0)
        assert ">> Flushing the following pending input:" in text
        assert ">>     discarded line" in text
        assert ">> (Done flushing)" in text

    def test_admin_036_flush_with_nothing_pending(self, client):
        """ADMIN-036: flush_input(conn, 1) with nothing queued says so."""
        client.send(";flush_input(player, 1)")
        text = client.receive(timeout=1.0)
        assert "No pending input to flush" in text

    def test_admin_037_force_input_at_front(self, client):
        """ADMIN-037: force_input(conn, line, 1) puts the line ahead of earlier queued input."""
        client.eval('{force_input(player, ";notify(player, \\"SECOND\\")", 1), '
                    'force_input(player, ";notify(player, \\"FIRST\\")", 1)}')
        text = client.receive(timeout=1.0)
        assert text.index("FIRST") < text.index("SECOND")

    def test_admin_038_programmer_cannot_touch_others_input(self, wizard_and_programmer):
        """ADMIN-038: flush_input and force_input on another player's connection are E_PERM."""
        _, prog = wizard_and_programmer
        assert_moo_raises(prog, "flush_input(#3)", "E_PERM")
        assert_moo_raises(prog, 'force_input(#3, "x")', "E_PERM")


class TestShutdown:
    """shutdown()."""

    def test_admin_040_shutdown(self, client, server):
        """ADMIN-040: shutdown(msg) tells connected players, logs who asked, and the server exits."""
        client.send(';shutdown("for testing")')
        text = client.receive(timeout=2.0)
        assert "*** Shutting down: shutdown() called by Wizard (#3): for testing ***" in text
        server.process.wait(timeout=10)
        assert "shutdown() called by Wizard (#3): for testing" in server.get_log_contents()
        assert server.output_db.exists()

    def test_admin_041_shutdown_needs_wizard(self, wizard_and_programmer, multiplayer_server):
        """ADMIN-041: shutdown() is wizard-only."""
        _, prog = wizard_and_programmer
        assert_moo_raises(prog, "shutdown()", "E_PERM")
        assert multiplayer_server.is_running()


DISASSEMBLY_SOURCE = [
    "x = {1, \"s\", #3, E_PERM};",
    "for i in [1..3]",
    "  x[i] = i * 2;",
    "endfor",
    "for item in (x)",
    "endfor",
    "y = `x[9] ! E_RANGE => 0';",
    "try",
    "  fork t (0)",
    "    return;",
    "  endfork",
    "except e (ANY)",
    "endtry",
    "{a, ?b = 3, @c} = x;",
    "return x[1..2];",
]


class TestDisassemble:
    """disassemble()."""

    @pytest.fixture
    def obj(self, client):
        obj = assert_moo_success(client.eval("create(#1)"))
        define_verb(client, obj, "dv", DISASSEMBLY_SOURCE)
        return obj

    def test_admin_050_listing_shape(self, client, obj):
        """ADMIN-050: disassemble() returns lines with a header, the main vector and each fork vector."""
        lines = assert_moo_success(client.eval(f'disassemble({obj}, "dv")'))
        for text in ("Language version number:", "Main code vector:", "Forked code vector 0:"):
            assert text in lines
        assert_moo_int(client.eval(f'typeof(disassemble({obj}, "dv")[1]) == STR'), 1)

    @pytest.mark.parametrize("opcode", [
        "PUSH_LITERAL \\\"s\\\"", "PUSH_LITERAL #3", "PUSH_LITERAL E_PERM", "FOR_RANGE i", "FOR_LIST",
        "INDEXSET", "CATCH", "TRY_EXCEPT 1", "FORK_NAMED 0 t", "SCATTER 3/1/3", "RANGE", "RETURN", "DONE",
    ])
    def test_admin_051_opcodes_named(self, client, obj, opcode):
        """ADMIN-051: Each construct in the source shows up as its named opcode."""
        listing = assert_moo_success(client.eval(f'disassemble({obj}, "dv")'))
        assert opcode.replace("\\", "") in listing.replace("\\", "")

    def test_admin_052_numeric_descriptor(self, client, obj):
        """ADMIN-052: The verb can be named by its 1-based index."""
        assert_moo_int(client.eval(f'disassemble({obj}, 1) == disassemble({obj}, "dv")'), 1)

    def test_admin_053_errors(self, client, obj):
        """ADMIN-053: A missing verb is E_VERBNF, an invalid object E_INVARG, a bad descriptor E_TYPE."""
        assert_moo_raises(client, f'disassemble({obj}, "nope")', "E_VERBNF")
        assert_moo_raises(client, 'disassemble(#999999, "dv")', "E_INVARG")
        assert_moo_raises(client, f"disassemble({obj}, {{}})", "E_TYPE")

    def test_admin_054_needs_read_permission(self, wizard_and_programmer):
        """ADMIN-054: Disassembling a verb without the r flag is E_PERM for a non-owner."""
        wiz, prog = wizard_and_programmer
        obj = assert_moo_success(wiz.eval("create(#1)"))
        define_verb(wiz, obj, "hidden", ["return 1;"], perms="x")
        assert_moo_raises(prog, f'disassemble({obj}, "hidden")', "E_PERM")
        define_verb(wiz, obj, "shown", ["return 1;"], perms="rx")
        assert_moo_success(prog.eval(f'disassemble({obj}, "shown")'))
