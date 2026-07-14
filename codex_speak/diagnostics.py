from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Final, Sequence


MAX_BYTES: Final[int] = 256 * 1024
_HEX_DIGITS: Final[frozenset[str]] = frozenset("0123456789abcdef")
_STATUSES: Final[frozenset[str]] = frozenset(
    {"completed", "blocked", "action_required", "silent", "unknown"}
)
_RESULTS: Final[frozenset[str]] = frozenset(
    {"spoken", "failed", "discarded", "cancelled"}
)
_MODES: Final[frozenset[str]] = frozenset({"summary", "full", "unknown"})
_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "unsupported_platform",
        "say_unavailable",
        "invalid_hook_input",
        "invalid_marker",
        "queue_corrupt",
        "expired",
        "say_failed",
        "queue_failed",
        "worker_start_failed",
        "invalid_settings",
        "helper_start_failed",
        "invalid_event",
        "stale_event",
        "boot_mismatch",
        "speech_start_failed",
        "cancel_identity_mismatch",
        "queue_clear_failed",
    }
)


def _metadata_is_valid(
    event_id: object,
    status: object,
    result: object,
    mode: object,
    segment_count: object,
    duration_ms: object,
    error_code: object,
) -> bool:
    return (
        isinstance(event_id, str)
        and len(event_id) == 24
        and all(character in _HEX_DIGITS for character in event_id)
        and isinstance(status, str)
        and status in _STATUSES
        and isinstance(result, str)
        and result in _RESULTS
        and isinstance(mode, str)
        and mode in _MODES
        and type(segment_count) is int
        and 0 <= segment_count <= 10_000
        and type(duration_ms) is int
        and duration_ms >= 0
        and (
            error_code is None
            or isinstance(error_code, str)
            and error_code in _ERROR_CODES
        )
    )


def _prepare_directory(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(data_dir, 0o700)


def _rotate_if_needed(path: Path, incoming_bytes: int) -> None:
    backup = path.with_name(path.name + ".1")
    if backup.exists():
        os.chmod(backup, 0o600)
    if not path.exists():
        return
    os.chmod(path, 0o600)
    if path.stat().st_size + incoming_bytes <= MAX_BYTES:
        return
    backup.unlink(missing_ok=True)
    os.replace(path, backup)
    os.chmod(backup, 0o600)


def record(
    data_dir: Path,
    *,
    event_id: str,
    status: str,
    result: str,
    mode: str = "unknown",
    segment_count: int = 0,
    duration_ms: int = 0,
    error_code: str | None = None,
    now: datetime | None = None,
) -> None:
    if not isinstance(data_dir, Path):
        return
    if now is not None and not isinstance(now, datetime):
        return
    if not _metadata_is_valid(
        event_id,
        status,
        result,
        mode,
        segment_count,
        duration_ms,
        error_code,
    ):
        return
    descriptor: int | None = None
    try:
        timestamp = now or datetime.now(timezone.utc)
        entry = {
            "timestamp": timestamp.isoformat(),
            "event_id": event_id,
            "status": status,
            "result": result,
            "mode": mode,
            "segment_count": segment_count,
            "duration_ms": duration_ms,
            "error_code": error_code,
        }
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
        line_bytes = line.encode("utf-8")
        if len(line_bytes) > MAX_BYTES:
            return
        _prepare_directory(data_dir)
        path = data_dir / "diagnostics.jsonl"
        _rotate_if_needed(path, len(line_bytes))
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "a", encoding="utf-8")
        descriptor = None
        with handle:
            handle.write(line)
    except (OSError, TypeError, ValueError):
        return
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


class _CliError(Exception):
    pass


class _StrictArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CliError from None


def _parser() -> argparse.ArgumentParser:
    parser = _StrictArgumentParser(prog="python3 -m codex_speak.diagnostics")
    parser.add_argument("--data-dir", required=True)
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_StrictArgumentParser,
    )
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--event-id", required=True)
    record_parser.add_argument("--status", required=True)
    record_parser.add_argument("--result", required=True)
    record_parser.add_argument("--mode", required=True)
    record_parser.add_argument("--segment-count", required=True)
    record_parser.add_argument("--duration-ms", required=True)
    record_parser.add_argument("--error-code", required=True)
    return parser


def _cli_integer(value: str) -> int | None:
    try:
        return int(value, 10)
    except (TypeError, ValueError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except (_CliError, SystemExit):
        return 2
    segment_count = _cli_integer(arguments.segment_count)
    duration_ms = _cli_integer(arguments.duration_ms)
    error_code = None if arguments.error_code == "NONE" else arguments.error_code
    if not _metadata_is_valid(
        arguments.event_id,
        arguments.status,
        arguments.result,
        arguments.mode,
        segment_count,
        duration_ms,
        error_code,
    ):
        return 2
    record(
        Path(arguments.data_dir),
        event_id=arguments.event_id,
        status=arguments.status,
        result=arguments.result,
        mode=arguments.mode,
        segment_count=segment_count,
        duration_ms=duration_ms,
        error_code=error_code,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
