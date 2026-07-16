import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "assets" / "CodexSpeakMenu.app"
EXECUTABLE = APP / "Contents" / "MacOS" / "CodexSpeakMenu"


class PackagingTests(unittest.TestCase):
    def test_menu_uses_one_template_mark_with_alpha_prompt_cutouts(self) -> None:
        controller = (
            ROOT / "menu-bar" / "Sources" / "CodexSpeakMenu" / "MenuController.swift"
        ).read_text(encoding="utf-8")
        status_icon = (
            ROOT / "menu-bar" / "Sources" / "CodexSpeakMenu" / "StatusIcon.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("applyDefaultStatusIcon()", controller)
        self.assertIn("StatusIcon.makeTemplateImage()", controller)
        self.assertIn("image.isTemplate = true", status_icon)
        self.assertIn("compositingOperation = .clear", status_icon)
        self.assertIn("CodexSpeakIconGeometry.chevronCutout", status_icon)
        self.assertIn("CodexSpeakIconGeometry.cursorCutout", status_icon)
        self.assertNotIn('title = "◖))"', controller)
        self.assertNotIn('title = "!"', controller)
        self.assertNotIn("systemSymbolName:", controller + status_icon)

    def test_menu_checkmarks_compare_all_modes_against_selected_mode(self) -> None:
        source = (
            ROOT / "menu-bar" / "Sources" / "CodexSpeakMenu" / "MenuController.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("silentItem.state = selectedMode == .silent", source)
        self.assertIn("summaryItem.state = selectedMode == .summary", source)
        self.assertIn("fullItem.state = selectedMode == .full", source)

    def test_menu_refreshes_persisted_mode_when_opened(self) -> None:
        source = (
            ROOT / "menu-bar" / "Sources" / "CodexSpeakMenu" / "MenuController.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("NSObject, NSMenuDelegate", source)
        self.assertIn("menu.delegate = self", source)
        self.assertRegex(
            source,
            r"func menuWillOpen\(_ menu: NSMenu\)\s*\{\s*refreshMode\(\)\s*\}",
        )

    def test_claimed_event_checkmarks_sync_even_when_diagnostics_recording_fails(self) -> None:
        source = (
            ROOT / "menu-bar" / "Sources" / "CodexSpeakMenu" / "MenuController.swift"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"try await coordinator\.handle\(event: event\)\s*"
            r"\}\s*catch\s*\{\s*"
            r'showLocalError\("Could not record playback result"\)\s*'
            r"\}\s*"
            r"selectedMode = await coordinator\.selectedMode\s*"
            r"updateCheckmarks\(\)",
        )

    def test_python_plugin_entries_do_not_write_bytecode_into_installed_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installed_root = Path(temporary) / "installed" / "codex-speak"
            installed_root.mkdir(parents=True)
            ignore_bytecode = shutil.ignore_patterns("__pycache__", "*.pyc")
            shutil.copytree(
                ROOT / "codex_speak",
                installed_root / "codex_speak",
                ignore=ignore_bytecode,
            )
            shutil.copytree(
                ROOT / "hooks",
                installed_root / "hooks",
                ignore=ignore_bytecode,
            )
            data_dir = Path(temporary) / "plugin-data"
            environment = os.environ.copy()
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            environment.pop("PYTHONPYCACHEPREFIX", None)
            environment["PLUGIN_ROOT"] = str(installed_root)

            commands = (
                ([sys.executable, "-B", str(installed_root / "hooks" / "session_start.py")], None),
                ([sys.executable, "-B", str(installed_root / "hooks" / "stop.py")], "{}"),
                ([sys.executable, "-B", "-m", "codex_speak.settings", "--data-dir", str(data_dir), "get"], None),
                ([sys.executable, "-B", "-m", "codex_speak.queue", "--data-dir", str(data_dir), "clear-pending"], None),
                ([sys.executable, "-B", "-m", "codex_speak.worker", "--help"], None),
                ([sys.executable, "-B", "-m", "codex_speak.bridge", "--help"], None),
                (
                    [
                        sys.executable,
                        "-B",
                        "-m",
                        "codex_speak.diagnostics",
                        "--data-dir",
                        str(data_dir),
                        "record",
                        "--event-id",
                        "0123456789abcdef01234567",
                        "--status",
                        "completed",
                        "--result",
                        "spoken",
                        "--mode",
                        "full",
                        "--segment-count",
                        "1",
                        "--duration-ms",
                        "1",
                        "--error-code",
                        "NONE",
                    ],
                    None,
                ),
            )
            for arguments, standard_input in commands:
                with self.subTest(arguments=arguments):
                    subprocess.run(
                        arguments,
                        cwd=installed_root,
                        env=environment,
                        input=standard_input,
                        text=True,
                        check=True,
                        capture_output=True,
                    )

            bytecode = [
                path.relative_to(installed_root)
                for path in installed_root.rglob("*")
                if path.name == "__pycache__" or path.suffix == ".pyc"
            ]
            self.assertEqual(bytecode, [])

    def test_manifest_has_exact_identity_and_only_supported_fields(self) -> None:
        manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["name"], "codex-speak")
        self.assertRegex(
            manifest["version"],
            r"^0\.2\.3(?:\+codex\.[a-z0-9-]+)?$",
        )
        self.assertEqual(manifest["interface"]["displayName"], "Codex Speak")
        self.assertEqual(
            set(manifest),
            {
                "name",
                "version",
                "description",
                "author",
                "license",
                "keywords",
                "interface",
            },
        )
        self.assertEqual(
            set(manifest["interface"]),
            {
                "displayName",
                "shortDescription",
                "longDescription",
                "developerName",
                "category",
                "capabilities",
                "defaultPrompt",
            },
        )

    def test_shipped_runtime_sources_contain_no_legacy_protocol_marker(self) -> None:
        source_roots = (
            ROOT / "codex_speak",
            ROOT / "hooks",
            ROOT / "menu-bar" / "Sources",
        )
        source_paths = [ROOT / ".codex-plugin" / "plugin.json"]
        source_paths.extend(
            sorted(
                path
                for source_root in source_roots
                for path in source_root.rglob("*")
                if path.is_file() and path.suffix in {".json", ".py", ".swift"}
            )
        )
        self.assertTrue(source_paths)
        for path in source_paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn(
                    "codex-voice-notifier:v1",
                    path.read_text(encoding="utf-8"),
                )

    def test_embedded_helper_has_exact_metadata_and_is_executable(self) -> None:
        self.assertTrue(os.access(EXECUTABLE, os.X_OK), EXECUTABLE)
        with (APP / "Contents" / "Info.plist").open("rb") as handle:
            metadata = plistlib.load(handle)
        self.assertEqual(
            metadata,
            {
                "CFBundleDevelopmentRegion": "en",
                "CFBundleDisplayName": "Codex Speak",
                "CFBundleExecutable": "CodexSpeakMenu",
                "CFBundleIdentifier": "com.howard.codex-speak.menu",
                "CFBundleInfoDictionaryVersion": "6.0",
                "CFBundleName": "Codex Speak",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": "1.0.0",
                "CFBundleVersion": "1",
                "LSMinimumSystemVersion": "13.0",
                "LSUIElement": True,
            },
        )

    def test_embedded_helper_is_exactly_universal_and_ad_hoc_signed(self) -> None:
        architectures = subprocess.run(
            ["lipo", "-archs", str(EXECUTABLE)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        self.assertEqual(set(architectures), {"arm64", "x86_64"})
        self.assertEqual(len(architectures), 2)
        subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(APP)],
            check=True,
            capture_output=True,
            text=True,
        )
        signature_details = subprocess.run(
            ["codesign", "--display", "--verbose=4", str(APP)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn(
            "Signature=adhoc",
            signature_details.stdout + signature_details.stderr,
        )

    def test_readme_locks_exact_menu_order_and_marketplace_version_prefix(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        exact_menu = """1. `Silent`
2. `Summary`
3. `Full`
4. `Stop Current Speech`
5. `Clear Pending Speeches`
6. `Quit Codex Speak`"""
        self.assertIn(exact_menu, readme)
        prefixes = set(re.findall(r"\d+\.\d+\.\d+\+codex\.", readme))
        self.assertEqual(prefixes, {"0.2.3+codex."})

    def test_build_script_is_local_and_builds_both_release_architectures(self) -> None:
        script = (ROOT / "scripts" / "build_menu_app.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("set -euo pipefail", script)
        self.assertIn("build_arch arm64", script)
        self.assertIn("build_arch x86_64", script)
        self.assertIn("--configuration release", script)
        self.assertIn('codesign --force --deep --sign -', script)
        self.assertIn('codesign --verify --deep --strict', script)
        for download_command in ("curl ", "wget ", "git clone", "pip install"):
            self.assertNotIn(download_command, script)


if __name__ == "__main__":
    unittest.main()
