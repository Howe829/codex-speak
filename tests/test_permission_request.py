from __future__ import annotations

import io
import json
import os
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

from codex_speak.queue import make_event_id, poll_next
import hooks.permission_request as permission_request
from hooks.permission_request import handle_event, permission_queue_identity


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
            {
                "command": "curl https://example.invalid",
                "description": "network",
            }
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

    def test_non_macos_records_fixed_metadata_without_starting_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"

            self.assertFalse(
                handle_event(
                    permission_payload(),
                    plugin_root=root,
                    data_dir=data_dir,
                    platform_name="linux",
                    mode_loader=lambda _: "summary",
                    start_consumer=lambda *_: self.fail("consumer must not start"),
                )
            )
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("unsupported_platform", diagnostics)

    def test_loader_failure_and_unknown_mode_never_enqueue(self) -> None:
        cases = (
            ("loader failure", lambda _: (_ for _ in ()).throw(OSError("private"))),
            ("unknown mode", lambda _: "verbose"),
        )
        for name, mode_loader in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                data_dir = root / "data"
                with patch("hooks.permission_request.enqueue") as enqueue_event:
                    self.assertFalse(
                        handle_event(
                            permission_payload(),
                            plugin_root=root,
                            data_dir=data_dir,
                            platform_name="darwin",
                            mode_loader=mode_loader,
                            start_consumer=lambda *_: self.fail(
                                "consumer must not start"
                            ),
                        )
                    )
                enqueue_event.assert_not_called()
                diagnostics = (data_dir / "diagnostics.jsonl").read_text(
                    encoding="utf-8"
                )
                self.assertIn("invalid_settings", diagnostics)
                self.assertNotIn("private", diagnostics)

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
                        start_consumer=lambda *_: self.fail(
                            "consumer must not start"
                        ),
                    )
                )
            enqueue_event.assert_not_called()
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(
                encoding="utf-8"
            )
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
                        start_consumer=lambda *_: self.fail(
                            "consumer must not start"
                        ),
                    )
                )
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(
                encoding="utf-8"
            )
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
                    start_consumer=lambda *_: (_ for _ in ()).throw(
                        OSError("private")
                    ),
                )
            )
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("helper_start_failed", diagnostics)
            self.assertNotIn("private", diagnostics)

    def test_main_always_exits_zero_with_empty_stdout_and_no_decision(self) -> None:
        for raw_input in ("not-json", json.dumps(permission_payload())):
            with (
                self.subTest(raw_input=raw_input[:8]),
                tempfile.TemporaryDirectory() as temporary,
            ):
                stdout = io.StringIO()
                with (
                    patch.dict(
                        os.environ,
                        {"PLUGIN_ROOT": temporary, "PLUGIN_DATA": temporary},
                        clear=True,
                    ),
                    patch(
                        "hooks.permission_request.sys.stdin",
                        io.StringIO(raw_input),
                    ),
                    patch("hooks.permission_request.sys.stdout", stdout),
                    patch("hooks.permission_request.sys.platform", "linux"),
                ):
                    self.assertEqual(permission_request.main(), 0)
                self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
