from collections import Counter
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

import codex_speak.queue as queue_module
from codex_speak.queue import (
    clear_pending,
    enqueue,
    make_event_id,
    poll_next,
    try_worker_lock,
)
from codex_speak.render import SpeechPayload


CLOCK_A = "11111111-1111-1111-1111-111111111111"
CLOCK_B = "22222222-2222-2222-2222-222222222222"


def summary_payload(status: str, text: str) -> SpeechPayload:
    return SpeechPayload("summary", status, (text,))


def _enqueue_in_process(data_dir: str, index: int, results) -> None:
    queued = enqueue(
        Path(data_dir),
        summary_payload("completed", f"event-{index}"),
        session_id=f"session-{index}",
        turn_id=f"turn-{index}",
    )
    results.put((index, queued))


def _try_lock_in_process(data_dir: str, connection) -> None:
    with try_worker_lock(Path(data_dir)) as acquired:
        connection.send(acquired)
    connection.close()


def _enqueue_after_ready(data_dir: str, connection) -> None:
    real_flock = fcntl.flock

    def tracked_flock(descriptor, operation):
        if operation == fcntl.LOCK_EX:
            connection.send("attempting")
            result = real_flock(descriptor, operation)
            connection.send("acquired")
            return result
        return real_flock(descriptor, operation)

    with patch("codex_speak.queue.fcntl.flock", side_effect=tracked_flock):
        queued = enqueue(
            Path(data_dir),
            summary_payload("completed", "delayed"),
            session_id="delayed-session",
            turn_id="delayed-turn",
        )
    connection.send(queued)
    connection.close()


def _poll_after_ready(data_dir: str, connection) -> None:
    real_flock = fcntl.flock

    def tracked_flock(descriptor, operation):
        if operation == fcntl.LOCK_EX:
            connection.send("attempting")
            result = real_flock(descriptor, operation)
            connection.send("acquired")
            return result
        return real_flock(descriptor, operation)

    with patch("codex_speak.queue.fcntl.flock", side_effect=tracked_flock):
        result = poll_next(Path(data_dir))
    connection.send(
        (
            result.event.speech_text if result.event is not None else None,
            result.wait_seconds,
        )
    )
    connection.close()


