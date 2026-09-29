"""Build and drive the LD_PRELOAD fault-injection shim (see fault_shim.c)."""

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

SHIM_SOURCE = Path(__file__).with_name('fault_shim.c')


def build_fault_shim(out_dir: Path) -> Optional[Path]:
    """Compile the fault-injection shim into out_dir.

    Returns:
        Path to the shared object, or None if LD_PRELOAD shims aren't
        supported here (not Linux, or no C compiler).

    Raises:
        subprocess.CalledProcessError: If compilation fails.
    """
    if platform.system() != 'Linux':
        return None
    cc = shutil.which('cc') or shutil.which('gcc')
    if not cc:
        return None
    shim = out_dir / 'fault_shim.so'
    subprocess.run([cc, '-shared', '-fPIC', '-O2', '-o', str(shim), str(SHIM_SOURCE), '-ldl'],
                   check=True, capture_output=True)
    return shim


class FaultInjector:
    """Arms faults in a server started with the shim preloaded."""

    def __init__(self, shim: Path, fault_dir: Path):
        self.fault_dir = fault_dir
        fault_dir.mkdir(parents=True, exist_ok=True)
        self.env = {'LD_PRELOAD': str(shim), 'MOO_FAULT_DIR': str(fault_dir)}

    def close_listener_on_next_accept(self, port: int) -> Path:
        """On the server's next accept(), close the listener on port and the new connection.

        Returns:
            The trigger file, which the shim removes once the fault has fired.
        """
        trigger = self.fault_dir / 'close-listener'
        trigger.write_text(str(port))
        return trigger

    def fail_waits(self, enabled: bool) -> None:
        """Make every select()/poll() fail with EINVAL while enabled."""
        trigger = self.fault_dir / 'fail-wait'
        if enabled:
            trigger.touch()
        else:
            trigger.unlink(missing_ok=True)
