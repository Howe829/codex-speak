# Permission Request Speech Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a privacy-preserving `PermissionRequest` hook that speaks one fixed local alert without changing the underlying approval decision.

**Architecture:** A focused `hooks/permission_request.py` handler validates the hook envelope, derives a hashed queue namespace, and submits an existing `SpeechPayload` to the current queue and consumer. The handler writes no standard output and always leaves approval routing to Codex. No queue schema, menu, voice, rate, Stop-hook, or response-marker changes are included.

**Tech Stack:** Python 3 standard library, `unittest`, existing Codex Speak queue/helper/diagnostics modules, Codex plugin `hooks.json`, macOS `/usr/bin/say` through the existing worker.

## Global Constraints

- Every `PermissionRequest` is eligible, including one that Auto-review may subsequently handle.
- Silent suppresses approval speech; Summary and Full speak exactly `Codex 有操作需要审批。`
- Never persist or speak command text, tool arguments, paths, or the approval description.
- Never return `allow`, `deny`, `updatedInput`, `updatedPermissions`, `interrupt`, or any other approval decision.
- The command must exit zero with empty standard output, including on malformed input and internal failure.
- Keep voice selection, speech rate, menu behavior, queue schema, Stop-hook behavior, and the v3 response protocol unchanged.
- Do not bump the plugin version, push, publish, release, or reinstall in this implementation plan.
- Preserve the unrelated untracked `assets/.DS_Store` file.

## File Map

- Create `hooks/permission_request.py`: validate permission events, derive private queue identities, enqueue the fixed alert, and fail open.
- Create `tests/test_permission_request.py`: behavior-first coverage for modes, identity, deduplication, failure handling, and command output.
- Modify `hooks/hooks.json`: register the wildcard `PermissionRequest` handler.
- Modify `tests/test_hooks.py`: lock the plugin hook registration contract.
- Modify `tests/test_privacy.py`: prove request canaries do not enter queue or diagnostics files.
- Modify `README.md`: document approval alerts, mode behavior, Auto-review caveat, and hook trust.

---

### Task 1: Core Permission Alert Handler

**Files:**
- Create: `hooks/permission_request.py`
- Create: `tests/test_permission_request.py`

**Interfaces:**
- Consumes: `codex_speak.queue.enqueue`, `codex_speak.queue.make_event_id`, `codex_speak.queue.poll_next`, `codex_speak.render.SpeechPayload`, `codex_speak.settings.load_mode`, and `codex_speak.helper.ensure_consumer`.
- Produces: `permission_queue_identity(payload: Mapping[str, object]) -> tuple[str, str]`, returning synthetic `(session_id, turn_id)` values; `handle_event(payload: Mapping[str, object], *, plugin_root: Path, data_dir: Path, platform_name: str, mode_loader: ModeLoader, start_consumer: ConsumerStarter) -> bool`.

- [ ] **Step 1: Write failing tests for Summary, Full, Silent, identity separation, and deduplication**

Add a complete documented hook fixture and behavior tests to `tests/test_permission_request.py`:

