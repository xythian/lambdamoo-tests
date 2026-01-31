"""Abstract protocol interfaces for MOO-compatible servers.

This module defines the abstract interfaces that any MOO-compatible server
must implement to be testable with this test suite. This allows testing
different server implementations (LambdaMOO, ToastStunt, etc.) with the
same test code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Optional, Dict, Any


@dataclass
class ServerConfig:
    """Configuration for a server instance."""
    binary: Path
    name: str = "unknown"
    version: str = "unknown"
    features: Dict[str, Any] = None

    def __post_init__(self):
        if self.features is None:
            self.features = {}


@dataclass
class ServerInstance:
    """Represents a running server instance."""
    config: ServerConfig
    port: int
    input_db: Path
    output_db: Path
    work_dir: Path
    pid: int

    def is_running(self) -> bool:
        """Check if the server process is still running."""
        raise NotImplementedError


class ClientProtocol(ABC):
    """Abstract protocol for MOO client interaction.

    Any client implementation must provide these methods to interact
    with a MOO-compatible server.
    """

    @abstractmethod
    def authenticate(self, identity: str) -> bool:
        """Authenticate as a user.

        Args:
            identity: User identity (e.g., 'Wizard', 'guest')

        Returns:
            True if authentication succeeded.
        """
        pass

    @abstractmethod
    def eval(self, expression: str, timeout: Optional[float] = None) -> Tuple[bool, str]:
        """Evaluate a MOO expression.

        Args:
            expression: The MOO expression to evaluate.
            timeout: Optional timeout in seconds.

        Returns:
            Tuple of (success, result_or_error).
        """
        pass

    @abstractmethod
    def checkpoint(self) -> bool:
        """Request a database checkpoint.

        Returns:
            True if checkpoint was initiated successfully.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the connection."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if still connected to server."""
        pass


class ServerProtocol(ABC):
    """Abstract protocol for MOO-compatible servers.

    Any server implementation must provide these methods to be
    testable with this test suite.
    """

    def __init__(self, config: ServerConfig):
        """Initialize with server configuration.

        Args:
            config: Server configuration including binary path.
        """
        self.config = config

    @abstractmethod
    def start(self, database: Path, port: Optional[int] = None,
              work_dir: Optional[Path] = None,
              emergency_mode: bool = False) -> ServerInstance:
        """Start a server instance.

        Args:
            database: Path to the input database file.
            port: Port to listen on (auto-allocate if None).
            work_dir: Working directory for this instance.
            emergency_mode: If True, start in emergency wizard mode (-e flag).
                           In this mode, no network listener is created and
                           commands are read from stdin.

        Returns:
            ServerInstance representing the running server.

        Raises:
            RuntimeError: If server fails to start.
        """
        pass

    @abstractmethod
    def stop(self, instance: ServerInstance, timeout: float = 5.0) -> Path:
        """Stop a server instance.

        Args:
            instance: The server instance to stop.
            timeout: Seconds to wait for graceful shutdown.

        Returns:
            Path to the output database.
        """
        pass

    @abstractmethod
    def connect(self, instance: ServerInstance,
                timeout: float = 5.0) -> ClientProtocol:
        """Connect to a running server.

        Args:
            instance: The server instance to connect to.
            timeout: Connection timeout in seconds.

        Returns:
            A connected client implementing ClientProtocol.
        """
        pass

    @abstractmethod
    def get_version(self) -> str:
        """Get the server version string.

        Returns:
            Version string (e.g., "1.9.0").
        """
        pass


class TestPhase:
    """Represents a phase in a persistence/upgrade test."""

    WRITE = "write"  # Phase where data is created
    READ = "read"    # Phase where data is verified


@dataclass
class ServerPair:
    """A pair of servers for persistence/upgrade testing.

    For persistence tests: write_server == read_server
    For upgrade tests: write_server != read_server (old -> new)
    """
    write_server: ServerProtocol
    read_server: ServerProtocol
    name: str  # e.g., "persistence" or "upgrade_from_waterpoint"
    write_db_dir: Path = None  # Database directory for write server

    @property
    def is_upgrade_test(self) -> bool:
        """True if this is an upgrade test (different servers)."""
        return self.write_server.config.binary != self.read_server.config.binary

    @property
    def is_persistence_test(self) -> bool:
        """True if this is a persistence test (same server)."""
        return not self.is_upgrade_test
