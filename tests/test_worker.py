from contextlib import contextmanager
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import ANY, patch

from codex_speak.protocol import Announcement
from codex_speak.queue import enqueue, try_worker_lock
from codex_speak.worker import run_worker, spawn_worker


CLOCK_A = "11111111-1111-1111-1111-111111111111"
CLOCK_B = "22222222-2222-2222-2222-222222222222"


class WorkerTests(unittest.TestCase):
    def _fake_executable(self, directory: Path) -> Path:
        path = directory / "say"
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_speaks_fifo_through_stdin_without_exposing_text_in_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            say_path = self._fake_executable(Path(temporary))
            speeches = (
                "first",
                "$(touch /tmp/pwned)",
                "-v Alex PRIVATE",
                "third",
            )
            for index, speech in enumerate(speeches):
                enqueue(
                    data_dir,
                    Announcement("completed", speech),
                    session_id=f"session-{index}",
                    turn_id=f"turn-{index}",
                    now=100.0 + index / 10,
                )
            calls = []

            def fake_run(arguments, **kwargs):
                remaining = [
                    json.loads(path.read_text(encoding="utf-8"))["speech_text"]
                    for path in (data_dir / "spool").glob("*.json")
                ]
                self.assertNotIn(kwargs["input"], remaining)
                self.assertEqual(
                    set(kwargs),
                    {"input", "text", "check", "stdout", "stderr"},
                )
                self.assertTrue(kwargs["text"])
                self.assertFalse(kwargs["check"])
                self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
                self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
                self.assertEqual(arguments, [str(say_path)])
                self.assertNotIn(kwargs["input"], " ".join(arguments))
                calls.append((arguments, kwargs["input"]))
                return subprocess.CompletedProcess(arguments, 0)

            result = run_worker(
                data_dir,
                say_path=say_path,
                run_command=fake_run,
                sleep=lambda _: None,
                clock=lambda: 102.0,
                monotonic=lambda: 10.0,
            )

            self.assertEqual(result, 0)
            self.assertEqual(
                calls,
                [
                    ([str(say_path)], "first"),
                    ([str(say_path)], "$(touch /tmp/pwned)"),
                    ([str(say_path)], "-v Alex PRIVATE"),
                    ([str(say_path)], "third"),
                ],
            )

    def test_fresh_event_is_spoken_across_different_wall_clock_domains(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            say_path = self._fake_executable(Path(temporary))
            with (
                patch("codex_speak.queue.time.time", return_value=10_000.0),
                patch("codex_speak.queue.time.monotonic", return_value=100.0),
            ):
                self.assertTrue(
                    enqueue(
                        data_dir,
                        Announcement("completed", "fresh event"),
                        session_id="session",
                        turn_id="turn",
                        clock_id=CLOCK_A,
                    )
                )

            calls = []

            def fake_run(arguments, **kwargs):
                calls.append((arguments, kwargs["input"]))
                return subprocess.CompletedProcess(arguments, 0)

            with (
                patch("codex_speak.worker.time.time", return_value=10_601.0),
                patch("codex_speak.worker.time.monotonic", return_value=101.0),
            ):
                result = run_worker(
                    data_dir,
                    say_path=say_path,
                    run_command=fake_run,
                    sleep=lambda _: None,
                    clock_id=CLOCK_A,
                )

            self.assertEqual(result, 0)
            self.assertEqual(calls, [([str(say_path)], "fresh event")])

    def test_different_boot_never_speaks_stale_event_with_similar_clock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            say_path = self._fake_executable(Path(temporary))
            self.assertTrue(
                enqueue(
                    data_dir,
                    Announcement("completed", "stale from prior boot"),
                    session_id="session",
                    turn_id="turn",
                    now=100.0,
                    clock_id=CLOCK_A,
                )
            )

            result = run_worker(
                data_dir,
                say_path=say_path,
                run_command=lambda *_args, **_kwargs: self.fail("say was invoked"),
                sleep=lambda _: None,
                clock=lambda: 101.0,
                monotonic=lambda: 10.0,
                clock_id=CLOCK_B,
            )

            self.assertEqual(result, 0)
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])

    def test_event_older_than_five_monotonic_minutes_is_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            say_path = self._fake_executable(Path(temporary))
            enqueue(
                data_dir,
                Announcement("completed", "expired event"),
                session_id="session",
                turn_id="turn",
                now=100.0,
            )

            result = run_worker(
                data_dir,
                say_path=say_path,
                run_command=lambda *_args, **_kwargs: self.fail("say was invoked"),
                sleep=lambda _: None,
                clock=lambda: 400.000001,
                monotonic=lambda: 10.0,
            )

            self.assertEqual(result, 0)
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn('"error_code":"expired"', diagnostics)
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])

    def test_waits_repolls_and_holds_lock_through_sleep_and_speech(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            say_path = self._fake_executable(Path(temporary))
            enqueue(
                data_dir,
                Announcement("completed", "ready after wait"),
                session_id="session",
                turn_id="turn",
                now=100.0,
            )
            current_time = [100.0]
            clock_calls = []
            sleep_calls = []
            run_calls = []

            def assert_worker_lock_held():
                with try_worker_lock(data_dir) as acquired:
                    self.assertFalse(acquired)

            def fake_clock():
                clock_calls.append(current_time[0])
                return current_time[0]

            def fake_sleep(seconds):
                assert_worker_lock_held()
                sleep_calls.append(seconds)
                current_time[0] += seconds

            def fake_run(arguments, **kwargs):
                assert_worker_lock_held()
                run_calls.append((arguments, kwargs["input"]))
                return subprocess.CompletedProcess(arguments, 0)

            result = run_worker(
                data_dir,
                say_path=say_path,
                run_command=fake_run,
                sleep=fake_sleep,
                clock=fake_clock,
                monotonic=lambda: 10.0,
            )

            self.assertEqual(result, 0)
            self.assertEqual(sleep_calls, [1.0])
            self.assertEqual(clock_calls, [100.0, 101.0, 101.0])
            self.assertEqual(
                run_calls,
                [([str(say_path)], "ready after wait")],
            )
            with try_worker_lock(data_dir) as acquired:
                self.assertTrue(acquired)

    def test_failed_say_does_not_block_later_events_or_leak_speech(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            say_path = self._fake_executable(Path(temporary))
            for index, speech in enumerate(("TOP_SECRET_ONE", "TOP_SECRET_TWO")):
                enqueue(
                    data_dir,
                    Announcement("completed", speech),
                    session_id=f"s-{index}",
                    turn_id=f"t-{index}",
                    now=100.0 + index / 10,
                )
            return_codes = iter((1, 0))
            calls = []

            def fake_run(arguments, **kwargs):
                calls.append(arguments)
                return subprocess.CompletedProcess(arguments, next(return_codes))

            result = run_worker(
                data_dir,
                say_path=say_path,
                run_command=fake_run,
                sleep=lambda _: None,
                clock=lambda: 102.0,
                monotonic=lambda: 10.0,
            )

            self.assertEqual(result, 0)
            self.assertEqual(len(calls), 2)
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
            self.assertIn('"error_code":"say_failed"', diagnostics)
            self.assertIn('"result":"spoken"', diagnostics)
            self.assertNotIn("TOP_SECRET_ONE", diagnostics)
            self.assertNotIn("TOP_SECRET_TWO", diagnostics)

    def test_runner_os_error_does_not_block_later_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            say_path = self._fake_executable(Path(temporary))
            for index in range(2):
                enqueue(
                    data_dir,
                    Announcement("blocked", f"message-{index}"),
                    session_id=f"s-{index}",
                    turn_id=f"t-{index}",
                    now=100.0 + index / 10,
                )
            calls = []

            def fake_run(arguments, **kwargs):
                calls.append(arguments)
                if len(calls) == 1:
                    raise OSError("say disappeared")
                return subprocess.CompletedProcess(arguments, 0)

            result = run_worker(
                data_dir,
                say_path=say_path,
                run_command=fake_run,
                sleep=lambda _: None,
                clock=lambda: 102.0,
                monotonic=lambda: 10.0,
            )

            self.assertEqual(result, 0)
            self.assertEqual(len(calls), 2)
            entries = [
                json.loads(line)
                for line in (data_dir / "diagnostics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                [(entry["result"], entry["error_code"]) for entry in entries],
                [("failed", "say_failed"), ("spoken", None)],
            )

    def test_missing_say_discards_event_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            enqueue(
                data_dir,
                Announcement("blocked", "cannot speak"),
                session_id="s",
                turn_id="t",
                now=100.0,
            )

            result = run_worker(
                data_dir,
                say_path=Path(temporary) / "missing-say",
                sleep=lambda _: None,
                clock=lambda: 102.0,
                monotonic=lambda: 10.0,
            )

            self.assertEqual(result, 0)
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
            self.assertIn('"result":"discarded"', diagnostics)
            self.assertIn('"error_code":"say_unavailable"', diagnostics)
            self.assertNotIn("cannot speak", diagnostics)
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])

    def test_non_executable_say_discards_without_calling_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            say_path = Path(temporary) / "say"
            say_path.write_text("not executable", encoding="utf-8")
            say_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            enqueue(
                data_dir,
                Announcement("action_required", "PRIVATE_SPEECH"),
                session_id="s",
                turn_id="t",
                now=100.0,
            )

            result = run_worker(
                data_dir,
                say_path=say_path,
                run_command=lambda *_args, **_kwargs: self.fail("runner was invoked"),
                sleep=lambda _: None,
                clock=lambda: 102.0,
                monotonic=lambda: 10.0,
            )

            self.assertEqual(result, 0)
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
            self.assertIn('"result":"discarded"', diagnostics)
            self.assertIn('"error_code":"say_unavailable"', diagnostics)
            self.assertNotIn("PRIVATE_SPEECH", diagnostics)
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])

    def test_lock_contender_exits_without_polling_or_speaking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            say_path = self._fake_executable(Path(temporary))
            enqueue(
                data_dir,
                Announcement("completed", "keep queued"),
                session_id="s",
                turn_id="t",
                now=100.0,
            )

            @contextmanager
            def unavailable_lock(_data_dir):
                yield False

            with patch("codex_speak.worker.try_worker_lock", unavailable_lock):
                result = run_worker(
                    data_dir,
                    say_path=say_path,
                    run_command=lambda *_args, **_kwargs: self.fail("say was invoked"),
                    clock=lambda: 102.0,
                )

            self.assertEqual(result, 0)
            self.assertEqual(len(list((data_dir / "spool").glob("*.json"))), 1)

    def test_spawn_worker_is_detached_and_uses_module_execution(self) -> None:
        plugin_root = Path("/plugin root")
        data_dir = Path("/plugin data")

        with patch("codex_speak.worker.subprocess.Popen") as popen:
            spawn_worker(plugin_root, data_dir)

        popen.assert_called_once_with(
            [
                ANY,
                "-m",
                "codex_speak.worker",
                "--data-dir",
                str(data_dir),
            ],
            cwd=str(plugin_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )


if __name__ == "__main__":
    unittest.main()
