# Task Title Speech Prefix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prefix every important Codex Speak announcement with the real Codex sidebar task title and status-appropriate, conversation-aware wording.

**Architecture:** Introduce a backward-compatible v3 marker carrying a speech-lead template with one `{{task_title}}` placeholder. Resolve the real task name through a bounded, read-only `thread/read` app-server request at Stop-hook time, sanitize it, substitute it during rendering, and fall back to a localized generic task name without blocking speech.

**Tech Stack:** Python 3.10+ standard library, Codex lifecycle hooks and app-server JSONL protocol, `unittest`, existing macOS Swift helper tests.

## Global Constraints

- Important statuses are exactly `completed`, `blocked`, and `action_required`; `silent` remains ordinary/non-important.
- Known conversation salutation and language are used; no user's name is hard-coded as a default.
- The real title source is Codex `thread/read`, keyed by the Stop-hook `session_id`.
- `thread.name` is preferred; non-empty `thread.preview` is the untitled-thread fallback.
- Title lookup has a 1.5-second deadline and consumes at most 65,536 output bytes.
- Sanitized task titles are at most 80 Unicode characters.
- v3 speech-lead templates are at most 120 Unicode characters and contain exactly one literal `{{task_title}}` placeholder for important statuses.
- v3 `silent` payloads require empty `speech_lead` and `speech_text`.
- v1 and v2 markers retain their existing parsing and speech behavior.
- Summary prefixes important summary text; Full prefixes only important responses, not ordinary `silent`-status visible bodies.
- Silent control mode performs no rendering, title lookup, queue write, or consumer startup.
- Failed title lookup uses `当前任务` for a Chinese lead and `current task` otherwise; it never suppresses speech or creates a diagnostic entry.
- Diagnostics never contain raw thread IDs, task titles, app-server output, assistant messages, or user input.
- Runtime dependencies remain Python standard library plus local Codex/macOS components; no network service or third-party Python package is added.
- This plan prepares source version `0.2.5` but does not publish, release, push, or reinstall it.

---

## File Structure

- Create `codex_speak/thread_title.py`: bounded app-server client and title sanitation.
- Create `tests/test_thread_title.py`: real child-process resolver tests and response parsing tests.
- Modify `codex_speak/protocol.py`: v3 marker grammar and parsed lead template.
- Modify `codex_speak/render.py`: title substitution, generic fallback, and lead/body composition.
- Modify `hooks/session_start.py`: v3 model-visible marker contract.
- Modify `hooks/stop.py`: best-effort title lookup before rendering.
- Modify `tests/test_protocol.py`: v3 validation and v1/v2 compatibility.
- Modify `tests/test_render.py`: Summary/Full composition and fallback behavior.
- Modify `tests/test_hooks.py`: SessionStart rules and Stop-hook integration.
- Modify `tests/test_privacy.py`: title and app-server canaries remain out of diagnostics/process arguments.
- Modify `.codex-plugin/plugin.json`: development source version `0.2.5`.
- Modify `tests/test_packaging.py`: source-version and README contract.
- Modify `README.md`: task-title behavior, privacy, upgrade, and troubleshooting.

---

### Task 1: Parse the backward-compatible v3 marker

**Files:**
- Modify: `codex_speak/protocol.py`
- Modify: `tests/test_protocol.py`

**Interfaces:**
- Consumes: existing `extract_response(message: str | None) -> ParsedResponse | None`.
- Produces: `TASK_TITLE_PLACEHOLDER: Final[str]`, `LEAD_HARD_LIMIT: Final[int]`, and `ParsedResponse.speech_lead_template: str` with an empty backward-compatible default.
- Produces: v3 marker support while leaving v1/v2 payloads unchanged.

- [ ] **Step 1: Add v3 test fixtures and failing parser tests**

Add this helper below `marker_v2` in `tests/test_protocol.py`:

```python
def marker_v3(status: str, lead: str, text: str) -> str:
    payload = json.dumps(
        {"status": status, "speech_lead": lead, "speech_text": text},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"[codex-speak-v3]: <codex-speak:v3#{payload}>"
```

Add these tests to `ProtocolTests`:

