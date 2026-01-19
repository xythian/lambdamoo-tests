#!/usr/bin/env python3
"""Cache cleanup utilities for LambdaMOO test suite.

This module provides commands to clean up cached repositories and builds.
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

from .config import get_config


def get_cache_info(cache_dir: Path) -> List[Tuple[Path, int]]:
    """Get info about items in a cache directory.

    Args:
        cache_dir: Path to cache directory.

    Returns:
        List of (path, size_bytes) tuples.
    """
    items = []
    if not cache_dir.exists():
        return items

    for item in cache_dir.iterdir():
        if item.is_dir():
            # Calculate directory size
            size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
            items.append((item, size))
        elif item.is_file():
            items.append((item, item.stat().st_size))

    return sorted(items, key=lambda x: x[0].name)


def format_size(size_bytes: int) -> str:
    """Format a size in bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def clean_directory(cache_dir: Path, dry_run: bool = False) -> Tuple[int, int]:
    """Clean a cache directory.

    Args:
        cache_dir: Path to cache directory.
        dry_run: If True, only report what would be deleted.

    Returns:
        Tuple of (items_removed, bytes_freed).
    """
    if not cache_dir.exists():
        return 0, 0

    items = get_cache_info(cache_dir)
    total_items = len(items)
    total_bytes = sum(size for _, size in items)

    if dry_run:
        return total_items, total_bytes

    # Actually delete
    for item, _ in items:
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)

    return total_items, total_bytes


def list_cache_contents(config=None):
    """List contents of all cache directories."""
    if config is None:
        config = get_config()

    print("Cache Contents")
    print("=" * 60)

    # Repo cache
    print(f"\nRepository Cache: {config.repo_cache_dir}")
    if config.repo_cache_dir.exists():
        items = get_cache_info(config.repo_cache_dir)
        if items:
            total = 0
            for path, size in items:
                print(f"  {path.name:30} {format_size(size):>10}")
                total += size
            print(f"  {'─' * 42}")
            print(f"  {'Total':30} {format_size(total):>10}")
        else:
            print("  (empty)")
    else:
        print("  (not created)")

    # Build cache
    print(f"\nBuild Cache: {config.build_cache_dir}")
    if config.build_cache_dir.exists():
        items = get_cache_info(config.build_cache_dir)
        if items:
            total = 0
            for path, size in items:
                # Try to read build info
                info_file = path / "build-info.txt"
                desc = ""
                if info_file.exists():
                    try:
                        content = info_file.read_text()
                        for line in content.split('\n'):
                            if line.startswith('repo:'):
                                repo = line.split(':', 1)[1].strip()
                                repo = repo.split('/')[-1]  # Just repo name
                                desc = f" ({repo})"
                                break
                    except Exception:
                        pass
                print(f"  {path.name}{desc:20} {format_size(size):>10}")
                total += size
            print(f"  {'─' * 42}")
            print(f"  {'Total':30} {format_size(total):>10}")
        else:
            print("  (empty)")
    else:
        print("  (not created)")


def main():
    """Main entry point for moo-clean command."""
    parser = argparse.ArgumentParser(
        description="Clean LambdaMOO test suite caches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show what's in the caches
  moo-clean --list

  # Clean everything (with confirmation)
  moo-clean --all

  # Clean only build cache
  moo-clean --builds

  # Clean only repo cache
  moo-clean --repos

  # Dry run - show what would be deleted
  moo-clean --all --dry-run

  # Force clean without confirmation
  moo-clean --all --force

Cache Locations:
  Repos:  ~/.cache/lambdamoo-tests/repos/
  Builds: ~/.cache/lambdamoo-tests/builds/
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

    args = parser.parse_args()

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


def get_cache_info_totals(cache_dir: Path) -> Tuple[int, int]:
    """Get total count and size for a cache directory."""
    items = get_cache_info(cache_dir)
    return len(items), sum(size for _, size in items)


if __name__ == "__main__":
    sys.exit(main())
