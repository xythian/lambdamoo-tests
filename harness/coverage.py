"""Measure which parts of the server's C source the test suite exercises.

A coverage build is configured with ``--enable-coverage``, which compiles the
server at -O0 with gcov instrumentation. The server adds its counts to the
``.gcda`` files beside each object file when it exits on SIGTERM, which is how
the test fixtures stop it. gcovr then turns those counts into reports.

The build tree has to outlive the test run, because gcovr needs the ``.gcno``
and ``.gcda`` files and the sources they refer to, so it lives in the report
directory rather than in the build cache.
"""

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from harness.build import build_from_source

# Generated sources: bison's parser and gperf's keyword table
EXCLUDED_SOURCES = [r"parser\.c", r"keywords\.c", r"y\.tab\.c"]

BUILTIN_PREFIX = "bf_"


def supports_coverage(source_dir: Path) -> bool:
    """Return whether a server source tree has the --enable-coverage option.

    Args:
        source_dir: Path to the source tree.
    """
    configure_ac = source_dir / "configure.ac"
    return configure_ac.exists() and "enable-coverage" in configure_ac.read_text(errors="replace")


def build_coverage_server(
    source_dir: Path,
    output_dir: Path,
    configure_flags: List[str],
    make_jobs: int = 4,
    reuse: bool = False,
) -> Path:
    """Copy a source tree into the report directory and build it with coverage.

    Args:
        source_dir: Server source tree to copy.
        output_dir: Report directory; the build goes in its ``build``
            subdirectory and the binary in ``bin``.
        configure_flags: Configure flags, without --enable-coverage.
        make_jobs: Number of parallel make jobs.
        reuse: Keep an existing build in output_dir instead of starting over.

    Returns:
        Path to the instrumented binary.

    Raises:
        RuntimeError: If the source tree has no --enable-coverage option.
    """
    build_dir = output_dir / "build"
    binary = output_dir / "bin" / "moo"
    if reuse and binary.exists() and build_dir.exists():
        print(f"Reusing coverage build in {build_dir}")
        return binary

    if not supports_coverage(source_dir):
        raise RuntimeError(
            f"{source_dir} has no --enable-coverage configure option; "
            "coverage needs a wp-lambdamoo tree that has it"
        )

    if build_dir.exists():
        shutil.rmtree(build_dir)
    shutil.copytree(source_dir, build_dir, symlinks=True, ignore=shutil.ignore_patterns("*.gcda"))

    flags = [f for f in configure_flags if f != "--enable-coverage"] + ["--enable-coverage"]
    return build_from_source(
        build_dir,
        binary.parent,
        configure_flags=shlex.join(flags),
        make_jobs=make_jobs,
    )


def reset_counters(build_dir: Path) -> int:
    """Delete the coverage counts left by earlier runs.

    Args:
        build_dir: The coverage build tree.

    Returns:
        Number of .gcda files removed.
    """
    removed = 0
    for gcda in build_dir.rglob("*.gcda"):
        gcda.unlink()
        removed += 1
    return removed


def run_gcovr(build_dir: Path, output_dir: Path) -> Dict[str, Path]:
    """Write text, HTML and JSON reports for a coverage build.

    Args:
        build_dir: The coverage build tree, holding the .gcda files.
        output_dir: Directory for the reports.

    Returns:
        Map of report kind ("txt", "html", "json", "summary") to its path.

    Raises:
        RuntimeError: If no counts were recorded or gcovr fails.
    """
    if not any(build_dir.rglob("*.gcda")):
        raise RuntimeError(
            f"No .gcda files in {build_dir}: no server exited cleanly, so there is nothing to report"
        )

    reports = {
        "txt": output_dir / "coverage.txt",
        "html": output_dir / "html" / "index.html",
        "json": output_dir / "coverage.json",
        "summary": output_dir / "summary.json",
    }
    reports["html"].parent.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, "-m", "gcovr", "--root", str(build_dir)]
    for pattern in EXCLUDED_SOURCES:
        cmd += ["--exclude", pattern]
    cmd += [
        # The server forks and chdirs, which leaves gcov unsure of some paths
        "--gcov-ignore-errors=no_working_dir_found",
        "--print-summary",
        "--txt", str(reports["txt"]),
        "--html-details", str(reports["html"]),
        "--json", str(reports["json"]),
        "--json-summary-pretty",
        "--json-summary", str(reports["summary"]),
    ]
    result = subprocess.run(cmd, cwd=build_dir)
    if result.returncode != 0:
        raise RuntimeError(f"gcovr failed with exit status {result.returncode}")
    return reports


def builtin_calls(coverage_json: Path) -> Dict[str, int]:
    """Count the calls to each builtin function.

    Builtins are implemented by C functions named ``bf_<name>``, so a
    ``bf_`` function with no calls is a builtin no test reached.

    Args:
        coverage_json: gcovr's --json report.

    Returns:
        Map of builtin name, without the bf_ prefix, to its call count.
    """
    data = json.loads(coverage_json.read_text())
    calls: Dict[str, int] = {}
    for file in data.get("files", []):
        for function in file.get("functions", []):
            name = function.get("demangled_name") or function.get("name", "")
            if name.startswith(BUILTIN_PREFIX):
                builtin = name[len(BUILTIN_PREFIX):]
                calls[builtin] = calls.get(builtin, 0) + function.get("execution_count", 0)
    return calls


def write_builtin_report(coverage_json: Path, output: Path) -> Optional[str]:
    """Write the uncalled builtins to a file and return a one-line summary.

    Args:
        coverage_json: gcovr's --json report.
        output: Where to write the list, one name per line.

    Returns:
        Summary like "67 of 153 builtins never called", or None if the
        report has no builtins in it.
    """
    calls = builtin_calls(coverage_json)
    if not calls:
        return None
    uncalled = sorted(name for name, count in calls.items() if count == 0)
    output.write_text("".join(f"{name}\n" for name in uncalled))
    return f"{len(uncalled)} of {len(calls)} builtins never called"


def summary_line(summary_json: Path) -> str:
    """Return the line, function and branch percentages from gcovr's JSON summary.

    Args:
        summary_json: gcovr's --json-summary report.
    """
    data = json.loads(summary_json.read_text())
    parts = []
    for key, label in (("line_percent", "lines"), ("function_percent", "functions"), ("branch_percent", "branches")):
        if key in data:
            parts.append(f"{data[key]:.1f}% {label}")
    return ", ".join(parts)

