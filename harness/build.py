#!/usr/bin/env python3
"""Build script for MOO server binaries.

This script builds MOO server binaries from source, supporting:
- Local source trees
- Remote git repositories (by name or URL)
- Specific git refs (branches, tags, commits)
- Custom configure flags
- Build caching

Usage:
    # Build from known repo
    moo-build --repo lambdamoo --output ./builds/

    # Build specific ref
    moo-build --repo lambdamoo --ref v1.8.1 --output ./builds/v1.8.1/

    # Build from URL
    moo-build --repo https://github.com/wrog/lambdamoo --ref master

    # Build from local source
    moo-build --source /path/to/lambdamoo --output ./builds/local/

    # Build with configure flags
    moo-build --repo wp-lambdamoo --configure-flags="--enable-waifs --with-i64"

    # List known repos
    moo-build --list-repos
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, List

from .config import get_config, Config, get_build_config, list_build_configs, PREDEFINED_BUILD_CONFIGS, RepoConfig
from .repos import (
    get_or_clone_repo,
    get_commit_hash,
    resolve_repo_url,
    list_known_repos,
    KNOWN_REPOS,
)


def run_cmd(
    cmd: List[str],
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=capture,
        text=True,
    )
    if result.returncode != 0 and capture:
        print(f"  FAILED: {result.stderr}")
    return result


def compute_build_hash(repo_url: str, ref: str, configure_flags: str) -> str:
    """Compute a hash for build caching based on inputs.

    Args:
        repo_url: Repository URL.
        ref: Git ref (resolved to commit hash for caching).
        configure_flags: Configure flags string.

    Returns:
        Short hash string for cache key.
    """
    content = f"{repo_url}:{ref}:{configure_flags}"
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def get_cached_build(
    config: Config,
    repo_url: str,
    commit_hash: str,
    configure_flags: str,
) -> Optional[Path]:
    """Check if a build is cached and return its path.

    Args:
        config: Configuration object.
        repo_url: Repository URL.
        commit_hash: Full commit hash.
        configure_flags: Configure flags string.

    Returns:
        Path to cached binary if exists, None otherwise.
    """
    build_hash = compute_build_hash(repo_url, commit_hash, configure_flags)
    cached_binary = config.build_cache_dir / build_hash / "moo"

    if cached_binary.exists():
        return cached_binary
    return None


def cache_build(
    config: Config,
    binary_path: Path,
    repo_url: str,
    commit_hash: str,
    configure_flags: str,
) -> Path:
    """Cache a built binary.

    Args:
        config: Configuration object.
        binary_path: Path to the built binary.
        repo_url: Repository URL.
        commit_hash: Full commit hash.
        configure_flags: Configure flags string.

    Returns:
        Path to the cached binary.
    """
    build_hash = compute_build_hash(repo_url, commit_hash, configure_flags)
    cache_dir = config.build_cache_dir / build_hash
    cache_dir.mkdir(parents=True, exist_ok=True)

    cached_binary = cache_dir / "moo"
    shutil.copy(binary_path, cached_binary)
    cached_binary.chmod(0o755)

    # Write metadata
    metadata_path = cache_dir / "build-info.txt"
    with open(metadata_path, "w") as f:
        f.write(f"repo: {repo_url}\n")
        f.write(f"commit: {commit_hash}\n")
        f.write(f"configure_flags: {configure_flags}\n")

    return cached_binary


def build_with_script(
    source_dir: Path,
    output_dir: Path,
    build_script: str,
    make_jobs: int = 4,
) -> Path:
    """Build MOO server using a custom build script.

    Args:
        source_dir: Path to the source tree.
        output_dir: Where to put the built binary.
        build_script: Path to build script (relative to source_dir).
        make_jobs: Number of parallel make jobs.

    Returns:
        Path to the built binary.
    """
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    script_path = source_dir / build_script
    if not script_path.exists():
        raise RuntimeError(f"Build script not found: {script_path}")

    # Make script executable
    script_path.chmod(0o755)

    print(f"Running build script: {build_script}")
    env = dict(os.environ)
    env['MAKE_JOBS'] = str(make_jobs)

    result = run_cmd([str(script_path)], cwd=source_dir, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"Build script failed: {result.stderr}")

    # Find the binary
    binary_src = source_dir / "moo"
    if not binary_src.exists():
        # Check common alternative locations
        for alt in ["build/moo", "src/moo"]:
            alt_path = source_dir / alt
            if alt_path.exists():
                binary_src = alt_path
                break

    if not binary_src.exists():
        raise RuntimeError(f"Binary not found after build script completed")

    # Copy binary to output
    binary_dst = output_dir / "moo"
    shutil.copy(binary_src, binary_dst)
    binary_dst.chmod(0o755)

    print(f"Built binary: {binary_dst}")
    return binary_dst


def build_from_source(
    source_dir: Path,
    output_dir: Path,
    configure_flags: str = "",
    make_jobs: int = 4,
    clean: bool = False,
    build_script: str = "",
) -> Path:
    """Build MOO server from a source directory.

    Args:
        source_dir: Path to the source tree.
        output_dir: Where to put the built binary.
        configure_flags: Extra flags for ./configure.
        make_jobs: Number of parallel make jobs.
        clean: If True, run make clean first.
        build_script: Custom build script to use instead of configure/make.

    Returns:
        Path to the built binary.
    """
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use custom build script if specified
    if build_script:
        return build_with_script(source_dir, output_dir, build_script, make_jobs)

    # Standard autoconf/configure/make build
    # Clean if requested
    if clean and (source_dir / "Makefile").exists():
        print("Running make clean...")
        run_cmd(["make", "clean"], cwd=source_dir)

    # Run autoconf if needed
    if not (source_dir / "configure").exists():
        if (source_dir / "configure.ac").exists():
            print("Running autoconf...")
            result = run_cmd(["autoconf"], cwd=source_dir)
            if result.returncode != 0:
                raise RuntimeError(f"autoconf failed: {result.stderr}")
        else:
            raise RuntimeError(f"No configure script and no configure.ac in {source_dir}")

    # Configure if needed
    if not (source_dir / "Makefile").exists():
        print("Running configure...")
        configure_cmd = ["./configure"]
        if configure_flags:
            configure_cmd.extend(configure_flags.split())
        result = run_cmd(configure_cmd, cwd=source_dir)
        if result.returncode != 0:
            raise RuntimeError(f"Configure failed: {result.stderr}")

    # Build
    print("Running make...")
    result = run_cmd(["make", f"-j{make_jobs}"], cwd=source_dir)
    if result.returncode != 0:
        raise RuntimeError(f"Make failed: {result.stderr}")

    # Find the binary
    binary_src = source_dir / "moo"
    if not binary_src.exists():
        raise RuntimeError(f"Binary not found at {binary_src}")

    # Copy binary to output
    binary_dst = output_dir / "moo"
    shutil.copy(binary_src, binary_dst)
    binary_dst.chmod(0o755)

    print(f"Built binary: {binary_dst}")
    return binary_dst


def build_server(
    source_dir: Optional[Path] = None,
    repo: Optional[str] = None,
    ref: Optional[str] = None,
    output_dir: Optional[Path] = None,
    configure_flags: str = "",
    build_config: Optional[str] = None,
    use_cache: bool = True,
    config: Optional[Config] = None,
) -> Path:
    """Build a MOO server from source or repository.

    Args:
        source_dir: Path to local source tree (mutually exclusive with repo).
        repo: Repository name or URL (mutually exclusive with source_dir).
        ref: Git ref to checkout (branch, tag, commit).
        output_dir: Where to put the built binary.
        configure_flags: Extra flags for ./configure (overrides build_config).
        build_config: Named build configuration (e.g., "waterpoint", "i64_unicode").
        use_cache: If True, use build caching.
        config: Configuration object (default: load from files).

    Returns:
        Path to the built binary.
    """
    if config is None:
        config = get_config()

    if source_dir and repo:
        raise ValueError("Cannot specify both source_dir and repo")
    if not source_dir and not repo:
        raise ValueError("Must specify either source_dir or repo")

    # Resolve configure flags from build_config if specified
    if build_config and not configure_flags:
        bc = get_build_config(build_config, config)
        if bc is None:
            available = ", ".join(config.build_configs.keys())
            raise ValueError(f"Unknown build config: {build_config}. Available: {available}")
        configure_flags = " ".join(bc.configure_flags)
        print(f"Using build config '{build_config}': {configure_flags or '(default)'}")

    # Handle repository-based build
    if repo:
        repo_url = resolve_repo_url(repo)

        # Get build script from repo config if this is a known repo
        build_script = ""
        if repo in config.repos:
            repo_config = config.repos[repo]
            build_script = repo_config.build_script

        # Get the repository
        repo_path = get_or_clone_repo(
            repo,
            config.repo_cache_dir,
            ref=ref,
            update=True,
        )

        # Get commit hash for caching
        commit_hash = get_commit_hash(repo_path)

        # Check cache
        if use_cache:
            cached = get_cached_build(config, repo_url, commit_hash, configure_flags)
            if cached:
                print(f"Using cached build: {cached}")
                if output_dir:
                    output_dir = Path(output_dir)
                    output_dir.mkdir(parents=True, exist_ok=True)
                    dst = output_dir / "moo"
                    shutil.copy(cached, dst)
                    dst.chmod(0o755)
                    return dst
                return cached

        # Build in a temporary directory to avoid polluting the repo
        with tempfile.TemporaryDirectory(prefix="moo_build_") as tmpdir:
            work_dir = Path(tmpdir) / "build"
            shutil.copytree(repo_path, work_dir)

            # Determine output location
            if output_dir:
                build_output = Path(output_dir)
            else:
                build_output = Path(tmpdir) / "output"

            binary = build_from_source(
                work_dir,
                build_output,
                configure_flags=configure_flags,
                make_jobs=config.make_jobs,
                build_script=build_script,
            )

            # Cache the build
            if use_cache:
                cached = cache_build(config, binary, repo_url, commit_hash, configure_flags)
                print(f"Cached build at: {cached}")

            # Copy to final output if needed
            if output_dir:
                return binary
            else:
                # If no output_dir specified, return cached location
                return cached if use_cache else binary

    else:
        # Local source build
        if output_dir is None:
            output_dir = source_dir / "build"

        return build_from_source(
            source_dir,
            output_dir,
            configure_flags=configure_flags,
            make_jobs=config.make_jobs,
        )


def main():
    """Main entry point for moo-build command."""
    parser = argparse.ArgumentParser(
        description="Build MOO server binary from source or repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build from known repo with named config
  moo-build --repo lambdamoo --config waterpoint --output ./builds/

  # Build specific version
  moo-build --repo lambdamoo --ref v1.8.1 --config i64_unicode

  # Build from URL
  moo-build --repo https://github.com/wrog/lambdamoo --ref master

  # Build from local source
  moo-build --source /path/to/lambdamoo --output ./builds/local/

  # Build with explicit configure flags (overrides --config)
  moo-build --repo lambdamoo --configure-flags="--enable-waifs"

  # List known repos
  moo-build --list-repos

  # List available build configs
  moo-build --list-configs

Known repositories:
  lambdamoo     - https://github.com/wrog/lambdamoo (multiple configs)
  wp-lambdamoo  - https://github.com/xythian/wp-lambdamoo (waterpoint config)

Build configurations (for --config):
  default, i64, i64_unicode, i64_xml, i64_waifs, i64_unicode_waifs, waterpoint, full
"""
    )

    # Source specification (mutually exclusive)
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
        "--output",
        type=Path,
        help="Output directory for built binary"
    )
    parser.add_argument(
        "--config",
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

    args = parser.parse_args()

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
        parser.error("Must specify --source or --repo")

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
        print(f"\nError: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
