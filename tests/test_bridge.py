import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_speak.queue import enqueue, make_event_id, try_worker_lock
from codex_speak.render import SpeechPayload


CLOCK = "11111111-1111-1111-1111-111111111111"


class InspectingOutput(io.StringIO):
    def __init__(self, data_dir: Path) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.event_was_claimed = False

    def flush(self) -> None:
        lines = self.getvalue().splitlines()
        if lines and json.loads(lines[-1]).get("type") == "event":
            self.event_was_claimed = not list(
                (self.data_dir / "spool").glob("*.json")
            )


class BridgeTests(unittest.TestCase):
    def _bridge(self):
        try:
            from codex_speak.bridge import run_bridge
        except ModuleNotFoundError:
            self.fail("codex_speak.bridge is not implemented")
        return run_bridge

    def _helper(self):
        try:
            from codex_speak import helper
        except ModuleNotFoundError:
            self.fail("codex_speak.helper is not implemented")
        return helper

    def test_bridge_prints_ready_then_claimed_event_and_flushes_each_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            enqueue(
                data_dir,
                SpeechPayload("full", "silent", ("第一段", "第二段")),
                session_id="session",
                turn_id="turn",
                now=100.0,
                clock_id=CLOCK,
            )
            output = InspectingOutput(data_dir)
            self.assertEqual(
                self._bridge()(
                    data_dir,
                    output=output,
                    sleep=lambda _: None,
                    clock=lambda: 101.0,
                    clock_id=CLOCK,
                    stop_requested=lambda: len(output.getvalue().splitlines()) >= 2,
                ),
                0,
            )
            self.assertTrue(output.event_was_claimed)
            self.assertEqual(
                [json.loads(line) for line in output.getvalue().splitlines()],
                [
                    {"type": "ready"},
                    {
                        "type": "event",
                        "event_id": make_event_id("session", "turn"),
                        "mode": "full",
                        "status": "silent",
                        "segments": ["第一段", "第二段"],
                    },
                ],
            )

    def test_lock_contender_prints_only_busy_and_claims_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            enqueue(
                data_dir,
                SpeechPayload("full", "silent", ("保留",)),
                session_id="session",
                turn_id="turn",
                now=100.0,
                clock_id=CLOCK,
            )
            output = io.StringIO()
            with try_worker_lock(data_dir) as acquired:
                self.assertTrue(acquired)
                self.assertEqual(
                    self._bridge()(data_dir, output=output, clock_id=CLOCK),
                    0,
                )
            self.assertEqual(output.getvalue(), '{"type":"busy"}\n')
            self.assertEqual(len(list((data_dir / "spool").glob("*.json"))), 1)

    def test_ensure_consumer_prefers_verified_helper_and_falls_back_when_missing(self) -> None:
        helper = self._helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "plugin"
            data_dir = Path(temporary) / "data"
            executable = root / helper.HELPER
            executable.parent.mkdir(parents=True)
            executable.write_text("helper", encoding="utf-8")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            with (
                patch.object(helper, "launch_verified_helper") as launch,
                patch.object(helper, "spawn_worker") as spawn,
            ):
                self.assertEqual(helper.ensure_consumer(root, data_dir), "helper")
            launch.assert_called_once_with(executable, root, data_dir)
            spawn.assert_not_called()

            executable.unlink()
            with patch.object(helper, "spawn_worker") as spawn:
                self.assertEqual(helper.ensure_consumer(root, data_dir), "fallback")
            spawn.assert_called_once_with(root, data_dir)

    def test_current_heartbeat_suppresses_launch(self) -> None:
        helper = self._helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "plugin"
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            executable = root / "helper"
            state = {
                "version": 1,
                "pid": 321,
                "boot_id": CLOCK,
                "monotonic": 100.0,
            }
            (data_dir / "helper-state.json").write_text(
                json.dumps(state), encoding="utf-8"
            )
            helper.launch_verified_helper(
                executable,
                root,
                data_dir,
                monotonic=lambda: 101.0,
                boot_id_loader=lambda: CLOCK,
                popen=lambda *_args, **_kwargs: self.fail("helper relaunched"),
            )

    def test_stale_or_invalid_heartbeat_is_removed_without_signaling_pid(self) -> None:
        helper = self._helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "plugin"
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            state_path = data_dir / "helper-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "pid": 999999,
                        "boot_id": CLOCK,
                        "monotonic": 1.0,
                    }
                ),
                encoding="utf-8",
            )

            class Process:
                pid = 444

            sleeps = []
            launches = []

            def sleep(_seconds):
                sleeps.append(True)
                state_path.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "pid": 444,
                            "boot_id": CLOCK,
                            "monotonic": 100.0,
                        }
                    ),
                    encoding="utf-8",
                )

            with patch("codex_speak.helper.os.kill") as kill:
                helper.launch_verified_helper(
                    Path("/helper"),
                    root,
                    data_dir,
                    monotonic=lambda: 100.0,
                    boot_id_loader=lambda: CLOCK,
                    popen=lambda arguments, **_kwargs: (
                        launches.append(arguments) or Process()
                    ),
                    sleep=sleep,
                )
            kill.assert_not_called()
            self.assertTrue(sleeps)
            self.assertEqual(
                launches,
                [[
                    "/helper",
                    "--plugin-root",
                    str(root),
                    "--data-dir",
                    str(data_dir),
                    "--python-executable",
                    str(Path(sys.executable)),
                ]],
            )

    def test_python_executable_must_be_absolute_file_and_executable(self) -> None:
        helper = self._helper()
        with tempfile.TemporaryDirectory() as temporary:
            non_executable = Path(temporary) / "python"
            non_executable.write_text("", encoding="utf-8")
            invalid_values = [
                "python3",
                str(non_executable),
                str(Path(temporary) / "missing"),
            ]
            for invalid in invalid_values:
                with patch.object(helper.sys, "executable", invalid):
                    with self.assertRaises(OSError):
                        helper._validated_python_executable()

        self.assertEqual(helper._validated_python_executable(), Path(sys.executable))

    def test_helper_launch_rejects_relative_launch_paths(self) -> None:
        helper = self._helper()
        with tempfile.TemporaryDirectory() as temporary:
            absolute = Path(temporary)
            cases = [
                (Path("helper"), absolute / "plugin", absolute / "data"),
                (absolute / "helper", Path("plugin"), absolute / "data"),
                (absolute / "helper", absolute / "plugin", Path("data")),
            ]
            for executable, plugin_root, data_dir in cases:
                with self.assertRaises(OSError):
                    helper.launch_verified_helper(
                        executable,
                        plugin_root,
                        data_dir,
                        boot_id_loader=lambda: CLOCK,
                        popen=lambda *_args, **_kwargs: self.fail("launched"),
                    )

    def test_helper_launch_failure_records_only_fixed_metadata_then_falls_back(self) -> None:
        helper = self._helper()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "plugin"
            data_dir = Path(temporary) / "data"
            executable = root / helper.HELPER
            executable.parent.mkdir(parents=True)
            executable.write_text("helper", encoding="utf-8")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            with (
                patch.object(
                    helper,
                    "launch_verified_helper",
                    side_effect=OSError("PRIVATE PATH AND ERROR"),
                ),
                patch.object(helper, "spawn_worker") as spawn,
            ):
                self.assertEqual(helper.ensure_consumer(root, data_dir), "fallback")
            spawn.assert_called_once_with(root, data_dir)
            diagnostic = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
            self.assertIn('"error_code":"helper_start_failed"', diagnostic)
            self.assertNotIn("PRIVATE PATH AND ERROR", diagnostic)


if __name__ == "__main__":
    unittest.main()
