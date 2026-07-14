import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from hooks.stop import handle_event
from codex_speak.protocol import Announcement
from codex_speak.queue import enqueue
from codex_speak.worker import run_worker


class PrivacyAndPackagingTests(unittest.TestCase):
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
                    + "\n\n<!-- codex-voice-notifier:v1 "
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
                    start_worker=run_queued_worker,
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
                Announcement("completed", secret),
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
                        + '\n<!-- codex-voice-notifier:v1 {"status":"completed"} -->'
                    ),
                },
                plugin_root=root,
                data_dir=data_dir,
                platform_name="darwin",
                start_worker=lambda plugin_root, plugin_data: None,
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
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)


if __name__ == "__main__":
    unittest.main()
