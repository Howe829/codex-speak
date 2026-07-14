import json
import os
from pathlib import Path
import plistlib
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "assets" / "CodexSpeakMenu.app"
EXECUTABLE = APP / "Contents" / "MacOS" / "CodexSpeakMenu"


class PackagingTests(unittest.TestCase):
    def test_manifest_has_exact_identity_and_only_supported_fields(self) -> None:
        manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["name"], "codex-speak")
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
