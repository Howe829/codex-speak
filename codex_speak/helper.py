from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
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
STATE_VERSION: Final[int] = 3
IDENTITY_HEX_LENGTH: Final[int] = 64
TOKEN_HEX_LENGTH: Final[int] = 64
HEARTBEAT_STALE_SECONDS: Final[float] = 5.0
VERIFY_ATTEMPTS: Final[int] = 60


@dataclass(frozen=True)
class _HelperState:
    phase: str
    pid: int
    boot_id: str
    monotonic: float
    identity: str
    token: str


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


def _valid_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
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
) -> _HelperState | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "phase",
        "pid",
        "boot_id",
        "monotonic",
        "identity",
        "token",
    }:
        return None
    version = raw.get("version")
    phase = raw.get("phase")
    pid = raw.get("pid")
    boot_id = raw.get("boot_id")
    heartbeat = raw.get("monotonic")
    identity = raw.get("identity")
    token = raw.get("token")
    if not (
        type(version) is int
        and version == STATE_VERSION
        and isinstance(phase, str)
        and phase in {"starting", "running"}
        and type(pid) is int
        and ((phase == "starting" and pid == 0) or (phase == "running" and pid > 0))
        and isinstance(boot_id, str)
        and _normalize_clock_id(boot_id) == current_boot_id
        and type(heartbeat) in (int, float)
        and math.isfinite(heartbeat)
        and 0.0 <= now - float(heartbeat) <= HEARTBEAT_STALE_SECONDS
        and _valid_hex(identity, IDENTITY_HEX_LENGTH)
        and _valid_hex(token, TOKEN_HEX_LENGTH)
    ):
        return None
    return _HelperState(
        phase=phase,
        pid=pid,
        boot_id=boot_id,
        monotonic=float(heartbeat),
        identity=identity,
        token=token,
    )


def _write_state_unlocked(path: Path, state: _HelperState) -> None:
    payload = {
        "version": STATE_VERSION,
        "phase": state.phase,
        "pid": state.pid,
        "boot_id": state.boot_id,
        "monotonic": state.monotonic,
        "identity": state.identity,
        "token": state.token,
    }
    temporary = path.parent / f".helper-state.{secrets.token_hex(16)}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _remove_matching_starting_unlocked(path: Path, token: str) -> None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return
    if (
        isinstance(raw, dict)
        and raw.get("version") == STATE_VERSION
        and raw.get("phase") == "starting"
        and raw.get("token") == token
    ):
        path.unlink(missing_ok=True)


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
    expected_token: str,
    expected_pid: int | None = None,
) -> int | None:
    with _file_lock(path.parent, HELPER_STATE_LOCK):
        state = _read_fresh_state_unlocked(
            path,
            current_boot_id=current_boot_id,
            now=now,
        )
    if not (
        state is not None
        and state.phase == "running"
        and state.identity == expected_identity
        and state.token == expected_token
        and (expected_pid is None or state.pid == expected_pid)
    ):
        return None
    try:
        os.chmod(path.parent, 0o700)
        os.chmod(path, 0o600)
    except OSError:
        return None
    return state.pid


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
    python_executable = _validated_python_executable()
    normalized_boot_id = _normalize_clock_id(boot_id_loader())
    if normalized_boot_id is None:
        raise OSError("boot identity unavailable")

    with _file_lock(data_dir, HELPER_LAUNCH_LOCK):
        state_path = data_dir / HELPER_STATE
        observed: _HelperState | None = None
        for _ in range(VERIFY_ATTEMPTS):
            with _file_lock(data_dir, HELPER_STATE_LOCK):
                observed = _read_fresh_state_unlocked(
                    state_path,
                    current_boot_id=normalized_boot_id,
                    now=monotonic(),
                )
            if observed is None:
                break
            if observed.phase == "running" and observed.identity == identity:
                return
            sleep(0.05)
        if observed is not None:
            with _file_lock(data_dir, HELPER_STATE_LOCK):
                current = _read_fresh_state_unlocked(
                    state_path,
                    current_boot_id=normalized_boot_id,
                    now=monotonic(),
                )
                if current is not None and current.phase == "running":
                    if current.identity == identity:
                        return
                    raise OSError("prior helper still active")
                if current is not None and current.token != observed.token:
                    raise OSError("helper reservation changed")
                if current is not None:
                    _remove_matching_starting_unlocked(state_path, current.token)

        token = secrets.token_hex(TOKEN_HEX_LENGTH // 2)
        reservation = _HelperState(
            phase="starting",
            pid=0,
            boot_id=normalized_boot_id,
            monotonic=monotonic(),
            identity=identity,
            token=token,
        )
        with _file_lock(data_dir, HELPER_STATE_LOCK):
            current = _read_fresh_state_unlocked(
                state_path,
                current_boot_id=normalized_boot_id,
                now=monotonic(),
            )
            if current is not None:
                if current.phase == "running" and current.identity == identity:
                    return
                raise OSError("helper ownership unavailable")
            state_path.unlink(missing_ok=True)
            _write_state_unlocked(state_path, reservation)

        arguments = [
            str(executable),
            "--plugin-root",
            str(plugin_root),
            "--data-dir",
            str(data_dir),
            "--python-executable",
            str(python_executable),
            "--helper-identity",
            identity,
            "--helper-token",
            token,
        ]
        try:
            process = popen(
                arguments,
                cwd=str(plugin_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException:
            with _file_lock(data_dir, HELPER_STATE_LOCK):
                _remove_matching_starting_unlocked(state_path, token)
            raise

        for _ in range(VERIFY_ATTEMPTS):
            if (
                _read_current_state(
                    state_path,
                    current_boot_id=normalized_boot_id,
                    now=monotonic(),
                    expected_identity=identity,
                    expected_token=token,
                    expected_pid=process.pid,
                )
                is not None
            ):
                return
            sleep(0.05)
        with _file_lock(data_dir, HELPER_STATE_LOCK):
            _remove_matching_starting_unlocked(state_path, token)
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
