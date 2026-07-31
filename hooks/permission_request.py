from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Callable, Final, Mapping


DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(DEFAULT_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_PLUGIN_ROOT))

from codex_speak.helper import ensure_consumer
from codex_speak.queue import enqueue
from codex_speak.render import SpeechPayload
from codex_speak.settings import load_mode


APPROVAL_SPEECH: Final[str] = "Codex 有操作需要审批。"
ModeLoader = Callable[[Path], str]
ConsumerStarter = Callable[[Path, Path], object]


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


def handle_event(
    payload: Mapping[str, object],
    *,
    plugin_root: Path,
    data_dir: Path,
    platform_name: str,
    mode_loader: ModeLoader = load_mode,
    start_consumer: ConsumerStarter = ensure_consumer,
) -> bool:
    if platform_name != "darwin":
        return False
    mode = mode_loader(data_dir)
    if mode == "silent":
        return False
    queue_session, queue_turn = permission_queue_identity(payload)
    queued = enqueue(
        data_dir,
        SpeechPayload(mode, "action_required", (APPROVAL_SPEECH,)),
        session_id=queue_session,
        turn_id=queue_turn,
    )
    if not queued:
        return False
    start_consumer(plugin_root, data_dir)
    return True
