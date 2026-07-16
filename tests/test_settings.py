import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from codex_speak.settings import load_mode, save_mode


class SettingsTests(unittest.TestCase):
    def test_malformed_existing_settings_records_invalid_settings_without_content(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = "PRIVATE_MODE_CANARY_92741"
            (root / "settings.json").write_text(secret, encoding="utf-8")

            self.assertEqual(load_mode(root), "summary")

            diagnostics = (root / "diagnostics.jsonl").read_text(encoding="utf-8")
            self.assertIn('"error_code":"invalid_settings"', diagnostics)
            self.assertNotIn(secret, diagnostics)

    def test_default_private_and_persistent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(load_mode(root), "summary")
            self.assertEqual(
                stat.S_IMODE((root / "settings.json").stat().st_mode),
                0o600,
            )
            self.assertEqual(save_mode(root, "full"), "full")
            self.assertEqual(load_mode(root), "full")

    def test_silent_mode_persists_with_version_one_across_loads(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(save_mode(root, "silent"), "silent")
            self.assertEqual(load_mode(root), "silent")
            self.assertEqual(
                json.loads((root / "settings.json").read_text(encoding="utf-8")),
                {"version": 1, "mode": "silent"},
            )

    def test_invalid_repairs_to_summary(self) -> None:
        invalid_values = (
            {"version": 1, "mode": "bad"},
            {"version": 1, "mode": "summary", "extra": True},
            {"version": True, "mode": "summary"},
            {"version": 2, "mode": "summary"},
            {"version": 1, "mode": True},
            [1, "summary"],
        )
        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value):
                with TemporaryDirectory() as directory:
                    root = Path(directory)
                    path = root / "settings.json"
                    path.write_text(json.dumps(invalid_value), encoding="utf-8")
                    self.assertEqual(load_mode(root), "summary")
                    self.assertEqual(
                        json.loads(path.read_text(encoding="utf-8")),
                        {"version": 1, "mode": "summary"},
                    )
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_save_rejects_invalid_modes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for invalid_mode in (True, None, "bad", "SUMMARY", 1):
                with self.subTest(invalid_mode=invalid_mode):
                    with self.assertRaises(ValueError):
                        save_mode(root, invalid_mode)
            self.assertFalse((root / "settings.json").exists())

    def test_atomic_write_leaves_no_temporary_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(save_mode(root, "summary"), "summary")
            self.assertEqual(
                [path.name for path in root.iterdir()],
                ["settings.json"],
            )
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)

    def test_load_valid_settings_normalizes_existing_permissions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "settings.json"
            path.write_text('{"version":1,"mode":"full"}', encoding="utf-8")
            root.chmod(0o755)
            path.chmod(0o644)

            self.assertEqual(load_mode(root), "full")

            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_cli_get_and_set_print_only_mode(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            get_default = self._run_cli(root, "get")
            self.assertEqual(get_default.returncode, 0)
            self.assertEqual(get_default.stdout, "summary\n")
            self.assertEqual(get_default.stderr, "")

            set_full = self._run_cli(root, "set", "full")
            self.assertEqual(set_full.returncode, 0)
            self.assertEqual(set_full.stdout, "full\n")
            self.assertEqual(set_full.stderr, "")

            get_full = self._run_cli(root, "get")
            self.assertEqual(get_full.returncode, 0)
            self.assertEqual(get_full.stdout, "full\n")
            self.assertEqual(get_full.stderr, "")

    def test_cli_sets_and_gets_silent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            set_silent = self._run_cli(root, "set", "silent")
            self.assertEqual(
                (set_silent.returncode, set_silent.stdout, set_silent.stderr),
                (0, "silent\n", ""),
            )
            get_silent = self._run_cli(root, "get")
            self.assertEqual(
                (get_silent.returncode, get_silent.stdout, get_silent.stderr),
                (0, "silent\n", ""),
            )

    def test_cli_rejects_abbreviated_options(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            completed = self._run_raw_cli("--data-d", str(root), "get")

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((root / "settings.json").exists())

    @staticmethod
    def _run_cli(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return SettingsTests._run_raw_cli(
            "--data-dir",
            str(root),
            *arguments,
        )

    @staticmethod
    def _run_raw_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).parents[1])
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "codex_speak.settings",
                *arguments,
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
