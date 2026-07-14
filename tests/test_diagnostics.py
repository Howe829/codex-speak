from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from codex_speak.diagnostics import MAX_BYTES, record


class DiagnosticsTests(unittest.TestCase):
    def test_writes_only_fixed_metadata_with_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            record(
                data_dir,
                event_id="a" * 24,
                status="completed",
                result="spoken",
                duration_ms=42,
                now=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
            )
            path = data_dir / "diagnostics.jsonl"
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload,
                {
                    "timestamp": "2026-07-11T12:00:00+00:00",
                    "event_id": "a" * 24,
                    "status": "completed",
                    "result": "spoken",
                    "mode": "unknown",
                    "segment_count": 0,
                    "duration_ms": 42,
                    "error_code": None,
                },
            )
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(data_dir.stat().st_mode), 0o700)

    def test_rejects_invalid_or_sensitive_metadata(self) -> None:
        invalid_cases = (
            ("event_id", "a" * 23),
            ("event_id", "A" * 24),
            ("event_id", "g" * 24),
            ("event_id", "/Users/private/voice.wav"),
            ("status", "user said a secret"),
            ("result", "speech contents"),
            ("mode", "https://private.example/speech"),
            ("error_code", "path:/private/recording.wav"),
            ("error_code", "voice-message.aiff"),
            ("error_code", "RuntimeError: private exception detail"),
        )
        for field, invalid_value in invalid_cases:
            with self.subTest(field=field, invalid_value=invalid_value):
                with tempfile.TemporaryDirectory() as temporary:
                    data_dir = Path(temporary)
                    values = {
                        "event_id": "a" * 24,
                        "status": "completed",
                        "result": "spoken",
                        "mode": "summary",
                        "error_code": None,
                    }
                    values[field] = invalid_value
                    record(data_dir, **values)
                    self.assertFalse((data_dir / "diagnostics.jsonl").exists())

    def test_accepts_expanded_fixed_metadata(self) -> None:
        error_codes = (
            "unsupported_platform",
            "say_unavailable",
            "invalid_hook_input",
            "invalid_marker",
            "queue_corrupt",
            "expired",
            "say_failed",
            "queue_failed",
            "worker_start_failed",
            "invalid_settings",
            "helper_start_failed",
            "invalid_event",
            "stale_event",
            "boot_mismatch",
            "speech_start_failed",
            "cancel_identity_mismatch",
            "queue_clear_failed",
        )
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for index, error_code in enumerate(error_codes):
                record(
                    data_dir,
                    event_id=f"{index:024x}",
                    status="completed",
                    result="cancelled" if index == 0 else "spoken",
                    mode="full" if index % 2 else "summary",
                    segment_count=min(index, 10_000),
                    duration_ms=index,
                    error_code=error_code,
                )
            entries = [
                json.loads(line)
                for line in (data_dir / "diagnostics.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(len(entries), len(error_codes))
            self.assertEqual(entries[0]["result"], "cancelled")
            self.assertEqual(entries[0]["mode"], "summary")
            self.assertEqual(entries[-1]["error_code"], "queue_clear_failed")
            self.assertEqual(
                set(entries[0]),
                {
                    "timestamp",
                    "event_id",
                    "status",
                    "result",
                    "mode",
                    "segment_count",
                    "duration_ms",
                    "error_code",
                },
            )

    def test_rejects_invalid_mode_and_segment_count(self) -> None:
        invalid_cases = (
            {"mode": True},
            {"mode": "private speech"},
            {"segment_count": True},
            {"segment_count": -1},
            {"segment_count": 10_001},
            {"segment_count": 1.0},
            {"segment_count": "1"},
        )
        for invalid_values in invalid_cases:
            with self.subTest(invalid_values=invalid_values):
                with tempfile.TemporaryDirectory() as temporary:
                    data_dir = Path(temporary)
                    values = {
                        "event_id": "a" * 24,
                        "status": "completed",
                        "result": "spoken",
                        "mode": "summary",
                        "segment_count": 1,
                    }
                    values.update(invalid_values)
                    record(data_dir, **values)
                    self.assertFalse((data_dir / "diagnostics.jsonl").exists())

    def test_segment_count_boundaries_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for index, segment_count in enumerate((0, 10_000)):
                record(
                    data_dir,
                    event_id=f"{index:024x}",
                    status="completed",
                    result="spoken",
                    mode="unknown",
                    segment_count=segment_count,
                )
            entries = [
                json.loads(line)
                for line in (data_dir / "diagnostics.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(
                [entry["segment_count"] for entry in entries],
                [0, 10_000],
            )

    def test_cli_records_metadata_and_prints_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            completed = self._run_cli(
                data_dir,
                "record",
                "--event-id",
                "a" * 24,
                "--status",
                "completed",
                "--mode",
                "summary",
                "--result",
                "spoken",
                "--segment-count",
                "1",
                "--duration-ms",
                "25",
                "--error-code",
                "NONE",
            )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout, "")
            self.assertEqual(completed.stderr, "")
            payload = json.loads(
                (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["error_code"], None)
            self.assertEqual(payload["segment_count"], 1)

    def test_cli_rejects_sensitive_values_without_echoing_them(self) -> None:
        sensitive_values = (
            "secret speech content",
            "https://private.example/audio",
            "/Users/private/audio.wav",
            "private-recording.aiff",
            "RuntimeError: secret exception",
        )
        for sensitive_value in sensitive_values:
            with self.subTest(sensitive_value=sensitive_value):
                with tempfile.TemporaryDirectory() as temporary:
                    data_dir = Path(temporary)
                    completed = self._run_cli(
                        data_dir,
                        "record",
                        "--event-id",
                        "a" * 24,
                        "--status",
                        "completed",
                        "--mode",
                        "summary",
                        "--result",
                        "spoken",
                        "--segment-count",
                        "1",
                        "--duration-ms",
                        "25",
                        "--error-code",
                        sensitive_value,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertNotIn(sensitive_value, completed.stdout)
                    self.assertNotIn(sensitive_value, completed.stderr)
                    self.assertFalse(
                        (data_dir / "diagnostics.jsonl").exists()
                    )

    @staticmethod
    def _run_cli(
        data_dir: Path,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).parents[1])
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "codex_speak.diagnostics",
                "--data-dir",
                str(data_dir),
                *arguments,
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )

    def test_invalid_or_overflowing_duration_is_ignored(self) -> None:
        for invalid_duration in (True, -1, 1.5, "42", float("inf")):
            with self.subTest(invalid_duration=invalid_duration):
                with tempfile.TemporaryDirectory() as temporary:
                    data_dir = Path(temporary)
                    record(
                        data_dir,
                        event_id="a" * 24,
                        status="completed",
                        result="spoken",
                        duration_ms=invalid_duration,
                    )
                    self.assertFalse((data_dir / "diagnostics.jsonl").exists())

    def test_invalid_runtime_argument_types_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            invalid_cases = (
                ("not-a-path", None),
                (Path(temporary), object()),
            )
            for data_dir, now in invalid_cases:
                with self.subTest(data_dir=data_dir, now=now):
                    record(
                        data_dir,
                        event_id="a" * 24,
                        status="completed",
                        result="spoken",
                        now=now,
                    )

    def test_prewrite_threshold_keeps_active_file_at_or_below_256_kib(self) -> None:
        now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
        entry = {
            "timestamp": now.isoformat(),
            "event_id": "b" * 24,
            "status": "blocked",
            "result": "failed",
            "mode": "unknown",
            "segment_count": 0,
            "duration_ms": 0,
            "error_code": "say_failed",
        }
        encoded_line = (
            json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")

        for excess, should_rotate in ((0, False), (1, True)):
            with self.subTest(excess=excess):
                with tempfile.TemporaryDirectory() as temporary:
                    data_dir = Path(temporary)
                    current = data_dir / "diagnostics.jsonl"
                    backup = data_dir / "diagnostics.jsonl.1"
                    old_current = b"x" * (MAX_BYTES - len(encoded_line) + excess)
                    current.write_bytes(old_current)
                    current.chmod(0o644)
                    backup.write_bytes(b"old-backup")
                    backup.chmod(0o644)

                    record(
                        data_dir,
                        event_id="b" * 24,
                        status="blocked",
                        result="failed",
                        error_code="say_failed",
                        now=now,
                    )

                    if should_rotate:
                        self.assertEqual(backup.read_bytes(), old_current)
                        self.assertEqual(current.read_bytes(), encoded_line)
                    else:
                        self.assertEqual(current.read_bytes(), old_current + encoded_line)
                        self.assertEqual(backup.read_bytes(), b"old-backup")
                    self.assertLessEqual(current.stat().st_size, MAX_BYTES)
                    self.assertEqual(stat.S_IMODE(current.stat().st_mode), 0o600)
                    self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
                    self.assertEqual(stat.S_IMODE(data_dir.stat().st_mode), 0o700)

    def test_drops_a_record_larger_than_the_cap_before_rotating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            current = data_dir / "diagnostics.jsonl"
            current.write_bytes(b"keep-current")
            with patch("codex_speak.diagnostics.MAX_BYTES", 1):
                record(
                    data_dir,
                    event_id="b" * 24,
                    status="blocked",
                    result="failed",
                    error_code="say_failed",
                )
            self.assertEqual(current.read_bytes(), b"keep-current")
            self.assertFalse((data_dir / "diagnostics.jsonl.1").exists())

    def test_existing_active_file_is_private_before_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            current = data_dir / "diagnostics.jsonl"
            current.write_bytes(b"x" * 400)
            current.chmod(0o644)
            events = []
            original_chmod = os.chmod
            original_replace = os.replace

            def tracked_chmod(path, mode):
                events.append(("chmod", Path(path).name, mode))
                return original_chmod(path, mode)

            def tracked_replace(source, destination):
                events.append(("replace", Path(source).name, Path(destination).name))
                return original_replace(source, destination)

            with (
                patch("codex_speak.diagnostics.MAX_BYTES", 512),
                patch("codex_speak.diagnostics.os.chmod", side_effect=tracked_chmod),
                patch("codex_speak.diagnostics.os.replace", side_effect=tracked_replace),
            ):
                record(
                    data_dir,
                    event_id="d" * 24,
                    status="blocked",
                    result="failed",
                    error_code="say_failed",
                )

            private_active = ("chmod", "diagnostics.jsonl", 0o600)
            rename = ("replace", "diagnostics.jsonl", "diagnostics.jsonl.1")
            self.assertLess(events.index(private_active), events.index(rename))
            backup = data_dir / "diagnostics.jsonl.1"
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_fchmod_happens_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            events = []
            handle = MagicMock()
            handle.__enter__.return_value = handle
            handle.write.side_effect = lambda _line: events.append("write")
            with (
                patch("codex_speak.diagnostics.os.open", return_value=71),
                patch(
                    "codex_speak.diagnostics.os.fchmod",
                    side_effect=lambda _descriptor, _mode: events.append("fchmod"),
                ),
                patch("codex_speak.diagnostics.os.fdopen", return_value=handle),
            ):
                record(
                    Path(temporary),
                    event_id="e" * 24,
                    status="completed",
                    result="spoken",
                )
            self.assertEqual(events, ["fchmod", "write"])

    def test_fchmod_failure_is_ignored_and_descriptor_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            handle = MagicMock()
            handle.__enter__.return_value = handle
            with (
                patch("codex_speak.diagnostics.os.open", return_value=72),
                patch(
                    "codex_speak.diagnostics.os.fchmod",
                    side_effect=OSError("denied"),
                ) as fchmod,
                patch("codex_speak.diagnostics.os.fdopen", return_value=handle),
                patch("codex_speak.diagnostics.os.close") as close,
            ):
                record(
                    Path(temporary),
                    event_id="e" * 24,
                    status="completed",
                    result="spoken",
                )
            fchmod.assert_called_once_with(72, 0o600)
            close.assert_called_once_with(72)
            handle.write.assert_not_called()

    def test_write_failure_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            handle = MagicMock()
            handle.__enter__.return_value = handle
            handle.write.side_effect = OSError("denied")
            with (
                patch("codex_speak.diagnostics.os.open", return_value=73),
                patch("codex_speak.diagnostics.os.fchmod") as fchmod,
                patch("codex_speak.diagnostics.os.fdopen", return_value=handle),
            ):
                record(
                    Path(temporary),
                    event_id="f" * 24,
                    status="completed",
                    result="spoken",
                )
            fchmod.assert_called_once_with(73, 0o600)
            handle.write.assert_called_once()

    def test_logging_failure_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch("codex_speak.diagnostics.os.open", side_effect=OSError("denied")):
                record(
                    Path(temporary),
                    event_id="c" * 24,
                    status="unknown",
                    result="failed",
                    error_code="say_failed",
                )


if __name__ == "__main__":
    unittest.main()
