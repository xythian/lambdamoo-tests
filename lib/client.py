"""MOO network client for testing."""

import re
import socket
import time
from typing import Optional, Tuple, List


class MooClient:
    """Network client for interacting with MOO servers."""

    # Patterns to match MOO evaluation results from do_command verb:
    # Success: "#-1:  => value" (caller object followed by result)
    EVAL_SUCCESS_PATTERN = re.compile(r'^[#\-\d]+:\s*=>\s*(.+)$', re.MULTILINE)
    # Error from eval(): "** error_info" (always indicates failure)
    EVAL_ERROR_PATTERN = re.compile(r'^\*\*\s+(.+)$', re.MULTILINE)
    # Traceback: multi-line error with "(End of traceback)"
    EVAL_TRACEBACK_PATTERN = re.compile(r'^#[^:]+:.*line\s+\d+:', re.MULTILINE)

    def __init__(self,
                 host: str = 'localhost',
                 port: int = 7777,
                 timeout: float = 5.0):
        """
        Create a new MOO client and connect to the server.

        Args:
            host: Server hostname or IP address.
            port: Server port number.
            timeout: Default timeout for operations in seconds.
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._buffer = ""
        self._connected = False

        self.connect()

    def connect(self):
        """Establish connection to the server."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(self.timeout)
        self._socket.connect((self.host, self.port))
        self._connected = True

        # Read initial connection output (welcome message, etc.)
        time.sleep(0.1)
        self._read_available()

    def close(self):
        """Close the connection."""
        if self._socket:
            try:
                self._socket.close()
            except socket.error:
                pass
            self._socket = None
        self._connected = False

    def _read_line(self, timeout: Optional[float] = None) -> str:
        """Read a single line from the socket (up to and including newline)."""
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
        return ''.join(data)

    def _read_available(self, timeout: float = 0.05) -> str:
        """Read any immediately available data without blocking long."""
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
        return ''.join(data)

    def send(self, command: str) -> None:
        """
        Send a command to the server.

        Args:
            command: The command text to send (newline will be appended).
        """
        if not self._connected:
            raise ConnectionError("Not connected to server")

        if not command.endswith('\n'):
            command += '\n'

        self._socket.sendall(command.encode('utf-8'))

    def receive_line(self, timeout: Optional[float] = None) -> str:
        """
        Receive a single line from the server.

        Args:
            timeout: Timeout in seconds. Uses default if None.

        Returns:
            The received line (including newline if present).
        """
        return self._read_line(timeout)

    def receive(self, timeout: Optional[float] = None) -> str:
        """
        Receive any available output from the server.

        Args:
            timeout: Timeout in seconds. Default 0.1s.

        Returns:
            The received text.
        """
        timeout = timeout if timeout is not None else 0.1
        return self._read_available(timeout)

    def send_and_receive(self,
                         command: str,
                         timeout: Optional[float] = None,
                         delay: float = 0.1) -> str:
        """
        Send a command and collect the response.

        Args:
            command: The command to send.
            timeout: Timeout for receiving response.
            delay: Delay before reading response to allow processing.

        Returns:
            The server's response.
        """
        self.send(command)
        time.sleep(delay)
        return self.receive(timeout)

    def eval(self, expression: str, timeout: Optional[float] = None) -> Tuple[bool, str]:
        """
        Evaluate a MOO expression and return the result.

        Args:
            expression: The MOO expression to evaluate.
            timeout: Timeout for the operation.

        Returns:
            Tuple of (success, result_or_error).
            - If success is True, result_or_error contains the value.
            - If success is False, result_or_error contains the error message.
        """
        # Send as a programmer command (prefix with ;)
        if not expression.startswith(';'):
            expression = ';' + expression

        self.send(expression)

        # Read response lines until we have a complete result
        # - Success: single line with "=> value"
        # - Compile error: single line "** {errors}"
        # - Runtime error: multiple lines ending with "(End of traceback)"
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

    def eval_expect_success(self, expression: str, timeout: Optional[float] = None) -> str:
        """
        Evaluate an expression, raising an exception on failure.

        Args:
            expression: The MOO expression to evaluate.
            timeout: Timeout for the operation.

        Returns:
            The result value.

        Raises:
            AssertionError: If the evaluation failed.
        """
        success, result = self.eval(expression, timeout)
        if not success:
            raise AssertionError(f"MOO evaluation failed: {result}")
        return result

    def login_wizard(self, player_name: str = "Wizard") -> bool:
        """
        Attempt to log in as a wizard player.

        This is a convenience method for tests that need wizard access.
        Assumes the standard login mechanism.

        Args:
            player_name: Name to use for login.

        Returns:
            True if login appeared successful.
        """
        response = self.send_and_receive(f"connect {player_name}")
        # Check for indicators of successful connection
        return "***" not in response.lower() or "connected" in response.lower()

    def login(self, player_name: str, password: str = "") -> bool:
        """
        Attempt to log in as a specific player.

        Args:
            player_name: Player name or object number.
            password: Player password.

        Returns:
            True if login appeared successful.
        """
        if password:
            response = self.send_and_receive(f"connect {player_name} {password}")
        else:
            response = self.send_and_receive(f"connect {player_name}")

        return "***" not in response.lower()

    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._connected and self._socket is not None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class MooClientPool:
    """Pool of MOO clients for multi-user testing."""

    def __init__(self, host: str, port: int, size: int = 5):
        """
        Create a pool of clients.

        Args:
            host: Server hostname.
            port: Server port.
            size: Number of clients in the pool.
        """
        self.host = host
        self.port = port
        self.clients: List[MooClient] = []

        for _ in range(size):
            client = MooClient(host, port)
            self.clients.append(client)

    def close_all(self):
        """Close all clients in the pool."""
        for client in self.clients:
            client.close()
        self.clients.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()
        return False

    def __len__(self):
        return len(self.clients)

    def __getitem__(self, index):
        return self.clients[index]
