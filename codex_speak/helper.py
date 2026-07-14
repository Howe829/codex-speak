from __future__ import annotations

import hashlib
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Callable, Final, Iterator

from .diagnostics import record
from .queue import _default_clock_id, _normalize_clock_id
from .worker import spawn_worker


HELPER: Final[Path] = Path(
    "assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu"
)
HELPER_EVENT_ID: Final[str] = hashlib.sha256(b"codex-speak-helper").hexdigest()[:24]
HELPER_STATE: Final[str] = "helper-state.json"
HELPER_STATE_LOCK: Final[str] = ".helper-state.lock"
HELPER_LAUNCH_LOCK: Final[str] = ".helper-launch.lock"
STATE_VERSION: Final[int] = 2
IDENTITY_HEX_LENGTH: Final[int] = 64
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


def _helper_identity(plugin_root: Path) -> str:
    canonical_root = plugin_root.resolve(strict=True)
    if not canonical_root.is_dir():
        raise OSError("plugin root unavailable")
    return hashlib.sha256(os.fsencode(canonical_root)).hexdigest()


def _valid_identity(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == IDENTITY_HEX_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


@contextmanager
def _file_lock(data_dir: Path, name: str) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(data_dir, 0o700)
    descriptor = os.open(
        data_dir / name,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_fresh_state_unlocked(
    path: Path,
    *,
    current_boot_id: str,
    now: float,
    expected_pid: int | None = None,
) -> tuple[int, str] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "pid",
        "boot_id",
        "monotonic",
        "identity",
    }:
        return None
    version = raw.get("version")
    pid = raw.get("pid")
    boot_id = raw.get("boot_id")
    heartbeat = raw.get("monotonic")
    identity = raw.get("identity")
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
        and _valid_identity(identity)
    ):
        return None
    return pid, identity


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
    expected_identity: str,
    expected_pid: int | None = None,
) -> int | None:
    with _file_lock(path.parent, HELPER_STATE_LOCK):
        state = _read_fresh_state_unlocked(
            path,
            current_boot_id=current_boot_id,
            now=now,
            expected_pid=expected_pid,
        )
    if state is None or state[1] != expected_identity:
        return None
    pid = state[0]
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
    plugin_root = plugin_root.resolve(strict=True)
    identity = _helper_identity(plugin_root)
    boot_id = boot_id_loader()
    normalized_boot_id = _normalize_clock_id(boot_id)
    if normalized_boot_id is None:
        raise OSError("boot identity unavailable")

    with _file_lock(data_dir, HELPER_LAUNCH_LOCK):
        state_path = data_dir / HELPER_STATE
        with _file_lock(data_dir, HELPER_STATE_LOCK):
            owner = _read_fresh_state_unlocked(
                state_path,
                current_boot_id=normalized_boot_id,
                now=monotonic(),
            )
        if owner is not None and owner[1] == identity:
            return
        if owner is not None:
            try:
                os.kill(owner[0], signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as error:
                raise OSError("prior helper unavailable") from error
            for _ in range(VERIFY_ATTEMPTS):
                with _file_lock(data_dir, HELPER_STATE_LOCK):
                    current_owner = _read_fresh_state_unlocked(
                        state_path,
                        current_boot_id=normalized_boot_id,
                        now=monotonic(),
                    )
                    if current_owner != owner:
                        break
                    try:
                        os.kill(owner[0], 0)
                    except ProcessLookupError:
                        state_path.unlink(missing_ok=True)
                        break
                    except OSError as error:
                        raise OSError("prior helper unavailable") from error
                sleep(0.05)
            else:
                raise OSError("prior helper did not stop")
        with _file_lock(data_dir, HELPER_STATE_LOCK):
            current_owner = _read_fresh_state_unlocked(
                state_path,
                current_boot_id=normalized_boot_id,
                now=monotonic(),
            )
            if current_owner is not None:
                if current_owner[1] == identity:
                    return
                raise OSError("prior helper ownership changed")
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
                "--helper-identity",
                identity,
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
                    expected_identity=identity,
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
