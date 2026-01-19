"""Repository management for LambdaMOO server sources.

This module handles cloning, updating, and managing git repositories
for different LambdaMOO server variants.
"""

import subprocess
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass


# Well-known LambdaMOO repositories
KNOWN_REPOS: Dict[str, str] = {
    "lambdamoo": "https://github.com/wrog/lambdamoo",
    "wp-lambdamoo": "https://github.com/xythian/wp-lambdamoo",
}

# Default branches for known repos (used as fallback, actual default detected from remote)
DEFAULT_BRANCHES: Dict[str, str] = {
    "lambdamoo": "main",  # wrog/lambdamoo uses main
    "wp-lambdamoo": "main",
}


@dataclass
class RepoInfo:
    """Information about a cloned repository."""
    name: str
    url: str
    path: Path
    current_ref: str
    is_dirty: bool


def run_git(args: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + args
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def resolve_repo_url(name_or_url: str) -> str:
    """Resolve a repo name or URL to a full URL.

    Args:
        name_or_url: Either a known repo name (e.g., "lambdamoo") or a full URL.

    Returns:
        The full git URL.
    """
    if name_or_url in KNOWN_REPOS:
        return KNOWN_REPOS[name_or_url]
    # Assume it's a URL if it contains :// or @
    if "://" in name_or_url or "@" in name_or_url:
        return name_or_url
    # Could also be a local path
    if Path(name_or_url).exists():
        return str(Path(name_or_url).resolve())
    raise ValueError(f"Unknown repository: {name_or_url}. "
                     f"Known repos: {', '.join(KNOWN_REPOS.keys())}")


def get_default_branch(name_or_url: str) -> str:
    """Get the default branch for a repository.

    Args:
        name_or_url: Repository name or URL.

    Returns:
        The default branch name.
    """
    if name_or_url in DEFAULT_BRANCHES:
        return DEFAULT_BRANCHES[name_or_url]
    return "master"  # Fallback default


def clone_repo(url: str, dest: Path, shallow: bool = False) -> Path:
    """Clone a repository to a destination directory.

    Args:
        url: Git repository URL.
        dest: Destination directory (will be created).
        shallow: If True, perform a shallow clone (--depth 1).

    Returns:
        Path to the cloned repository.
    """
    dest = Path(dest)
    if dest.exists():
        raise ValueError(f"Destination already exists: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)

    args = ["clone"]
    if shallow:
        args.extend(["--depth", "1"])
    args.extend([url, str(dest)])

    print(f"Cloning {url} to {dest}...")
    run_git(args)

    return dest


def update_repo(repo_path: Path) -> None:
    """Update a repository by fetching latest changes.

    Args:
        repo_path: Path to the repository.
    """
    repo_path = Path(repo_path)
    if not (repo_path / ".git").exists():
        raise ValueError(f"Not a git repository: {repo_path}")

    print(f"Fetching updates for {repo_path}...")
    run_git(["fetch", "--all", "--tags"], cwd=repo_path)


def checkout_ref(repo_path: Path, ref: str) -> None:
    """Checkout a specific ref (branch, tag, or commit).

    Args:
        repo_path: Path to the repository.
        ref: Git ref to checkout (branch, tag, or commit hash).
    """
    repo_path = Path(repo_path)
    print(f"Checking out {ref}...")
    run_git(["checkout", ref], cwd=repo_path)


def get_current_ref(repo_path: Path) -> str:
    """Get the current HEAD ref.

    Args:
        repo_path: Path to the repository.

    Returns:
        Current branch name, tag, or commit hash.
    """
    repo_path = Path(repo_path)

    # Try to get branch name
    result = run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo_path, check=False)
    if result.returncode == 0:
        return result.stdout.strip()

    # Fall back to commit hash
    result = run_git(["rev-parse", "--short", "HEAD"], cwd=repo_path)
    return result.stdout.strip()


def get_commit_hash(repo_path: Path, ref: str = "HEAD") -> str:
    """Get the full commit hash for a ref.

    Args:
        repo_path: Path to the repository.
        ref: Git ref (default: HEAD).

    Returns:
        Full commit hash.
    """
    result = run_git(["rev-parse", ref], cwd=repo_path)
    return result.stdout.strip()


def is_dirty(repo_path: Path) -> bool:
    """Check if the repository has uncommitted changes.

    Args:
        repo_path: Path to the repository.

    Returns:
        True if there are uncommitted changes.
    """
    result = run_git(["status", "--porcelain"], cwd=repo_path)
    return len(result.stdout.strip()) > 0


def get_remote_default_branch(repo_path: Path) -> Optional[str]:
    """Get the default branch from the remote.

    Args:
        repo_path: Path to the repository.

    Returns:
        Default branch name, or None if it cannot be determined.
    """
    # Try to get the default branch from origin/HEAD
    result = run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo_path, check=False)
    if result.returncode == 0:
        # Returns something like "refs/remotes/origin/main"
        ref = result.stdout.strip()
        if ref.startswith("refs/remotes/origin/"):
            return ref[len("refs/remotes/origin/"):]

    # Fallback: check if common branch names exist
    for branch in ["main", "master"]:
        result = run_git(["rev-parse", "--verify", f"origin/{branch}"], cwd=repo_path, check=False)
        if result.returncode == 0:
            return branch

    return None


