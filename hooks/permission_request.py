from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Callable, Final, Mapping


DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(DEFAULT_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_PLUGIN_ROOT))

from codex_speak.diagnostics import record
from codex_speak.helper import ensure_consumer
from codex_speak.queue import discard_event, enqueue, make_event_id, try_worker_lock
from codex_speak.render import SpeechPayload
from codex_speak.settings import load_mode


APPROVAL_SPEECH: Final[str] = "Codex 有操作需要审批。"
ModeLoader = Callable[[Path], str]
ConsumerStarter = Callable[[Path, Path], object]
INVALID_EVENT_ID = make_event_id(
    "invalid-session-id",
    "invalid-permission-request",
)


def permission_queue_identity(
    payload: Mapping[str, object],
) -> tuple[str, str]:
    canonical = json.dumps(
        [
            payload["session_id"],
            payload["turn_id"],
            payload["tool_name"],
            payload["tool_input"],
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return (f"permission-session:{digest}", "permission-request")


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _safe_permission_identity(
    payload: Mapping[str, object],
) -> tuple[str, str] | None:
    if not all(
        _nonempty_string(payload.get(field))
        for field in ("session_id", "turn_id", "tool_name")
    ) or "tool_input" not in payload:
        return None
    try:
        return permission_queue_identity(payload)
    except (KeyError, TypeError, ValueError):
        return None


def handle_event(
    payload: Mapping[str, object],
    *,
    plugin_root: Path,
    data_dir: Path,
    platform_name: str,
    mode_loader: ModeLoader = load_mode,
    start_consumer: ConsumerStarter = ensure_consumer,
) -> bool:
    identity = _safe_permission_identity(payload)
    event_id = (
        make_event_id(identity[0], identity[1])
        if identity is not None
        else INVALID_EVENT_ID
    )
    if platform_name != "darwin":
        record(
            data_dir,
            event_id=event_id,
            status="action_required" if identity is not None else "unknown",
            result="discarded",
            mode="unknown",
            error_code="unsupported_platform",
        )
        return False
    if identity is None:
        record(
            data_dir,
            event_id=INVALID_EVENT_ID,
            status="unknown",
            result="discarded",
            mode="unknown",
            error_code="invalid_hook_input",
        )
        return False
    try:
        mode = mode_loader(data_dir)
    except (OSError, TypeError, ValueError):
        record(
            data_dir,
            event_id=event_id,
            status="action_required",
            result="failed",
            mode="unknown",
            error_code="invalid_settings",
        )
        return False
    if mode == "silent":
        return False
    if mode not in {"summary", "full"}:
        record(
            data_dir,
            event_id=event_id,
            status="action_required",
            result="failed",
            mode="unknown",
            error_code="invalid_settings",
        )
        return False

    try:
        queued = enqueue(
            data_dir,
            SpeechPayload(mode, "action_required", (APPROVAL_SPEECH,)),
            session_id=identity[0],
            turn_id=identity[1],
        )
    except (OSError, TypeError, ValueError):
        try:
            discard_event(data_dir, event_id)
        except (OSError, TypeError, ValueError):
            pass
        record(
            data_dir,
            event_id=event_id,
            status="action_required",
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
            discard_event(data_dir, event_id)
        except (OSError, TypeError, ValueError):
            pass
        record(
            data_dir,
            event_id=event_id,
            status="action_required",
            result="failed",
            mode=mode,
            segment_count=1,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
