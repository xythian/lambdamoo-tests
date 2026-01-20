"""Configuration management for LambdaMOO test suite.

This module handles configuration for the test suite, including:
- Build cache locations
- Known repository URLs
- Database paths
- Environment-specific settings

Configuration is loaded from (in order of precedence):
1. Environment variables (MOO_* prefix)
2. Project-local .moo-tests.toml
3. User config ~/.config/lambdamoo-tests/config.toml
4. Built-in defaults
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Any, List

# Try to import tomllib (Python 3.11+) or tomli as fallback
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


@dataclass
class BuildConfig:
    """A named build configuration with specific configure flags."""
    name: str
    configure_flags: List[str]
    description: str = ""


# Predefined build configurations for LambdaMOO
# These map to ./configure options in the main lambdamoo repo
PREDEFINED_BUILD_CONFIGS: Dict[str, BuildConfig] = {
    "default": BuildConfig(
        name="default",
        configure_flags=[],
        description="Default build with no extra options",
    ),
    "i32": BuildConfig(
        name="i32",
        configure_flags=["--enable-sz=i32"],
        description="Explicit 32-bit integers (for testing overflow behavior)",
    ),
    "i64": BuildConfig(
        name="i64",
        configure_flags=["--enable-sz=i64"],
        description="64-bit integers",
    ),
    "i64_unicode": BuildConfig(
        name="i64_unicode",
        configure_flags=["--enable-sz=i64", "--enable-unicode"],
        description="64-bit integers + Unicode strings",
    ),
    "i64_xml": BuildConfig(
        name="i64_xml",
        configure_flags=["--enable-sz=i64", "--enable-xml"],
        description="64-bit integers + XML support",
    ),
    "i64_waifs": BuildConfig(
        name="i64_waifs",
        configure_flags=["--enable-sz=i64", "--enable-waifs=dict"],
        description="64-bit integers + Waifs with dict syntax",
    ),
    "i64_unicode_waifs": BuildConfig(
        name="i64_unicode_waifs",
        configure_flags=["--enable-sz=i64", "--enable-unicode", "--enable-waifs=dict"],
        description="64-bit integers + Unicode + Waifs",
    ),
    "waterpoint": BuildConfig(
        name="waterpoint",
        configure_flags=[
            "--enable-sz=i64",
            "--enable-unicode",
            "--enable-xml",
            "--enable-waifs=dict",
        ],
        description="Full Waterpoint config (i64 + unicode + xml + waifs)",
    ),
    "full": BuildConfig(
        name="full",
        configure_flags=[
            "--enable-sz=i64",
            "--enable-unicode",
            "--enable-xml",
            "--enable-waifs=dict",
        ],
        description="Full feature set (alias for waterpoint)",
    ),
}


@dataclass
class RepoConfig:
    """Configuration for a known repository."""
    url: str
    default_branch: str = "master"
    configure_flags: str = ""
    # Default build config name for this repo (if any)
    default_build_config: str = ""
    # Custom build script (relative to repo root), if any
    build_script: str = ""
    # Known features for repos that don't report them via server_version
    # List of: i64, unicode, xml, waifs, waif_dict
    known_features: List[str] = field(default_factory=list)


@dataclass
class Config:
    """Main configuration for the test suite."""

    # Directory for caching cloned repositories
    repo_cache_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "lambdamoo-tests" / "repos")

    # Directory for caching built binaries
    build_cache_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "lambdamoo-tests" / "builds")

    # Directory for test databases (auto-generated, server-scoped)
    database_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "lambdamoo-tests" / "databases")

    # Path to Minimal.db (if known)
    minimal_db: Optional[Path] = None

    # Default MOO binary path (if known)
    moo_binary: Optional[Path] = None

    # Known repositories
    repos: Dict[str, RepoConfig] = field(default_factory=dict)

    # Named build configurations
    build_configs: Dict[str, BuildConfig] = field(default_factory=dict)

    # Default configure flags for builds
    default_configure_flags: str = ""

    # Number of parallel jobs for make
    make_jobs: int = 4

    def __post_init__(self):
        # Ensure paths are Path objects
        if isinstance(self.repo_cache_dir, str):
            self.repo_cache_dir = Path(self.repo_cache_dir)
        if isinstance(self.build_cache_dir, str):
            self.build_cache_dir = Path(self.build_cache_dir)
        if isinstance(self.database_dir, str):
            self.database_dir = Path(self.database_dir)
        if isinstance(self.minimal_db, str):
            self.minimal_db = Path(self.minimal_db)
        if isinstance(self.moo_binary, str):
            self.moo_binary = Path(self.moo_binary)

        # Expand ~ in paths
        self.repo_cache_dir = self.repo_cache_dir.expanduser()
        self.build_cache_dir = self.build_cache_dir.expanduser()
        self.database_dir = self.database_dir.expanduser()
        if self.minimal_db:
            self.minimal_db = self.minimal_db.expanduser()
        if self.moo_binary:
            self.moo_binary = self.moo_binary.expanduser()

        # Add default known repos if not overridden
        if "lambdamoo" not in self.repos:
            self.repos["lambdamoo"] = RepoConfig(
                url="https://github.com/wrog/lambdamoo",
                default_branch="main",
                default_build_config="",  # Multiple configs available
            )
        if "wp-lambdamoo" not in self.repos:
            self.repos["wp-lambdamoo"] = RepoConfig(
                url="https://github.com/xythian/wp-lambdamoo",
                default_branch="main",
                default_build_config="waterpoint",  # Single config
                build_script="build.sh",  # Custom build script
                # wp-lambdamoo doesn't report features via server_version
                known_features=["i64", "unicode", "xml", "waifs", "waif_dict"],
            )

        # Add predefined build configs if not overridden
        for name, config in PREDEFINED_BUILD_CONFIGS.items():
            if name not in self.build_configs:
                self.build_configs[name] = config


# Default configuration file locations
USER_CONFIG_PATH = Path.home() / ".config" / "lambdamoo-tests" / "config.toml"
PROJECT_CONFIG_NAME = ".moo-tests.toml"


def _find_project_config() -> Optional[Path]:
    """Find project-local config file by walking up from cwd."""
    current = Path.cwd()
    while current != current.parent:
        config_path = current / PROJECT_CONFIG_NAME
        if config_path.exists():
            return config_path
        current = current.parent
    return None


def _load_toml(path: Path) -> Dict[str, Any]:
    """Load a TOML file and return its contents."""
    if tomllib is None:
        # No TOML parser available, return empty dict
        return {}
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _parse_repos(repos_dict: Dict[str, Any]) -> Dict[str, RepoConfig]:
    """Parse repos section from config file."""
    result = {}
    for name, info in repos_dict.items():
        if isinstance(info, str):
            # Simple URL string
            result[name] = RepoConfig(url=info)
        elif isinstance(info, dict):
            result[name] = RepoConfig(
                url=info.get("url", ""),
                default_branch=info.get("default_branch", "master"),
                configure_flags=info.get("configure_flags", ""),
            )
    return result


def load_config() -> Config:
    """Load configuration from files and environment.

    Returns:
        Config object with merged settings.
    """
    config = Config()

    # Load user config
    user_data = _load_toml(USER_CONFIG_PATH)

    # Load project config (overrides user)
    project_path = _find_project_config()
    project_data = _load_toml(project_path) if project_path else {}

    # Merge configs (project overrides user)
    for data in [user_data, project_data]:
        if not data:
            continue

        # Paths section
        if "paths" in data:
            paths = data["paths"]
            if "repo_cache_dir" in paths:
                config.repo_cache_dir = Path(paths["repo_cache_dir"]).expanduser()
            if "build_cache_dir" in paths:
                config.build_cache_dir = Path(paths["build_cache_dir"]).expanduser()
            if "database_dir" in paths:
                config.database_dir = Path(paths["database_dir"]).expanduser()
            if "minimal_db" in paths:
                config.minimal_db = Path(paths["minimal_db"]).expanduser()
            if "moo_binary" in paths:
                config.moo_binary = Path(paths["moo_binary"]).expanduser()

        # Build section
        if "build" in data:
            build = data["build"]
            if "configure_flags" in build:
                config.default_configure_flags = build["configure_flags"]
            if "make_jobs" in build:
                config.make_jobs = int(build["make_jobs"])

        # Repos section
        if "repos" in data:
            config.repos.update(_parse_repos(data["repos"]))

    # Environment overrides (highest precedence)
    if env_repo_cache := os.environ.get("MOO_REPO_CACHE_DIR"):
        config.repo_cache_dir = Path(env_repo_cache).expanduser()
    if env_build_cache := os.environ.get("MOO_BUILD_CACHE_DIR"):
        config.build_cache_dir = Path(env_build_cache).expanduser()
    if env_db_dir := os.environ.get("MOO_DATABASE_DIR"):
        config.database_dir = Path(env_db_dir).expanduser()
    if env_minimal := os.environ.get("MOO_MINIMAL_DB"):
        config.minimal_db = Path(env_minimal).expanduser()
    if env_binary := os.environ.get("MOO_BINARY"):
        config.moo_binary = Path(env_binary).expanduser()
    if env_flags := os.environ.get("MOO_CONFIGURE_FLAGS"):
        config.default_configure_flags = env_flags
    if env_jobs := os.environ.get("MOO_MAKE_JOBS"):
        config.make_jobs = int(env_jobs)

    return config


def get_config() -> Config:
    """Get the current configuration (cached).

    Returns:
        Config object.
    """
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def reset_config():
    """Reset the cached configuration."""
    global _cached_config
    _cached_config = None


# Cached config instance
_cached_config: Optional[Config] = None


def get_build_config(name: str, config: Optional[Config] = None) -> Optional[BuildConfig]:
    """Get a build configuration by name.

    Args:
        name: Build configuration name.
        config: Optional Config object (default: load from files).

    Returns:
        BuildConfig if found, None otherwise.
    """
    if config is None:
        config = get_config()
    return config.build_configs.get(name)


def list_build_configs(config: Optional[Config] = None) -> Dict[str, BuildConfig]:
    """List all available build configurations.

    Args:
        config: Optional Config object (default: load from files).

    Returns:
        Dictionary of build config name to BuildConfig.
    """
    if config is None:
        config = get_config()
    return dict(config.build_configs)


def generate_sample_config() -> str:
    """Generate a sample configuration file.

    Returns:
        Sample TOML configuration as a string.
    """
    return '''# LambdaMOO Test Suite Configuration
# Place this file at ~/.config/lambdamoo-tests/config.toml (user)
# or .moo-tests.toml in your project directory (project)

[paths]
# Directory for caching cloned repositories
repo_cache_dir = "~/.cache/lambdamoo-tests/repos"

# Directory for caching built binaries
build_cache_dir = "~/.cache/lambdamoo-tests/builds"

# Directory for test databases
database_dir = "~/.cache/lambdamoo-tests/databases"

# Path to Minimal.db (optional, auto-detected if not set)
# minimal_db = "/path/to/Minimal.db"

# Default MOO binary (optional, auto-detected if not set)
# moo_binary = "/path/to/moo"

[build]
# Default configure flags for all builds
configure_flags = ""

# Number of parallel jobs for make
make_jobs = 4

[repos.lambdamoo]
url = "https://github.com/wrog/lambdamoo"
default_branch = "main"
# No default_build_config - multiple configs available

[repos.wp-lambdamoo]
url = "https://github.com/xythian/wp-lambdamoo"
default_branch = "main"
default_build_config = "waterpoint"

# Add custom repos like this:
# [repos.my-fork]
# url = "https://github.com/myuser/lambdamoo"
# default_branch = "my-feature"
# default_build_config = "i64_unicode"

# Predefined build configurations (these are built-in):
#   default         - Default build with no extra options
#   i64             - 64-bit integers
#   i64_unicode     - 64-bit integers + Unicode strings
#   i64_xml         - 64-bit integers + XML support
#   i64_waifs       - 64-bit integers + Waifs with dict syntax
#   i64_unicode_waifs - 64-bit integers + Unicode + Waifs
#   waterpoint      - Full Waterpoint config (i64 + unicode + xml + waifs)
#   full            - Full feature set (alias for waterpoint)

# Add custom build configurations like this:
# [build_configs.my_config]
# configure_flags = ["--enable-sz=i64", "--enable-unicode", "--my-custom-flag"]
# description = "My custom build configuration"
'''
