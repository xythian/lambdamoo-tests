"""Helpers for tests of the JIT on kruton/lambdamoo's JIT branches.

The JIT on kruton/lambdamoo's JIT branches compiles a verb once it has been
called enough times (the pool's hot threshold, 32 by default).  Tests
record results with the verb cold (interpreted), warm it up past the
threshold, let the pool rotate so region specialization can stitch
monomorphic verb calls together, and then check that the hot results are
unchanged.  Per-program entry counters are only kept while
jit_profile_detail(1) is on, so the fixture turns it on.
"""

import json
import re
import textwrap
import time
from typing import Any, Dict, Iterable, List



WARMUP_CALLS = 40

_TOKEN = re.compile(r'''
    \s*(?:
      (?P<str>"(?:[^"\\]|\\.)*")
    | (?P<float>-?\d+\.\d*(?:[eE][-+]?\d+)?|-?\d+[eE][-+]?\d+)
    | (?P<int>-?\d+)
    | (?P<obj>\#-?\d+)
    | (?P<err>E_[A-Z]+)
    | (?P<punct>[{},])
    )''', re.VERBOSE)


def parse_moo(text: str) -> Any:
    """Parse a MOO literal as printed by the server into Python values.

    Integers, floats and strings map to Python equivalents, lists to lists,
    and objects and errors to their printed form (e.g. "#1", "E_DIV").
    """
    tokens = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ValueError(f"Cannot parse MOO value at {pos}: {text!r}")
        tokens.append((m.lastgroup, m.group(m.lastgroup)))
        pos = m.end()

    def value(i):
        kind, tok = tokens[i]
        if kind == 'punct' and tok == '{':
            items = []
            i += 1
            if tokens[i] == ('punct', '}'):
                return items, i + 1
            while True:
                item, i = value(i)
                items.append(item)
                if tokens[i] == ('punct', ','):
                    i += 1
                elif tokens[i] == ('punct', '}'):
                    return items, i + 1
                else:
                    raise ValueError(f"Unexpected token {tokens[i]!r} in {text!r}")
        if kind == 'int':
            return int(tok), i + 1
        if kind == 'float':
            return float(tok), i + 1
        if kind == 'str':
            return json.loads(tok), i + 1
        if kind in ('obj', 'err'):
            return tok, i + 1
        raise ValueError(f"Unexpected token {tok!r} in {text!r}")

    result, end = value(0)
    if end != len(tokens):
        raise ValueError(f"Trailing data in MOO value: {text!r}")
    return result


class Raw(str):
    """MOO source inserted verbatim by moo_literal, e.g. Raw("#1") or Raw("E_DIV")."""


def moo_literal(value: Any) -> str:
    """Format ints, floats, strings, Raw source and (nested) lists as a MOO literal."""
    if isinstance(value, Raw):
        return str(value)
    if isinstance(value, bool):
        raise TypeError("MOO has no booleans")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple, bytes)):
        return '{' + ', '.join(moo_literal(v) for v in value) + '}'
    raise TypeError(f"Cannot format {value!r} as MOO")


