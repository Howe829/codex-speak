from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import codex_speak.hook_runtime as hook_runtime
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

    def test_rejects_empty_or_oversized_source_without_target_temporary_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            data_dir = base / "data"
            stdout = io.StringIO()
            stderr = io.StringIO()
            for payload in (b"", b"x" * 65_537):
                with self.subTest(size=len(payload)):
                    plugin_root = make_plugin(base / str(len(payload)), payload)
                    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                        self.assertFalse(install_stop_launcher(plugin_root, data_dir))
                    runtime_dir = data_dir / RUNTIME_HOOK_DIRECTORY
                    self.assertFalse((runtime_dir / STOP_LAUNCHER_NAME).exists())
                    self.assertFalse(
                        runtime_dir.exists()
                        and any(
                            path.name.startswith(f".{STOP_LAUNCHER_NAME}.")
                            for path in runtime_dir.iterdir()
                        )
                    )
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")

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

    def test_failed_temporary_permission_normalization_removes_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plugin_root = make_plugin(base, b"launcher\n")
            data_dir = base / "data"
            original_fchmod = os.fchmod

            def fail_file_permissions(descriptor: int, mode: int) -> None:
                if stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise OSError
                original_fchmod(descriptor, mode)

            with patch(
                "codex_speak.hook_runtime.os.fchmod",
                side_effect=fail_file_permissions,
            ):
                self.assertFalse(install_stop_launcher(plugin_root, data_dir))

            runtime_dir = data_dir / RUNTIME_HOOK_DIRECTORY
            self.assertFalse((runtime_dir / STOP_LAUNCHER_NAME).exists())
            self.assertFalse(
                any(path.name.startswith(f".{STOP_LAUNCHER_NAME}.") for path in runtime_dir.iterdir())
            )

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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_source_replacement_race_cannot_persist_linked_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            packaged = b"packaged-launcher\n"
            outside_payload = b"outside-launcher\n"
            plugin_root = make_plugin(base, packaged)
            source = plugin_root / "hooks" / STOP_LAUNCHER_NAME
            outside = base / "outside-launcher.py"
            outside.write_bytes(outside_payload)
            data_dir = base / "data"
            stdout = io.StringIO()
            stderr = io.StringIO()
            original_reader = hook_runtime._read_packaged_launcher

            def replace_source_then_read(path: Path) -> bytes:
                path.unlink()
                path.symlink_to(outside)
                return original_reader(path)

            with (
                patch(
                    "codex_speak.hook_runtime._read_packaged_launcher",
                    side_effect=replace_source_then_read,
                ),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                self.assertFalse(install_stop_launcher(plugin_root, data_dir))

            runtime_dir = data_dir / RUNTIME_HOOK_DIRECTORY
            self.assertFalse((runtime_dir / STOP_LAUNCHER_NAME).exists())
            self.assertFalse(
                runtime_dir.exists()
                and any(path.name.startswith(f".{STOP_LAUNCHER_NAME}.") for path in runtime_dir.iterdir())
            )
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_runtime_directory_replacement_race_cannot_escape_directory_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            payload = b"packaged-launcher\n"
            plugin_root = make_plugin(base, payload)
            data_dir = base / "data"
            runtime_dir = data_dir / RUNTIME_HOOK_DIRECTORY
            outside = base / "outside"
            outside.mkdir()
            moved_runtime_dir = base / "runtime-directory-after-swap"
            original_path_chmod = Path.chmod
            original_fchmod = os.fchmod
            swapped = False

            def swap_runtime_directory() -> None:
                nonlocal swapped
                if not swapped:
                    runtime_dir.rename(moved_runtime_dir)
                    runtime_dir.symlink_to(outside, target_is_directory=True)
                    swapped = True

            def replace_path_chmod(
                path: Path, mode: int, *, follow_symlinks: bool = True
            ) -> None:
                original_path_chmod(path, mode, follow_symlinks=follow_symlinks)
                if path == runtime_dir:
                    swap_runtime_directory()

            def replace_directory_after_fchmod(descriptor: int, mode: int) -> None:
                original_fchmod(descriptor, mode)
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    swap_runtime_directory()

            with (
                patch("pathlib.Path.chmod", side_effect=replace_path_chmod),
                patch(
                    "codex_speak.hook_runtime.os.fchmod",
                    side_effect=replace_directory_after_fchmod,
                ),
            ):
                self.assertTrue(install_stop_launcher(plugin_root, data_dir))

            target = moved_runtime_dir / STOP_LAUNCHER_NAME
            self.assertTrue(swapped)
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(moved_runtime_dir.stat().st_mode), 0o700)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)
