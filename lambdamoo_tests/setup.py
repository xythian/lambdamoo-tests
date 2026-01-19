#!/usr/bin/env python3
"""Test suite setup tool for LambdaMOO integration tests.

This tool creates the test databases needed for running the test suite.
It can use an existing MOO binary or build one from source.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Import config system
try:
    from harness.config import get_config
except ImportError:
    # Allow running standalone before package is installed
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from harness.config import get_config


def find_moo_binary(config=None) -> Optional[Path]:
    """Find the MOO binary in common locations.

    Args:
        config: Optional Config object to check configured paths.

    Returns:
        Path to MOO binary if found, None otherwise.
    """
    if config is None:
        config = get_config()

    # Check configured path first
    if config.moo_binary and config.moo_binary.exists():
        return config.moo_binary

    # Check environment variable
    import os
    if env_binary := os.environ.get("MOO_BINARY"):
        path = Path(env_binary).expanduser()
        if path.exists() and path.is_file():
            return path

    # Search common locations
    search_paths = [
        Path.cwd() / "moo",
        Path.cwd() / "build" / "moo",
        Path.cwd().parent / "moo",
        Path.cwd().parent / "build" / "moo",
        config.build_cache_dir / "moo" if config.build_cache_dir.exists() else None,
        Path("/usr/local/bin/moo"),
        Path("/usr/bin/moo"),
    ]

    for path in search_paths:
        if path and path.exists() and path.is_file():
            return path

    # Check build cache for any cached binaries
    if config.build_cache_dir.exists():
        for subdir in config.build_cache_dir.iterdir():
            if subdir.is_dir():
                binary = subdir / "moo"
                if binary.exists():
                    return binary

    return None


def find_minimal_db(config=None) -> Optional[Path]:
    """Find Minimal.db in common locations.

    Args:
        config: Optional Config object to check configured paths.

    Returns:
        Path to Minimal.db if found, None otherwise.
    """
    if config is None:
        config = get_config()

    # Check configured path first
    if config.minimal_db and config.minimal_db.exists():
        return config.minimal_db

    # Check environment variable
    import os
    if env_db := os.environ.get("MOO_MINIMAL_DB"):
        path = Path(env_db).expanduser()
        if path.exists() and path.is_file():
            return path

    # Search common locations
    search_paths = [
        # Check in databases/ directory (may be bundled)
        Path(__file__).parent.parent / "databases" / "Minimal.db",
        Path.cwd() / "databases" / "Minimal.db",
        # Check parent directories (common when adjacent to server source)
        Path.cwd().parent / "Minimal.db",
        Path.cwd().parent.parent / "Minimal.db",
        # System locations
        Path("/usr/share/lambdamoo/Minimal.db"),
        Path("/usr/local/share/lambdamoo/Minimal.db"),
    ]

    for path in search_paths:
        if path.exists() and path.is_file():
            return path

    # Check repo cache for Minimal.db from cloned repos
    if config.repo_cache_dir.exists():
        for repo_dir in config.repo_cache_dir.iterdir():
            if repo_dir.is_dir():
                minimal_path = repo_dir / "Minimal.db"
                if minimal_path.exists():
                    return minimal_path

    return None


def setup_test_database(moo_binary: Path, input_db: Path, output_dir: Path) -> bool:
    """Set up Test.db with programmer support using emergency mode.

    Args:
        moo_binary: Path to MOO server binary.
        input_db: Path to Minimal.db.
        output_dir: Directory to write Test.db.

    Returns:
        True if successful, False otherwise.
    """
    output_db = output_dir / "Test.db"

    # Commands to execute in emergency mode
    # This creates a do_command verb that allows programmer eval via ";<expr>"
    commands = r'''
;add_verb(#0, {#3, "rxd", "do_command"}, {"this", "none", "this"})
;set_verb_code(#0, "do_command", {"if (callers())", "  return 0;", "endif", "cmd = argstr;", "if (length(cmd) > 0 && cmd[1] == \";\" && is_player(player) && player.programmer)", "  set_task_perms(player);", "  expr = cmd[2..length(cmd)];", "  code = \"return \" + expr + \";\";", "  result = eval(code);", "  if (result[1])", "    notify(player, tostr(caller, \":  => \", toliteral(result[2])));", "  else", "    notify(player, tostr(\"** \", toliteral(result[2])));", "  endif", "  return 1;", "endif", "return 0;"})
quit
'''

    print(f"Creating Test.db...")

    # Remove old output if exists
    if output_db.exists():
        output_db.unlink()

    result = subprocess.run(
        [str(moo_binary), '-e', str(input_db), str(output_db)],
        input=commands,
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:
        print(f"Error creating Test.db: {result.stderr}")
        return False

    if output_db.exists():
        print(f"  Test.db created ({output_db.stat().st_size} bytes)")
        return True

    print("  Failed to create Test.db")
    return False


def setup_multiplayer_database(moo_binary: Path, input_db: Path, output_dir: Path) -> bool:
    """Set up Multiplayer.db with multiple test players.

    Args:
        moo_binary: Path to MOO server binary.
        input_db: Path to Minimal.db.
        output_dir: Directory to write Multiplayer.db.

    Returns:
        True if successful, False otherwise.
    """
    output_db = output_dir / "Multiplayer.db"

    # Commands to execute in emergency mode
    # Creates Player2 (#4) and Player3 (#5) with programmer flag
    # Also sets up do_command for eval and do_login_command for name lookup
    commands = r'''
;create(#1, #1)
;set_player_flag(#4, 1)
;#4.name = "Player2"
;#4.programmer = 1
;create(#1, #1)
;set_player_flag(#5, 1)
;#5.name = "Player3"
;#5.programmer = 1
;add_verb(#0, {#3, "rxd", "do_command"}, {"this", "none", "this"})
;set_verb_code(#0, "do_command", {"if (callers())", "  return 0;", "endif", "cmd = argstr;", "if (length(cmd) > 0 && cmd[1] == \";\" && is_player(player) && player.programmer)", "  set_task_perms(player);", "  expr = cmd[2..length(cmd)];", "  code = \"return \" + expr + \";\";", "  result = eval(code);", "  if (result[1])", "    notify(player, tostr(caller, \":  => \", toliteral(result[2])));", "  else", "    notify(player, tostr(\"** \", toliteral(result[2])));", "  endif", "  return 1;", "endif", "return 0;"})
;delete_verb(#0, "do_login_command")
;add_verb(#0, {#3, "rxd", "do_login_command"}, {"this", "none", "this"})
;set_verb_code(#0, "do_login_command", {"if (length(args) < 2)", "  return #-1;", "endif", "name = args[2];", "for p in (players())", "  if (p.name == name)", "    return p;", "  endif", "endfor", "return #-1;"})
;players()
quit
'''

    print(f"Creating Multiplayer.db...")

    # Remove old output if exists
    if output_db.exists():
        output_db.unlink()

    result = subprocess.run(
        [str(moo_binary), '-e', str(input_db), str(output_db)],
        input=commands,
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:
        print(f"Error creating Multiplayer.db: {result.stderr}")
        return False

    if output_db.exists():
        print(f"  Multiplayer.db created ({output_db.stat().st_size} bytes)")
        return True

    print("  Failed to create Multiplayer.db")
    return False


def ensure_test_db(moo_binary: Path, db_dir: Path, config=None) -> Optional[Path]:
    """Ensure Test.db exists for a server, creating if needed.

    Args:
        moo_binary: Path to MOO server binary.
        db_dir: Directory to store the database.
        config: Optional Config object.

    Returns:
        Path to Test.db if available, None if setup failed.
    """
    db_path = db_dir / "Test.db"

    # Already exists
    if db_path.exists():
        return db_path

    # Need to create it - find Minimal.db
    minimal_db = find_minimal_db(config)
    if not minimal_db:
        return None

    # Create directory
    db_dir.mkdir(parents=True, exist_ok=True)

    # Set up the database
    if setup_test_database(moo_binary, minimal_db, db_dir):
        return db_path
    return None


def ensure_multiplayer_db(moo_binary: Path, db_dir: Path, config=None) -> Optional[Path]:
    """Ensure Multiplayer.db exists for a server, creating if needed.

    Args:
        moo_binary: Path to MOO server binary.
        db_dir: Directory to store the database.
        config: Optional Config object.

    Returns:
        Path to Multiplayer.db if available, None if setup failed.
    """
    db_path = db_dir / "Multiplayer.db"

    # Already exists
    if db_path.exists():
        return db_path

    # Need to create it - find Minimal.db
    minimal_db = find_minimal_db(config)
    if not minimal_db:
        return None

    # Create directory
    db_dir.mkdir(parents=True, exist_ok=True)

    # Set up the database
    if setup_multiplayer_database(moo_binary, minimal_db, db_dir):
        return db_path
    return None


def check_prerequisites(moo_binary: Path, input_db: Path) -> bool:
    """Verify that required files exist and MOO binary is executable.

    Args:
        moo_binary: Path to MOO binary.
        input_db: Path to Minimal.db.

    Returns:
        True if prerequisites are met, False otherwise.
    """
    if not moo_binary.exists():
        print(f"  MOO binary not found: {moo_binary}")
        return False

    if not input_db.exists():
        print(f"  Minimal.db not found: {input_db}")
        return False

    # Test that MOO binary is executable
    try:
        result = subprocess.run(
            [str(moo_binary), "-h"],
            capture_output=True,
            timeout=5
        )
        if result.returncode not in [0, 1]:  # MOO returns 1 for help
            print(f"  MOO binary may not be executable")
            return False
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  Cannot execute MOO binary: {e}")
        return False

    return True


def main():
    """Main setup function."""
    parser = argparse.ArgumentParser(
        description="Set up test databases for LambdaMOO test suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect paths and set up all databases
  moo-test-setup

  # Use specific MOO binary
  moo-test-setup --moo-binary ./builds/moo

  # Use specific Minimal.db
  moo-test-setup --minimal-db /path/to/Minimal.db

  # Set up only specific database
  moo-test-setup --only test
  moo-test-setup --only multiplayer

  # Build MOO from source if needed
  moo-test-setup --build-if-missing --repo lambdamoo

Environment Variables:
  MOO_BINARY      - Path to MOO binary
  MOO_MINIMAL_DB  - Path to Minimal.db

Configuration:
  Settings can also be configured in:
  - ~/.config/lambdamoo-tests/config.toml (user)
  - .moo-tests.toml (project)
"""
    )

    parser.add_argument(
        "--moo-binary",
        type=Path,
        help="Path to MOO server binary (auto-detect if not specified)"
    )
    parser.add_argument(
        "--minimal-db",
        type=Path,
        help="Path to Minimal.db (auto-detect if not specified)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory for test databases (default: ./databases)"
    )
    parser.add_argument(
        "--only",
        choices=["test", "multiplayer"],
        help="Set up only the specified database"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check prerequisites without creating databases"
    )
    parser.add_argument(
        "--build-if-missing",
        action="store_true",
        help="Build MOO binary if not found"
    )
    parser.add_argument(
        "--repo",
        default="lambdamoo",
        help="Repository to build from if --build-if-missing (default: lambdamoo)"
    )
    parser.add_argument(
        "--ref",
        help="Git ref to build if --build-if-missing"
    )

    args = parser.parse_args()

    # Load config
    config = get_config()

    # Determine output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = config.database_dir
    output_dir = Path(output_dir)

    # Find or validate MOO binary
    if args.moo_binary:
        moo_binary = args.moo_binary
    else:
        moo_binary = find_moo_binary(config)

    # Build if missing and requested
    if not moo_binary and args.build_if_missing:
        print("MOO binary not found, building from source...")
        try:
            from harness.build import build_server
            moo_binary = build_server(
                repo=args.repo,
                ref=args.ref,
            )
            print(f"Built MOO binary: {moo_binary}")
        except Exception as e:
            print(f"Failed to build MOO binary: {e}")
            sys.exit(1)

    if not moo_binary:
        print("Could not find MOO binary.")
        print("Options:")
        print("  - Specify path with --moo-binary")
        print("  - Set MOO_BINARY environment variable")
        print("  - Use --build-if-missing to build from source")
        print("  - Build manually with: moo-build --repo lambdamoo")
        sys.exit(1)

    # Find or validate Minimal.db
    if args.minimal_db:
        minimal_db = args.minimal_db
    else:
        minimal_db = find_minimal_db(config)
        if not minimal_db:
            print("Could not find Minimal.db.")
            print("Options:")
            print("  - Specify path with --minimal-db")
            print("  - Set MOO_MINIMAL_DB environment variable")
            print("  - Obtain from LambdaMOO source repo")
            sys.exit(1)

    print("LambdaMOO Test Suite Setup")
    print("=" * 40)
    print(f"MOO binary:  {moo_binary}")
    print(f"Minimal.db:  {minimal_db}")
    print(f"Output dir:  {output_dir}")
    print()

    # Check prerequisites
    print("Checking prerequisites...")
    if not check_prerequisites(moo_binary, minimal_db):
        print("\nPrerequisites check failed")
        sys.exit(1)

    print("  Prerequisites OK")

    if args.check_only:
        print("\nCheck complete (--check-only specified)")
        sys.exit(0)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Set up databases
    print("\nSetting up test databases...")
    success = True

    if not args.only or args.only == "test":
        if not setup_test_database(moo_binary, minimal_db, output_dir):
            success = False

    if not args.only or args.only == "multiplayer":
        if not setup_multiplayer_database(moo_binary, minimal_db, output_dir):
            success = False

    if success:
        print("\nSetup complete!")
        print(f"\nTest databases created in: {output_dir}")
        print("\nYou can now run tests with:")
        print("  pytest")
        print("  # or")
        print("  pytest --candidate=/path/to/moo")
    else:
        print("\nSetup failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
