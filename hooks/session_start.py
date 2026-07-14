from __future__ import annotations

import json
import sys


PROTOCOL_CONTEXT = """
Codex Voice Notifier is active. For every final response, append exactly one single-line HTML comment as the final non-whitespace content:
<!-- codex-voice-notifier:v1 {"status":"STATUS","speech_text":"TEXT"} -->

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


def main() -> int:
    json.dump(build_output(), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
