import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from hooks.stop import handle_event
from codex_speak.bridge import run_bridge
from codex_speak.queue import enqueue
from codex_speak.render import SpeechPayload, normalize_full_text, segment_text
from codex_speak.worker import run_worker


def summary_payload(status: str, text: str) -> SpeechPayload:
    return SpeechPayload("summary", status, (text,))


class PrivacyAndPackagingTests(unittest.TestCase):
    def test_full_mode_bridge_claims_then_drains_private_runtime(self) -> None:
        canaries = {
            "prompt": "BRIDGE_PROMPT_CANARY_10457",
            "body": "BRIDGE_BODY_CANARY_21929",
            "summary": "BRIDGE_SUMMARY_CANARY_32771",
            "code": "BRIDGE_CODE_CANARY_43391",
            "url": "BRIDGE_URL_CANARY_54121",
            "path": "BRIDGE_PATH_CANARY_65809",
            "segment": "BRIDGE_SEGMENT_CANARY_76157",
        }
        visible_body = (
            f"{canaries['body']} `{canaries['code']}` "
            f"https://example.invalid/{canaries['url']} "
            f"/private/tmp/{canaries['path']} {canaries['segment']}"
        )
        expected_segments = segment_text(normalize_full_text(visible_body))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"
            data_dir.mkdir(mode=0o700)
            state_path = data_dir / "helper-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "pid": 123,
                        "boot_id": "11111111-1111-1111-1111-111111111111",
                        "monotonic": 10.0,
                        "identity": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )
            state_path.chmod(0o600)
            output = io.StringIO()

            def run_helper_bridge(plugin_root: Path, plugin_data: Path) -> None:
                self.assertEqual((plugin_root, plugin_data), (root, data_dir))
                run_bridge(
                    plugin_data,
                    output=output,
                    sleep=lambda _: None,
                    clock=lambda: time.monotonic() + 2.0,
                    stop_requested=lambda: len(output.getvalue().splitlines()) >= 2,
                )

            marker = json.dumps(
                {"status": "completed", "speech_text": canaries["summary"]},
                separators=(",", ":"),
            )
            self.assertTrue(
                handle_event(
                    {
                        "session_id": "bridge-private-session",
                        "turn_id": "bridge-private-turn",
                        "last_assistant_message": (
                            f"{visible_body}\n<!-- codex-speak:v1 {marker} -->"
                        ),
                        "user_input": canaries["prompt"],
                    },
                    plugin_root=root,
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: "full",
                    start_consumer=run_helper_bridge,
                )
            )
            bridge_messages = [
                json.loads(line) for line in output.getvalue().splitlines()
            ]
            self.assertEqual(bridge_messages[0], {"type": "ready"})
            self.assertEqual(bridge_messages[1]["segments"], list(expected_segments))
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])

            output.seek(0)
            output.truncate()
            del bridge_messages
            for path in data_dir.rglob("*"):
                if path.is_file():
                    contents = path.read_bytes()
                    for canary in canaries.values():
                        self.assertNotIn(canary.encode(), contents, path)

    def test_full_mode_fallback_leaves_canaries_only_in_fake_say_stdin(self) -> None:
        for outcome, return_code in (("success", 0), ("failure", 9)):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temporary:
                suffix = outcome.upper()
                canaries = {
                    "prompt": f"PROMPT_CANARY_10931_{suffix}",
                    "body": f"BODY_CANARY_21403_{suffix}",
                    "summary": f"SUMMARY_CANARY_32719_{suffix}",
                    "code": f"CODE_CANARY_43801_{suffix}",
                    "url": f"URL_CANARY_54319_{suffix}",
                    "path": f"PATH_CANARY_65927_{suffix}",
                    "segment_one": f"SEGMENT_CANARY_76111_{suffix}",
                    "segment_two": f"SEGMENT_CANARY_87383_{suffix}",
                }
                visible_body = (
                    f"{canaries['body']} `{canaries['code']}` "
                    f"https://example.invalid/{canaries['url']} "
                    f"/private/tmp/{canaries['path']} "
                    f"{canaries['segment_one']} "
                    + ("first filler " * 70)
                    + f"{canaries['segment_two']} "
                    + ("second filler " * 70)
                )
                normalized = normalize_full_text(visible_body)
                expected_segments = segment_text(normalized)
                self.assertGreaterEqual(len(expected_segments), 2)
                self.assertIn("代码", normalized)
                self.assertIn("链接", normalized)
                self.assertIn("相关文件", normalized)
                for key in ("code", "url", "path", "prompt", "summary"):
                    self.assertNotIn(canaries[key], normalized)

                root = Path(temporary)
                data_dir = root / "data"
                say_path = root / "fake-say"
                say_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                say_path.chmod(0o700)
                fake_stdin: list[str] = []
                process_arguments: list[list[str]] = []

                def fake_run(arguments, **kwargs):
                    process_arguments.append(arguments)
                    fake_stdin.append(kwargs["input"])
                    return subprocess.CompletedProcess(arguments, return_code)

                def run_fallback(plugin_root: Path, plugin_data: Path) -> None:
                    self.assertEqual((plugin_root, plugin_data), (root, data_dir))
                    run_worker(
                        plugin_data,
                        say_path=say_path,
                        run_command=fake_run,
                        sleep=lambda _: None,
                        clock=lambda: time.monotonic() + 2.0,
                        monotonic=lambda: 10.0,
                    )

                marker = json.dumps(
                    {
                        "status": "completed",
                        "speech_text": canaries["summary"],
                    },
                    separators=(",", ":"),
                )
                self.assertTrue(
                    handle_event(
                        {
                            "session_id": "private-session",
                            "turn_id": f"private-{outcome}",
                            "last_assistant_message": (
                                f"{visible_body}\n<!-- codex-speak:v1 {marker} -->"
                            ),
                            "user_input": canaries["prompt"],
                        },
                        plugin_root=root,
                        data_dir=data_dir,
                        platform_name="darwin",
                        mode_loader=lambda _: "full",
                        start_consumer=run_fallback,
                    )
                )

                expected_stdin = (
                    list(expected_segments)
                    if return_code == 0
                    else [expected_segments[0]]
                )
                self.assertEqual(fake_stdin, expected_stdin)
                self.assertEqual(
                    process_arguments,
                    [[str(say_path)]] * len(expected_stdin),
                )
                serialized_arguments = json.dumps(process_arguments)
                for canary in canaries.values():
                    self.assertNotIn(canary, serialized_arguments)
                self.assertFalse((data_dir / "helper-state.json").exists())
                self.assertEqual(list((data_dir / "spool").glob("*.json")), [])
                for path in data_dir.rglob("*"):
                    if path.is_file():
                        contents = path.read_bytes()
                        for canary in canaries.values():
                            self.assertNotIn(canary.encode(), contents, path)

    def test_valid_stop_event_never_persists_assistant_user_or_claimed_speech(
        self,
    ) -> None:
        assistant_secret = "PRIVATE_ASSISTANT_BODY_SENTINEL_26191"
        speech_secret = "PrivateMarkerSpeechSentinel48327"
        user_secret = "PRIVATE_USER_INPUT_SENTINEL_79543"
        secrets = (assistant_secret, speech_secret, user_secret)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"
            say_path = root / "fake-say"
            say_path.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            say_path.chmod(0o700)
            captured = []

            def assert_plugin_data_omits_secrets() -> None:
                for path in data_dir.rglob("*"):
                    if not path.is_file():
                        continue
                    contents = path.read_bytes()
                    for secret in secrets:
                        self.assertNotIn(secret.encode("utf-8"), contents, path)

            def fake_run(arguments, **kwargs):
                captured.append((arguments, kwargs["input"]))
                self.assertEqual(arguments, [str(say_path)])
                self.assertEqual(kwargs["input"], speech_secret)
                self.assertNotIn(speech_secret, " ".join(arguments))
                assert_plugin_data_omits_secrets()
                return subprocess.CompletedProcess(arguments, 0)

            def run_queued_worker(plugin_root: Path, plugin_data: Path) -> None:
                self.assertEqual(plugin_root, root)
                self.assertEqual(plugin_data, data_dir)
                run_worker(
                    plugin_data,
                    say_path=say_path,
                    run_command=fake_run,
                    sleep=lambda _: None,
                    clock=lambda: time.monotonic() + 2.0,
                    monotonic=lambda: 10.0,
                )

            payload = {
                "session_id": "private-session",
                "turn_id": "private-turn",
                "last_assistant_message": (
                    assistant_secret
                    + "\n\n<!-- codex-speak:v1 "
                    + json.dumps(
                        {"status": "completed", "speech_text": speech_secret},
                        separators=(",", ":"),
                    )
                    + " -->"
                ),
                "user_input": user_secret,
            }

            self.assertTrue(
                handle_event(
                    payload,
                    plugin_root=root,
                    data_dir=data_dir,
                    platform_name="darwin",
                    mode_loader=lambda _: "summary",
                    start_consumer=run_queued_worker,
                )
            )
            self.assertEqual(captured, [([str(say_path)], speech_secret)])
            assert_plugin_data_omits_secrets()

    def test_processed_speech_is_absent_from_plugin_data(self) -> None:
        secret = "PRIVATE_SPEECH_SENTINEL_92841"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"
            say_path = root / "say"
            say_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            say_path.chmod(0o700)
            enqueue(
                data_dir,
                summary_payload("completed", secret),
                session_id="private-session",
                turn_id="private-turn",
                now=100.0,
            )
            captured = []

            def fake_run(arguments, **kwargs):
                captured.append((arguments, kwargs["input"]))
                return subprocess.CompletedProcess(arguments, 0)

            run_worker(
                data_dir,
                say_path=say_path,
                run_command=fake_run,
                sleep=lambda _: None,
                clock=lambda: 102.0,
                monotonic=lambda: 10.0,
            )
            self.assertEqual(captured, [([str(say_path)], secret)])
            for path in data_dir.rglob("*"):
                if path.is_file():
                    self.assertNotIn(secret.encode("utf-8"), path.read_bytes(), path)

    def test_malformed_marker_diagnostic_does_not_store_message(self) -> None:
        secret = "PRIVATE_RESPONSE_SENTINEL_51723"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"
            handle_event(
                {
                    "session_id": "session",
                    "turn_id": "turn",
                    "last_assistant_message": (
                        secret
                        + '\n<!-- codex-speak:v1 {"status":"completed"} -->'
                    ),
                },
                plugin_root=root,
                data_dir=data_dir,
                platform_name="darwin",
                mode_loader=lambda _: "summary",
                start_consumer=lambda plugin_root, plugin_data: None,
            )
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("invalid_marker", diagnostics)
            self.assertNotIn(secret, diagnostics)

    def test_manifest_uses_default_hook_discovery(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["name"], "codex-speak")
        self.assertEqual(manifest["interface"]["displayName"], "Codex Speak")
        self.assertNotIn("hooks", manifest)
        self.assertTrue((root / "hooks" / "hooks.json").is_file())

    def test_readme_covers_install_trust_update_and_privacy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        for required in (
            "codex plugin add codex-speak@personal",
            "/hooks",
            "new thread",
            "update_plugin_cachebuster.py",
            "PLUGIN_DATA",
            "five minutes",
            "AGENTS.md",
            "memory",
            "does not hard-code a user's name",
            "active primary instruction",
            "standard library",
            "maintainer/development check",
            "python3 -m venv /private/tmp/codex-plugin-validator",
            "/private/tmp/codex-plugin-validator/bin/python -m pip install PyYAML",
            "/private/tmp/codex-plugin-validator/bin/python",
            "Summary",
            "Full",
            "Stop Current Speech",
            "Clear Pending Speeches",
            "Quit Codex Speak",
            "Plugin Toggle",
            "controls the whole plugin",
            "context-free",
            "fallback",
            "codex-voice-notifier",
            "./scripts/build_menu_app.sh",
            "ad hoc",
            "signed sharing",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)


if __name__ == "__main__":
    unittest.main()
