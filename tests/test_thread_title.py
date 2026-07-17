from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import warnings

from codex_speak import thread_title
from codex_speak.thread_title import resolve_thread_title


class ThreadTitleTests(unittest.TestCase):
    def _server(self, root: Path, body: str) -> tuple[str, ...]:
        path = root / "fake_app_server.py"
        path.write_text(body, encoding="utf-8")
        return (sys.executable, str(path))

    def _staged_server(self, root: Path, body: str) -> tuple[str, ...]:
        return self._server(
            root,
            f"""
import json, select, sys
initialize = json.loads(sys.stdin.readline())
assert initialize["id"] == 1
assert initialize["method"] == "initialize"
if select.select([sys.stdin], [], [], 0.02)[0]:
    raise RuntimeError("follow-up arrived before initialize response")
print(json.dumps({{"id": 1, "result": {{"codexHome": "/tmp"}}}}), flush=True)
initialized = json.loads(sys.stdin.readline())
thread_read = json.loads(sys.stdin.readline())
assert initialized == {{"method": "initialized", "params": {{}}}}
assert thread_read["id"] == 2
assert thread_read["method"] == "thread/read"
if select.select([sys.stdin], [], [], 0.02)[0]:
    raise RuntimeError("stdin closed before thread response")
thread_id = thread_read["params"]["threadId"]
{body}
""".strip(),
        )

    def test_reads_matching_name_after_unrelated_notification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self._staged_server(
                root,
                """
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
            command = self._staged_server(
                root,
                """
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
            with self.subTest(
                script=script
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                command = self._staged_server(
                    root,
                    script,
                )
                self.assertIsNone(
                    resolve_thread_title(
                        "thread-3", root, command=command, timeout_seconds=1.0
                    )
                )

    def test_timeout_during_initialize_reaps_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pid_path = root / "pid"
            command = self._server(
                root,
                f"""
import os, pathlib, sys, time
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
sys.stdin.readline()
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

    def test_rejects_non_integer_response_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self._staged_server(
                root,
                """
print(json.dumps({"id": 2.0, "result": {"thread": {
    "id": thread_id,
    "name": "wrong"
}}}), flush=True)
""".strip(),
            )
            self.assertIsNone(
                resolve_thread_title(
                    "thread-6", root, command=command, timeout_seconds=1.0
                )
            )

    def test_invalid_commands_never_raise(self) -> None:
        commands = (
            (),
            (sys.executable, None),
            (object(),),
            "not-a-command-sequence",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for command in commands:
                with self.subTest(command=command):
                    self.assertIsNone(
                        resolve_thread_title(
                            "thread-7",
                            root,
                            command=command,  # type: ignore[arg-type]
                            timeout_seconds=0.1,
                        )
                    )

    def test_exceptional_inputs_never_raise(self) -> None:
        class BrokenCommand:
            def __iter__(self):
                raise RuntimeError("must not escape")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                (
                    "broken command iterator",
                    {
                        "command": BrokenCommand(),
                        "timeout_seconds": 0.1,
                    },
                ),
                (
                    "oversized timeout",
                    {
                        "command": (),
                        "timeout_seconds": 10**10_000,
                    },
                ),
            )
            for label, case in cases:
                with self.subTest(label=label):
                    self.assertIsNone(
                        resolve_thread_title(
                            "thread-7b",
                            root,
                            **case,  # type: ignore[arg-type]
                        )
                    )

    def test_closes_process_pipes_without_resource_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self._staged_server(
                root,
                """
print(json.dumps({"id": 2, "result": {"thread": {
    "id": thread_id,
    "name": "closed pipes"
}}}), flush=True)
""".strip(),
            )
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                self.assertEqual(
                    resolve_thread_title(
                        "thread-8", root, command=command, timeout_seconds=1.0
                    ),
                    "closed pipes",
                )
            self.assertFalse(
                [warning for warning in caught if warning.category is ResourceWarning]
            )

    def test_keeps_stdin_open_and_reaps_child_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pid_path = root / "pid"
            command = self._staged_server(
                root,
                f"""
import os, pathlib, time
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
print(json.dumps({{"id": 2, "result": {{"thread": {{
    "id": thread_id,
    "name": "stdin open"
}}}}}}), flush=True)
time.sleep(5)
""".strip(),
            )
            self.assertEqual(
                resolve_thread_title(
                    "thread-8b", root, command=command, timeout_seconds=1.0
                ),
                "stdin open",
            )
            pid = int(pid_path.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_discards_app_server_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self._staged_server(
                root,
                """
print("/Users/private/raw-app-server-error", file=sys.stderr, flush=True)
print(json.dumps({"id": 2, "result": {"thread": {
    "id": thread_id,
    "name": "private title"
}}}), flush=True)
""".strip(),
            )
            captured = io.StringIO()
            with redirect_stderr(captured):
                self.assertEqual(
                    resolve_thread_title(
                        "thread-8c", root, command=command, timeout_seconds=1.0
                    ),
                    "private title",
                )
            self.assertEqual(captured.getvalue(), "")

    @unittest.skipUnless(hasattr(signal, "SIGTERM"), "requires process signals")
    def test_total_timeout_kills_sigterm_resistant_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pid_path = root / "pid"
            command = self._server(
                root,
                f"""
import os, pathlib, signal, sys, time
signal.signal(signal.SIGTERM, lambda *_: None)
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
sys.stdin.readline()
time.sleep(5)
""".strip(),
            )
            started = time.monotonic()
            self.assertIsNone(
                resolve_thread_title(
                    "thread-9", root, command=command, timeout_seconds=0.15
                )
            )
            self.assertLess(time.monotonic() - started, 0.3)
            pid = int(pid_path.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_large_request_cannot_block_past_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pid_path = root / "pid"
            command = self._server(
                root,
                f"""
import json, os, pathlib, sys, time
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
json.loads(sys.stdin.readline())
print(json.dumps({{"id": 1, "result": {{"codexHome": "/tmp"}}}}), flush=True)
time.sleep(1)
""".strip(),
            )
            started = time.monotonic()
            self.assertIsNone(
                resolve_thread_title(
                    "x" * (512 * 1024),
                    root,
                    command=command,
                    timeout_seconds=0.15,
                )
            )
            self.assertLess(time.monotonic() - started, 0.4)
            pid = int(pid_path.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_reaps_descendant_after_server_leader_exits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            descendant_pid_path = root / "descendant-pid"
            command = self._staged_server(
                root,
                f"""
import os, pathlib, subprocess, time
descendant_code = (
    "import os, pathlib, time;"
    "pathlib.Path({str(descendant_pid_path)!r}).write_text(str(os.getpid()));"
    "time.sleep(5)"
)
subprocess.Popen(
    [sys.executable, "-c", descendant_code],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
limit = time.monotonic() + 1
while not pathlib.Path({str(descendant_pid_path)!r}).exists():
    if time.monotonic() >= limit:
        raise RuntimeError("descendant did not start")
    time.sleep(0.01)
print(json.dumps({{"id": 2, "result": {{"thread": {{
    "id": thread_id,
    "name": "group cleaned"
}}}}}}), flush=True)
os._exit(0)
""".strip(),
            )
            descendant_pid: int | None = None
            try:
                self.assertEqual(
                    resolve_thread_title(
                        "thread-10", root, command=command, timeout_seconds=1.0
                    ),
                    "group cleaned",
                )
                descendant_pid = int(descendant_pid_path.read_text(encoding="utf-8"))
                limit = time.monotonic() + 0.5
                while time.monotonic() < limit:
                    try:
                        os.kill(descendant_pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.01)
                with self.assertRaises(ProcessLookupError):
                    os.kill(descendant_pid, 0)
            finally:
                if descendant_pid is not None:
                    try:
                        os.kill(descendant_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_requested_timeout_is_capped_at_global_maximum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self._server(
                root,
                """
import sys, time
sys.stdin.readline()
time.sleep(5)
""".strip(),
            )
            started = time.monotonic()
            self.assertIsNone(
                resolve_thread_title(
                    "thread-11", root, command=command, timeout_seconds=1.7
                )
            )
            self.assertLess(time.monotonic() - started, 1.65)

    def test_hostile_session_id_string_subclass_never_raises(self) -> None:
        class HostileString(str):
            def strip(self, chars=None):
                raise RuntimeError("must not escape")

        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(
                resolve_thread_title(
                    HostileString("thread-12"),
                    Path(temporary),
                    command=(),
                    timeout_seconds=0.1,
                )
            )

    def test_default_command_uses_absolute_discovered_executable(self) -> None:
        with patch.object(thread_title.shutil, "which", return_value="relative/codex"):
            command = thread_title._resolved_command(None)
        self.assertIsNotNone(command)
        assert command is not None
        self.assertTrue(Path(command[0]).is_absolute())
        self.assertEqual(
            command[1:],
            ("app-server", "--stdio", "--disable", "remote_plugin"),
        )

    def test_stages_initialize_and_keeps_stdin_open_for_thread_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self._server(
                root,
                """
import json, select, sys
initialize = json.loads(sys.stdin.readline())
assert initialize["id"] == 1
assert initialize["method"] == "initialize"
if select.select([sys.stdin], [], [], 0.05)[0]:
    raise RuntimeError("follow-up arrived before initialize response")
print(json.dumps({"method": "remoteControl/status/changed", "params": {}}), flush=True)
print(json.dumps({"id": 1, "result": {"codexHome": "/tmp"}}), flush=True)
initialized = json.loads(sys.stdin.readline())
thread_read = json.loads(sys.stdin.readline())
assert initialized == {"method": "initialized", "params": {}}
assert thread_read["id"] == 2
assert thread_read["method"] == "thread/read"
if select.select([sys.stdin], [], [], 0.05)[0]:
    raise RuntimeError("stdin closed before thread response")
thread_id = thread_read["params"]["threadId"]
print(json.dumps({"id": 2, "result": {"thread": {
    "id": thread_id,
    "name": "strict staged title"
}}}), flush=True)
""".strip(),
            )
            self.assertEqual(
                resolve_thread_title(
                    "thread-13", root, command=command, timeout_seconds=1.0
                ),
                "strict staged title",
            )

    def test_invalid_initialize_response_sends_no_follow_up(self) -> None:
        responses = (
            '{"id":1,"error":{"message":"failed"}}',
            '{"id":1,"result":{},"error":{"message":"failed"}}',
            '{"id":1,"result":[]}',
            '{"id":1.0,"result":{}}',
        )
        for response in responses:
            with self.subTest(
                response=response
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                follow_up_path = root / "follow-up"
                command = self._server(
                    root,
                    f"""
import pathlib, select, sys, time
sys.stdin.readline()
print({response!r}, flush=True)
if select.select([sys.stdin], [], [], 0.2)[0]:
    follow_up = sys.stdin.readline()
    if follow_up:
        pathlib.Path({str(follow_up_path)!r}).write_text(follow_up)
time.sleep(0.2)
""".strip(),
                )
                self.assertIsNone(
                    resolve_thread_title(
                        "thread-14", root, command=command, timeout_seconds=0.5
                    )
                )
                self.assertFalse(follow_up_path.exists())

    def test_timeout_during_thread_read_reaps_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pid_path = root / "phase-two-pid"
            command = self._server(
                root,
                f"""
import json, os, pathlib, sys, time
initialize = json.loads(sys.stdin.readline())
print(json.dumps({{"id": 1, "result": {{"codexHome": "/tmp"}}}}), flush=True)
json.loads(sys.stdin.readline())
json.loads(sys.stdin.readline())
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
time.sleep(5)
""".strip(),
            )
            started = time.monotonic()
            self.assertIsNone(
                resolve_thread_title(
                    "thread-15", root, command=command, timeout_seconds=0.2
                )
            )
            self.assertLess(time.monotonic() - started, 0.4)
            pid = int(pid_path.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)


if __name__ == "__main__":
    unittest.main()
