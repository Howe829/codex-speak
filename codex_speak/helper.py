from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Final

from .diagnostics import record
from .queue import _default_clock_id, _normalize_clock_id
from .worker import spawn_worker


HELPER: Final[Path] = Path(
    "assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu"
)
HELPER_EVENT_ID: Final[str] = hashlib.sha256(b"codex-speak-helper").hexdigest()[:24]
HELPER_STATE: Final[str] = "helper-state.json"
STATE_VERSION: Final[int] = 1
HEARTBEAT_STALE_SECONDS: Final[float] = 5.0
VERIFY_ATTEMPTS: Final[int] = 60


def _validated_python_executable() -> Path:
    executable = Path(sys.executable)
    if (
        not executable.is_absolute()
        or not executable.is_file()
        or not os.access(executable, os.X_OK)
    ):
        raise OSError("python executable unavailable")
    return executable


def record_helper_start_failed_without_exception_text(data_dir: Path) -> None:
    record(
        data_dir,
        event_id=HELPER_EVENT_ID,
        status="unknown",
        result="failed",
        mode="unknown",
        error_code="helper_start_failed",
    )


def _read_current_state(
    path: Path,
    *,
    current_boot_id: str,
    now: float,
    expected_pid: int | None = None,
) -> int | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "pid",
        "boot_id",
        "monotonic",
    }:
        return None
    version = raw.get("version")
    pid = raw.get("pid")
    boot_id = raw.get("boot_id")
    heartbeat = raw.get("monotonic")
    if not (
        type(version) is int
        and version == STATE_VERSION
        and type(pid) is int
        and pid > 0
        and (expected_pid is None or pid == expected_pid)
        and isinstance(boot_id, str)
        and _normalize_clock_id(boot_id) == current_boot_id
        and type(heartbeat) in (int, float)
        and math.isfinite(heartbeat)
        and 0.0 <= now - float(heartbeat) <= HEARTBEAT_STALE_SECONDS
    ):
        return None
    try:
        os.chmod(path.parent, 0o700)
        os.chmod(path, 0o600)
    except OSError:
        return None
    return pid


def launch_verified_helper(
    executable: Path,
    plugin_root: Path,
    data_dir: Path,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    boot_id_loader: Callable[[], str | None] = _default_clock_id,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    if not all(path.is_absolute() for path in (executable, plugin_root, data_dir)):
        raise OSError("helper launch paths must be absolute")
    boot_id = boot_id_loader()
    normalized_boot_id = _normalize_clock_id(boot_id)
    if normalized_boot_id is None:
        raise OSError("boot identity unavailable")

    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(data_dir, 0o700)
    state_path = data_dir / HELPER_STATE
    if (
        _read_current_state(
            state_path,
            current_boot_id=normalized_boot_id,
            now=monotonic(),
        )
        is not None
    ):
        return

    state_path.unlink(missing_ok=True)
    process = popen(
        [
            str(executable),
            "--plugin-root",
            str(plugin_root),
            "--data-dir",
            str(data_dir),
            "--python-executable",
            str(_validated_python_executable()),
        ],
        cwd=str(plugin_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    for _ in range(VERIFY_ATTEMPTS):
        if (
            _read_current_state(
                state_path,
                current_boot_id=normalized_boot_id,
                now=monotonic(),
                expected_pid=process.pid,
            )
            is not None
        ):
            return
        sleep(0.05)
    raise OSError("helper heartbeat unavailable")


def ensure_consumer(plugin_root: Path, data_dir: Path) -> str:
    executable = plugin_root / HELPER
    if executable.is_file() and os.access(executable, os.X_OK):
        try:
            launch_verified_helper(executable, plugin_root, data_dir)
            return "helper"
        except OSError:
            record_helper_start_failed_without_exception_text(data_dir)
    spawn_worker(plugin_root, data_dir)
    return "fallback"
