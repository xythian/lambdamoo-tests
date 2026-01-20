"""LambdaMOO implementation of the server protocol.

This module provides concrete implementations of ServerProtocol and
ClientProtocol for LambdaMOO servers.
"""

import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple, List

from .protocol import (
    ServerProtocol,
    ClientProtocol,
    ServerConfig,
    ServerInstance,
)


class MooServerInstance(ServerInstance):
    """LambdaMOO-specific server instance with process handle."""

    def __init__(self, config: ServerConfig, port: int, input_db: Path,
                 output_db: Path, work_dir: Path, process: subprocess.Popen,
                 log_file: Path):
        super().__init__(
            config=config,
            port=port,
            input_db=input_db,
            output_db=output_db,
            work_dir=work_dir,
            pid=process.pid,
        )
        self.process = process
        self.log_file = log_file

    def is_running(self) -> bool:
        """Check if the server process is still running."""
        return self.process.poll() is None

    def get_log_contents(self) -> str:
        """Read the server log file contents."""
        if self.log_file.exists():
            return self.log_file.read_text()
        return ""


class MooClient(ClientProtocol):
    """LambdaMOO client implementation using TCP sockets."""

    # Patterns to match MOO evaluation results from do_command verb:
    # Success: "#-1:  => value" (caller object followed by result)
    EVAL_SUCCESS_PATTERN = re.compile(r'^[#\-\d]+:\s*=>\s*(.+)$', re.MULTILINE)
    # Error from eval(): "** error_info" (always indicates failure)
    EVAL_ERROR_PATTERN = re.compile(r'^\*\*\s+(.+)$', re.MULTILINE)
    # Traceback: multi-line error with "(End of traceback)"
    EVAL_TRACEBACK_PATTERN = re.compile(r'^#[^:]+:.*line\s+\d+:', re.MULTILINE)

    def __init__(self, host: str = 'localhost', port: int = 7777,
                 timeout: float = 5.0, trace: bool = False, trace_file=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._connected = False
        self._trace = trace
        self._trace_file = trace_file  # File object or None for stderr
        self._transcript: List[Tuple[str, str, str]] = []  # (direction, timestamp, data)

    def _log_trace(self, direction: str, data: str) -> None:
        """Log a trace message for network traffic.

        Args:
            direction: 'SEND' or 'RECV'
            data: The data being sent or received
        """
        import sys
        timestamp = time.strftime('%H:%M:%S')
        self._transcript.append((direction, timestamp, data))

        if self._trace:
            # Format for display: show newlines as \n for clarity
            display_data = data.replace('\n', '\\n')
            if len(display_data) > 200:
                display_data = display_data[:200] + '...'

            output = self._trace_file if self._trace_file else sys.stderr
            prefix = '>>>' if direction == 'SEND' else '<<<'
            print(f"[{timestamp}] {prefix} {display_data}", file=output, flush=True)

    def get_transcript(self) -> List[Tuple[str, str, str]]:
        """Return the full transcript of network traffic.

        Returns:
            List of (direction, timestamp, data) tuples
        """
        return list(self._transcript)

    def format_transcript(self) -> str:
        """Format the transcript as a human-readable string."""
        lines = []
        for direction, timestamp, data in self._transcript:
            prefix = '>>>' if direction == 'SEND' else '<<<'
            # Show data with visible newlines
            display_data = data.replace('\n', '\\n')
            lines.append(f"[{timestamp}] {prefix} {display_data}")
        return '\n'.join(lines)

    def connect(self) -> None:
        """Establish connection to the server."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(self.timeout)
        self._socket.connect((self.host, self.port))
        self._connected = True

        # Read initial connection output (welcome message, etc.)
        time.sleep(0.1)
        self._read_available()

    def close(self) -> None:
        """Close the connection."""
        if self._socket:
            try:
                self._socket.close()
            except socket.error:
                pass
            self._socket = None
        self._connected = False

    def is_connected(self) -> bool:
        """Check if still connected to server."""
        return self._connected and self._socket is not None

    def _read_line(self, timeout: Optional[float] = None) -> str:
        """Read a single line from the socket."""
        timeout = timeout or self.timeout
        self._socket.settimeout(timeout)
        data = []
        try:
            while True:
                chunk = self._socket.recv(1)
                if not chunk:
                    break
                char = chunk.decode('utf-8', errors='replace')
                data.append(char)
                if char == '\n':
                    break
        except socket.timeout:
            pass
        finally:
            self._socket.settimeout(self.timeout)
        result = ''.join(data)
        if result:
            self._log_trace('RECV', result)
        return result

    def _read_available(self, timeout: float = 0.05) -> str:
        """Read any immediately available data."""
        self._socket.settimeout(timeout)
        data = []
        try:
            while True:
                chunk = self._socket.recv(4096)
                if not chunk:
                    break
                data.append(chunk.decode('utf-8', errors='replace'))
        except socket.timeout:
            pass
        finally:
            self._socket.settimeout(self.timeout)
        result = ''.join(data)
        if result:
            self._log_trace('RECV', result)
        return result

    def _send(self, command: str) -> None:
        """Send a command to the server."""
        if not self._connected:
            raise ConnectionError("Not connected to server")
        if not command.endswith('\n'):
            command += '\n'
        self._log_trace('SEND', command)
        self._socket.sendall(command.encode('utf-8'))

    def send(self, command: str) -> None:
        """Send a command to the server (public API)."""
        self._send(command)

    def receive_line(self, timeout: Optional[float] = None) -> str:
        """Receive a single line from the server."""
        return self._read_line(timeout)

    def receive(self, timeout: Optional[float] = None) -> str:
        """Receive any available output from the server."""
        timeout = timeout if timeout is not None else 0.1
        return self._read_available(timeout)

    def authenticate(self, identity: str) -> bool:
        """Authenticate as a user (e.g., 'Wizard')."""
        self._send(f"connect {identity}")
        time.sleep(0.1)
        response = self._read_available()
        # Check for indicators of successful connection
        return "***" not in response.lower() or "connected" in response.lower()

    def eval(self, expression: str, timeout: Optional[float] = None) -> Tuple[bool, str]:
        """Evaluate a MOO expression."""
        # Send as a programmer command (prefix with ;)
        if not expression.startswith(';'):
            expression = ';' + expression

        self._send(expression)

        # Read response lines until we have a complete result
        timeout = timeout or self.timeout
        lines = []
        while True:
            line = self._read_line(timeout)
            if not line:
                break
            lines.append(line)
            # Check for completion markers
            if '=>' in line or '(End of traceback)' in line:
                break
            if line.startswith('**') and '{' in line and line.rstrip().endswith('}'):
                break

        response = ''.join(lines)

        # Check for success: "#-1:  => value"
        match = self.EVAL_SUCCESS_PATTERN.search(response)
        if match:
            return True, match.group(1).strip()

        # Check for error: "** error_info" or traceback
        match = self.EVAL_ERROR_PATTERN.search(response)
        if match:
            return False, match.group(1).strip()

        # Check for traceback (multi-line error)
        if self.EVAL_TRACEBACK_PATTERN.search(response):
            return False, response.strip()

        # Couldn't parse - return raw response as failure
        return False, response.strip() if response.strip() else "(no response)"

    def checkpoint(self) -> bool:
        """Request a database checkpoint."""
        success, _ = self.eval('dump_database()')
        if success:
            # Give the server time to write
            time.sleep(0.5)
        return success

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class MooServer(ServerProtocol):
    """LambdaMOO server implementation."""

    # Pattern to extract the actual listening port from server log
    LISTEN_PORT_PATTERN = re.compile(r'LISTEN:.*now listening on port (\d+)')

    def __init__(self, config: ServerConfig, work_dir: Optional[Path] = None,
                 trace: bool = False):
        super().__init__(config)
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix='moo_test_'))
        self._instances: List[MooServerInstance] = []
        self._instance_counter = 0  # For unique directory names
        self.trace = trace  # Default trace setting for connections

    def _wait_for_listen_port(self, log_file: Path, timeout: float = 10.0) -> Optional[int]:
        """Wait for the server to log its listening port and return it.

        The server logs 'LISTEN: #0 now listening on port <N>' when ready.
        Using port 0 lets the OS assign an ephemeral port atomically.
        """
        start = time.time()
        while time.time() - start < timeout:
            if log_file.exists():
                content = log_file.read_text()
                match = self.LISTEN_PORT_PATTERN.search(content)
                if match:
                    return int(match.group(1))
                # Check for binding errors
                if 'Address already in use' in content:
                    return None
            time.sleep(0.1)
        return None

    def _wait_for_ready(self, port: int, timeout: float = 10.0) -> bool:
        """Wait for the server to be ready to accept connections."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                result = sock.connect_ex(('localhost', port))
                sock.close()
                if result == 0:
                    return True
            except socket.error:
                pass
            time.sleep(0.1)
        return False

    def start(self, database: Path, port: Optional[int] = None,
              work_dir: Optional[Path] = None) -> MooServerInstance:
        """Start a LambdaMOO server instance.

        If port is not specified, uses ephemeral port assignment (port 0)
        which lets the OS assign an available port atomically, avoiding
        race conditions.
        """
        database = Path(database).resolve()
        if not database.exists():
            raise FileNotFoundError(f"Database not found: {database}")

        # Use ephemeral port (0) by default - OS assigns atomically
        requested_port = port if port is not None else 0

        # Create unique instance directory
        self._instance_counter += 1
        instance_dir = work_dir or (self.work_dir / f"instance_{self._instance_counter}")
        instance_dir.mkdir(parents=True, exist_ok=True)

        # Copy database to working directory
        input_db = instance_dir / "input.db"
        shutil.copy(database, input_db)

        output_db = instance_dir / "output.db"
        log_file = instance_dir / "server.log"

        # Build command line
        cmd = [
            str(self.config.binary),
            '-l', str(log_file),
            str(input_db),
            str(output_db),
            '-p', str(requested_port),
        ]

        # Start the server
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(instance_dir),
        )

        # Wait for server to log its actual listening port
        actual_port = self._wait_for_listen_port(log_file)
        if actual_port is None:
            # Server failed to start
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            log_contents = log_file.read_text() if log_file.exists() else "(no log)"
            raise RuntimeError(
                f"Server failed to start - could not bind to port.\n"
                f"Log contents:\n{log_contents}"
            )

        instance = MooServerInstance(
            config=self.config,
            port=actual_port,
            input_db=input_db,
            output_db=output_db,
            work_dir=instance_dir,
            process=process,
            log_file=log_file,
        )

        # Verify we can actually connect
        if not self._wait_for_ready(actual_port):
            self.stop(instance)
            log_contents = instance.get_log_contents()
            raise RuntimeError(
                f"Server failed to start within timeout.\n"
                f"Log contents:\n{log_contents}"
            )

        self._instances.append(instance)
        return instance

    def stop(self, instance: MooServerInstance, timeout: float = 10.0) -> Path:
        """Stop a LambdaMOO server instance and wait for database to be written.

        The server writes its output database on graceful shutdown (SIGTERM),
        so we must wait for the process to fully exit before the database
        can be safely read by another server.
        """
        if instance in self._instances:
            self._instances.remove(instance)

        # Check if process already exited (but still need to reap it)
        exit_code = instance.process.poll()
        if exit_code is not None:
            # Process already exited, just ensure it's reaped
            instance.process.wait()
            return instance.output_db

        # Try graceful shutdown first (SIGTERM) - server writes DB on SIGTERM
        instance.process.terminate()

        try:
            instance.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Force kill - database may not be written properly
            instance.process.kill()
            instance.process.wait()

        # Wait for filesystem to sync and verify database exists
        # The server writes the DB before exiting, but filesystem may buffer
        for _ in range(10):  # Up to 1 second
            if instance.output_db.exists():
                return instance.output_db
            time.sleep(0.1)

        # Return path even if it doesn't exist - let caller handle the error
        return instance.output_db

    def connect(self, instance: MooServerInstance,
                timeout: float = 5.0, trace: Optional[bool] = None,
                trace_file=None) -> MooClient:
        """Connect to a running LambdaMOO server."""
        # Use server's default trace setting if not specified
        if trace is None:
            trace = self.trace
        client = MooClient(host='localhost', port=instance.port, timeout=timeout,
                           trace=trace, trace_file=trace_file)
        client.connect()
        return client

    def get_version(self) -> str:
        """Get the server version string."""
        # Would need to run server and query, for now return from config
        return self.config.version

    def stop_all(self) -> None:
        """Stop all running server instances."""
        for instance in list(self._instances):
            self.stop(instance)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_all()
        return False
