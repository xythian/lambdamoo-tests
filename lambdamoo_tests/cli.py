#!/usr/bin/env python3
"""Main CLI entry point for LambdaMOO Test Suite.

This provides the `lmt` command with subcommands for all test suite operations.

Usage:
    lmt build --repo lambdamoo --config waterpoint
    lmt setup --moo-binary ./moo
    lmt clean --list
    lmt test --candidate ./moo
"""

import argparse
import sys
from pathlib import Path


def add_build_parser(subparsers):
    """Add the 'build' subcommand parser."""
    parser = subparsers.add_parser(
        'build',
        help='Build MOO server from source or repository',
        description='Build MOO server binary from source or repository',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  lmt build --repo lambdamoo --config waterpoint
  lmt build --repo lambdamoo --ref v1.8.1 --config i64_unicode
  lmt build --source /path/to/lambdamoo --output ./builds/
  lmt build --list-repos
  lmt build --list-configs
"""
    )

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--source",
        type=Path,
        help="Path to local source tree"
    )
    source_group.add_argument(
        "--repo",
        help="Repository name (lambdamoo, wp-lambdamoo) or URL"
    )

    parser.add_argument(
        "--ref",
        help="Git ref to checkout (branch, tag, commit)"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output directory for built binary"
    )
    parser.add_argument(
        "--config", "-c",
        dest="build_config",
        help="Named build configuration (e.g., waterpoint, i64_unicode)"
    )
    parser.add_argument(
        "--configure-flags",
        default="",
        help="Extra flags for ./configure (overrides --config)"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable build caching"
    )
    parser.add_argument(
        "--list-repos",
        action="store_true",
        help="List known repositories and exit"
    )
    parser.add_argument(
        "--list-configs",
        action="store_true",
        help="List available build configurations and exit"
    )

    return parser


def add_setup_parser(subparsers):
    """Add the 'setup' subcommand parser."""
    parser = subparsers.add_parser(
        'setup',
        help='Set up test databases',
        description='Set up test databases for LambdaMOO test suite',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  lmt setup
  lmt setup --moo-binary ./builds/moo --minimal-db ./Minimal.db
  lmt setup --build-if-missing --repo lambdamoo
  lmt setup --only test
  lmt setup --check-only
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
        "--output-dir", "-o",
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

    return parser


def add_clean_parser(subparsers):
    """Add the 'clean' subcommand parser."""
    parser = subparsers.add_parser(
        'clean',
        help='Clean cached repositories and builds',
        description='Clean LambdaMOO test suite caches',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  lmt clean --list
  lmt clean --all
  lmt clean --builds
  lmt clean --repos
  lmt clean --all --dry-run
  lmt clean --all --force
"""
    )

    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List cache contents without deleting"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Clean all caches (repos and builds)"
    )
    parser.add_argument(
        "--repos", "-r",
        action="store_true",
        help="Clean repository cache"
    )
    parser.add_argument(
        "--builds", "-b",
        action="store_true",
        help="Clean build cache"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Skip confirmation prompt"
    )

    return parser


