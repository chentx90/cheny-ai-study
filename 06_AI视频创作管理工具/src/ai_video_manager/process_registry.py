"""Track OS child processes (CLI) so shutdown can terminate them."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_processes: set[subprocess.Popen[Any]] = set()


def register_process(proc: subprocess.Popen[Any]) -> None:
    with _lock:
        _processes.add(proc)


def unregister_process(proc: subprocess.Popen[Any]) -> None:
    with _lock:
        _processes.discard(proc)


def kill_all_processes(*, grace_seconds: float = 1.0) -> int:
    """Terminate tracked child processes. Returns how many were signaled."""
    with _lock:
        procs = list(_processes)
        _processes.clear()
    killed = 0
    for proc in procs:
        if proc.poll() is not None:
            continue
        killed += 1
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, AttributeError):
                    proc.terminate()
        except Exception:
            logger.exception("Failed to terminate child pid=%s", getattr(proc, "pid", "?"))
    if not procs:
        return 0
    import time

    deadline = time.time() + max(grace_seconds, 0.1)
    for proc in procs:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            proc.wait(timeout=remaining)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    for proc in procs:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
    if killed:
        logger.info("Terminated %s CLI child process(es)", killed)
    return killed
