from __future__ import annotations

import json
import math
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import time
from typing import Final, Mapping, Sequence

from .render import MAX_TASK_TITLE_CHARS, normalize_full_text


DEFAULT_COMMAND: Final[tuple[str, ...]] = ("codex", "app-server", "--stdio")
LOOKUP_TIMEOUT_SECONDS: Final[float] = 1.5
MAX_OUTPUT_BYTES: Final[int] = 65_536
THREAD_READ_REQUEST_ID: Final[int] = 2


def _request_bytes(session_id: str) -> bytes:
    messages = (
        {
            "method": "initialize",
            "id": 1,
            "params": {
                "clientInfo": {
                    "name": "codex_speak",
                    "title": "Codex Speak",
                    "version": "0.2.5",
                },
                "capabilities": {
                    "optOutNotificationMethods": ["remoteControl/status/changed"]
                },
            },
        },
        {"method": "initialized", "params": {}},
        {
            "method": "thread/read",
            "id": THREAD_READ_REQUEST_ID,
            "params": {"threadId": session_id, "includeTurns": False},
        },
    )
    return b"".join(
        json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        for message in messages
    )


def _title_from_message(message: object, session_id: str) -> tuple[bool, str | None]:
    if (
        not isinstance(message, Mapping)
        or type(message.get("id")) is not int
        or message.get("id") != THREAD_READ_REQUEST_ID
    ):
        return False, None
    result = message.get("result")
    if not isinstance(result, Mapping):
        return True, None
    thread = result.get("thread")
    if not isinstance(thread, Mapping) or thread.get("id") != session_id:
        return True, None
    name = thread.get("name")
    preview = thread.get("preview")
    raw_title = (
        name.strip()
        if isinstance(name, str) and name.strip()
        else preview.strip()
        if isinstance(preview, str) and preview.strip()
        else ""
    )
    title = normalize_full_text(raw_title)[:MAX_TASK_TITLE_CHARS].strip()
    return True, title or None


def _terminate(process: subprocess.Popen[bytes], *, deadline: float) -> None:
    if process.poll() is not None:
        process.wait()
        return

    try:
        process.terminate()
    except ProcessLookupError:
        process.wait()
        return
    except OSError:
        pass

    remaining = max(0.0, deadline - time.monotonic())
    try:
        process.wait(timeout=min(0.2, remaining))
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def _resolved_command(command: Sequence[str] | None) -> tuple[str, ...] | None:
    if isinstance(command, (str, bytes)):
        return None
    try:
        selected = tuple(command) if command is not None else DEFAULT_COMMAND
        if (
            not selected
            or not all(isinstance(part, str) for part in selected)
            or not selected[0]
            or any("\0" in part for part in selected)
        ):
            return None
        executable = (
            shutil.which(selected[0]) if selected[0] == "codex" else selected[0]
        )
    except Exception:
        return None
    if not executable:
        return None
    return (executable, *selected[1:])


def resolve_thread_title(
    session_id: str,
    cwd: Path,
    *,
    command: Sequence[str] | None = None,
    timeout_seconds: float = LOOKUP_TIMEOUT_SECONDS,
) -> str | None:
    if (
        not isinstance(session_id, str)
        or not session_id.strip()
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
    ):
        return None
    try:
        timeout = float(timeout_seconds)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(timeout) or timeout <= 0:
        return None

    deadline = time.monotonic() + timeout
    selected = _resolved_command(command)
    if selected is None or time.monotonic() >= deadline:
        return None

    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    try:
        process = subprocess.Popen(
            selected,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=False,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(_request_bytes(session_id))
        process.stdin.flush()
        process.stdin.close()

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        buffered = b""
        consumed = 0

        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            ready = selector.select(remaining)
            if not ready:
                break
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > MAX_OUTPUT_BYTES:
                return None
            buffered += chunk
            while b"\n" in buffered:
                line, buffered = buffered.split(b"\n", 1)
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError, RecursionError):
                    continue
                matched, title = _title_from_message(message, session_id)
                if matched:
                    return title
        return None
    except Exception:
        return None
    finally:
        if selector is not None:
            try:
                selector.close()
            except OSError:
                pass
        if process is not None:
            try:
                _terminate(process, deadline=deadline)
            except (OSError, subprocess.SubprocessError):
                pass
            finally:
                for pipe in (process.stdin, process.stdout):
                    if pipe is not None and not pipe.closed:
                        try:
                            pipe.close()
                        except OSError:
                            pass
