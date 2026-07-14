from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable

from .diagnostics import record
from .queue import poll_next, try_worker_lock


def run_worker(
    data_dir: Path,
    *,
    say_path: Path = Path("/usr/bin/say"),
    run_command: Callable[..., subprocess.CompletedProcess] | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    monotonic: Callable[[], float] | None = None,
    clock_id: str | None = None,
) -> int:
    runner = run_command or subprocess.run
    sleeper = sleep or time.sleep
    poll_clock = clock or time.monotonic
    timer = monotonic or time.monotonic

    with try_worker_lock(data_dir) as acquired:
        if not acquired:
            return 0

        while True:
            result = poll_next(data_dir, now=poll_clock(), clock_id=clock_id)
            event = result.event
            if event is None:
                if result.wait_seconds is None:
                    return 0
                sleeper(max(0.01, min(result.wait_seconds, 1.0)))
                continue

            if not say_path.is_file() or not os.access(say_path, os.X_OK):
                record(
                    data_dir,
                    event_id=event.event_id,
                    status=event.status,
                    result="discarded",
                    mode=event.mode,
                    error_code="say_unavailable",
                )
                continue

            started = timer()
            completed_segments = 0
            failed = False
            for segment in event.segments:
                try:
                    completed = runner(
                        [str(say_path)],
                        input=segment,
                        text=True,
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError:
                    failed = True
                    break
                if completed.returncode != 0:
                    failed = True
                    break
                completed_segments += 1

            duration_ms = max(0, int((timer() - started) * 1000))
            record(
                data_dir,
                event_id=event.event_id,
                status=event.status,
                result="failed" if failed else "spoken",
                mode=event.mode,
                segment_count=completed_segments,
                duration_ms=duration_ms,
                error_code="say_failed" if failed else None,
            )


def spawn_worker(plugin_root: Path, data_dir: Path) -> None:
    subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-m",
            "codex_speak.worker",
            "--data-dir",
            str(data_dir),
        ],
        cwd=str(plugin_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        return run_worker(arguments.data_dir)
    except BaseException:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
