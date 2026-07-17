from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_rejects_cross_marketplace_family_symlink_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            trusted_marketplace = base / "trusted-marketplace" / "codex-speak"
            outside_family = base / "outside-marketplace" / "codex-speak"
            marker = base / "outside-stop-executed"
            create_runtime(
                outside_family,
                "9.0.0",
                stop_source=(
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
                    "print('outside')\n"
                ),
            )
            trusted_marketplace.parent.mkdir(parents=True)
            trusted_marketplace.symlink_to(outside_family, target_is_directory=True)
            original = trusted_marketplace / "0.2.5"

            self.assertIsNone(select_stop_hook(original))
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(
                        Path(__file__).resolve().parent.parent
                        / "hooks"
                        / "stop_launcher.py"
                    ),
                ],
                capture_output=True,
                check=False,
                env={"PLUGIN_ROOT": str(original)},
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "{}\n")
            self.assertEqual(result.stderr, "")
            self.assertFalse(marker.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_rejects_symlinked_marketplace_identity_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            cache = base / "cache"
            trusted_marketplace = cache / "trusted-marketplace"
            outside_marketplace = base / "outside-marketplace"
            outside_family = outside_marketplace / "codex-speak"
            marker = base / "outside-identity-stop-executed"
            create_runtime(
                outside_family,
                "9.0.0",
                stop_source=(
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
                    "print('outside')\n"
                ),
            )
            cache.mkdir()
            trusted_marketplace.symlink_to(
                outside_marketplace,
                target_is_directory=True,
            )
            original = trusted_marketplace / "codex-speak" / "0.2.5"

            self.assertIsNone(select_stop_hook(original))
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(
                        Path(__file__).resolve().parent.parent
                        / "hooks"
                        / "stop_launcher.py"
                    ),
                ],
                capture_output=True,
                check=False,
                env={"PLUGIN_ROOT": str(original)},
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "{}\n")
            self.assertEqual(result.stderr, "")
            self.assertFalse(marker.exists())

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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_validated_stop_descriptor_survives_post_validation_path_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            family = base / "howe829" / "codex-speak"
            root = create_runtime(
                family,
                "0.2.6",
                stop_source=(
                    "import os\n"
                    "leaked = []\n"
                    "for descriptor in range(3, 64):\n"
                    "    try:\n"
                    "        os.fstat(descriptor)\n"
                    "    except OSError:\n"
                    "        continue\n"
                    "    leaked.append(descriptor)\n"
                    "print('original' if not leaked else f'leaked:{leaked}')\n"
                ),
            )
            outside_marker = base / "outside-stop-executed"
            outside_stop = base / "outside-stop.py"
            outside_stop.write_text(
                "from pathlib import Path\n"
                f"Path({str(outside_marker)!r}).write_text("
                "'executed', encoding='utf-8')\n"
                "print('outside')\n",
                encoding="utf-8",
            )
            ready = base / "exec-ready"
            release = base / "exec-release"
            driver = (
                "import os\n"
                "from pathlib import Path\n"
                "import sys\n"
                "import time\n"
                "from hooks import stop_launcher\n"
                "ready = Path(sys.argv[1])\n"
                "release = Path(sys.argv[2])\n"
                "real_execv = os.execv\n"
                "def delayed_execv(path, arguments):\n"
                "    ready.write_text('ready', encoding='utf-8')\n"
                "    deadline = time.monotonic() + 10\n"
                "    while not release.exists():\n"
                "        if time.monotonic() >= deadline:\n"
                "            raise OSError('release timeout')\n"
                "        time.sleep(0.01)\n"
                "    real_execv(path, arguments)\n"
                "stop_launcher.os.execv = delayed_execv\n"
                "raise SystemExit(stop_launcher.main())\n"
            )
            environment = os.environ.copy()
            environment["PLUGIN_ROOT"] = str(root)
            process = subprocess.Popen(
                [sys.executable, "-B", "-c", driver, str(ready), str(release)],
                cwd=Path(__file__).resolve().parent.parent,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(lambda: process.poll() is None and process.kill())
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None:
                if time.monotonic() >= deadline:
                    self.fail("launcher did not reach the exec boundary")
                time.sleep(0.01)
            self.assertIsNone(process.poll())

            stop_hook = root / "hooks" / "stop.py"
            stop_hook.unlink()
            stop_hook.symlink_to(outside_stop)
            release.write_text("release", encoding="utf-8")
            stdout, stderr = process.communicate(timeout=10)

            self.assertEqual(process.returncode, 0)
            self.assertEqual(stdout, "original\n")
            self.assertEqual(stderr, "")
            self.assertFalse(outside_marker.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "requires rename semantics")
    def test_validated_root_anchors_production_style_stop_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            family = base / "howe829" / "codex-speak"
            root = create_runtime(
                family,
                "0.2.6",
                stop_source=(
                    "from __future__ import annotations\n"
                    "import os\n"
                    "from pathlib import Path\n"
                    "import sys\n"
                    "DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parents[1]\n"
                    "if str(DEFAULT_PLUGIN_ROOT) not in sys.path:\n"
                    "    sys.path.insert(0, str(DEFAULT_PLUGIN_ROOT))\n"
                    "from codex_speak.helper import IMPORT_SOURCE\n"
                    "leaked = []\n"
                    "for descriptor in range(3, 64):\n"
                    "    try:\n"
                    "        os.fstat(descriptor)\n"
                    "    except OSError:\n"
                    "        continue\n"
                    "    leaked.append(descriptor)\n"
                    "print(IMPORT_SOURCE if not leaked else f'leaked:{leaked}')\n"
                ),
            )
            original_package = root / "codex_speak"
            original_package.mkdir()
            (original_package / "__init__.py").write_text("", encoding="utf-8")
            (original_package / "helper.py").write_text(
                "IMPORT_SOURCE = 'original'\n", encoding="utf-8"
            )
            outside_marker = base / "outside-import-executed"
            ready = base / "root-exec-ready"
            release = base / "root-exec-release"
            driver = (
                "import os\n"
                "from pathlib import Path\n"
                "import sys\n"
                "import time\n"
                "from hooks import stop_launcher\n"
                "ready = Path(sys.argv[1])\n"
                "release = Path(sys.argv[2])\n"
                "real_execv = os.execv\n"
                "def delayed_execv(path, arguments):\n"
                "    ready.write_text('ready', encoding='utf-8')\n"
                "    deadline = time.monotonic() + 10\n"
                "    while not release.exists():\n"
                "        if time.monotonic() >= deadline:\n"
                "            raise OSError('release timeout')\n"
                "        time.sleep(0.01)\n"
                "    real_execv(path, arguments)\n"
                "stop_launcher.os.execv = delayed_execv\n"
                "raise SystemExit(stop_launcher.main())\n"
            )
            environment = os.environ.copy()
            environment["PLUGIN_ROOT"] = str(root)
            process = subprocess.Popen(
                [sys.executable, "-B", "-c", driver, str(ready), str(release)],
                cwd=Path(__file__).resolve().parent.parent,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(lambda: process.poll() is None and process.kill())
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None:
                if time.monotonic() >= deadline:
                    self.fail("launcher did not reach the root exec boundary")
                time.sleep(0.01)
            self.assertIsNone(process.poll())

            validated_root = family / "validated-root"
            root.rename(validated_root)
            replacement_root = create_runtime(family, "0.2.6")
            outside_package = replacement_root / "codex_speak"
            outside_package.mkdir()
            (outside_package / "__init__.py").write_text("", encoding="utf-8")
            (outside_package / "helper.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(outside_marker)!r}).write_text("
                "'executed', encoding='utf-8')\n"
                "IMPORT_SOURCE = 'outside'\n",
                encoding="utf-8",
            )
            release.write_text("release", encoding="utf-8")
            stdout, stderr = process.communicate(timeout=10)

            self.assertEqual(process.returncode, 0)
            self.assertEqual(stdout, "original\n")
            self.assertEqual(stderr, "")
            self.assertFalse(outside_marker.exists())

    def test_direct_script_execution_emits_empty_result_for_missing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "howe829" / "codex-speak" / "0.2.5"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve().parent.parent / "hooks" / "stop_launcher.py"),
                ],
                capture_output=True,
                check=False,
                env={"PLUGIN_ROOT": str(missing)},
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "{}\n")
            self.assertEqual(result.stderr, "")