class JitHarness:
    """Defines verbs on #0 and inspects their JIT state."""

    def __init__(self, client, log_file=None):
        self.client = client
        self.log_file = log_file
        self.define('__jit_stats', '''
            {vname, keys} = args;
            meta = verb_info(this, vname, 1)[4];
            r = {};
            for k in (keys)
              v = E_INVARG;
              for p in (meta)
                if (p[1] == k)
                  v = p[2];
                endif
              endfor
              r = {@r, v};
            endfor
            return r;
        ''')
        self.value('jit_profile_detail(1)')

    def define(self, name: str, source: str) -> None:
        """Add (or reprogram) verb #0:<name> with the given MOO source."""
        lines = [line for line in textwrap.dedent(source).strip().splitlines() if line.strip()]
        ok, _ = self.client.eval(f'verb_info(#0, {json.dumps(name)})')
        if not ok:
            added = self.client.eval(
                f'add_verb(#0, {{player, "rxd", {json.dumps(name)}}}, {{"this", "none", "this"}})')
            assert added[0], f"add_verb {name} failed: {added[1]}"
        result = self.client.eval(f'set_verb_code(#0, {json.dumps(name)}, {moo_literal(lines)})')
        assert result == (True, '{}'), f"set_verb_code {name} failed: {result[1]}"

    def eval(self, expr: str, timeout: float = 30):
        """Evaluate an expression, returning the client's (success, text) pair.

        If the server panicked, the panic lines from its log are appended.
        """
        ok, result = self.client.eval(expr, timeout=timeout)
        if not ok and ('server panic' in result or result == '(no response)'):
            result += self.panic_log()
        return ok, result

    def value(self, expr: str, timeout: float = 30) -> Any:
        """Evaluate an expression that must succeed and parse its value."""
        ok, result = self.eval(expr, timeout=timeout)
        assert ok, f"{expr} failed: {result}"
        return parse_moo(result)

    def panic_log(self) -> str:
        """Return the PANIC message and traceback from the server log, if any."""
        if not self.log_file:
            return ""
        for _ in range(20):
            try:
                with open(self.log_file, errors='replace') as f:
                    log = f.read()
            except OSError:
                return ""
            if 'PANIC-DUMPING' in log or '(End of traceback)' in log.split('*** PANIC', 1)[-1]:
                break
            time.sleep(0.1)
        if '*** PANIC' not in log:
            return ""
        panic = log[log.index('*** PANIC'):]
        lines = [line.split(': ', 1)[-1] for line in panic.splitlines()]
        end = next((i for i, line in enumerate(lines) if 'End of traceback' in line), 8)
        return "\n[server log]\n" + "\n".join(lines[:end + 1])

    def warm(self, expr: str, calls: int = WARMUP_CALLS) -> None:
        """Evaluate expr repeatedly, each time in its own task."""
        for _ in range(calls):
            self.value(expr)

    def warm_and_rotate(self, *exprs: str, calls: int = WARMUP_CALLS) -> None:
        """Warm up, rotate the pool, then warm up again.

        Rotation starts a new pool generation, retiring compiled code so that
        the next warm-up recompiles it with region specialization (stitching
        of monomorphic verb calls) informed by the first warm-up's profile.
        """
        for expr in exprs:
            self.warm(expr, calls)
        self.rotate()
        for expr in exprs:
            self.warm(expr, calls)

    def rotate(self) -> None:
        """Rotate the JIT pool so pending region specializations are compiled."""
        self.value('jit_pool_rotate()')

    def stats(self, name: str, keys: Iterable[str]) -> Dict[str, Any]:
        """Return the named fields of verb_info(#0, name, 1)'s JIT metadata."""
        keys = list(keys)
        values = self.value(f'#0:__jit_stats({json.dumps(name)}, {moo_literal(keys)})')
        return dict(zip(keys, values))

    def assert_native(self, *names: str) -> None:
        """Assert each verb has been compiled and its native code entered.

        A verb need not be compiled right now: after a pool rotation a callee
        whose calls were stitched into its callers may never get hot again.
        """
        for name in names:
            s = self.stats(name, ['state', 'compile_successes', 'entries', 'reason', 'diagnostic'])
            assert s['compile_successes'] >= 1, f"#0:{name} was never compiled: {s}"
            assert s['entries'] > 0, f"#0:{name} compiled but native code never entered: {s}"


def expect_calls(harness: JitHarness, verb: str, inputs: List[Any]) -> List[Any]:
    """Call #0:<verb>(@input) for each input, capturing {1, value} or {0, error}."""
    driver = f'__drive_{verb}'
    harness.define(driver, f'''
        results = {{}};
        for a in (args[1])
          try
            r = {{1, this:{verb}(@a)}};
          except e (ANY)
            r = {{0, e[1]}};
          endtry
          results = {{@results, r}};
        endfor
        return results;
    ''')
    return harness.value(f'#0:{driver}({moo_literal(inputs)})')