def list_refs(repo_path: Path) -> Dict[str, List[str]]:
    """List available refs in a repository.

    Args:
        repo_path: Path to the repository.

    Returns:
        Dictionary with 'branches' and 'tags' lists.
    """
    repo_path = Path(repo_path)

    # Get branches
    result = run_git(["branch", "-a", "--format=%(refname:short)"], cwd=repo_path)
    branches = [b.strip() for b in result.stdout.strip().split('\n') if b.strip()]

    # Get tags
    result = run_git(["tag", "-l"], cwd=repo_path)
    tags = [t.strip() for t in result.stdout.strip().split('\n') if t.strip()]

    return {"branches": branches, "tags": tags}


def get_repo_info(repo_path: Path) -> RepoInfo:
    """Get information about a repository.

    Args:
        repo_path: Path to the repository.

    Returns:
        RepoInfo with repository details.
    """
    repo_path = Path(repo_path)

    # Get remote URL
    result = run_git(["remote", "get-url", "origin"], cwd=repo_path, check=False)
    url = result.stdout.strip() if result.returncode == 0 else "unknown"

    # Derive name from URL or path
    if url != "unknown":
        name = url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
    else:
        name = repo_path.name

    return RepoInfo(
        name=name,
        url=url,
        path=repo_path,
        current_ref=get_current_ref(repo_path),
        is_dirty=is_dirty(repo_path),
    )


def get_or_clone_repo(
    name_or_url: str,
    cache_dir: Path,
    ref: Optional[str] = None,
    update: bool = True,
) -> Path:
    """Get a repository, cloning if necessary.

    This is the main entry point for obtaining a repository. It will:
    1. Clone the repo if not already present in cache_dir
    2. Optionally fetch updates
    3. Checkout the specified ref (if provided)

    Args:
        name_or_url: Repository name or URL.
        cache_dir: Directory to cache cloned repositories.
        ref: Git ref to checkout. If None, stays on current/default branch.
        update: If True, fetch updates before checkout.

    Returns:
        Path to the repository.
    """
    url = resolve_repo_url(name_or_url)

    # Determine repo directory name
    repo_name = url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    repo_path = Path(cache_dir) / repo_name

    # Clone if needed (git clone automatically checks out the default branch)
    freshly_cloned = False
    if not repo_path.exists():
        clone_repo(url, repo_path)
        freshly_cloned = True
    elif update:
        update_repo(repo_path)

    # Checkout ref if explicitly specified
    if ref:
        checkout_ref(repo_path, ref)
    elif not freshly_cloned and update:
        # For existing repos being updated, ensure we're on the default branch
        # and have the latest changes
        default_branch = get_remote_default_branch(repo_path)
        if default_branch:
            current = get_current_ref(repo_path)
            if current != default_branch:
                checkout_ref(repo_path, default_branch)
            # Pull latest changes on the default branch
            run_git(["pull", "--ff-only"], cwd=repo_path, check=False)

    return repo_path


def list_known_repos() -> Dict[str, str]:
    """List known repository names and URLs.

    Returns:
        Dictionary mapping names to URLs.
    """
    return dict(KNOWN_REPOS)