def add_test_parser(subparsers):
    """Add the 'test' subcommand parser."""
    parser = subparsers.add_parser(
        'test',
        help='Run the test suite',
        description='Run LambdaMOO test suite',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with explicit binary
  lmt test --candidate ./moo

  # Build candidate from repo (name derived automatically)
  lmt test --build lambdamoo:waterpoint
  lmt test --build main=lambdamoo:waterpoint  # Explicit name
  lmt test --build wp-lambdamoo  # Uses build script

  # Upgrade testing with builds
  lmt test --build lambdamoo:waterpoint --prior-build wp=wp-lambdamoo

  # Multiple priors
  lmt test --build main=lambdamoo:waterpoint \\
           --prior-build wp=wp-lambdamoo \\
           --prior-build old=lambdamoo:v1.8.0:i64

  # Filter tests
  lmt test -k test_connection
  lmt test -m persistence

Build spec format:
  [name=]repo[:config]        Repo with optional name and config
  [name=]repo:ref:config      With specific git ref
  Note: --prior-build requires name=, --build derives name if omitted
"""
    )

    # Candidate specification (mutually exclusive)
    candidate_group = parser.add_mutually_exclusive_group()
    candidate_group.add_argument(
        "--candidate",
        type=Path,
        help="Path to the candidate MOO server binary"
    )
    candidate_group.add_argument(
        "--build", "-b",
        dest="build_spec",
        metavar="SPEC",
        help="Build candidate from repo, repo:config, or repo:ref:config"
    )

    parser.add_argument(
        "--prior",
        action="append",
        default=[],
        metavar="NAME:PATH",
        help="Prior version binary in format 'name:path' (can be repeated)"
    )
    parser.add_argument(
        "--prior-build",
        action="append",
        default=[],
        metavar="NAME=SPEC",
        help="Build prior version: 'name=repo', 'name=repo:config', or 'name=repo:ref:config'"
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep test artifacts (databases, logs) after test run"
    )
    parser.add_argument(
        "-k",
        dest="keyword",
        help="Only run tests matching the given keyword expression"
    )
    parser.add_argument(
        "-m", "--mark",
        dest="marker",
        help="Only run tests matching the given marker"
    )
    parser.add_argument(
        "pytest_args",
        nargs="*",
        help="Additional arguments to pass to pytest"
    )

    return parser


def cmd_build(args):
    """Execute the build command."""
    from harness.build import build_server, list_known_repos
    from harness.config import list_build_configs

    # Handle --list-repos
    if args.list_repos:
        print("Known repositories:")
        for name, url in list_known_repos().items():
            print(f"  {name:15} {url}")
        return 0

    # Handle --list-configs
    if args.list_configs:
        print("Available build configurations:")
        configs = list_build_configs()
        for name, bc in sorted(configs.items()):
            flags = " ".join(bc.configure_flags) if bc.configure_flags else "(default)"
            print(f"  {name:20} {bc.description}")
            print(f"                       Flags: {flags}")
        return 0

    # Require source or repo
    if not args.source and not args.repo:
        print("Error: Must specify --source or --repo", file=sys.stderr)
        return 1

    try:
        binary = build_server(
            source_dir=args.source,
            repo=args.repo,
            ref=args.ref,
            output_dir=args.output,
            configure_flags=args.configure_flags,
            build_config=args.build_config,
            use_cache=not args.no_cache,
        )
        print(f"\nSuccess: {binary}")
        return 0
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


def cmd_setup(args):
    """Execute the setup command."""
    from lambdamoo_tests.setup import (
        find_moo_binary,
        find_minimal_db,
        check_prerequisites,
        setup_test_database,
        setup_multiplayer_database,
    )
    from harness.config import get_config

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
            moo_binary = build_server(repo=args.repo, ref=args.ref)
            print(f"Built MOO binary: {moo_binary}")
        except Exception as e:
            print(f"Failed to build MOO binary: {e}", file=sys.stderr)
            return 1

    if not moo_binary:
        print("Could not find MOO binary.", file=sys.stderr)
        print("Options:")
        print("  - Specify path with --moo-binary")
        print("  - Set MOO_BINARY environment variable")
        print("  - Use --build-if-missing to build from source")
        print("  - Build manually with: lmt build --repo lambdamoo")
        return 1

    # Find or validate Minimal.db
    if args.minimal_db:
        minimal_db = args.minimal_db
    else:
        minimal_db = find_minimal_db(config)
        if not minimal_db:
            print("Could not find Minimal.db.", file=sys.stderr)
            print("Options:")
            print("  - Specify path with --minimal-db")
            print("  - Set MOO_MINIMAL_DB environment variable")
            print("  - Obtain from LambdaMOO source repo")
            return 1

    print("LambdaMOO Test Suite Setup")
    print("=" * 40)
    print(f"MOO binary:  {moo_binary}")
    print(f"Minimal.db:  {minimal_db}")
    print(f"Output dir:  {output_dir}")
    print()

    # Check prerequisites
    print("Checking prerequisites...")
    if not check_prerequisites(moo_binary, minimal_db):
        print("\nPrerequisites check failed", file=sys.stderr)
        return 1

    print("  Prerequisites OK")

    if args.check_only:
        print("\nCheck complete (--check-only specified)")
        return 0

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
        print("  lmt test")
        return 0
    else:
        print("\nSetup failed", file=sys.stderr)
        return 1


def cmd_clean(args):
    """Execute the clean command."""
    from harness.clean import (
        list_cache_contents,
        get_cache_info_totals,
        clean_directory,
        format_size,
    )
    from harness.config import get_config

    config = get_config()

    # Default to --list if no action specified
    if not any([args.list, args.all, args.repos, args.builds]):
        args.list = True

    # Handle --list
    if args.list:
        list_cache_contents(config)
        return 0

    # Determine what to clean
    clean_repos = args.all or args.repos
    clean_builds = args.all or args.builds

    # Calculate what would be cleaned
    repos_items, repos_bytes = 0, 0
    builds_items, builds_bytes = 0, 0

    if clean_repos:
        repos_items, repos_bytes = get_cache_info_totals(config.repo_cache_dir)
    if clean_builds:
        builds_items, builds_bytes = get_cache_info_totals(config.build_cache_dir)

    total_items = repos_items + builds_items
    total_bytes = repos_bytes + builds_bytes

    if total_items == 0:
        print("Nothing to clean.")
        return 0

    # Show what will be deleted
    print("Will delete:")
    if clean_repos and repos_items > 0:
        print(f"  Repository cache: {repos_items} items, {format_size(repos_bytes)}")
    if clean_builds and builds_items > 0:
        print(f"  Build cache:      {builds_items} items, {format_size(builds_bytes)}")
    print(f"  Total:            {total_items} items, {format_size(total_bytes)}")

    if args.dry_run:
        print("\n(Dry run - nothing deleted)")
        return 0

    # Confirm unless --force
    if not args.force:
        try:
            response = input("\nProceed? [y/N] ")
            if response.lower() not in ['y', 'yes']:
                print("Cancelled.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 0

    # Actually clean
    if clean_repos:
        items, bytes_freed = clean_directory(config.repo_cache_dir)
        if items > 0:
            print(f"Cleaned repository cache: {items} items, {format_size(bytes_freed)}")

    if clean_builds:
        items, bytes_freed = clean_directory(config.build_cache_dir)
        if items > 0:
            print(f"Cleaned build cache: {items} items, {format_size(bytes_freed)}")

    print("Done.")
    return 0


def parse_build_spec(spec: str):
    """Parse a build spec into (name, repo, ref, config).

    Formats:
        repo                -> (None, repo, None, None)
        repo:config         -> (None, repo, None, config)
        repo:ref:config     -> (None, repo, ref, config)
        name=repo           -> (name, repo, None, None)
        name=repo:config    -> (name, repo, None, config)
        name=repo:ref:config -> (name, repo, ref, config)

    Returns:
        Tuple of (name, repo, ref, config) where name, ref, and config may be None.
    """
    # Check for name= prefix
    name = None
    if '=' in spec:
        name, spec = spec.split('=', 1)
        if not name:
            raise ValueError(f"Invalid build spec: name cannot be empty")

    parts = spec.split(':')
    if len(parts) == 1:
        return (name, parts[0], None, None)
    elif len(parts) == 2:
        return (name, parts[0], None, parts[1])
    elif len(parts) == 3:
        return (name, parts[0], parts[1], parts[2])
    else:
        raise ValueError(f"Invalid build spec: {spec}. Use 'repo', 'repo:config', or 'repo:ref:config'")


def parse_prior_build_spec(spec: str):
    """Parse a prior build spec into (name, repo, ref, config).

    Same format as build spec, but name is required:
        name=repo                -> (name, repo, None, None)
        name=repo:config         -> (name, repo, None, config)
        name=repo:ref:config     -> (name, repo, ref, config)

    Returns:
        Tuple of (name, repo, ref, config) where ref and config may be None.
    """
    name, repo, ref, config = parse_build_spec(spec)
    if not name:
        raise ValueError(
            f"Invalid prior build spec: {spec}. "
            "Name is required. Use 'name=repo', 'name=repo:config', or 'name=repo:ref:config'"
        )
    return (name, repo, ref, config)


def derive_server_name(repo: str, ref: str, config: str) -> str:
    """Derive a server name from build spec components."""
    parts = [repo.replace('-', '_')]
    if ref:
        # Sanitize ref for use as name component
        ref_clean = ref.replace('/', '_').replace('.', '_')
        parts.append(ref_clean)
    if config:
        parts.append(config)
    return '_'.join(parts)


def resolve_or_build(repo: str, ref: str, config: str, name: str = None) -> tuple:
    """Resolve a binary from cache or build it.

    Args:
        repo: Repository name or URL.
        ref: Git ref (branch, tag, commit) or None for default.
        config: Build configuration name, or None to use repo's build script.
        name: Server name, or None to derive from spec.

    Returns:
        Tuple of (name, Path to binary, list of known features or None).
    """
    from harness.build import build_server
    from harness.config import get_config, get_build_config

    cfg = get_config()

    # Derive name if not provided
    if not name:
        name = derive_server_name(repo, ref, config)

    # Validate config name if provided
    if config:
        bc = get_build_config(config, cfg)
        if bc is None:
            available = ", ".join(cfg.build_configs.keys())
            raise ValueError(f"Unknown build config: {config}. Available: {available}")

    # Get known features from repo config (if this is a known repo)
    known_features = None
    if repo in cfg.repos:
        repo_config = cfg.repos[repo]
        if repo_config.known_features:
            known_features = repo_config.known_features

    # Build description for logging
    spec_str = repo
    if ref:
        spec_str += f"@{ref}"
    if config:
        spec_str += f" [{config}]"
    print(f"Resolving '{name}': {spec_str}")

    # build_server will use cache if available
    binary = build_server(
        repo=repo,
        ref=ref,
        build_config=config,
        use_cache=True,
        config=cfg,
    )

    print(f"  -> {binary}")
    return (name, binary, known_features)


def cmd_test(args):
    """Execute the test command."""
    import subprocess

    # Resolve candidate binary and name
    candidate_name = None
    candidate_binary = None
    candidate_features = None

    if args.candidate:
        candidate_binary = args.candidate
        candidate_name = "candidate"  # Default name for explicit binary
        if not candidate_binary.exists():
            print(f"Error: Candidate binary not found: {candidate_binary}", file=sys.stderr)
            return 1
    elif args.build_spec:
        try:
            name, repo, ref, config = parse_build_spec(args.build_spec)
            candidate_name, candidate_binary, candidate_features = resolve_or_build(repo, ref, config, name)
        except Exception as e:
            print(f"Error building candidate: {e}", file=sys.stderr)
            return 1

    # Resolve prior binaries
    prior_args = []

    # Explicit prior binaries
    for prior in args.prior:
        if ':' not in prior:
            print(f"Error: Invalid --prior format: {prior}. Use 'name:path'", file=sys.stderr)
            return 1
        prior_args.append(prior)

    # Built prior binaries
    for prior_spec in args.prior_build:
        try:
            name, repo, ref, config = parse_prior_build_spec(prior_spec)
            prior_name, binary, _ = resolve_or_build(repo, ref, config, name)
            prior_args.append(f"{prior_name}:{binary}")
        except Exception as e:
            print(f"Error building prior: {e}", file=sys.stderr)
            return 1

    # Build pytest command
    pytest_cmd = [sys.executable, "-m", "pytest"]

    if candidate_binary:
        pytest_cmd.append(f"--candidate={candidate_binary}")
        if candidate_name:
            pytest_cmd.append(f"--candidate-name={candidate_name}")
        if candidate_features:
            pytest_cmd.append(f"--candidate-features={','.join(candidate_features)}")

    for prior in prior_args:
        pytest_cmd.append(f"--prior={prior}")

    if args.keep_artifacts:
        pytest_cmd.append("--keep-artifacts")

    if args.keyword:
        pytest_cmd.extend(["-k", args.keyword])

    if args.marker:
        pytest_cmd.extend(["-m", args.marker])

    # Add any additional pytest args
    if args.pytest_args:
        pytest_cmd.extend(args.pytest_args)

    # Run pytest
    print(f"\nRunning: {' '.join(str(x) for x in pytest_cmd)}\n")
    result = subprocess.run(pytest_cmd)
    return result.returncode


def main():
    """Main entry point for the lmt command."""
    parser = argparse.ArgumentParser(
        prog='lmt',
        description='LambdaMOO Test Suite - Build, test, and validate MOO servers',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  build    Build MOO server from source or repository
  setup    Set up test databases
  clean    Clean cached repositories and builds
  test     Run the test suite

Examples:
  # Build a server with waterpoint config
  lmt build --repo lambdamoo --config waterpoint

  # Set up test databases
  lmt setup --moo-binary ./builds/moo

  # Run tests
  lmt test --candidate ./builds/moo

  # Clean caches
  lmt clean --all

  # Use project-local cache
  lmt --cache-dir ./.lmt build --repo lambdamoo --config waterpoint

For help on a specific command:
  lmt <command> --help

Environment Variables:
  MOO_BUILD_CACHE_DIR   Build cache directory
  MOO_REPO_CACHE_DIR    Repository cache directory
"""
    )

    parser.add_argument(
        '--version', '-V',
        action='version',
        version='%(prog)s 0.1.0'
    )
    parser.add_argument(
        '--cache-dir', '-C',
        type=Path,
        metavar='DIR',
        help='Cache directory for builds and repos (default: ~/.cache/lambdamoo-tests)'
    )

    subparsers = parser.add_subparsers(dest='command', metavar='<command>')

    # Add subcommand parsers
    add_build_parser(subparsers)
    add_setup_parser(subparsers)
    add_clean_parser(subparsers)
    add_test_parser(subparsers)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Apply global --cache-dir option to config
    if args.cache_dir:
        from harness.config import get_config, reset_config
        import os
        cache_dir = args.cache_dir.resolve()
        os.environ['MOO_BUILD_CACHE_DIR'] = str(cache_dir / 'builds')
        os.environ['MOO_REPO_CACHE_DIR'] = str(cache_dir / 'repos')
        reset_config()  # Force config reload with new env vars

    # Dispatch to command handler
    handlers = {
        'build': cmd_build,
        'setup': cmd_setup,
        'clean': cmd_clean,
        'test': cmd_test,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