class QueueTests(unittest.TestCase):
    def test_float_v3_format_version_is_deleted_without_playback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            event_id = make_event_id("session", "turn")
            spool = data_dir / "spool"
            spool.mkdir(mode=0o700)
            path = spool / f"00000000000000000001-{event_id}.json"
            path.write_text(
                json.dumps(
                    {
                        "format_version": 3.0,
                        "clock_id": CLOCK_A,
                        "event_id": event_id,
                        "session_key": queue_module._session_key("session"),
                        "mode": "full",
                        "status": "silent",
                        "segments": ["must not play"],
                        "created_at": 100.0,
                        "not_before": 101.0,
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o600)

            result = poll_next(data_dir, now=101.0, clock_id=CLOCK_A)

            self.assertIsNone(result.event)
            self.assertFalse(path.exists())

    def test_float_v3_dedupe_envelope_is_not_accepted_as_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            data_dir.mkdir(mode=0o700, exist_ok=True)
            event_id = make_event_id("session", "turn")
            dedupe_path = data_dir / "dedupe.json"
            dedupe_path.write_text(
                json.dumps(
                    {
                        "format_version": 3.0,
                        "clock_id": CLOCK_A,
                        "entries": {event_id: 100.0},
                    }
                ),
                encoding="utf-8",
            )
            dedupe_path.chmod(0o600)

            self.assertTrue(
                enqueue(
                    data_dir,
                    SpeechPayload("full", "silent", ("play once",)),
                    session_id="session",
                    turn_id="turn",
                    now=100.5,
                    clock_id=CLOCK_A,
                )
            )
            rewritten = json.loads(dedupe_path.read_text(encoding="utf-8"))
            self.assertIs(type(rewritten["format_version"]), int)
            self.assertEqual(rewritten["format_version"], 3)

    def test_v3_event_preserves_full_payload_segments_and_silent_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self.assertTrue(
                enqueue(
                    data_dir,
                    SpeechPayload("full", "silent", ("第一段", "第二段")),
                    session_id="session",
                    turn_id="turn",
                    now=100.0,
                    clock_id=CLOCK_A,
                )
            )

            event = poll_next(
                data_dir, now=101.0, clock_id=CLOCK_A
            ).event

            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event.format_version, 3)
            self.assertEqual(event.mode, "full")
            self.assertEqual(event.status, "silent")
            self.assertEqual(event.segments, ("第一段", "第二段"))

    def test_invalid_v3_and_legacy_events_are_deleted_without_playback(self) -> None:
        event_id = make_event_id("session", "turn")
        valid = {
            "format_version": 3,
            "clock_id": CLOCK_A,
            "event_id": event_id,
            "session_key": queue_module._session_key("session"),
            "mode": "full",
            "status": "silent",
            "segments": ["valid"],
            "created_at": 100.0,
            "not_before": 101.0,
        }
        invalid_events = {
            "empty segments": {**valid, "segments": []},
            "empty segment": {**valid, "segments": [""]},
            "oversized segment": {**valid, "segments": ["x" * 601]},
            "too many segments": {**valid, "segments": ["x"] * 10_001},
            "unknown mode": {**valid, "mode": "verbose"},
            "unknown status": {**valid, "status": "private"},
            "summary silent": {**valid, "mode": "summary"},
            "extra field": {**valid, "extra": "private"},
            "v2 event": {
                "format_version": 2,
                "clock_id": CLOCK_A,
                "event_id": event_id,
                "session_key": queue_module._session_key("session"),
                "status": "completed",
                "speech_text": "legacy",
                "created_at": 100.0,
                "not_before": 101.0,
            },
            "v1 event": {
                "event_id": event_id,
                "session_key": queue_module._session_key("session"),
                "status": "completed",
                "speech_text": "legacy",
                "created_at": 100.0,
                "not_before": 101.0,
            },
        }
        for name, raw in invalid_events.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                data_dir = Path(temporary)
                spool = data_dir / "spool"
                spool.mkdir(mode=0o700)
                path = spool / f"00000000000000000001-{event_id}.json"
                path.write_text(json.dumps(raw), encoding="utf-8")
                path.chmod(0o600)

                result = poll_next(data_dir, now=101.0, clock_id=CLOCK_A)

                self.assertIsNone(result.event)
                self.assertFalse(path.exists())

    def test_enqueue_rejects_invalid_segmented_payloads(self) -> None:
        invalid_payloads = (
            SpeechPayload("summary", "silent", ("text",)),
            SpeechPayload("unknown", "completed", ("text",)),
            SpeechPayload("full", "silent", ()),
            SpeechPayload("full", "silent", ("x" * 601,)),
            SpeechPayload("full", "silent", ("x",) * 10_001),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(ValueError, "invalid speech payload"):
                    enqueue(
                        Path(temporary),
                        payload,
                        session_id="session",
                        turn_id="turn",
                        now=100.0,
                        clock_id=CLOCK_A,
                    )

    def test_two_full_events_in_one_session_are_played_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for turn_id, text, now in (
                ("turn-1", "first", 100.0),
                ("turn-2", "second", 100.5),
            ):
                self.assertTrue(
                    enqueue(
                        data_dir,
                        SpeechPayload("full", "silent", (text,)),
                        session_id="same-session",
                        turn_id=turn_id,
                        now=now,
                        clock_id=CLOCK_A,
                    )
                )

            self.assertEqual(len(list((data_dir / "spool").glob("*.json"))), 2)
            spoken = []
            while True:
                event = poll_next(
                    data_dir, now=101.5, clock_id=CLOCK_A
                ).event
                if event is None:
                    break
                spoken.extend(event.segments)
            self.assertEqual(spoken, ["first", "second"])

    def test_clear_pending_removes_all_events_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for index in range(2):
                self.assertTrue(
                    enqueue(
                        data_dir,
                        SpeechPayload("full", "silent", (f"event-{index}",)),
                        session_id=f"session-{index}",
                        turn_id=f"turn-{index}",
                        now=100.0,
                        clock_id=CLOCK_A,
                    )
                )

            self.assertEqual(clear_pending(data_dir), 2)
            self.assertEqual(clear_pending(data_dir), 0)

    def test_clear_pending_cli_prints_only_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = StringIO()
            with redirect_stdout(output):
                result = queue_module.main(
                    ["--data-dir", temporary, "clear-pending"]
                )
            self.assertEqual(result, 0)
            self.assertEqual(output.getvalue(), "0\n")

    def test_default_clock_id_prefers_boot_file_normalizes_and_caches(self) -> None:
        queue_module._default_clock_id.cache_clear()
        try:
            with (
                patch.object(
                    Path,
                    "read_text",
                    return_value=CLOCK_A.upper(),
                ) as read_text,
                patch("codex_speak.queue.subprocess.run") as run,
            ):
                self.assertEqual(queue_module._default_clock_id(), CLOCK_A)
                self.assertEqual(queue_module._default_clock_id(), CLOCK_A)

            read_text.assert_called_once_with(encoding="ascii")
            run.assert_not_called()
        finally:
            queue_module._default_clock_id.cache_clear()

    def test_default_clock_id_uses_strict_sysctl_fallback_and_fails_safe(
        self,
    ) -> None:
        cases = (
            (CLOCK_B.upper() + "\n", CLOCK_B),
            ("not-a-boot-uuid\n", None),
        )
        for stdout, expected in cases:
            with self.subTest(stdout=stdout):
                queue_module._default_clock_id.cache_clear()
                try:
                    with (
                        patch.object(Path, "read_text", side_effect=OSError("missing")),
                        patch(
                            "codex_speak.queue.subprocess.run",
                            return_value=Mock(stdout=stdout),
                        ) as run,
                    ):
                        self.assertEqual(queue_module._default_clock_id(), expected)
                    self.assertEqual(
                        run.call_args.args[0],
                        ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"],
                    )
                finally:
                    queue_module._default_clock_id.cache_clear()

    def test_event_id_is_stable_lowercase_24_hex(self) -> None:
        event_id = make_event_id("session", "turn")
        self.assertEqual(event_id, make_event_id("session", "turn"))
        self.assertRegex(event_id, r"\A[0-9a-f]{24}\Z")
        self.assertNotEqual(event_id, make_event_id("session", "other-turn"))
        self.assertNotEqual(
            make_event_id("a\0b", "c"),
            make_event_id("a", "b\0c"),
        )

    def test_private_event_waits_one_second_then_is_removed_on_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            queued = enqueue(
                data_dir,
                summary_payload("completed", "任务完成"),
                session_id="session",
                turn_id="turn",
                now=100.0,
            )
            self.assertTrue(queued)
            spool = data_dir / "spool"
            events = list(spool.glob("*.json"))
            self.assertEqual(len(events), 1)
            self.assertEqual(stat.S_IMODE(data_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(spool.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(events[0].stat().st_mode), 0o600)
            for private_file in ("queue.lock", "sequence.json", "dedupe.json"):
                self.assertEqual(
                    stat.S_IMODE((data_dir / private_file).stat().st_mode),
                    0o600,
                )

            waiting = poll_next(data_dir, now=100.5)
            self.assertIsNone(waiting.event)
            self.assertAlmostEqual(waiting.wait_seconds or 0.0, 0.5, places=3)

            ready = poll_next(data_dir, now=101.0)
            self.assertEqual(ready.event.speech_text if ready.event else None, "任务完成")
            self.assertEqual(list(spool.glob("*.json")), [])

    def test_default_relative_timing_uses_monotonic_not_wall_clock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            announcement = summary_payload("completed", "monotonic event")
            with (
                patch(
                    "codex_speak.queue.time.time",
                    side_effect=AssertionError("relative timing used wall clock"),
                ),
                patch(
                    "codex_speak.queue.time.monotonic",
                    side_effect=(100.0, 101.0),
                ),
            ):
                self.assertTrue(
                    enqueue(
                        data_dir,
                        announcement,
                        session_id="session",
                        turn_id="turn",
                    )
                )
                result = poll_next(data_dir)

            self.assertEqual(
                result.event.speech_text if result.event else None,
                "monotonic event",
            )

    def test_duplicate_event_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            announcement = summary_payload("completed", "once")
            self.assertTrue(
                enqueue(data_dir, announcement, session_id="s", turn_id="t", now=100.0)
            )
            self.assertFalse(
                enqueue(data_dir, announcement, session_id="s", turn_id="t", now=100.1)
            )

    def test_v2_dedupe_envelope_migrates_without_replaying_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            data_dir.chmod(0o700)
            event_id = make_event_id("session", "turn")
            dedupe_path = data_dir / "dedupe.json"
            dedupe_path.write_text(
                json.dumps(
                    {
                        "format_version": 2,
                        "clock_id": CLOCK_A,
                        "entries": {event_id: 99.0},
                    }
                ),
                encoding="utf-8",
            )
            dedupe_path.chmod(0o600)

            self.assertFalse(
                enqueue(
                    data_dir,
                    SpeechPayload("full", "silent", ("duplicate",)),
                    session_id="session",
                    turn_id="turn",
                    now=100.0,
                    clock_id=CLOCK_A,
                )
            )
            migrated = json.loads(dedupe_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["format_version"], 3)
            self.assertEqual(migrated["entries"], {event_id: 99.0})

    def test_different_boot_discards_spool_but_preserves_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            announcement = summary_payload("completed", "stale speech")
            self.assertTrue(
                enqueue(
                    data_dir,
                    announcement,
                    session_id="session",
                    turn_id="turn",
                    now=100.0,
                    clock_id=CLOCK_A,
                )
            )

            self.assertFalse(
                enqueue(
                    data_dir,
                    announcement,
                    session_id="session",
                    turn_id="turn",
                    now=100.5,
                    clock_id=CLOCK_B,
                )
            )
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])
            dedupe = json.loads(
                (data_dir / "dedupe.json").read_text(encoding="utf-8")
            )
            event_id = make_event_id("session", "turn")
            self.assertEqual(dedupe["format_version"], 3)
            self.assertEqual(dedupe["clock_id"], CLOCK_B)
            self.assertEqual(dedupe["entries"], {event_id: 100.5})

    def test_v1_wall_clock_spool_and_dedupe_migrate_without_speech(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            spool = data_dir / "spool"
            spool.mkdir(parents=True, mode=0o700)
            event_id = make_event_id("legacy-session", "legacy-turn")
            legacy_event = spool / f"00000000000000000001-{event_id}.json"
            legacy_event.write_text(
                json.dumps(
                    {
                        "event_id": event_id,
                        "session_key": queue_module._session_key("legacy-session"),
                        "status": "completed",
                        "speech_text": "legacy private speech",
                        "created_at": 1_783_902_023.0,
                        "not_before": 1_783_902_024.0,
                    }
                ),
                encoding="utf-8",
            )
            legacy_event.chmod(0o600)
            (data_dir / "dedupe.json").write_text(
                json.dumps({event_id: 1_783_902_023.0, "invalid": "value"}),
                encoding="utf-8",
            )

            result = poll_next(data_dir, now=200.0, clock_id=CLOCK_B)

            self.assertIsNone(result.event)
            self.assertFalse(legacy_event.exists())
            dedupe = json.loads(
                (data_dir / "dedupe.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                dedupe,
                {
                    "format_version": 3,
                    "clock_id": CLOCK_B,
                    "entries": {event_id: 200.0},
                },
            )
            self.assertFalse(
                enqueue(
                    data_dir,
                    summary_payload("completed", "duplicate"),
                    session_id="legacy-session",
                    turn_id="legacy-turn",
                    now=200.1,
                    clock_id=CLOCK_B,
                )
            )

    def test_boot_mismatch_cleanup_keeps_new_event_sequence_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for index in range(2):
                self.assertTrue(
                    enqueue(
                        data_dir,
                        summary_payload("completed", f"stale-{index}"),
                        session_id=f"stale-session-{index}",
                        turn_id=f"stale-turn-{index}",
                        now=100.0 + index / 10,
                        clock_id=CLOCK_A,
                    )
                )
            previous_sequence = json.loads(
                (data_dir / "sequence.json").read_text(encoding="utf-8")
            )

            self.assertIsNone(
                poll_next(data_dir, now=100.2, clock_id=CLOCK_B).event
            )
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
            self.assertEqual(diagnostics.count('"error_code":"boot_mismatch"'), 2)
            self.assertNotIn("stale-0", diagnostics)
            self.assertNotIn("stale-1", diagnostics)
            for index in range(2):
                self.assertTrue(
                    enqueue(
                        data_dir,
                        summary_payload("completed", f"fresh-{index}"),
                        session_id=f"fresh-session-{index}",
                        turn_id=f"fresh-turn-{index}",
                        now=100.2 + index / 10,
                        clock_id=CLOCK_B,
                    )
                )
            current_sequences = sorted(
                int(path.name.split("-", 1)[0])
                for path in (data_dir / "spool").glob("*.json")
            )
            self.assertEqual(len(current_sequences), 2)
            self.assertGreater(current_sequences[0], previous_sequence)

            spoken = []
            while True:
                result = poll_next(data_dir, now=101.3, clock_id=CLOCK_B)
                if result.event is None:
                    break
                spoken.append(result.event.speech_text)
            self.assertEqual(spoken, ["fresh-0", "fresh-1"])

    def test_unavailable_default_clock_discards_spool_without_speaking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self.assertTrue(
                enqueue(
                    data_dir,
                    summary_payload("completed", "do not speak"),
                    session_id="session",
                    turn_id="turn",
                    now=100.0,
                    clock_id=CLOCK_A,
                )
            )

            with patch("codex_speak.queue._default_clock_id", return_value=None):
                result = poll_next(data_dir, now=101.0)

            self.assertIsNone(result.event)
            self.assertEqual(list((data_dir / "spool").glob("*.json")), [])

    def test_invalid_and_future_dedupe_entries_cannot_evict_current_duplicate(
        self,
    ) -> None:
        session_id = "current-session"
        turn_id = "current-turn"
        current_id = make_event_id(session_id, turn_id)
        cases = {
            "future": (
                (
                    f"{index:024x}"
                    for index in range(1024)
                    if f"{index:024x}" != current_id
                ),
                101.0,
            ),
            "invalid-key": ((f"invalid-{index}" for index in range(512)), 100.0),
        }
        for name, (keys, timestamp) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                data_dir = Path(temporary)
                data_dir.chmod(0o700)
                crowders = {}
                for key in keys:
                    crowders[key] = timestamp
                    if len(crowders) == queue_module.DEDUPE_LIMIT:
                        break
                dedupe = data_dir / "dedupe.json"
                dedupe.write_text(
                    json.dumps(
                        {
                            "format_version": 3,
                            "clock_id": CLOCK_A,
                            "entries": {**crowders, current_id: 99.0},
                        }
                    ),
                    encoding="utf-8",
                )
                dedupe.chmod(0o600)

                self.assertFalse(
                    enqueue(
                        data_dir,
                        summary_payload("completed", "duplicate"),
                        session_id=session_id,
                        turn_id=turn_id,
                        now=100.0,
                        clock_id=CLOCK_A,
                    )
                )
                self.assertEqual(list((data_dir / "spool").glob("*.json")), [])

    def test_existing_queue_files_are_made_private_before_duplicate_early_return(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            announcement = summary_payload("completed", "once")
            self.assertTrue(
                enqueue(data_dir, announcement, session_id="s", turn_id="t", now=100.0)
            )
            with try_worker_lock(data_dir) as acquired:
                self.assertTrue(acquired)
            private_paths = [
                data_dir / "queue.lock",
                data_dir / "worker.lock",
                data_dir / "sequence.json",
                data_dir / "dedupe.json",
                next((data_dir / "spool").glob("*.json")),
            ]
            for path in private_paths:
                path.chmod(0o644)

            self.assertFalse(
                enqueue(data_dir, announcement, session_id="s", turn_id="t", now=100.1)
            )
            for path in private_paths:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_new_same_session_event_supersedes_pending_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            enqueue(
                data_dir,
                SpeechPayload("summary", "completed", ("old",)),
                session_id="same-session",
                turn_id="turn-1",
                now=100.0,
            )
            enqueue(
                data_dir,
                SpeechPayload("summary", "action_required", ("new",)),
                session_id="same-session",
                turn_id="turn-2",
                now=100.5,
            )
            self.assertEqual(len(list((data_dir / "spool").glob("*.json"))), 1)
            result = poll_next(data_dir, now=101.5)
            self.assertEqual(result.event.speech_text if result.event else None, "new")

    def test_replacement_event_write_failure_leaves_old_event_playable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self.assertTrue(
                enqueue(
                    data_dir,
                    summary_payload("completed", "old"),
                    session_id="same-session",
                    turn_id="turn-1",
                    now=100.0,
                )
            )
            original_atomic_write = queue_module._atomic_write_json

            def fail_replacement_event(path, value):
                if path.parent.name == "spool":
                    raise OSError("event write failed")
                return original_atomic_write(path, value)

            with (
                patch(
                    "codex_speak.queue._atomic_write_json",
                    side_effect=fail_replacement_event,
                ),
                self.assertRaisesRegex(OSError, "event write failed"),
            ):
                enqueue(
                    data_dir,
                    summary_payload("action_required", "new"),
                    session_id="same-session",
                    turn_id="turn-2",
                    now=100.5,
                )

            result = poll_next(data_dir, now=101.0)
            self.assertEqual(result.event.speech_text if result.event else None, "old")

    def test_dedupe_write_failure_is_recoverable_without_duplicate_speech(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self.assertTrue(
                enqueue(
                    data_dir,
                    summary_payload("completed", "old"),
                    session_id="same-session",
                    turn_id="turn-1",
                    now=100.0,
                )
            )
            replacement_id = make_event_id("same-session", "turn-2")
            original_atomic_write = queue_module._atomic_write_json

            def fail_replacement_dedupe(path, value):
                if (
                    path.name == "dedupe.json"
                    and replacement_id in value.get("entries", {})
                ):
                    raise OSError("dedupe write failed")
                return original_atomic_write(path, value)

            with (
                patch(
                    "codex_speak.queue._atomic_write_json",
                    side_effect=fail_replacement_dedupe,
                ),
                self.assertRaisesRegex(OSError, "dedupe write failed"),
            ):
                enqueue(
                    data_dir,
                    summary_payload("action_required", "new"),
                    session_id="same-session",
                    turn_id="turn-2",
                    now=100.5,
                )

            self.assertFalse(
                enqueue(
                    data_dir,
                    summary_payload("action_required", "new"),
                    session_id="same-session",
                    turn_id="turn-2",
                    now=100.6,
                )
            )
            spoken = []
            while True:
                result = poll_next(data_dir, now=102.0)
                if result.event is None:
                    break
                spoken.append(result.event.speech_text)
            self.assertEqual(spoken, ["new"])
            self.assertFalse(
                enqueue(
                    data_dir,
                    summary_payload("action_required", "new"),
                    session_id="same-session",
                    turn_id="turn-2",
                    now=102.1,
                )
            )

    def test_poll_reconciles_crash_event_before_claim_and_retries_write_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            original_atomic_write = queue_module._atomic_write_json

            def fail_dedupe(path, value):
                if path.name == "dedupe.json":
                    raise OSError("dedupe write failed")
                return original_atomic_write(path, value)

            with (
                patch(
                    "codex_speak.queue._atomic_write_json",
                    side_effect=fail_dedupe,
                ),
                self.assertRaisesRegex(OSError, "dedupe write failed"),
            ):
                enqueue(
                    data_dir,
                    summary_payload("completed", "crash-event"),
                    session_id="crash-session",
                    turn_id="crash-turn",
                    now=100.0,
                )
            event_path = next((data_dir / "spool").glob("*.json"))

            with (
                patch(
                    "codex_speak.queue._atomic_write_json",
                    side_effect=fail_dedupe,
                ),
                self.assertRaisesRegex(OSError, "dedupe write failed"),
            ):
                poll_next(data_dir, now=101.0)
            self.assertTrue(event_path.exists())

            first = poll_next(data_dir, now=101.0)
            second = poll_next(data_dir, now=101.0)
            self.assertEqual(
                first.event.speech_text if first.event else None,
                "crash-event",
            )
            self.assertIsNone(second.event)
            self.assertFalse(
                enqueue(
                    data_dir,
                    summary_payload("completed", "crash-event"),
                    session_id="crash-session",
                    turn_id="crash-turn",
                    now=101.1,
                )
            )

    def test_poll_recovers_crash_state_by_speaking_only_newest_pending_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self.assertTrue(
                enqueue(
                    data_dir,
                    summary_payload("completed", "old"),
                    session_id="same-session",
                    turn_id="turn-1",
                    now=100.0,
                )
            )
            spool = data_dir / "spool"
            old_path = next(spool.glob("*.json"))
            old_payload = json.loads(old_path.read_text(encoding="utf-8"))
            new_id = make_event_id("same-session", "turn-2")
            sequence = int(old_path.name.split("-", 1)[0]) + 1
            new_path = spool / f"{sequence:020d}-{new_id}.json"
            new_path.write_text(
                json.dumps(
                    {
                        **old_payload,
                        "event_id": new_id,
                        "status": "action_required",
                        "segments": ["new"],
                        "created_at": 100.5,
                        "not_before": 101.5,
                    }
                ),
                encoding="utf-8",
            )
            new_path.chmod(0o600)

            spoken = []
            while True:
                result = poll_next(data_dir, now=102.0)
                if result.event is None:
                    break
                spoken.append(result.event.speech_text)
            self.assertEqual(spoken, ["new"])

    def test_crash_supersession_uses_sequence_when_wall_clock_moves_backward(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self.assertTrue(
                enqueue(
                    data_dir,
                    summary_payload("completed", "old"),
                    session_id="same-session",
                    turn_id="turn-1",
                    now=100.0,
                )
            )
            spool = data_dir / "spool"
            old_path = next(spool.glob("*.json"))
            old_payload = json.loads(old_path.read_text(encoding="utf-8"))
            later_id = make_event_id("same-session", "turn-2")
            later_sequence = int(old_path.name.split("-", 1)[0]) + 1
            later_path = spool / f"{later_sequence:020d}-{later_id}.json"
            later_path.write_text(
                json.dumps(
                    {
                        **old_payload,
                        "event_id": later_id,
                        "status": "action_required",
                        "segments": ["later-sequence"],
                        "created_at": 99.5,
                        "not_before": 100.5,
                    }
                ),
                encoding="utf-8",
            )
            later_path.chmod(0o600)

            spoken = []
            while True:
                result = poll_next(data_dir, now=101.5)
                if result.event is None:
                    break
                spoken.append(result.event.speech_text)
            self.assertEqual(spoken, ["later-sequence"])

    def test_fifo_order_for_distinct_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for index in range(3):
                enqueue(
                    data_dir,
                    summary_payload("completed", str(index)),
                    session_id=f"session-{index}",
                    turn_id=f"turn-{index}",
                    now=100.0 + index / 10,
                )
            spoken = []
            while True:
                result = poll_next(data_dir, now=102.0)
                if result.event is None:
                    break
                spoken.append(result.event.speech_text)
            self.assertEqual(spoken, ["0", "1", "2"])

    def test_expired_and_corrupt_events_are_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            enqueue(
                data_dir,
                summary_payload("blocked", "PRIVATE_STALE_SPEECH_91827"),
                session_id="stale-session",
                turn_id="stale-turn",
                now=100.0,
            )
            expired = poll_next(data_dir, now=401.0)
            self.assertIsNone(expired.event)

            corrupt = data_dir / "spool" / "99999999999999999999-corrupt.json"
            corrupt.write_text("not json", encoding="utf-8")
            os.chmod(corrupt, 0o600)
            result = poll_next(data_dir, now=402.0)
            self.assertIsNone(result.event)
            self.assertFalse(corrupt.exists())
            diagnostics = (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
            self.assertIn('"status":"blocked"', diagnostics)
            self.assertIn('"status":"unknown"', diagnostics)
            self.assertIn('"result":"discarded"', diagnostics)
            self.assertIn('"error_code":"stale_event"', diagnostics)
            self.assertIn('"error_code":"invalid_event"', diagnostics)
            self.assertNotIn("PRIVATE_STALE_SPEECH_91827", diagnostics)

    def test_structured_event_with_invalid_metadata_is_queue_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self.assertIsNone(poll_next(data_dir, now=0.0).event)
            corrupt = data_dir / "spool" / "00000000000000000001-invalid.json"
            corrupt.write_text(
                json.dumps(
                    {
                        "event_id": "A" * 24,
                        "session_key": "b" * 16,
                        "status": "private-status",
                        "speech_text": "sensitive speech",
                        "created_at": 0.0,
                        "not_before": 0.0,
                    }
                ),
                encoding="utf-8",
            )
            corrupt.chmod(0o600)

            result = poll_next(data_dir, now=1.0)

            self.assertIsNone(result.event)
            self.assertFalse(corrupt.exists())
            entry = json.loads(
                (data_dir / "diagnostics.jsonl").read_text(encoding="utf-8")
            )
            self.assertRegex(entry["event_id"], r"\A[0-9a-f]{24}\Z")
            self.assertEqual(entry["status"], "unknown")
            self.assertEqual(entry["result"], "discarded")
            self.assertEqual(entry["error_code"], "invalid_event")
            diagnostics = json.dumps(entry)
            self.assertNotIn("private-status", diagnostics)
            self.assertNotIn("sensitive speech", diagnostics)

    def test_invalid_event_times_are_discarded_without_blocking_next_event(self) -> None:
        cases = {
            "far-future": (10_000.0, 10_001.0),
            "inconsistent-settle": (100.0, 101.5),
        }
        for name, (created_at, not_before) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                data_dir = Path(temporary)
                self.assertTrue(
                    enqueue(
                        data_dir,
                        summary_payload("completed", "valid"),
                        session_id="valid-session",
                        turn_id="valid-turn",
                        now=100.0,
                    )
                )
                corrupt = (
                    data_dir
                    / "spool"
                    / f"00000000000000000000-{make_event_id(name, 'turn')}.json"
                )
                corrupt.write_text(
                    json.dumps(
                        {
                            "event_id": make_event_id(name, "turn"),
                            "session_key": "c" * 16,
                            "status": "completed",
                            "speech_text": "invalid-time",
                            "created_at": created_at,
                            "not_before": not_before,
                        }
                    ),
                    encoding="utf-8",
                )
                corrupt.chmod(0o600)

                result = poll_next(data_dir, now=101.0)

                self.assertEqual(
                    result.event.speech_text if result.event else None,
                    "valid",
                )
                self.assertFalse(corrupt.exists())
                diagnostics = (
                    data_dir / "diagnostics.jsonl"
                ).read_text(encoding="utf-8")
                self.assertIn('"status":"unknown"', diagnostics)
                self.assertIn('"result":"discarded"', diagnostics)
                self.assertIn('"error_code":"invalid_event"', diagnostics)
                self.assertNotIn("invalid-time", diagnostics)

    def test_enqueue_discards_temporally_invalid_matching_spool_events(self) -> None:
        cases = {
            "far-future": (10_000.0, 10_001.0, "invalid_event"),
            "expired": (-201.0, -200.0, "stale_event"),
        }
        for name, (created_at, not_before, error_code) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                data_dir = Path(temporary)
                self.assertIsNone(
                    poll_next(data_dir, now=100.0, clock_id=CLOCK_A).event
                )
                session_id = f"{name}-session"
                turn_id = f"{name}-turn"
                event_id = make_event_id(session_id, turn_id)
                stale = data_dir / "spool" / f"00000000000000000001-{event_id}.json"
                stale.write_text(
                    json.dumps(
                        {
                            "format_version": 3,
                            "clock_id": CLOCK_A,
                            "event_id": event_id,
                            "session_key": queue_module._session_key(session_id),
                            "mode": "summary",
                            "status": "completed",
                            "segments": ["stale-matching-event"],
                            "created_at": created_at,
                            "not_before": not_before,
                        }
                    ),
                    encoding="utf-8",
                )
                stale.chmod(0o600)

                self.assertTrue(
                    enqueue(
                        data_dir,
                        summary_payload("completed", "legitimate"),
                        session_id=session_id,
                        turn_id=turn_id,
                        now=100.0,
                        clock_id=CLOCK_A,
                    )
                )

                self.assertFalse(stale.exists())
                events = list((data_dir / "spool").glob("*.json"))
                self.assertEqual(len(events), 1)
                result = poll_next(data_dir, now=101.0, clock_id=CLOCK_A)
                self.assertEqual(
                    result.event.speech_text if result.event else None,
                    "legitimate",
                )
                diagnostics = (
                    data_dir / "diagnostics.jsonl"
                ).read_text(encoding="utf-8")
                self.assertIn(f'"error_code":"{error_code}"', diagnostics)
                self.assertNotIn("stale-matching-event", diagnostics)

    def test_only_one_worker_lock_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context = multiprocessing.get_context("spawn")
            parent_connection, child_connection = context.Pipe(duplex=False)
            data_dir = Path(temporary)
            with try_worker_lock(data_dir) as first:
                self.assertTrue(first)
                self.assertEqual(
                    stat.S_IMODE((data_dir / "worker.lock").stat().st_mode),
                    0o600,
                )
                process = context.Process(
                    target=_try_lock_in_process,
                    args=(temporary, child_connection),
                )
                process.start()
                child_connection.close()
                self.assertTrue(parent_connection.poll(10), "child did not report lock result")
                self.assertFalse(parent_connection.recv())
                process.join(timeout=10)
                self.assertFalse(process.is_alive(), "lock contender did not exit")
                self.assertEqual(process.exitcode, 0)
            parent_connection.close()

    def test_worker_lock_can_be_reacquired_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with try_worker_lock(data_dir) as first:
                self.assertTrue(first)
            with try_worker_lock(data_dir) as second:
                self.assertTrue(second)

    def test_concurrent_processes_enqueue_without_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context = multiprocessing.get_context("spawn")
            results = context.Queue()
            processes = [
                context.Process(
                    target=_enqueue_in_process,
                    args=(temporary, index, results),
                )
                for index in range(8)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=10)
                self.assertFalse(process.is_alive(), "enqueue child did not exit")
                self.assertEqual(process.exitcode, 0)

            enqueue_results = [results.get(timeout=10) for _ in processes]
            results.close()
            results.join_thread()
            self.assertEqual(
                sorted(enqueue_results),
                [(index, True) for index in range(8)],
            )

            values = []
            ready_at = time.monotonic() + 2.0
            while True:
                result = poll_next(Path(temporary), now=ready_at)
                if result.event is None:
                    break
                values.append(result.event.speech_text)
            expected = [f"event-{index}" for index in range(8)]
            self.assertEqual(len(values), 8)
            self.assertEqual(Counter(values), Counter(expected))

    def test_settle_delay_starts_after_waiting_for_queue_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            data_dir.chmod(0o700)
            lock_path = data_dir / "queue.lock"
            lock_path.touch(mode=0o600)
            context = multiprocessing.get_context("spawn")
            parent_connection, child_connection = context.Pipe()

            with lock_path.open("a+") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                process = context.Process(
                    target=_enqueue_after_ready,
                    args=(temporary, child_connection),
                )
                process.start()
                child_connection.close()
                self.assertTrue(parent_connection.poll(10), "child did not attempt flock")
                self.assertEqual(parent_connection.recv(), "attempting")
                self.assertFalse(
                    parent_connection.poll(0.2),
                    "child acquired flock before parent released it",
                )
                time.sleep(0.9)
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

            self.assertTrue(parent_connection.poll(10), "child did not acquire flock")
            self.assertEqual(parent_connection.recv(), "acquired")
            self.assertTrue(parent_connection.poll(10), "child did not finish enqueue")
            self.assertTrue(parent_connection.recv())
            process.join(timeout=10)
            self.assertFalse(process.is_alive(), "delayed enqueue child did not exit")
            self.assertEqual(process.exitcode, 0)
            result = poll_next(data_dir, now=time.monotonic())
            self.assertIsNone(result.event)
            self.assertGreater(result.wait_seconds or 0.0, 0.5)
            parent_connection.close()

    def test_poll_uses_time_after_waiting_for_queue_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self.assertTrue(
                enqueue(
                    data_dir,
                    summary_payload("completed", "ready-after-lock"),
                    session_id="poll-session",
                    turn_id="poll-turn",
                )
            )
            context = multiprocessing.get_context("spawn")
            parent_connection, child_connection = context.Pipe()

            with (data_dir / "queue.lock").open("a+") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                process = context.Process(
                    target=_poll_after_ready,
                    args=(temporary, child_connection),
                )
                process.start()
                child_connection.close()
                self.assertTrue(parent_connection.poll(10), "child did not attempt flock")
                self.assertEqual(parent_connection.recv(), "attempting")
                self.assertFalse(
                    parent_connection.poll(0.2),
                    "child acquired flock before parent released it",
                )
                time.sleep(0.9)
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

            self.assertTrue(parent_connection.poll(10), "child did not acquire flock")
            self.assertEqual(parent_connection.recv(), "acquired")
            self.assertTrue(parent_connection.poll(10), "child did not finish poll")
            self.assertEqual(parent_connection.recv(), ("ready-after-lock", 0.0))
            process.join(timeout=10)
            self.assertFalse(process.is_alive(), "delayed poll child did not exit")
            self.assertEqual(process.exitcode, 0)
            parent_connection.close()


if __name__ == "__main__":
    unittest.main()
