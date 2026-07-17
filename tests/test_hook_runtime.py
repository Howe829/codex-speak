from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from codex_speak.hook_runtime import (
    RUNTIME_HOOK_DIRECTORY,
    STOP_LAUNCHER_NAME,
    install_stop_launcher,
)


def make_plugin(base: Path, payload: bytes) -> Path:
    plugin_root = base / "plugin"
    source = plugin_root / "hooks" / "stop_launcher.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    return plugin_root


class HookRuntimeTests(unittest.TestCase):
    def test_installs_packaged_launcher_byte_for_byte_with_private_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plugin_root = base / "plugin"
            source = plugin_root / "hooks" / "stop_launcher.py"
            source.parent.mkdir(parents=True)
            payload = b"#!/usr/bin/env python3\nprint('{}')\n"
            source.write_bytes(payload)
            data_dir = base / "data"

            self.assertTrue(install_stop_launcher(plugin_root, data_dir))

            runtime_dir = data_dir / "runtime-hooks"
            target = runtime_dir / "stop_launcher.py"
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(runtime_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(list(runtime_dir.iterdir()), [target])

    def test_reinstall_is_idempotent_and_repairs_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plugin_root = make_plugin(base, b"launcher-v1\n")
            data_dir = base / "data"
            self.assertTrue(install_stop_launcher(plugin_root, data_dir))
            target = data_dir / "runtime-hooks" / "stop_launcher.py"
            target.chmod(0o644)
            self.assertTrue(install_stop_launcher(plugin_root, data_dir))
            self.assertEqual(target.read_bytes(), b"launcher-v1\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_failed_replace_preserves_target_and_removes_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plugin_root = make_plugin(base, b"launcher-v2\n")
            data_dir = base / "data"
            runtime_dir = data_dir / RUNTIME_HOOK_DIRECTORY
            runtime_dir.mkdir(parents=True)
            target = runtime_dir / STOP_LAUNCHER_NAME
            target.write_bytes(b"complete-launcher\n")
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch("codex_speak.hook_runtime.os.replace", side_effect=OSError),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                self.assertFalse(install_stop_launcher(plugin_root, data_dir))

            self.assertEqual(target.read_bytes(), b"complete-launcher\n")
            self.assertFalse(
                any(path.name.startswith(f".{STOP_LAUNCHER_NAME}.") for path in runtime_dir.iterdir())
            )
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")

    def test_concurrent_installations_leave_one_private_byte_exact_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            payload = b"#!/usr/bin/env python3\nprint('stable')\n"
            plugin_root = make_plugin(base, payload)
            data_dir = base / "data"

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(
                    executor.map(
                        lambda _: install_stop_launcher(plugin_root, data_dir), range(32)
                    )
                )

            runtime_dir = data_dir / RUNTIME_HOOK_DIRECTORY
            target = runtime_dir / STOP_LAUNCHER_NAME
            self.assertEqual(results, [True] * 32)
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(runtime_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertFalse(
                any(path.name.startswith(f".{STOP_LAUNCHER_NAME}.") for path in runtime_dir.iterdir())
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_rejects_symlinked_source_and_runtime_directory_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside-launcher.py"
            outside.write_bytes(b"outside\n")
            plugin_root = base / "plugin"
            source = plugin_root / "hooks" / STOP_LAUNCHER_NAME
            source.parent.mkdir(parents=True)
            source.symlink_to(outside)
            data_dir = base / "data"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                self.assertFalse(install_stop_launcher(plugin_root, data_dir))
            self.assertFalse((data_dir / RUNTIME_HOOK_DIRECTORY / STOP_LAUNCHER_NAME).exists())
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")

            plugin_root = make_plugin(base / "second", b"launcher\n")
            runtime_dir = data_dir / RUNTIME_HOOK_DIRECTORY
            runtime_dir.parent.mkdir(parents=True, exist_ok=True)
            outside_runtime = base / "outside-runtime"
            outside_runtime.mkdir()
            runtime_dir.symlink_to(outside_runtime, target_is_directory=True)
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                self.assertFalse(install_stop_launcher(plugin_root, data_dir))
            self.assertEqual(list(outside_runtime.iterdir()), [])
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")

    def test_rejects_missing_or_unreadable_source_without_partial_target_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            data_dir = base / "data"
            missing = base / "missing-plugin"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                self.assertFalse(install_stop_launcher(missing, data_dir))
            self.assertFalse((data_dir / RUNTIME_HOOK_DIRECTORY / STOP_LAUNCHER_NAME).exists())
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")

            plugin_root = make_plugin(base / "unreadable", b"launcher\n")
            with (
                patch(
                    "codex_speak.hook_runtime._read_packaged_launcher",
                    side_effect=OSError,
                ),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                self.assertFalse(install_stop_launcher(plugin_root, data_dir))
            self.assertFalse((data_dir / RUNTIME_HOOK_DIRECTORY / STOP_LAUNCHER_NAME).exists())
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