```python
def test_extracts_v3_lead_and_preserves_v1_v2(self) -> None:
    self.assertEqual(
        extract_response(
            "正文\n\n"
            + marker_v3(
                "completed",
                "豪哥，任务：{{task_title}}已完成。",
                "正文结果。",
            )
        ),
        ParsedResponse(
            "completed",
            "正文结果。",
            "正文",
            "豪哥，任务：{{task_title}}已完成。",
        ),
    )
    self.assertEqual(
        extract_response("正文\n\n" + marker_v2("completed", "完成。")),
        ParsedResponse("completed", "完成。", "正文"),
    )
    self.assertEqual(
        extract_response(marker("completed", "完成。")),
        ParsedResponse("completed", "完成。", ""),
    )

def test_v3_accepts_each_important_status_and_silent(self) -> None:
    leads = {
        "completed": "任务：{{task_title}}已完成。",
        "blocked": "任务：{{task_title}}遇到阻塞。",
        "action_required": "任务：{{task_title}}需要你处理。",
    }
    for status, lead in leads.items():
        with self.subTest(status=status):
            self.assertEqual(
                extract_response(marker_v3(status, lead, "正文。")),
                ParsedResponse(status, "正文。", "", lead),
            )
    self.assertEqual(
        extract_response(marker_v3("silent", "", "")),
        ParsedResponse("silent", "", "", ""),
    )

def test_v3_requires_exact_keys_and_one_title_placeholder(self) -> None:
    invalid_payloads = (
        {"status": "completed", "speech_text": "正文。"},
        {
            "status": "completed",
            "speech_lead": "任务已完成。",
            "speech_text": "正文。",
        },
        {
            "status": "completed",
            "speech_lead": "{{task_title}}{{task_title}}",
            "speech_text": "正文。",
        },
        {
            "status": "completed",
            "speech_lead": "任务：{{task_title}}已完成。",
            "speech_text": "",
        },
        {
            "status": "completed",
            "speech_lead": "任务：{{task_title}}已完成。",
            "speech_text": "正文。",
            "extra": True,
        },
        {
            "status": "silent",
            "speech_lead": "任务：{{task_title}}",
            "speech_text": "",
        },
        {"status": "silent", "speech_lead": "", "speech_text": "不要播"},
    )
    for payload in invalid_payloads:
        with self.subTest(payload=payload):
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            message = f"[codex-speak-v3]: <codex-speak:v3#{encoded}>"
            self.assertIsNone(extract_response(message))

def test_v3_rejects_mixed_duplicate_unsafe_and_overlong_leads(self) -> None:
    valid = marker_v3(
        "completed", "任务：{{task_title}}已完成。", "正文。"
    )
    self.assertIsNone(extract_response(valid + "\n" + valid))
    self.assertIsNone(extract_response(valid + "\n" + marker_v2("completed", "完成")))
    self.assertIsNone(
        extract_response(
            marker_v3(
                "completed",
                "任务：{{task_title}}<已完成。",
                "正文。",
            )
        )
    )
    overlong = "甲" * 120 + "{{task_title}}"
    self.assertIsNone(
        extract_response(marker_v3("completed", overlong, "正文。"))
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
  tests.test_protocol.ProtocolTests.test_extracts_v3_lead_and_preserves_v1_v2 \
  tests.test_protocol.ProtocolTests.test_v3_accepts_each_important_status_and_silent \
  tests.test_protocol.ProtocolTests.test_v3_requires_exact_keys_and_one_title_placeholder \
  tests.test_protocol.ProtocolTests.test_v3_rejects_mixed_duplicate_unsafe_and_overlong_leads -v
```

Expected: FAIL because `ParsedResponse` has no fourth field and v3 is not recognized.

- [ ] **Step 3: Implement the v3 grammar and data model**

Update the protocol constants and `ParsedResponse` in `codex_speak/protocol.py`:

```python
LEAD_HARD_LIMIT: Final[int] = 120
TASK_TITLE_PLACEHOLDER: Final[str] = "{{task_title}}"
_TASK_TITLE_SENTINEL: Final[str] = "\ue000CodexSpeakTaskTitle\ue001"

_V3_MARKER_RE = re.compile(
    r"(?:\A|\n)\[codex-speak-v3\]: <codex-speak:v3#(?P<payload>\{[^\r\n]*\})>\s*\Z"
)


@dataclass(frozen=True, slots=True)
class ParsedResponse:
    status: str
    summary_text: str
    visible_body: str
    speech_lead_template: str = ""
```

Change `_sanitize_speech_text` to accept an explicit limit while preserving its current default:

```python
def _sanitize_speech_text(value: str, *, hard_limit: int = HARD_LIMIT) -> str:
    text = "".join(
        "\n" if char in {"\r", "\n"} else " " if char.isspace() else ""
        if unicodedata.category(char) in {"Cc", "Cf"}
        else char
        for char in value
    )
    text = _MARKDOWN_LINE_PREFIX_RE.sub("", text)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _URL_RE.sub("链接", text)
    text = _ABSOLUTE_PATH_RE.sub("相关文件", text)
    text = _STRIKETHROUGH_RE.sub("", text)
    text = _MARKDOWN_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) <= hard_limit:
        return text

    candidate = text[:hard_limit]
    boundary = max(candidate.rfind(mark) for mark in _SENTENCE_ENDINGS)
    if boundary >= 0:
        return candidate[: boundary + 1].rstrip()
    return candidate.rstrip()
```

Because the existing Markdown sanitizer removes underscores, protect the
literal placeholder while sanitizing the lead. Add:

