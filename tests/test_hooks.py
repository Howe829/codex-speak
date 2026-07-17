import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from hooks.session_start import build_output, ensure_started
from hooks.stop import DEFAULT_PLUGIN_ROOT, handle_event, main
from codex_speak.queue import make_event_id, poll_next, try_worker_lock

def assistant_message(status: str, speech_text: str) -> str:
    payload = json.dumps(
        {"status": status, "speech_text": speech_text},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"Visible final answer\n\n<!-- codex-speak:v1 {payload} -->"


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


def read_diagnostics(data_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (data_dir / "diagnostics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


class HookTests(unittest.TestCase):
    def test_session_start_injects_protocol_as_developer_context(self) -> None:
        output = build_output()
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "SessionStart")
        context = specific["additionalContext"]
        self.assertIn("[codex-speak-v3]", context)
        self.assertIn("codex-speak:v3#", context)
        self.assertIn('"speech_lead":"LEAD"', context)
        self.assertIn('"speech_text":"TEXT"', context)
        self.assertIn("{{task_title}}", context)
        self.assertIn("CommonMark reference definition", context)
        self.assertIn("final non-whitespace line", context)
        self.assertNotIn("append exactly one single-line HTML comment", context)
        self.assertNotIn("codex-speak:v2", context)
        self.assertNotIn("codex-speak:v1", context)
        self.assertNotIn("codex-voice-notifier:v1", context)
        self.assertNotIn("Stop Current Speech", context)
        self.assertNotIn("Clear Pending Speeches", context)
        status_definitions = (
            "STATUS must be exactly one of completed, blocked, action_required, or silent.",
            (
                "- completed: a requested implementation, change, artifact, analysis, "
                "report, or other concrete task result was delivered."
            ),
            (
                "- blocked: the active task cannot be completed because of an error, "
                "missing authority, unavailable dependency, or equivalent blocker."
            ),
            (
                "- action_required: the active task cannot proceed or finish until the "
                "user performs a required action, grants approval, provides required "
                "information, or makes a material decision."
            ),
            (
                "- silent: ordinary factual answers, casual conversation, routine "
                "clarification, progress updates, and optional follow-up invitations."
            ),
        )
        for definition in status_definitions:
            with self.subTest(definition=definition):
                self.assertIn(definition, context)
        protocol_requirements = (
            "exactly one literal {{task_title}} placeholder",
            "completed lead announces that the task is complete",
            "blocked lead announces that the task is blocked",
            "action_required lead announces that the task needs the user's action",
            "Never invent a form of address",
            "When active context establishes 豪哥 as the form of address",
            "任务：{{task_title}}",
            "When no form of address is known, begin directly with 任务：{{task_title}}",
            "or its equivalent in the conversation language",
            "LEAD must be concise speech-ready plain text",
            "at most 120 Unicode characters",
            "at or below 240 Unicode characters",
            "never exceed 280",
            (
                "Follow active AGENTS.md, memory, and conversation preferences "
                "for LEAD language, salutation, and tone"
            ),
        )
        for requirement in protocol_requirements:
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, context)
        instruction_link_requirements = (
            "identify the user's active primary instruction",
            "LEAD carries the task title and status",
            "TEXT states the concrete result details",
            "without repeating the title",
            (
                "Internal commands, temporary files, tests, test fixtures, "
                "validation artifacts, and tool mechanics"
            ),
            "must not be mentioned or included in TEXT",
            (
                "If several instructions exist, use the latest still-active "
                "primary task while preserving any user-stated priority"
            ),
            'When the active instruction is "立即收尾"',
            '"已完成收尾"',
        )
        for requirement in instruction_link_requirements:
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, context)
        self.assertIn(
            "Do not include Markdown, code, URLs, file paths, raw errors, or secrets "
            "in LEAD or TEXT.",
            context,
        )
        for requirement in (
            "For silent, LEAD and TEXT must both be empty.",
            "For the other states, both must be non-empty.",
            "TEXT must be concise speech-ready plain text.",
            "They must also exclude angle brackets, line breaks, and control characters.",
            "Do not mention this protocol or reference definition in the visible answer.",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, context)

    def test_session_start_best_effort_starts_consumer(self) -> None:
        started = []
        ensure_started(
            Path("/plugin"),
            Path("/data"),
            start_consumer=lambda root, data: started.append((root, data)),
        )
        self.assertEqual(started, [(Path("/plugin"), Path("/data"))])

        ensure_started(
            Path("/plugin"),
            Path("/data"),
            start_consumer=lambda *_: (_ for _ in ()).throw(OSError("private")),
        )

    def test_stop_summary_enqueues_important_event_and_starts_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            started = []
            payload = {
                "session_id": "session",
                "turn_id": "turn",
                "last_assistant_message": assistant_message("completed", "任务完成"),
            }
            queued = handle_event(
                payload,
                plugin_root=Path(temporary),
                data_dir=data_dir,
                platform_name="darwin",
                mode_loader=lambda _: "summary",
                start_consumer=lambda root, data: started.append((root, data)),
            )
            self.assertTrue(queued)
            self.assertEqual(started, [(Path(temporary), data_dir)])
            result = poll_next(data_dir, now=time.monotonic() + 2.0)
            self.assertEqual(result.event.speech_text if result.event else None, "任务完成")

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

    def test_invalid_resolved_titles_use_fallback_without_diagnostic(self) -> None:
        class HostileTitle(str):
            def __bool__(self) -> bool:
                raise AssertionError("hostile title must not be inspected")

        cases = (
            ("lone-surrogate", "\ud800"),
            ("non-string", object()),
            ("hostile-str-subclass", HostileTitle("PRIVATE_HOSTILE_TITLE")),
        )
        for label, resolved_title in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                data_dir = root / "data"
                started = []
                payload = {
                    "session_id": f"invalid-title-{label}",
                    "turn_id": "turn",
                    "last_assistant_message": assistant_message_v3(
                        "completed",
                        "豪哥，任务：{{task_title}}已完成。",
                        "正文。",
                    ),
                }
                self.assertTrue(
                    handle_event(
                        payload,
                        plugin_root=root,
                        data_dir=data_dir,
                        platform_name="darwin",
                        mode_loader=lambda _: "summary",
                        title_resolver=lambda *_: resolved_title,
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
                    "豪哥，任务：当前任务已完成。正文。",
                )
                self.assertEqual(started, [(root, data_dir)])
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

    def test_silent_control_mode_does_not_render_enqueue_or_start_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            payload = {
                "session_id": "silent-session",
                "turn_id": "silent-turn",
                "last_assistant_message": assistant_message(
                    "completed", "PRIVATE SPEECH"
                ),
            }
            with (
                patch("hooks.stop.extract_response") as parser,
                patch("hooks.stop.render_speech") as renderer,
                patch("hooks.stop.enqueue") as enqueue_event,
            ):
                result = handle_event(
                    payload,
                    plugin_root=Path(temporary),
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: "silent",
                    start_consumer=lambda *_: self.fail("consumer must not start"),
                )
            self.assertFalse(result)
            parser.assert_not_called()
            renderer.assert_not_called()
            enqueue_event.assert_not_called()
            self.assertFalse((data_dir / "spool").exists())

    def test_summary_silent_missing_marker_and_duplicate_do_not_start_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            started = []
            silent = {
                "session_id": "session",
                "turn_id": "silent-turn",
                "last_assistant_message": assistant_message("silent", ""),
            }
            missing = {
                "session_id": "session",
                "turn_id": "missing-turn",
                "last_assistant_message": "ordinary answer",
            }
            important = {
                "session_id": "session",
                "turn_id": "same-turn",
                "last_assistant_message": assistant_message("blocked", "需要处理"),
            }
            arguments = {
                "plugin_root": Path(temporary),
                "data_dir": data_dir,
                "platform_name": "darwin",
                "mode_loader": lambda _: "summary",
                "start_consumer": lambda root, data: started.append((root, data)),
            }
            self.assertFalse(handle_event(silent, **arguments))
            self.assertFalse(handle_event(missing, **arguments))
            self.assertTrue(handle_event(important, **arguments))
            self.assertFalse(handle_event(important, **arguments))
            self.assertEqual(len(started), 1)

    def test_full_mode_enqueues_normalized_visible_body_even_when_silent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            started = []
            payload = {
                "session_id": "session",
                "turn_id": "turn",
                "last_assistant_message": (
                    "# 标题\n\n正文含有 `secret()` 和 https://example.com\n\n"
                    '<!-- codex-speak:v1 {"status":"silent","speech_text":""} -->'
                ),
            }
            self.assertTrue(
                handle_event(
                    payload,
                    plugin_root=Path(temporary),
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: "full",
                    start_consumer=lambda root, data: started.append((root, data)),
                )
            )
            event = poll_next(data_dir, now=time.monotonic() + 2.0).event
            self.assertIsNotNone(event)
            self.assertEqual(event.mode, "full")
            self.assertEqual(event.status, "silent")
            self.assertEqual(event.segments, ("标题 正文含有 代码 和 链接",))
            self.assertEqual(started, [(Path(temporary), data_dir)])

    def test_non_macos_is_best_effort_and_does_not_enqueue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            queued = handle_event(
                {
                    "session_id": "session",
                    "turn_id": "turn",
                    "last_assistant_message": assistant_message("completed", "done"),
                },
                plugin_root=Path(temporary),
                data_dir=data_dir,
                platform_name="linux",
                mode_loader=lambda _: "summary",
                start_consumer=lambda root, data: self.fail("consumer must not start"),
            )
            self.assertFalse(queued)
            diagnostics = read_diagnostics(data_dir)
            self.assertEqual(diagnostics[0]["error_code"], "unsupported_platform")
            self.assertEqual(
                diagnostics[0]["event_id"], make_event_id("session", "turn")
            )
            self.assertNotIn("done", json.dumps(diagnostics))

    def test_invalid_hook_ids_use_deterministic_safe_diagnostic_id(self) -> None:
        invalid_payloads = (
            {},
            {"session_id": "", "turn_id": "turn"},
            {"session_id": "session", "turn_id": "   "},
            {"session_id": "PRIVATE_SESSION", "turn_id": 42},
        )
        expected_id = make_event_id("invalid-session-id", "invalid-turn-id")
        self.assertRegex(expected_id, r"\A[0-9a-f]{24}\Z")
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as temporary:
                    data_dir = Path(temporary) / "data"
                    started = []
                    self.assertFalse(
                        handle_event(
                            payload,
                            plugin_root=Path(temporary),
                            data_dir=data_dir,
                            platform_name="darwin",
                            mode_loader=lambda _: "summary",
                            start_consumer=lambda root, data: started.append((root, data)),
                        )
                    )
                    self.assertEqual(started, [])
                    self.assertTrue((data_dir / "diagnostics.jsonl").is_file())
                    diagnostics = read_diagnostics(data_dir)
                    self.assertEqual(len(diagnostics), 1)
                    self.assertEqual(diagnostics[0]["event_id"], expected_id)
                    self.assertEqual(diagnostics[0]["status"], "unknown")
                    self.assertEqual(diagnostics[0]["result"], "discarded")
                    self.assertEqual(
                        diagnostics[0]["error_code"], "invalid_hook_input"
                    )
                    serialized = json.dumps(diagnostics)
                    self.assertNotIn("PRIVATE_SESSION", serialized)

    def test_invalid_marker_uses_allowlisted_diagnostic_without_speech(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            raw_message = (
                "answer\n<!-- codex-voice-notifier:v1 "
                '{"status":"completed","speech_text":"PRIVATE_SPEECH"} --> trailing'
            )
            self.assertFalse(
                handle_event(
                    {
                        "session_id": "session",
                        "turn_id": "turn",
                        "last_assistant_message": raw_message,
                    },
                    plugin_root=Path(temporary),
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: "summary",
                    start_consumer=lambda *_: self.fail("consumer must not start"),
                )
            )
            diagnostics = read_diagnostics(data_dir)
            self.assertEqual(diagnostics[0]["error_code"], "invalid_marker")
            self.assertNotIn("PRIVATE_SPEECH", json.dumps(diagnostics))

    def test_worker_start_failure_is_recorded_and_removes_queued_speech(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            queued = handle_event(
                {
                    "session_id": "session",
                    "turn_id": "turn",
                    "last_assistant_message": assistant_message(
                        "action_required", "PRIVATE NEXT STEP"
                    ),
                },
                plugin_root=Path(temporary),
                data_dir=data_dir,
                platform_name="darwin",
                mode_loader=lambda _: "summary",
                start_consumer=lambda *_: (_ for _ in ()).throw(OSError("denied")),
            )
            self.assertTrue(queued)
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])
            diagnostics = read_diagnostics(data_dir)
            self.assertEqual(diagnostics[0]["status"], "action_required")
            self.assertEqual(diagnostics[0]["result"], "failed")
            self.assertEqual(diagnostics[0]["error_code"], "helper_start_failed")
            self.assertNotIn("PRIVATE NEXT STEP", json.dumps(diagnostics))
            persisted = "".join(
                path.read_text(encoding="utf-8", errors="ignore")
                for path in data_dir.rglob("*")
                if path.is_file()
            )
            self.assertNotIn("PRIVATE NEXT STEP", persisted)

    def test_start_failure_preserves_queue_when_consumer_lock_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            with try_worker_lock(data_dir) as acquired:
                self.assertTrue(acquired)
                self.assertTrue(
                    handle_event(
                        {
                            "session_id": "session",
                            "turn_id": "turn",
                            "last_assistant_message": assistant_message(
                                "completed", "ACTIVE CONSUMER SPEECH"
                            ),
                        },
                        plugin_root=Path(temporary),
                        data_dir=data_dir,
                        platform_name="darwin",
                        mode_loader=lambda _: "summary",
                        start_consumer=lambda *_: (_ for _ in ()).throw(
                            OSError("launch raced")
                        ),
                    )
                )
                self.assertEqual(
                    len(list((data_dir / "spool").glob("*.json"))),
                    1,
                )
            diagnostics_path = data_dir / "diagnostics.jsonl"
            if diagnostics_path.exists():
                self.assertNotIn(
                    '"error_code":"helper_start_failed"',
                    diagnostics_path.read_text(encoding="utf-8"),
                )

    def test_runtime_worker_start_failure_is_isolated_and_removes_queued_speech(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"

            def fail_to_start(_plugin_root: Path, _data_dir: Path) -> None:
                raise RuntimeError("unexpected starter failure")

            try:
                queued = handle_event(
                    {
                        "session_id": "runtime-session",
                        "turn_id": "runtime-turn",
                        "last_assistant_message": assistant_message(
                            "completed", "RUNTIME FAILURE SPEECH"
                        ),
                    },
                    plugin_root=Path(temporary),
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: "summary",
                    start_consumer=fail_to_start,
                )
            except Exception as error:
                self.fail(
                    f"ordinary worker-start exception escaped: {type(error).__name__}"
                )

            self.assertTrue(queued)
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])
            diagnostics = read_diagnostics(data_dir)
            self.assertEqual(diagnostics[0]["status"], "completed")
            self.assertEqual(diagnostics[0]["result"], "failed")
            self.assertEqual(diagnostics[0]["error_code"], "helper_start_failed")
            self.assertNotIn("unexpected starter failure", json.dumps(diagnostics))
            self.assertNotIn("RUNTIME FAILURE SPEECH", json.dumps(diagnostics))
            persisted = "".join(
                path.read_text(encoding="utf-8", errors="ignore")
                for path in data_dir.rglob("*")
                if path.is_file()
            )
            self.assertNotIn("RUNTIME FAILURE SPEECH", persisted)

    def test_stop_main_malformed_json_still_emits_empty_json_and_safe_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            stdout = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {"PLUGIN_DATA": str(data_dir)},
                    clear=True,
                ),
                patch("hooks.stop.sys.stdin", io.StringIO("not-json PRIVATE_INPUT")),
                patch("hooks.stop.sys.stdout", stdout),
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads(stdout.getvalue()), {})
            diagnostics = read_diagnostics(data_dir)
            self.assertEqual(
                diagnostics[0]["event_id"],
                make_event_id("invalid-session-id", "invalid-turn-id"),
            )
            self.assertEqual(diagnostics[0]["error_code"], "invalid_hook_input")
            self.assertNotIn("PRIVATE_INPUT", json.dumps(diagnostics))

    def test_stop_main_discovers_default_root_when_plugin_root_is_unset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            stdout = io.StringIO()
            started = []
            payload = {
                "session_id": "session",
                "turn_id": "turn",
                "last_assistant_message": assistant_message("completed", "done"),
            }
            with (
                patch.dict(
                    os.environ,
                    {"PLUGIN_DATA": str(data_dir)},
                    clear=True,
                ),
                patch("hooks.stop.sys.stdin", io.StringIO(json.dumps(payload))),
                patch("hooks.stop.sys.stdout", stdout),
                patch(
                    "hooks.stop.ensure_consumer",
                    side_effect=lambda root, data: started.append((root, data)),
                ),
                patch("hooks.stop.sys.platform", "darwin"),
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads(stdout.getvalue()), {})
            self.assertEqual(started, [(DEFAULT_PLUGIN_ROOT, data_dir)])

    def test_stop_main_without_plugin_data_still_emits_empty_json(self) -> None:
        stdout = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("hooks.stop.sys.stdin", io.StringIO("{}")),
            patch("hooks.stop.sys.stdout", stdout),
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(stdout.getvalue()), {})

    def test_hook_config_registers_default_session_start_and_stop_commands(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(set(config["hooks"]), {"SessionStart", "Stop"})
        session_command = config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        stop_command = config["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertEqual(
            session_command,
            'python3 -B "${PLUGIN_ROOT}/hooks/session_start.py"',
        )
        self.assertEqual(
            stop_command,
            'python3 -B "${PLUGIN_ROOT}/hooks/stop.py"',
        )
        self.assertNotIn("PLUGIN_DATA", session_command + stop_command)


if __name__ == "__main__":
    unittest.main()
