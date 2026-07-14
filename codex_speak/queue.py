from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Final, Iterator, Sequence

from .diagnostics import record
from .protocol import ALL_STATUSES
from .render import MAX_SEGMENT_CHARS, SpeechPayload


SETTLE_SECONDS: Final[float] = 1.0
EXPIRY_SECONDS: Final[float] = 300.0
DEDUPE_SECONDS: Final[float] = 24 * 60 * 60
DEDUPE_LIMIT: Final[int] = 512
FORMAT_VERSION: Final[int] = 3
MAX_SEGMENTS: Final[int] = 10_000
_HEX_DIGITS: Final[frozenset[str]] = frozenset("0123456789abcdef")
_BOOT_SESSION_PATH: Final[Path] = Path("/private/var/run/bootSessionMA.txt")
_CLOCK_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)


class _ExactArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class QueueEvent:
    format_version: int
    clock_id: str
    event_id: str
    session_key: str
    mode: str
    status: str
    segments: tuple[str, ...]
    created_at: float
    not_before: float

    @property
    def speech_text(self) -> str:
        """Compatibility view for callers that still consume one segment at a time."""
        return "".join(self.segments)


@dataclass(frozen=True, slots=True)
class QueuePoll:
    event: QueueEvent | None
    wait_seconds: float | None


def _normalize_clock_id(value: object) -> str | None:
    if not isinstance(value, str) or _CLOCK_ID_PATTERN.fullmatch(value) is None:
        return None
    return value.lower()


@lru_cache(maxsize=1)
def _default_clock_id() -> str | None:
    try:
        file_value = _BOOT_SESSION_PATH.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        file_value = ""
    normalized = _normalize_clock_id(file_value)
    if normalized is not None:
        return normalized

    try:
        completed = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _normalize_clock_id(completed.stdout.strip())


def _resolve_clock_id(clock_id: str | None) -> str | None:
    if clock_id is None:
        return _default_clock_id()
    normalized = _normalize_clock_id(clock_id)
    if normalized is None:
        raise ValueError("invalid clock identity")
    return normalized