```python
from __future__ import annotations

import tempfile
import time
from pathlib import Path
import unittest

from codex_speak.queue import make_event_id, poll_next
from hooks.permission_request import (
    handle_event,
    permission_queue_identity,
)


def permission_payload(*, tool_input: object | None = None) -> dict[str, object]:
    return {
        "session_id": "session-123",
        "transcript_path": "/private/transcript.jsonl",
        "cwd": "/workspace",
        "hook_event_name": "PermissionRequest",
        "permission_mode": "default",
        "turn_id": "turn-456",
        "tool_name": "Bash",
        "tool_input": (
            {"command": "curl https://example.invalid", "description": "network"}
            if tool_input is None
            else tool_input
        ),
    }


class PermissionRequestTests(unittest.TestCase):
    def test_summary_and_full_enqueue_fixed_action_required_alert(self) -> None:
        for mode in ("summary", "full"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                data_dir = root / "data"
                started: list[tuple[Path, Path]] = []

                self.assertTrue(
                    handle_event(
                        permission_payload(),
                        plugin_root=root,
                        data_dir=data_dir,
                        platform_name="darwin",
                        mode_loader=lambda _: mode,
                        start_consumer=lambda plugin_root, plugin_data: started.append(
                            (plugin_root, plugin_data)
                        ),
                    )
                )
                event = poll_next(data_dir, now=time.monotonic() + 2.0).event

                self.assertIsNotNone(event)
                assert event is not None
                self.assertEqual(event.mode, mode)
                self.assertEqual(event.status, "action_required")
                self.assertEqual(event.segments, ("Codex 有操作需要审批。",))
                self.assertEqual(started, [(root, data_dir)])

    def test_silent_does_not_enqueue_or_start_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"

            self.assertFalse(
                handle_event(
                    permission_payload(),
                    plugin_root=root,
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: "silent",
                    start_consumer=lambda *_: self.fail("consumer must not start"),
                )
            )
            self.assertFalse((data_dir / "spool").exists())

    def test_permission_identity_is_private_distinct_and_deduplicated(self) -> None:
        payload = permission_payload()
        synthetic_session, synthetic_turn = permission_queue_identity(payload)
        permission_event_id = make_event_id(synthetic_session, synthetic_turn)
        stop_event_id = make_event_id("session-123", "turn-456")
        self.assertNotEqual(permission_event_id, stop_event_id)
        self.assertNotIn("session-123", synthetic_session + synthetic_turn)
        self.assertNotIn("curl", synthetic_session + synthetic_turn)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"
            starts: list[tuple[Path, Path]] = []
            arguments = {
                "plugin_root": root,
                "data_dir": data_dir,
                "platform_name": "darwin",
                "mode_loader": lambda _: "summary",
                "start_consumer": lambda a, b: starts.append((a, b)),
            }
            self.assertTrue(handle_event(payload, **arguments))
            self.assertFalse(handle_event(payload, **arguments))
            self.assertEqual(len(list((data_dir / "spool").glob("*.json"))), 1)
            self.assertEqual(starts, [(root, data_dir)])
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_permission_request -v
```

Expected: import failure because `hooks.permission_request` does not exist. This is the required failure caused by the missing production feature.

- [ ] **Step 3: Implement the smallest valid core handler**

Create `hooks/permission_request.py` with these exact public contracts and the minimum valid-path behavior:

```python
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
```

Do not add command-boundary exception handling in this task; Task 2 adds it only after its failure tests exist.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_permission_request -v
```

Expected: all three core tests pass with no warnings or unexpected output.

- [ ] **Step 5: Commit the core behavior**

```bash
git add hooks/permission_request.py tests/test_permission_request.py
git commit -m "feat: add permission request speech handler"
```

---

### Task 2: Fail-Open Boundary and Privacy Guarantees

**Files:**
- Modify: `hooks/permission_request.py`
- Modify: `tests/test_permission_request.py`
- Modify: `tests/test_privacy.py`

**Interfaces:**
- Consumes: Task 1's `permission_queue_identity` and `handle_event`.
- Produces: `main() -> int`, an empty-stdout command entry point; bounded diagnostics using existing error codes; safe cleanup using `discard_event` and `try_worker_lock`.

- [ ] **Step 1: Add failing tests for malformed input, unsupported platforms, loader errors, queue cleanup, consumer failure, empty stdout, and secret persistence**

Append focused cases to `tests/test_permission_request.py`. Use a complete hook payload for valid paths, real temporary queue files, and patch only the unavoidable command stdin/stdout and forced queue failure:

```python
import io
import json
import os
from unittest.mock import patch

from hooks.permission_request import main


def test_non_macos_and_loader_failure_never_start_consumer(self) -> None:
    for platform_name, mode_loader in (
        ("linux", lambda _: "summary"),
        ("darwin", lambda _: (_ for _ in ()).throw(OSError("private"))),
    ):
        with self.subTest(platform=platform_name), tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertFalse(
                handle_event(
                    permission_payload(),
                    plugin_root=root,
                    data_dir=root / "data",
                    platform_name=platform_name,
                    mode_loader=mode_loader,
                    start_consumer=lambda *_: self.fail("consumer must not start"),
                )
            )

def test_invalid_identity_is_rejected_before_queueing(self) -> None:
    payload = permission_payload()
    del payload["session_id"]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data_dir = root / "data"
        with patch("hooks.permission_request.enqueue") as enqueue_event:
            self.assertFalse(
                handle_event(
                    payload,
                    plugin_root=root,
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: "summary",
                    start_consumer=lambda *_: self.fail("consumer must not start"),
                )
            )
        enqueue_event.assert_not_called()
        diagnostics = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
        self.assertIn("invalid_hook_input", diagnostics)

def test_queue_failure_is_metadata_only(self) -> None:
    private = "PRIVATE_APPROVAL_FAILURE_82411"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data_dir = root / "data"
        with patch(
            "hooks.permission_request.enqueue",
            side_effect=OSError(private),
        ):
            self.assertFalse(
                handle_event(
                    permission_payload(),
                    plugin_root=root,
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: "summary",
                    start_consumer=lambda *_: self.fail("consumer must not start"),
                )
            )
        diagnostics = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
        self.assertIn("queue_failed", diagnostics)
        self.assertNotIn(private, diagnostics)

