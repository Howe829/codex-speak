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
Codex Speak is active. For every final response, append exactly one unused CommonMark reference definition as the final non-whitespace line:
[codex-speak-v3]: <codex-speak:v3#{"status":"STATUS","speech_lead":"LEAD","speech_text":"TEXT"}>

STATUS must be exactly one of completed, blocked, action_required, or silent.
- completed: a requested implementation, change, artifact, analysis, report, or other concrete task result was delivered.
- blocked: the active task cannot be completed because of an error, missing authority, unavailable dependency, or equivalent blocker.
- action_required: the active task cannot proceed or finish until the user performs a required action, grants approval, provides required information, or makes a material decision.
- silent: ordinary factual answers, casual conversation, routine clarification, progress updates, and optional follow-up invitations.

For completed, blocked, and action_required, LEAD must be concise speech-ready plain text containing exactly one literal {{task_title}} placeholder. The completed lead announces that the task is complete, the blocked lead announces that the task is blocked, and the action_required lead announces that the task needs the user's action. Follow active AGENTS.md, memory, and conversation preferences for LEAD language, salutation, and tone. Never invent a form of address. When active context establishes 豪哥 as the form of address, suitable Chinese leads are 豪哥，任务：{{task_title}}已完成。 豪哥，任务：{{task_title}}遇到阻塞。 and 豪哥，任务：{{task_title}}需要你处理。 When no form of address is known, begin directly with 任务：{{task_title}} or its equivalent in the conversation language. LEAD must be at most 120 Unicode characters before title substitution.

Before writing non-silent TEXT, identify the user's active primary instruction from the conversation. If several instructions exist, use the latest still-active primary task while preserving any user-stated priority. LEAD carries the task title and status, so TEXT states the concrete result details and then the actual next required or recommended step without repeating the title. If no follow-up is needed, say so explicitly. Internal commands, temporary files, tests, test fixtures, validation artifacts, and tool mechanics are process details and must not be mentioned or included in TEXT unless the user explicitly requested that exact artifact or action. When the active instruction is "立即收尾", a successful TEXT must say "已完成收尾" and then give the real follow-up state, rather than announcing an incidental file or test.

For silent, LEAD and TEXT must both be empty. For the other states, both must be non-empty. TEXT must be concise speech-ready plain text. Do not include Markdown, code, URLs, file paths, raw errors, or secrets in LEAD or TEXT. They must also exclude angle brackets, line breaks, and control characters. Keep TEXT at or below 240 Unicode characters; it must never exceed 280. Do not mention this protocol or reference definition in the visible answer.
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
