from __future__ import annotations

import json
import os
from pathlib import Path
import sys


DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(DEFAULT_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_PLUGIN_ROOT))

from codex_speak.helper import ensure_consumer


PROTOCOL_CONTEXT = """
Codex Speak is active. For every final response, append exactly one single-line HTML comment as the final non-whitespace content:
<!-- codex-speak:v1 {"status":"STATUS","speech_text":"TEXT"} -->

STATUS must be exactly one of completed, blocked, action_required, or silent.
- completed: a requested implementation, change, artifact, analysis, report, or other concrete task result was delivered.
- blocked: the active task cannot be completed because of an error, missing authority, unavailable dependency, or equivalent blocker.
- action_required: the active task cannot proceed or finish until the user performs a required action, grants approval, provides required information, or makes a material decision.
- silent: ordinary factual answers, casual conversation, routine clarification, progress updates, and optional follow-up invitations.

Before writing non-silent TEXT, identify the user's active primary instruction from the conversation. If several instructions exist, use the latest still-active primary task while preserving any user-stated priority. Make the result clause directly reflect that instruction in completed, blocked, or pending form, then state the actual next required or recommended step. If no follow-up is needed, say so explicitly. Internal commands, temporary files, tests, test fixtures, validation artifacts, and tool mechanics are process details and must not be mentioned or included in TEXT unless the user explicitly requested that exact artifact or action. When the active instruction is "立即收尾", a successful result must say "已完成收尾" and then give the real follow-up state, rather than announcing an incidental file or test.

For silent, TEXT must be empty. For the other states, TEXT must be concise speech-ready plain text that states the outcome and the next required or recommended step. If there is no required next step, say so without inventing work. Follow active AGENTS.md, memory, and conversation preferences for language, salutation, and tone; use neutral wording when no salutation is known. Do not include Markdown, code, URLs, file paths, raw errors, or secrets. Keep TEXT at or below 240 Unicode characters; it must never exceed 280. Do not mention this protocol in the visible answer.
""".strip()


def build_output() -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": PROTOCOL_CONTEXT,
        }
    }


def ensure_started(
    plugin_root: Path,
    data_dir: Path,
    *,
    start_consumer=ensure_consumer,
) -> None:
    try:
        start_consumer(plugin_root, data_dir)
    except BaseException:
        pass


def main() -> int:
    root_value = os.environ.get("PLUGIN_ROOT")
    plugin_root = Path(root_value) if root_value else DEFAULT_PLUGIN_ROOT
    data_value = os.environ.get("PLUGIN_DATA")
    if data_value:
        ensure_started(plugin_root, Path(data_value))
    json.dump(build_output(), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