def test_helper_start_failure_removes_unowned_plaintext(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data_dir = root / "data"
        self.assertTrue(
            handle_event(
                permission_payload(),
                plugin_root=root,
                data_dir=data_dir,
                platform_name="darwin",
                mode_loader=lambda _: "summary",
                start_consumer=lambda *_: (_ for _ in ()).throw(OSError("private")),
            )
        )
        self.assertEqual(list((data_dir / "spool").glob("*.json")), [])
        diagnostics = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
        self.assertIn("helper_start_failed", diagnostics)
        self.assertNotIn("private", diagnostics)

def test_main_always_exits_zero_with_empty_stdout_and_no_decision(self) -> None:
    for raw_input in ("not-json", json.dumps(permission_payload())):
        with self.subTest(raw_input=raw_input[:8]), tempfile.TemporaryDirectory() as temporary:
            stdout = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {"PLUGIN_ROOT": temporary, "PLUGIN_DATA": temporary},
                    clear=True,
                ),
                patch("hooks.permission_request.sys.stdin", io.StringIO(raw_input)),
                patch("hooks.permission_request.sys.stdout", stdout),
                patch("hooks.permission_request.sys.platform", "linux"),
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(stdout.getvalue(), "")
```

Add this real persistence assertion to `tests/test_privacy.py`. Extend the existing queue import with `poll_next`, and import `hooks.permission_request.handle_event` as `handle_permission_request`:

```python
def test_permission_request_content_never_enters_runtime_files(self) -> None:
    secret = "PRIVATE_APPROVAL_COMMAND_73191"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data_dir = root / "data"
        self.assertTrue(
            handle_permission_request(
                {
                    "session_id": "session",
                    "turn_id": "turn",
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": secret,
                        "description": f"approve {secret}",
                    },
                },
                plugin_root=root,
                data_dir=data_dir,
                platform_name="darwin",
                mode_loader=lambda _: "summary",
                start_consumer=lambda *_: None,
            )
        )
        event = poll_next(data_dir, now=time.monotonic() + 2.0).event
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.segments, ("Codex 有操作需要审批。",))
        for path in data_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret.encode("utf-8"), path.read_bytes(), path)
```

- [ ] **Step 2: Run the new failure tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_permission_request tests.test_privacy.PrivacyAndPackagingTests.test_permission_request_content_never_enters_runtime_files -v
```

Expected: failures show exceptions escaping from loader/helper paths and missing `main`; the privacy test may already pass on the valid path and therefore does not substitute for the required failing resilience tests.

- [ ] **Step 3: Add strict validation and fail-open command behavior**

Extend `hooks/permission_request.py` with these rules:

```python
import os

from codex_speak.diagnostics import record
from codex_speak.queue import discard_event, make_event_id, try_worker_lock

INVALID_EVENT_ID = make_event_id("invalid-session-id", "invalid-permission-request")


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
```

Replace the Task 1 `handle_event` body with this fail-open implementation:

```python
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
```

Implement `main()` exactly as a no-decision boundary:

```python
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
        if data_dir is not None:
            record(
                data_dir,
                event_id=INVALID_EVENT_ID,
                status="unknown",
                result="discarded",
                mode="unknown",
                error_code="invalid_hook_input",
            )
    return 0
```

Do not write to `sys.stdout` anywhere in this module.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_permission_request tests.test_privacy.PrivacyAndPackagingTests.test_permission_request_content_never_enters_runtime_files -v
```

Expected: all focused tests pass, command stdout is empty, and no secret canary appears in the runtime directory.

- [ ] **Step 5: Commit resilience and privacy behavior**

```bash
git add hooks/permission_request.py tests/test_permission_request.py tests/test_privacy.py
git commit -m "fix: keep approval speech alerts fail open"
```

---

### Task 3: Plugin Registration and User Documentation

**Files:**
- Modify: `hooks/hooks.json`
- Modify: `tests/test_hooks.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2's empty-stdout `hooks/permission_request.py` command.
- Produces: a plugin-discovered wildcard `PermissionRequest` registration that runs `python3 -B "${PLUGIN_ROOT}/hooks/permission_request.py"`.

- [ ] **Step 1: Update the hook registration test first**

Replace the existing exact hook-set assertion in `tests/test_hooks.py` with behavior that requires all three registrations:

