from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from hooks.stop_launcher import MAX_CANDIDATES, main, parse_version, select_stop_hook


def create_runtime(
    family: Path,
    version: str,
    *,
    manifest_name: str = "codex-speak",
    manifest_version: str | None = None,
    stop_source: str = "print('{}')\n",
) -> Path:
    root = family / version
    (root / ".codex-plugin").mkdir(parents=True)
    (root / "hooks").mkdir()
    manifest = {
        "name": manifest_name,
        "version": manifest_version if manifest_version is not None else version,
    }
    (root / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (root / "hooks" / "stop.py").write_text(stop_source, encoding="utf-8")
    return root


class StopLauncherTests(unittest.TestCase):
    def test_parse_version_accepts_only_supported_numeric_release_builds(self) -> None:
        self.assertEqual(parse_version("0.2.6"), (0, 2, 6, 0, ""))
        self.assertEqual(
            parse_version("0.2.6+codex.20260717010101"),
            (0, 2, 6, 1, "20260717010101"),
        )
        for value in (
            "v0.2.6",
            "0.2",
            "0.2.6.1",
            "00.2.6",
            "0.02.6",
            "0.2.6+other.build",
            "0.2.6+codex.UPPER",
            "0.2.6+codex.a/b",
            "../0.2.6",
        ):
            with self.subTest(value=value):
                self.assertIsNone(parse_version(value))

    def test_prefers_valid_original_root_even_when_newer_sibling_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            family = Path(temporary) / "howe829" / "codex-speak"
            original = create_runtime(family, "0.2.6")
            create_runtime(family, "0.2.7")
            self.assertEqual(
                select_stop_hook(original),
                (original.resolve(), (original / "hooks" / "stop.py").resolve()),
            )

    def test_selects_highest_valid_sibling_after_original_is_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            family = Path(temporary) / "howe829" / "codex-speak"
            original = family / "0.2.5"
            create_runtime(family, "0.2.6")
            selected = create_runtime(family, "0.3.0")
            self.assertEqual(
                select_stop_hook(original),
                (selected.resolve(), (selected / "hooks" / "stop.py").resolve()),
            )

    def test_formal_build_is_a_deterministic_same_release_tiebreaker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            family = Path(temporary) / "howe829" / "codex-speak"
            original = family / "0.2.5"
            create_runtime(family, "0.2.6")
            selected = create_runtime(family, "0.2.6+codex.z2")
            create_runtime(family, "0.2.6+codex.a1")
            self.assertEqual(select_stop_hook(original)[0], selected.resolve())

    def test_rejects_wrong_name_mismatched_manifest_malformed_and_nested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            family = Path(temporary) / "howe829" / "codex-speak"
            original = family / "0.2.5"
            create_runtime(family, "0.2.6", manifest_name="other-plugin")
            create_runtime(family, "0.2.7", manifest_version="0.2.8")
            malformed = create_runtime(family, "0.2.8")
            (malformed / ".codex-plugin" / "plugin.json").write_text("{", encoding="utf-8")
            create_runtime(family / "nested", "9.0.0")
            self.assertIsNone(select_stop_hook(original))

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_rejects_symlink_root_manifest_and_stop_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            family = base / "howe829" / "codex-speak"
            original = family / "0.2.5"
            outside = create_runtime(base / "outside", "9.0.0")
            family.mkdir(parents=True)
            (family / "0.2.6").symlink_to(outside, target_is_directory=True)
            manifest_link = create_runtime(family, "0.2.7")
            (manifest_link / ".codex-plugin" / "plugin.json").unlink()
            (manifest_link / ".codex-plugin" / "plugin.json").symlink_to(
                outside / ".codex-plugin" / "plugin.json"
            )
            stop_link = create_runtime(family, "0.2.8")
            (stop_link / "hooks" / "stop.py").unlink()
            (stop_link / "hooks" / "stop.py").symlink_to(
                outside / "hooks" / "stop.py"
            )
            self.assertIsNone(select_stop_hook(original))

    def test_rejects_family_with_more_than_candidate_scan_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            family = Path(temporary) / "howe829" / "codex-speak"
            original = family / "0.2.5"
            for index in range(MAX_CANDIDATES + 1):
                (family / f"0.0.{index}").mkdir(parents=True)
            self.assertIsNone(select_stop_hook(original))

    def test_main_emits_only_empty_hook_result_when_no_runtime_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stdout = io.StringIO()
            stderr = io.StringIO()
            missing = Path(temporary) / "howe829" / "codex-speak" / "0.2.5"
            with (
                patch.dict(os.environ, {"PLUGIN_ROOT": str(missing)}, clear=True),
                patch("hooks.stop_launcher.sys.stdout", stdout),
                patch("hooks.stop_launcher.sys.stderr", stderr),
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(stdout.getvalue(), "{}\n")
            self.assertEqual(stderr.getvalue(), "")

    def test_main_emits_empty_hook_result_when_execv_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = create_runtime(
                Path(temporary) / "howe829" / "codex-speak", "0.2.6"
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch.dict(os.environ, {"PLUGIN_ROOT": str(root)}, clear=True),
                patch("hooks.stop_launcher.os.execv", side_effect=OSError),
                patch("hooks.stop_launcher.sys.stdout", stdout),
                patch("hooks.stop_launcher.sys.stderr", stderr),
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(stdout.getvalue(), "{}\n")
            self.assertEqual(stderr.getvalue(), "")