def make_event_id(session_id: str, turn_id: str) -> str:
    encoded_pair = json.dumps(
        [session_id, turn_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded_pair).hexdigest()
    return digest[:24]


def _session_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def _make_private_if_exists(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except FileNotFoundError:
        pass


def _prepare(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(data_dir, 0o700)
    spool = data_dir / "spool"
    spool.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(spool, 0o700)
    for name in ("dedupe.json", "sequence.json", "queue.lock", "worker.lock"):
        _make_private_if_exists(data_dir / name)
    for path in spool.glob("*.json"):
        _make_private_if_exists(path)
    return spool


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def _locked(path: Path, *, blocking: bool) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    handle = os.fdopen(descriptor, "a+")
    acquired = False
    try:
        os.fchmod(handle.fileno(), 0o600)
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), operation)
            acquired = True
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _load_json(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return fallback


def _next_sequence(data_dir: Path) -> int:
    path = data_dir / "sequence.json"
    previous = _load_json(path, 0)
    if not isinstance(previous, int):
        previous = 0
    sequence = max(previous + 1, time.time_ns())
    _atomic_write_json(path, sequence)
    return sequence


def _is_event_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 24
        and all(character in _HEX_DIGITS for character in value)
    )


def _dedupe_envelope(clock_id: str, entries: dict[str, float]) -> dict[str, object]:
    return {
        "format_version": FORMAT_VERSION,
        "clock_id": clock_id,
        "entries": entries,
    }


def _same_clock_entries(raw: object, now: float) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    valid = {
        key: float(value)
        for key, value in raw.items()
        if _is_event_id(key)
        and type(value) in (int, float)
        and math.isfinite(value)
        and now - DEDUPE_SECONDS <= float(value) <= now
    }
    newest = sorted(valid.items(), key=lambda item: item[1], reverse=True)[:DEDUPE_LIMIT]
    return dict(newest)


def _rebased_entries(raw: object, now: float) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    candidates = [
        (key, float(value))
        for key, value in raw.items()
        if _is_event_id(key)
        and type(value) in (int, float)
        and math.isfinite(value)
    ]
    newest = sorted(
        candidates,
        key=lambda item: (item[1], item[0]),
        reverse=True,
    )[:DEDUPE_LIMIT]
    return {key: now for key, _ in newest}


def _load_dedupe(
    data_dir: Path,
    now: float,
    clock_id: str,
) -> tuple[dict[str, float], bool]:
    path = data_dir / "dedupe.json"
    existed = path.exists()
    raw = _load_json(path, {})
    is_current = (
        isinstance(raw, dict)
        and type(raw.get("format_version")) is int
        and raw.get("format_version") == FORMAT_VERSION
        and _normalize_clock_id(raw.get("clock_id")) == raw.get("clock_id")
        and isinstance(raw.get("entries"), dict)
    )
    is_legacy_envelope = (
        isinstance(raw, dict)
        and type(raw.get("format_version")) is int
        and raw.get("format_version") in {1, 2}
        and _normalize_clock_id(raw.get("clock_id")) == raw.get("clock_id")
        and isinstance(raw.get("entries"), dict)
    )
    if (is_current or is_legacy_envelope) and raw["clock_id"] == clock_id:
        entries = _same_clock_entries(raw["entries"], now)
    elif is_current or is_legacy_envelope:
        entries = _rebased_entries(raw["entries"], now)
    else:
        entries = _rebased_entries(raw, now)
    expected = _dedupe_envelope(clock_id, entries)
    return entries, existed and raw != expected


def _read_event(path: Path) -> QueueEvent:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("event is not an object")
    if set(raw) != {
        "format_version",
        "clock_id",
        "event_id",
        "session_key",
        "mode",
        "status",
        "segments",
        "created_at",
        "not_before",
    }:
        raise ValueError("event has unexpected fields")
    format_version = raw.get("format_version")
    clock_id = raw.get("clock_id")
    event_id = raw.get("event_id")
    session_key = raw.get("session_key")
    mode = raw.get("mode")
    status = raw.get("status")
    segments = raw.get("segments")
    created_at = raw.get("created_at")
    not_before = raw.get("not_before")
    if not (
        type(format_version) is int
        and format_version == FORMAT_VERSION
        and _normalize_clock_id(clock_id) == clock_id
        and _is_event_id(event_id)
        and isinstance(session_key, str)
        and len(session_key) == 16
        and all(character in _HEX_DIGITS for character in session_key)
        and isinstance(mode, str)
        and mode in {"summary", "full"}
        and isinstance(status, str)
        and status in ALL_STATUSES
        and (status != "silent" or mode == "full")
        and isinstance(segments, list)
        and 1 <= len(segments) <= MAX_SEGMENTS
        and all(
            isinstance(segment, str)
            and 1 <= len(segment) <= MAX_SEGMENT_CHARS
            for segment in segments
        )
        and type(created_at) in (int, float)
        and math.isfinite(created_at)
        and type(not_before) in (int, float)
        and math.isfinite(not_before)
        and math.isclose(
            float(not_before) - float(created_at),
            SETTLE_SECONDS,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    ):
        raise ValueError("event has invalid fields")
    event = QueueEvent(
        format_version=FORMAT_VERSION,
        clock_id=clock_id,
        event_id=event_id,
        session_key=session_key,
        mode=mode,
        status=status,
        segments=tuple(segments),
        created_at=float(created_at),
        not_before=float(not_before),
    )
    return event


def _superseded_paths(events: list[tuple[Path, QueueEvent]]) -> set[Path]:
    ordered = sorted(events, key=lambda item: item[0].name)
    superseded: set[Path] = set()
    for index, (older_path, older) in enumerate(ordered):
        for _, newer in ordered[index + 1 :]:
            if (
                newer.session_key == older.session_key
                and newer.mode == "summary"
                and older.mode == "summary"
                and older.created_at < newer.not_before
                and newer.created_at < older.not_before
            ):
                superseded.add(older_path)
                break
    return superseded


def _discard_corrupt(data_dir: Path, path: Path) -> None:
    corrupt_id = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:24]
    path.unlink(missing_ok=True)
    record(
        data_dir,
        event_id=corrupt_id,
        status="unknown",
        result="discarded",
        error_code="queue_corrupt",
    )


def _discard_expired(data_dir: Path, path: Path, event: QueueEvent) -> None:
    path.unlink(missing_ok=True)
    record(
        data_dir,
        event_id=event.event_id,
        status=event.status,
        result="discarded",
        error_code="expired",
    )


def enqueue(
    data_dir: Path,
    payload: SpeechPayload,
    *,
    session_id: str,
    turn_id: str,
    now: float | None = None,
    clock_id: str | None = None,
) -> bool:
    current_clock_id = _resolve_clock_id(clock_id)
    if current_clock_id is None:
        raise OSError("clock identity unavailable")
    spool = _prepare(data_dir)
    event_id = make_event_id(session_id, turn_id)
    session_key = _session_key(session_id)
    if not (
        payload.mode in {"summary", "full"}
        and payload.status in ALL_STATUSES
        and (payload.status != "silent" or payload.mode == "full")
        and 1 <= len(payload.segments) <= MAX_SEGMENTS
        and all(
            isinstance(segment, str)
            and 1 <= len(segment) <= MAX_SEGMENT_CHARS
            for segment in payload.segments
        )
    ):
        raise ValueError("invalid speech payload")

    with _locked(data_dir / "queue.lock", blocking=True) as acquired:
        if not acquired:
            return False
        timestamp = time.monotonic() if now is None else float(now)
        dedupe, dedupe_changed = _load_dedupe(
            data_dir,
            timestamp,
            current_clock_id,
        )
        if dedupe_changed:
            _atomic_write_json(
                data_dir / "dedupe.json",
                _dedupe_envelope(current_clock_id, dedupe),
            )
        spool_events: list[tuple[Path, QueueEvent]] = []
        for path in sorted(spool.glob("*.json")):
            try:
                existing = _read_event(path)
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                _discard_corrupt(data_dir, path)
                continue
            if existing.clock_id != current_clock_id:
                _discard_corrupt(data_dir, path)
                continue
            if existing.created_at > timestamp + SETTLE_SECONDS:
                _discard_corrupt(data_dir, path)
                continue
            if timestamp - existing.created_at > EXPIRY_SECONDS:
                _discard_expired(data_dir, path, existing)
                continue
            spool_events.append((path, existing))

        if event_id in dedupe:
            return False

        duplicates = [
            event for _, event in spool_events if event.event_id == event_id
        ]
        if duplicates:
            newest_duplicate = max(duplicates, key=lambda event: event.created_at)
            dedupe[event_id] = newest_duplicate.created_at
            newest = sorted(
                dedupe.items(), key=lambda item: item[1], reverse=True
            )[:DEDUPE_LIMIT]
            _atomic_write_json(
                data_dir / "dedupe.json",
                _dedupe_envelope(current_clock_id, dict(newest)),
            )
            for path in _superseded_paths(spool_events):
                path.unlink(missing_ok=True)
            return False

        superseded = [
            path
            for path, existing in spool_events
            if payload.mode == "summary"
            and existing.mode == "summary"
            and existing.session_key == session_key
            and existing.not_before > timestamp
        ]

        sequence = _next_sequence(data_dir)
        event = QueueEvent(
            format_version=FORMAT_VERSION,
            clock_id=current_clock_id,
            event_id=event_id,
            session_key=session_key,
            mode=payload.mode,
            status=payload.status,
            segments=payload.segments,
            created_at=timestamp,
            not_before=timestamp + SETTLE_SECONDS,
        )
        event_path = spool / f"{sequence:020d}-{event_id}.json"
        _atomic_write_json(event_path, asdict(event))

        dedupe[event_id] = timestamp
        newest = sorted(dedupe.items(), key=lambda item: item[1], reverse=True)[:DEDUPE_LIMIT]
        _atomic_write_json(
            data_dir / "dedupe.json",
            _dedupe_envelope(current_clock_id, dict(newest)),
        )
        for path in superseded:
            path.unlink(missing_ok=True)
        return True


def poll_next(
    data_dir: Path,
    *,
    now: float | None = None,
    clock_id: str | None = None,
) -> QueuePoll:
    current_clock_id = _resolve_clock_id(clock_id)
    spool = _prepare(data_dir)
    with _locked(data_dir / "queue.lock", blocking=True) as acquired:
        if not acquired:
            return QueuePoll(event=None, wait_seconds=0.05)
        if current_clock_id is None:
            for path in sorted(spool.glob("*.json")):
                _discard_corrupt(data_dir, path)
            return QueuePoll(event=None, wait_seconds=None)
        timestamp = time.monotonic() if now is None else float(now)
        dedupe, dedupe_changed = _load_dedupe(
            data_dir,
            timestamp,
            current_clock_id,
        )
        if dedupe_changed:
            _atomic_write_json(
                data_dir / "dedupe.json",
                _dedupe_envelope(current_clock_id, dedupe),
            )
        events: list[tuple[Path, QueueEvent]] = []
        for path in sorted(spool.glob("*.json")):
            try:
                event = _read_event(path)
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                _discard_corrupt(data_dir, path)
                continue

            if event.clock_id != current_clock_id:
                _discard_corrupt(data_dir, path)
                continue

            if event.created_at > timestamp + SETTLE_SECONDS:
                _discard_corrupt(data_dir, path)
                continue

            if timestamp - event.created_at > EXPIRY_SECONDS:
                _discard_expired(data_dir, path, event)
                continue

            events.append((path, event))

        reconciled = dict(dedupe)
        for _, event in events:
            reconciled[event.event_id] = min(event.created_at, timestamp)
        newest = sorted(
            reconciled.items(), key=lambda item: item[1], reverse=True
        )[:DEDUPE_LIMIT]
        reconciled = dict(newest)
        if reconciled != dedupe:
            _atomic_write_json(
                data_dir / "dedupe.json",
                _dedupe_envelope(current_clock_id, reconciled),
            )

        superseded = _superseded_paths(events)
        for path in superseded:
            path.unlink(missing_ok=True)
        for path, event in events:
            if path in superseded:
                continue
            if event.not_before > timestamp:
                return QueuePoll(event=None, wait_seconds=event.not_before - timestamp)

            path.unlink(missing_ok=True)
            return QueuePoll(event=event, wait_seconds=0.0)
        return QueuePoll(event=None, wait_seconds=None)


def discard_event(data_dir: Path, event_id: str) -> None:
    """Remove any queued plaintext for one event while holding the queue lock."""
    if not _is_event_id(event_id):
        raise ValueError("invalid event identity")
    spool = _prepare(data_dir)
    with _locked(data_dir / "queue.lock", blocking=True) as acquired:
        if not acquired:
            raise OSError("queue lock unavailable")
        for path in spool.glob(f"*-{event_id}.json"):
            path.unlink(missing_ok=True)


def clear_pending(data_dir: Path) -> int:
    spool = _prepare(data_dir)
    with _locked(data_dir / "queue.lock", blocking=True) as acquired:
        if not acquired:
            raise OSError("queue lock unavailable")
        paths = list(spool.glob("*.json"))
        for path in paths:
            path.unlink(missing_ok=True)
        return len(paths)


@contextmanager
def try_worker_lock(data_dir: Path) -> Iterator[bool]:
    _prepare(data_dir)
    with _locked(data_dir / "worker.lock", blocking=False) as acquired:
        yield acquired


def main(argv: Sequence[str] | None = None) -> int:
    parser = _ExactArgumentParser(prog="python3 -m codex_speak.queue")
    parser.add_argument("--data-dir", type=Path, required=True)
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_ExactArgumentParser,
    )
    subparsers.add_parser("clear-pending")
    arguments = parser.parse_args(argv)
    if arguments.command == "clear-pending":
        print(clear_pending(arguments.data_dir))
        return 0
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