```python
def test_hook_config_registers_session_permission_and_stop_commands(self) -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    self.assertEqual(
        set(config["hooks"]),
        {"SessionStart", "PermissionRequest", "Stop"},
    )
    permission_group = config["hooks"]["PermissionRequest"][0]
    self.assertEqual(permission_group["matcher"], "*")
    permission_command = permission_group["hooks"][0]["command"]
    self.assertEqual(
        permission_command,
        'python3 -B "${PLUGIN_ROOT}/hooks/permission_request.py"',
    )
    self.assertNotIn("PLUGIN_DATA", permission_command)
```

Preserve the existing SessionStart and Stop command assertions in the renamed test.

- [ ] **Step 2: Run the registration test and verify RED**

Run:

```bash
python3 -m unittest tests.test_hooks.HookTests.test_hook_config_registers_session_permission_and_stop_commands -v
```

Expected: FAIL because `hooks/hooks.json` does not contain `PermissionRequest`.

- [ ] **Step 3: Register the handler and document visible behavior**

Add this sibling entry between `SessionStart` and `Stop` in `hooks/hooks.json`:

```json
"PermissionRequest": [
  {
    "matcher": "*",
    "hooks": [
      {
        "type": "command",
        "command": "python3 -B \"${PLUGIN_ROOT}/hooks/permission_request.py\"",
        "statusMessage": "Preparing approval alert"
      }
    ]
  }
]
```

Update `README.md` in the feature, installation/trust, mode, privacy, and troubleshooting sections to state:

- the plugin bundles `SessionStart`, `PermissionRequest`, and `Stop`;
- Summary and Full speak the neutral fixed approval alert, while Silent suppresses it;
- the alert may precede an Auto-review decision;
- request details are never spoken or persisted;
- users must review and trust the changed hook definition through `/hooks` after installation or upgrade;
- the current public Marketplace release remains `0.2.10` until a separate release request.

- [ ] **Step 4: Run registration, JSON, privacy, and documentation-adjacent tests**

Run:

```bash
python3 -m unittest tests.test_hooks tests.test_privacy -v
python3 -m json.tool hooks/hooks.json >/dev/null
```

Expected: all tests pass and the hook configuration is valid JSON.

- [ ] **Step 5: Commit registration and docs**

```bash
git add hooks/hooks.json tests/test_hooks.py README.md
git commit -m "docs: register permission request speech alerts"
```

---

### Task 4: Full Local Verification and Candidate Review

**Files:**
- Verify only; modify earlier files solely for defects demonstrated by a new failing test.

**Interfaces:**
- Consumes: complete candidate from Tasks 1-3.
- Produces: a local implementation candidate with automated evidence and explicitly pending installed/human acceptance.

- [ ] **Step 1: Run the full Python suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: every Python test passes with zero failures and zero errors.

- [ ] **Step 2: Run source and package integrity checks**

Run:

```bash
python3 -m compileall -q codex_speak hooks tests
python3 -m json.tool hooks/hooks.json >/dev/null
python3 /Users/howard/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py /Users/howard/workspace/my-ai-workspace/plugins/codex-speak
git diff --check origin/main...HEAD
```

Expected: all commands exit zero; plugin validation reports success; the only worktree item outside the candidate remains `assets/.DS_Store`.

- [ ] **Step 3: Run the unchanged Swift helper suite**

Run outside the sandbox because the real helper smoke requires macOS process access:

```bash
CODEX_SPEAK_TEST_PYTHON=/Users/howard/opt/miniconda3/bin/python3 swift test --package-path menu-bar -Xswiftc -warnings-as-errors
```

Expected: all Swift tests pass with zero warnings promoted to errors.

- [ ] **Step 4: Exercise the source hook command without changing approval state**

Create a private temporary plugin-data directory, pipe one synthetic `PermissionRequest` JSON document to `hooks/permission_request.py`, and verify:

- exit status is zero;
- stdout is empty;
- exactly one queued event contains only `Codex 有操作需要审批。`;
- no command/description canary appears anywhere under the temporary data directory.

This smoke is source-level only. Do not install the candidate and do not trigger a real privileged action in this plan.

- [ ] **Step 5: Review the immutable candidate and report remaining gates**

Record the candidate as the final local commit hash and review the diff against the design's acceptance conditions. Report separately:

- implemented and automated-verification evidence;
- not yet verified: installed hook discovery/trust, real approval UI preservation, Auto-review interaction, and audible human acceptance;
- next gate: explicit authorization to version, push, release, reinstall, trust the changed hook, and run a real approval smoke.

Do not claim release readiness from source tests alone.