```python
def _sanitize_speech_lead(value: str) -> str | None:
    if (
        value.count(TASK_TITLE_PLACEHOLDER) != 1
        or _TASK_TITLE_SENTINEL in value
    ):
        return None
    protected = value.replace(
        TASK_TITLE_PLACEHOLDER, _TASK_TITLE_SENTINEL
    )
    sanitized = _sanitize_speech_text(
        protected,
        hard_limit=max(len(protected), LEAD_HARD_LIMIT + len(_TASK_TITLE_SENTINEL)),
    ).replace(_TASK_TITLE_SENTINEL, TASK_TITLE_PLACEHOLDER)
    if (
        len(sanitized) > LEAD_HARD_LIMIT
        or sanitized.count(TASK_TITLE_PLACEHOLDER) != 1
    ):
        return None
    return sanitized
```

Replace `_parse_exact_payload` with a version-aware parser:

```python
def _parse_exact_payload(
    payload_text: str, *, version: str
) -> tuple[str, str, str] | None:
    try:
        payload = json.loads(payload_text)
    except (json.JSONDecodeError, TypeError):
        return None

    expected_keys = (
        {"status", "speech_lead", "speech_text"}
        if version == "v3"
        else {"status", "speech_text"}
    )
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return None

    status = payload.get("status")
    raw_speech = payload.get("speech_text")
    raw_lead = payload.get("speech_lead", "")
    if (
        not isinstance(status, str)
        or status not in ALL_STATUSES
        or not isinstance(raw_speech, str)
        or not isinstance(raw_lead, str)
    ):
        return None

    speech_text = _sanitize_speech_text(raw_speech)
    if status == "silent":
        if raw_speech or raw_lead:
            return None
        return "silent", "", ""

    if not speech_text:
        return None
    if version == "v3":
        speech_lead = _sanitize_speech_lead(raw_lead)
        if speech_lead is None:
            return None
    else:
        speech_lead = ""
    return status, speech_text, speech_lead
```

Update `extract_response` to collect and parse all three versions:

```python
matches = [
    *(("v1", match) for match in _V1_MARKER_RE.finditer(message)),
    *(("v2", match) for match in _V2_MARKER_RE.finditer(message)),
    *(("v3", match) for match in _V3_MARKER_RE.finditer(message)),
]
if len(matches) != 1:
    return None
version, match = matches[0]
payload_text = match.group("payload")
if version in {"v2", "v3"} and any(
    character in payload_text for character in "<>"
):
    return None
parsed = _parse_exact_payload(payload_text, version=version)
if parsed is None:
    return None
prefix = message[: match.start()]
if any(sentinel in prefix for sentinel in _MARKER_SENTINELS):
    return None
status, summary, speech_lead = parsed
return ParsedResponse(status, summary, prefix.rstrip(), speech_lead)
```

- [ ] **Step 4: Run protocol tests and verify GREEN**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest tests.test_protocol -v
```

Expected: all protocol tests PASS, including unchanged v1/v2 cases.

- [ ] **Step 5: Commit the protocol unit**

```bash
git add codex_speak/protocol.py tests/test_protocol.py
git commit -m "feat: add task title speech protocol v3"
```

---

### Task 2: Compose task leads in Summary and Full modes

**Files:**
- Modify: `codex_speak/render.py`
- Modify: `tests/test_render.py`

**Interfaces:**
- Consumes: `ParsedResponse.speech_lead_template` and `TASK_TITLE_PLACEHOLDER` from Task 1.
- Produces: `MAX_TASK_TITLE_CHARS: Final[int] = 80`.
- Produces: `compose_speech_lead(template: str, task_title: str | None) -> str`.
- Extends: `render_speech(response, mode, *, task_title=None)`.

- [ ] **Step 1: Write failing composition and fallback tests**

Import `compose_speech_lead` in `tests/test_render.py`, then add:

```python
def test_summary_and_full_prefix_only_important_v3_responses(self) -> None:
    done = ParsedResponse(
        "completed",
        "摘要正文。",
        "完整正文。",
        "豪哥，任务：{{task_title}}已完成。",
    )
    ordinary = ParsedResponse("silent", "", "普通回答。", "")

    self.assertEqual(
        render_speech(done, "summary", task_title="真实标题"),
        SpeechPayload(
            "summary",
            "completed",
            ("豪哥，任务：真实标题已完成。摘要正文。",),
        ),
    )
    self.assertEqual(
        render_speech(done, "full", task_title="真实标题"),
        SpeechPayload(
            "full",
            "completed",
            ("豪哥，任务：真实标题已完成。完整正文。",),
        ),
    )
    self.assertEqual(
        render_speech(ordinary, "full", task_title="不应出现"),
        SpeechPayload("full", "silent", ("普通回答。",)),
    )

def test_task_lead_uses_language_appropriate_generic_fallback(self) -> None:
    self.assertEqual(
        compose_speech_lead(
            "豪哥，任务：{{task_title}}遇到阻塞。", None
        ),
        "豪哥，任务：当前任务遇到阻塞。",
    )
    self.assertEqual(
        compose_speech_lead(
            "Task {{task_title}} needs your attention. ", ""
        ),
        "Task current task needs your attention. ",
    )

