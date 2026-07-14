from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import sys
import time
from typing import Callable, TextIO

from .queue import poll_next, try_worker_lock


def _write_line(output: TextIO, value: dict[str, object]) -> None:
    json.dump(value, output, ensure_ascii=False, separators=(",", ":"))
    output.write("\n")
    output.flush()


def run_bridge(
    data_dir: Path,
    *,
    output: TextIO | None = None,
    input: TextIO | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    clock_id: str | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> int:
    writer = output or sys.stdout
    reader = input or sys.stdin
    should_stop = stop_requested or (lambda: False)
    with try_worker_lock(data_dir) as acquired:
        if not acquired:
            _write_line(writer, {"type": "busy"})
            return 0
        _write_line(writer, {"type": "ready"})
        while not should_stop():
            result = poll_next(data_dir, now=clock(), clock_id=clock_id)
            if result.event is not None:
                event = result.event
                _write_line(
                    writer,
                    {
                        "type": "event",
                        "event_id": event.event_id,
                        "mode": event.mode,
                        "status": event.status,
                        "segments": list(event.segments),
                    },
                )
                acknowledgement = reader.readline(1025)
                if len(acknowledgement) > 1024 or not acknowledgement.endswith("\n"):
                    return 0
                try:
                    ack = json.loads(acknowledgement)
                except (json.JSONDecodeError, TypeError, ValueError):
                    return 0
                if not (
                    isinstance(ack, dict)
                    and set(ack) == {"type", "event_id"}
                    and ack.get("type") == "ack"
                    and ack.get("event_id") == event.event_id
                ):
                    return 0
                continue
            wait_seconds = result.wait_seconds
            sleep(0.1 if wait_seconds is None else max(0.01, min(wait_seconds, 1.0)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    watch = subparsers.add_parser("watch", allow_abbrev=False)
    watch.add_argument("--data-dir", required=True, type=Path)
    arguments = parser.parse_args(argv)
    stopping = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    try:
        return run_bridge(
            arguments.data_dir,
            stop_requested=lambda: stopping,
        )
    except BaseException:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
