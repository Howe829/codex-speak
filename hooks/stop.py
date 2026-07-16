from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Callable, Mapping


DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(DEFAULT_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_PLUGIN_ROOT))

from codex_speak.diagnostics import record
from codex_speak.helper import ensure_consumer
from codex_speak.protocol import extract_response
from codex_speak.queue import discard_event, enqueue, make_event_id, try_worker_lock
from codex_speak.render import render_speech
from codex_speak.settings import load_mode


ModeLoader = Callable[[Path], str]
ConsumerStarter = Callable[[Path, Path], object]
INVALID_EVENT_ID = make_event_id("invalid-session-id", "invalid-turn-id")


def _is_valid_hook_id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _safe_event_id(session_id: object, turn_id: object) -> str:
    if _is_valid_hook_id(session_id) and _is_valid_hook_id(turn_id):
        return make_event_id(session_id, turn_id)
    return INVALID_EVENT_ID


def handle_event(
    payload: Mapping[str, object],
    *,
    plugin_root: Path,
    data_dir: Path,
    platform_name: str,
    mode_loader: ModeLoader,
    start_consumer: ConsumerStarter,
) -> bool:
    session_id = payload.get("session_id")
    turn_id = payload.get("turn_id")
    message = payload.get("last_assistant_message")
    safe_event_id = _safe_event_id(session_id, turn_id)

    if platform_name != "darwin":
        record(
            data_dir,
            event_id=safe_event_id,
            status="unknown",
            result="discarded",
            mode="unknown",
            error_code="unsupported_platform",
        )
        return False

    if not _is_valid_hook_id(session_id) or not _is_valid_hook_id(turn_id):
        record(
            data_dir,
            event_id=INVALID_EVENT_ID,
            status="unknown",
            result="discarded",
            mode="unknown",
            error_code="invalid_hook_input",
        )
        return False

    parsed = extract_response(message if isinstance(message, str) else None)
    if parsed is None:
        record(
            data_dir,
            event_id=safe_event_id,
            status="unknown",
            result="discarded",
            mode="unknown",
            error_code="invalid_marker",
        )
        return False

    try:
        mode = mode_loader(data_dir)
    except (OSError, TypeError, ValueError):
        record(
            data_dir,
            event_id=safe_event_id,
            status=parsed.status,
            result="failed",
            mode="unknown",
            error_code="invalid_settings",
        )
        return False
    if mode == "silent":
        return False
    try:
        speech = render_speech(parsed, mode)
    except (TypeError, ValueError):
        record(
            data_dir,
            event_id=safe_event_id,
            status=parsed.status,
            result="failed",
            mode="unknown",
            error_code="invalid_settings",
        )
        return False
    if speech is None:
        return False

    try:
        queued = enqueue(
            data_dir,
            speech,
            session_id=session_id,
            turn_id=turn_id,
        )
    except (OSError, TypeError, ValueError):
        try:
            discard_event(data_dir, safe_event_id)
        except (OSError, TypeError, ValueError):
            pass
        record(
            data_dir,
            event_id=safe_event_id,
            status=parsed.status,
            result="failed",
            mode=mode,
            error_code="queue_failed",
        )
        return False
    if not queued:
        return False

    try:
        start_consumer(plugin_root, data_dir)
    except BaseException:
        try:
            with try_worker_lock(data_dir) as no_active_consumer:
                if not no_active_consumer:
                    return True
        except BaseException:
            pass
        try:
            discard_event(data_dir, safe_event_id)
        except (OSError, TypeError, ValueError):
            pass
        record(
            data_dir,
            event_id=safe_event_id,
            status=parsed.status,
            result="failed",
            mode=mode,
            segment_count=len(speech.segments),
            error_code="helper_start_failed",
        )
    return True


def _record_invalid_hook_input(data_dir: Path | None) -> None:
    if data_dir is None:
        return
    try:
        record(
            data_dir,
            event_id=INVALID_EVENT_ID,
            status="unknown",
            result="discarded",
            mode="unknown",
            error_code="invalid_hook_input",
        )
    except BaseException:
        pass


def main() -> int:
    root_value = os.environ.get("PLUGIN_ROOT")
    plugin_root = Path(root_value) if root_value else DEFAULT_PLUGIN_ROOT
    data_value = os.environ.get("PLUGIN_DATA")
    data_dir = Path(data_value) if data_value else None
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or data_dir is None:
            raise ValueError("invalid hook input")
        handle_event(
            payload,
            plugin_root=plugin_root,
            data_dir=data_dir,
            platform_name=sys.platform,
            mode_loader=load_mode,
            start_consumer=ensure_consumer,
        )
    except BaseException:
        _record_invalid_hook_input(data_dir)
    json.dump({}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