def test_task_title_is_normalized_and_capped_before_substitution(self) -> None:
    unsafe = "**标题** https://example.com /Users/private/x " + "甲" * 100
    lead = compose_speech_lead("任务：{{task_title}}已完成。", unsafe)
    self.assertNotIn("https://", lead)
    self.assertNotIn("/Users/private", lead)
    title = lead.removeprefix("任务：").removesuffix("已完成。")
    self.assertLessEqual(len(title), 80)

def test_legacy_responses_keep_existing_rendered_text(self) -> None:
    legacy = ParsedResponse("completed", "旧摘要。", "旧全文。")
    self.assertEqual(
        render_speech(legacy, "summary", task_title="不应添加"),
        SpeechPayload("summary", "completed", ("旧摘要。",)),
    )
    self.assertEqual(
        render_speech(legacy, "full", task_title="不应添加"),
        SpeechPayload("full", "completed", ("旧全文。",)),
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
  tests.test_render.RenderTests.test_summary_and_full_prefix_only_important_v3_responses \
  tests.test_render.RenderTests.test_task_lead_uses_language_appropriate_generic_fallback \
  tests.test_render.RenderTests.test_task_title_is_normalized_and_capped_before_substitution \
  tests.test_render.RenderTests.test_legacy_responses_keep_existing_rendered_text -v
```

Expected: FAIL because `compose_speech_lead` and the `task_title` parameter do not exist.

- [ ] **Step 3: Implement lead substitution and composition**

Import the placeholder and add the constants in `codex_speak/render.py`:

```python
from .protocol import ParsedResponse, TASK_TITLE_PLACEHOLDER

MAX_TASK_TITLE_CHARS: Final[int] = 80
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
```

Add this function after `normalize_full_text` so title sanitation reuses the
existing full-text safety boundary:

```python
def compose_speech_lead(
    template: str, task_title: str | None
) -> str:
    normalized_title = normalize_full_text(task_title or "")[
        :MAX_TASK_TITLE_CHARS
    ].strip()
    if not normalized_title:
        normalized_title = (
            "当前任务" if _CJK_RE.search(template) else "current task"
        )
    return template.replace(TASK_TITLE_PLACEHOLDER, normalized_title)
```

Replace `render_speech` with:

```python
def render_speech(
    response: ParsedResponse,
    mode: SpeechMode,
    *,
    task_title: str | None = None,
) -> SpeechPayload | None:
    if mode == "summary":
        if response.status == "silent":
            return None
        text = response.summary_text
    elif mode == "full":
        text = normalize_full_text(response.visible_body)
    else:
        raise ValueError(f"unsupported speech mode: {mode}")

    if response.speech_lead_template:
        text = compose_speech_lead(
            response.speech_lead_template, task_title
        ) + text

    segments = segment_text(text)
    if not segments:
        return None
    return SpeechPayload(mode, response.status, segments)
```

- [ ] **Step 4: Run render and protocol tests and verify GREEN**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest tests.test_render tests.test_protocol -v
```

Expected: all tests PASS and segment concatenation remains lossless.

- [ ] **Step 5: Commit the rendering unit**

```bash
git add codex_speak/render.py tests/test_render.py
git commit -m "feat: compose task title speech leads"
```

---

### Task 3: Resolve the real Codex sidebar title with a bounded client

**Files:**
- Create: `codex_speak/thread_title.py`
- Create: `tests/test_thread_title.py`

**Interfaces:**
- Consumes: `normalize_full_text` and `MAX_TASK_TITLE_CHARS` from Task 2.
- Produces: `resolve_thread_title(session_id: str, cwd: Path, *, command: Sequence[str] | None = None, timeout_seconds: float = 1.5) -> str | None`.
- Produces: no diagnostics, no exceptions, and no raw app-server stderr.

- [ ] **Step 1: Write real-process resolver tests**

Create `tests/test_thread_title.py`:

```python
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from codex_speak.thread_title import resolve_thread_title


class ThreadTitleTests(unittest.TestCase):
    def _server(self, root: Path, body: str) -> tuple[str, ...]:
        path = root / "fake_app_server.py"
        path.write_text(body, encoding="utf-8")
        return (sys.executable, str(path))

    def test_reads_matching_name_after_unrelated_notification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self._server(
                root,
                """
import json, sys
messages = [json.loads(sys.stdin.readline()) for _ in range(3)]
thread_id = messages[2]["params"]["threadId"]
print(json.dumps({"id": 1, "result": {"codexHome": "/tmp"}}), flush=True)
print(json.dumps({"method": "remoteControl/status/changed", "params": {}}), flush=True)
print(json.dumps({"id": 2, "result": {"thread": {
    "id": thread_id,
    "name": "真实侧栏标题",
    "preview": "旧预览"
}}}, ensure_ascii=False), flush=True)
""".strip(),
            )
            self.assertEqual(
                resolve_thread_title(
                    "thread-1", root, command=command, timeout_seconds=1.0
                ),
                "真实侧栏标题",
            )

    def test_falls_back_to_preview_and_sanitizes_title(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self._server(
                root,
                """
import json, sys
messages = [json.loads(sys.stdin.readline()) for _ in range(3)]
thread_id = messages[2]["params"]["threadId"]
print(json.dumps({"id": 2, "result": {"thread": {
    "id": thread_id,
    "name": None,
    "preview": "**标题** https://example.com /Users/private/file " + "甲" * 100
}}}, ensure_ascii=False), flush=True)
""".strip(),
            )
            title = resolve_thread_title(
                "thread-2", root, command=command, timeout_seconds=1.0
            )
            self.assertIsNotNone(title)
            assert title is not None
            self.assertNotIn("https://", title)
            self.assertNotIn("/Users/private", title)
            self.assertLessEqual(len(title), 80)

    def test_rejects_mismatched_thread_malformed_and_oversized_output(self) -> None:
        scripts = (
            'print("{\\"id\\":2,\\"result\\":{\\"thread\\":{\\"id\\":\\"other\\",\\"name\\":\\"wrong\\"}}}", flush=True)',
            'print("not-json", flush=True)',
            'print("x" * 70000, flush=True)',
        )
        for script in scripts:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                command = self._server(
                    root,
                    "import sys\n[sys.stdin.readline() for _ in range(3)]\n" + script,
                )
                self.assertIsNone(
                    resolve_thread_title(
                        "thread-3", root, command=command, timeout_seconds=1.0
                    )
                )

    def test_timeout_reaps_child_and_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pid_path = root / "pid"
            command = self._server(
                root,
                f"""
import os, pathlib, sys, time
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
[sys.stdin.readline() for _ in range(3)]
time.sleep(5)
""".strip(),
            )
            started = time.monotonic()
            self.assertIsNone(
                resolve_thread_title(
                    "thread-4", root, command=command, timeout_seconds=0.2
                )
            )
            self.assertLess(time.monotonic() - started, 1.0)
            pid = int(pid_path.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_missing_codex_command_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(
                resolve_thread_title(
                    "thread-5",
                    Path(temporary),
                    command=("/definitely/missing/codex",),
                    timeout_seconds=0.1,
                )
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test module and verify RED**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest tests.test_thread_title -v
```

Expected: ERROR because `codex_speak.thread_title` does not exist.

- [ ] **Step 3: Implement the bounded app-server reader**

Create `codex_speak/thread_title.py`:

```python
from __future__ import annotations

import json
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
                    "optOutNotificationMethods": [
                        "remoteControl/status/changed"
                    ]
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


def _title_from_message(
    message: object, session_id: str
) -> tuple[bool, str | None]:
    if not isinstance(message, Mapping) or message.get("id") != THREAD_READ_REQUEST_ID:
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


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        process.wait()
        return
    process.terminate()
    try:
        process.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=0.2)


def _resolved_command(command: Sequence[str] | None) -> tuple[str, ...] | None:
    selected = tuple(command) if command is not None else DEFAULT_COMMAND
    if not selected:
        return None
    executable = (
        shutil.which(selected[0])
        if selected[0] == "codex"
        else selected[0]
    )
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
    selected = _resolved_command(command)
    if not session_id.strip() or selected is None or timeout_seconds <= 0:
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
        deadline = time.monotonic() + timeout_seconds
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
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                matched, title = _title_from_message(message, session_id)
                if matched:
                    return title
        return None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            try:
                _terminate(process)
            except (OSError, subprocess.SubprocessError):
                pass
```

- [ ] **Step 4: Run title, render, and protocol tests and verify GREEN**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
  tests.test_thread_title tests.test_render tests.test_protocol -v
```

Expected: all tests PASS; timeout test completes in under one second with no live child.

- [ ] **Step 5: Commit the resolver unit**

```bash
git add codex_speak/thread_title.py tests/test_thread_title.py
git commit -m "feat: resolve codex task titles locally"
```

---

### Task 4: Wire title lookup into the Stop hook without weakening privacy

**Files:**
- Modify: `hooks/stop.py`
- Modify: `tests/test_hooks.py`
- Modify: `tests/test_privacy.py`

**Interfaces:**
- Consumes: `resolve_thread_title(session_id, cwd)` from Task 3.
- Consumes: `render_speech(..., task_title=...)` from Task 2.
- Produces: injectable `TitleResolver = Callable[[str, Path], str | None]` in `handle_event`.

- [ ] **Step 1: Add a v3 hook-message helper and failing integration tests**

Add below `assistant_message` in `tests/test_hooks.py`:

```python
def assistant_message_v3(
    status: str, speech_lead: str, speech_text: str, *, body: str = "Visible final answer"
) -> str:
    payload = json.dumps(
        {
            "status": status,
            "speech_lead": speech_lead,
            "speech_text": speech_text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{body}\n\n[codex-speak-v3]: <codex-speak:v3#{payload}>"
```

Add these tests:

```python
def test_v3_stop_resolves_real_title_for_summary_and_full(self) -> None:
    cases = (
        ("summary", "摘要正文。"),
        ("full", "完整正文。"),
    )
    for mode, expected_body in cases:
        with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"
            started = []
            title_calls = []
            payload = {
                "session_id": "real-session",
                "turn_id": f"{mode}-turn",
                "cwd": str(root),
                "last_assistant_message": assistant_message_v3(
                    "completed",
                    "豪哥，任务：{{task_title}}已完成。",
                    "摘要正文。",
                    body="完整正文。",
                ),
            }
            self.assertTrue(
                handle_event(
                    payload,
                    plugin_root=root,
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: mode,
                    title_resolver=lambda session, cwd: (
                        title_calls.append((session, cwd)) or "真实侧栏标题"
                    ),
                    start_consumer=lambda plugin_root, plugin_data: started.append(
                        (plugin_root, plugin_data)
                    ),
                )
            )
            event = poll_next(data_dir, now=time.monotonic() + 2.0).event
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(
                event.speech_text,
                f"豪哥，任务：真实侧栏标题已完成。{expected_body}",
            )
            self.assertEqual(title_calls, [("real-session", root)])
            self.assertEqual(started, [(root, data_dir)])

def test_title_lookup_failure_uses_fallback_without_diagnostic(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data_dir = root / "data"
        payload = {
            "session_id": "fallback-session",
            "turn_id": "fallback-turn",
            "last_assistant_message": assistant_message_v3(
                "blocked",
                "豪哥，任务：{{task_title}}遇到阻塞。",
                "需要处理。",
            ),
        }
        self.assertTrue(
            handle_event(
                payload,
                plugin_root=root,
                data_dir=data_dir,
                platform_name="darwin",
                mode_loader=lambda _: "summary",
                title_resolver=lambda *_: (_ for _ in ()).throw(OSError("private")),
                start_consumer=lambda *_: None,
            )
        )
        event = poll_next(data_dir, now=time.monotonic() + 2.0).event
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(
            event.speech_text,
            "豪哥，任务：当前任务遇到阻塞。需要处理。",
        )
        self.assertFalse((data_dir / "diagnostics.jsonl").exists())

def test_silent_control_and_legacy_markers_never_resolve_title(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        arguments = {
            "plugin_root": root,
            "data_dir": root / "data",
            "platform_name": "darwin",
            "start_consumer": lambda *_: None,
            "title_resolver": lambda *_: self.fail("title lookup must not run"),
        }
        v3_payload = {
            "session_id": "silent-session",
            "turn_id": "silent-turn",
            "last_assistant_message": assistant_message_v3(
                "completed",
                "任务：{{task_title}}已完成。",
                "正文。",
            ),
        }
        self.assertFalse(
            handle_event(v3_payload, mode_loader=lambda _: "silent", **arguments)
        )
        legacy_payload = {
            "session_id": "legacy-session",
            "turn_id": "legacy-turn",
            "last_assistant_message": assistant_message("completed", "旧正文。"),
        }
        self.assertTrue(
            handle_event(legacy_payload, mode_loader=lambda _: "summary", **arguments)
        )
```

Add a privacy test to `tests/test_privacy.py` using a v3 marker and a failing
consumer:

```python
def test_task_title_and_app_server_failure_never_enter_diagnostics(self) -> None:
    title_secret = "PRIVATE_TASK_TITLE_48291"
    server_secret = "PRIVATE_APP_SERVER_ERROR_59317"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data_dir = root / "data"
        payload_value = json.dumps(
            {
                "status": "completed",
                "speech_lead": "任务：{{task_title}}已完成。",
                "speech_text": "正文。",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        handle_event(
            {
                "session_id": "PRIVATE_RAW_SESSION_60429",
                "turn_id": "turn",
                "last_assistant_message": (
                    "正文\n[codex-speak-v3]: <codex-speak:v3#"
                    + payload_value
                    + ">"
                ),
            },
            plugin_root=root,
            data_dir=data_dir,
            platform_name="darwin",
            mode_loader=lambda _: "summary",
            title_resolver=lambda *_: title_secret,
            start_consumer=lambda *_: (_ for _ in ()).throw(
                OSError(server_secret)
            ),
        )
        diagnostics = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(title_secret, diagnostics)
        self.assertNotIn(server_secret, diagnostics)
        self.assertNotIn("PRIVATE_RAW_SESSION_60429", diagnostics)
```

- [ ] **Step 2: Run focused hook/privacy tests and verify RED**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
  tests.test_hooks.HookTests.test_v3_stop_resolves_real_title_for_summary_and_full \
  tests.test_hooks.HookTests.test_title_lookup_failure_uses_fallback_without_diagnostic \
  tests.test_hooks.HookTests.test_silent_control_and_legacy_markers_never_resolve_title \
  tests.test_privacy.PrivacyAndPackagingTests.test_task_title_and_app_server_failure_never_enter_diagnostics -v
```

Expected: FAIL because `handle_event` has no `title_resolver` argument and does not pass titles to rendering.

- [ ] **Step 3: Add best-effort title lookup to `handle_event`**

Update imports and aliases in `hooks/stop.py`:

```python
from codex_speak.thread_title import resolve_thread_title

ModeLoader = Callable[[Path], str]
ConsumerStarter = Callable[[Path, Path], object]
TitleResolver = Callable[[str, Path], str | None]
```

Extend the signature:

```python
def handle_event(
    payload: Mapping[str, object],
    *,
    plugin_root: Path,
    data_dir: Path,
    platform_name: str,
    mode_loader: ModeLoader,
    start_consumer: ConsumerStarter,
    title_resolver: TitleResolver = resolve_thread_title,
) -> bool:
```

After the Silent-mode return and before `render_speech`, insert:

```python
    task_title: str | None = None
    if parsed.speech_lead_template:
        cwd_value = payload.get("cwd")
        lookup_cwd = (
            Path(cwd_value)
            if isinstance(cwd_value, str)
            and bool(cwd_value.strip())
            and Path(cwd_value).is_absolute()
            else plugin_root
        )
        try:
            task_title = title_resolver(session_id, lookup_cwd)
        except BaseException:
            task_title = None
```

Change the render call to:

```python
        speech = render_speech(parsed, mode, task_title=task_title)
```

Do not add any diagnostic branch for resolver failure. Leave `main()` using the
default resolver.

- [ ] **Step 4: Run hook, privacy, protocol, render, and resolver tests**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
  tests.test_hooks tests.test_privacy tests.test_protocol \
  tests.test_render tests.test_thread_title -v
```

Expected: all tests PASS; legacy tests never spawn app-server because their
parsed lead is empty.

- [ ] **Step 5: Commit the Stop-hook integration**

```bash
git add hooks/stop.py tests/test_hooks.py tests/test_privacy.py
git commit -m "feat: announce real codex task titles"
```

---

### Task 5: Inject the v3 conversation-aware speech contract

**Files:**
- Modify: `hooks/session_start.py`
- Modify: `tests/test_hooks.py`

**Interfaces:**
- Consumes: exact v3 fields and limits from Task 1.
- Produces: SessionStart developer context that makes the model emit one v3 reference definition per final answer.

- [ ] **Step 1: Replace the SessionStart assertions with failing v3 contract checks**

In `test_session_start_injects_protocol_as_developer_context`, replace the v2
and salutation assertions with:

```python
self.assertIn("[codex-speak-v3]", context)
self.assertIn("codex-speak:v3#", context)
self.assertIn('"speech_lead":"LEAD"', context)
self.assertIn('"speech_text":"TEXT"', context)
self.assertIn("{{task_title}}", context)
self.assertNotIn("codex-speak:v2", context)
self.assertNotIn("codex-speak:v1", context)
self.assertNotIn("codex-voice-notifier:v1", context)

for requirement in (
    "exactly one literal {{task_title}} placeholder",
    "completed lead announces that the task is complete",
    "blocked lead announces that the task is blocked",
    "action_required lead announces that the task needs the user's action",
    "Never invent a form of address",
    "When active context establishes 豪哥 as the form of address",
    "任务：{{task_title}}",
    "at most 120 Unicode characters",
    "at or below 240 Unicode characters",
    "never exceed 280",
):
    with self.subTest(requirement=requirement):
        self.assertIn(requirement, context)
```

Retain the existing assertions for status definitions, active-primary-task
selection, unspoken process details, language/tone, forbidden content, and the
special `立即收尾` behavior.

- [ ] **Step 2: Run the SessionStart test and verify RED**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
  tests.test_hooks.HookTests.test_session_start_injects_protocol_as_developer_context -v
```

Expected: FAIL because SessionStart still injects the v2 two-field contract.

- [ ] **Step 3: Replace `PROTOCOL_CONTEXT` with the v3 contract**

Use this complete constant in `hooks/session_start.py`:

```python
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
```

- [ ] **Step 4: Run all hook and protocol tests and verify GREEN**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest tests.test_hooks tests.test_protocol -v
```

Expected: all tests PASS and the injected context contains v3 but not v1/v2.

- [ ] **Step 5: Commit the SessionStart contract**

```bash
git add hooks/session_start.py tests/test_hooks.py
git commit -m "feat: inject task title speech instructions"
```

---

### Task 6: Document and verify the 0.2.5 source candidate

**Files:**
- Modify: `.codex-plugin/plugin.json`
- Modify: `README.md`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_privacy.py`

**Interfaces:**
- Consumes: completed v3, resolver, renderer, and hook behavior from Tasks 1–5.
- Produces: source version `0.2.5`, public documentation, and a release-grade local verification report.
- Does not change: `.agents/plugins/marketplace.json` remains pinned to released `v0.2.4` until a separate release task.

- [ ] **Step 1: Add failing source-version and README contract assertions**

Change the manifest version expectation in `tests/test_packaging.py`:

```python
self.assertRegex(
    manifest["version"],
    r"^0\.2\.5(?:\+codex\.[a-z0-9-]+)?$",
)
```

Add to `test_readme_covers_install_trust_update_and_privacy` in
`tests/test_privacy.py`:

```python
for required in (
    "real Codex task title",
    "completed, blocked, and action-required",
    "current task",
    "thread/read",
    "1.5 seconds",
    "version 0.2.5",
    "v3 SessionStart",
    "v1 and v2",
    "task title is temporary speech content",
):
    with self.subTest(required=required):
        self.assertIn(required, readme)
```

- [ ] **Step 2: Run packaging/privacy contract tests and verify RED**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
  tests.test_packaging.PackagingTests.test_manifest_has_exact_identity_and_only_supported_fields \
  tests.test_privacy.PrivacyAndPackagingTests.test_readme_covers_install_trust_update_and_privacy -v
```

Expected: FAIL because the manifest is `0.2.4` and README does not describe title prefixes.

- [ ] **Step 3: Update manifest and README**

Set `.codex-plugin/plugin.json` to version `0.2.5` without changing any other
manifest field.

Update `README.md` with these exact points in the existing sections:

```markdown
Important completed, blocked, and action-required announcements begin with the
real Codex task title. The lead follows the conversation language and known
form of address; unknown users get a neutral lead. Codex Speak reads the title
locally through Codex `thread/read` and falls back to `current task` (or the
Chinese equivalent) when lookup does not finish within 1.5 seconds.
```

In Privacy and fallback, add:

```markdown
The task title is temporary speech content: it receives the same private queue
permissions and claim-before-playback lifecycle as the rest of the speech. Raw
thread IDs, titles, and app-server output never enter diagnostics. The local
title read does not add a network service.
```

In migration/update guidance, replace the v2-only wording with:

```markdown
Version 0.2.5 introduces the v3 SessionStart marker for task-title leads. The
parser retains v1 and v2 compatibility, but existing tasks keep their original
protocol behavior until a newly started task loads v3.
```

Add a troubleshooting bullet stating that a generic `current task` lead means
the bounded local title lookup failed or the thread was untitled; speech itself
continues normally.

- [ ] **Step 4: Run the complete verification matrix**

Run Python tests and bytecode-free compilation:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m compileall -q hooks codex_speak tests
python3 -m json.tool hooks/hooks.json >/dev/null
```

Expected: all Python tests PASS, compileall exits 0, hooks JSON is valid.

Run the unchanged helper suite as a regression gate:

```bash
swift test --package-path menu-bar -Xswiftc -warnings-as-errors
```

Expected: all Swift tests PASS; the existing opt-in real-process smoke test may remain skipped.

Run the plugin validator using the available validator environment:

```bash
export REPO_ROOT="$(pwd)"
export PLUGIN_CREATOR_ROOT="${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator"
python3 "$PLUGIN_CREATOR_ROOT/scripts/validate_plugin.py" "$REPO_ROOT"
```

If that interpreter lacks PyYAML, use the README's disposable validator venv
recipe. Expected: validator PASS with no errors.

Confirm no title/version work accidentally changed the embedded helper:

```bash
git diff --name-only 688027a
```

Expected: no menu-bar source or embedded app files appear. The manifest,
README, and their tests are still modified because the final commit is the next
step.

- [ ] **Step 5: Commit the source-candidate metadata and docs**

```bash
git add .codex-plugin/plugin.json README.md tests/test_packaging.py tests/test_privacy.py
git commit -m "docs: prepare codex speak 0.2.5"
```

- [ ] **Step 6: Record final verification evidence**

```bash
git status --short --branch
git log --oneline 688027a..HEAD
```

Expected: the branch is clean and ahead only by the implementation commits.
Do not push, tag, publish a release, change the public marketplace ref, or
reinstall without a separate explicit instruction.

---

## Acceptance Walkthrough After a Later Explicit Install

This is not part of this implementation plan's authorized mutations. After an
explicit install request, use a newly started trusted task and verify:

1. Rename two Codex tasks to different sidebar titles.
2. Complete an important response in each task and confirm each title is spoken.
3. Trigger `blocked` and `action_required` responses and confirm distinct lead wording.
4. In Summary, confirm ordinary answers stay silent.
5. In Full, confirm ordinary visible answers are read without a task lead while important responses include it.
6. Select Silent and confirm neither title lookup nor speech occurs.
7. Make title lookup unavailable and confirm the localized generic task fallback plays within the bounded delay.
8. Confirm `/hooks` shows the changed SessionStart and Stop definitions as trusted before acceptance.
