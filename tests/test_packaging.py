import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from codex_speak.hook_runtime import install_stop_launcher


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "assets" / "CodexSpeakMenu.app"
EXECUTABLE = APP / "Contents" / "MacOS" / "CodexSpeakMenu"


def make_fake_runtime(family: Path, version: str) -> Path:
    root = family / version
    (root / ".codex-plugin").mkdir(parents=True)
    (root / "hooks").mkdir()
    (root / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "codex-speak", "version": version}),
        encoding="utf-8",
    )
    (root / "hooks" / "stop_launcher.py").write_bytes(
        (ROOT / "hooks" / "stop_launcher.py").read_bytes()
    )
    (root / "hooks" / "stop.py").write_text(
        "from pathlib import Path\n"
        "import os\n"
        "import sys\n"
        "expected = Path(__file__).resolve().parents[1]\n"
        "if Path(os.environ['PLUGIN_ROOT']).resolve() != expected:\n"
        "    raise SystemExit(7)\n"
        "environment_canary = os.environ.get('UNRELATED_HANDOFF_CANARY')\n"
        "if environment_canary is not None:\n"
        "    sys.stdout.write(f'env:{environment_canary}\\n')\n"
        "sys.stdout.write(sys.stdin.read())\n",
        encoding="utf-8",
    )
    return root


def _paeth_predictor(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _read_png_rgba(path: Path) -> tuple[int, int, list[bytes]]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG: {path}")

    width = height = 0
    image_data = bytearray()
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
            width, height = header[:2]
            if header[2:] != (8, 6, 0, 0, 0):
                raise AssertionError(f"unsupported PNG format: {header[2:]}")
        elif chunk_type == b"IDAT":
            image_data.extend(chunk)
        elif chunk_type == b"IEND":
            break

    bytes_per_pixel = 4
    stride = width * bytes_per_pixel
    inflated = zlib.decompress(image_data)
    if len(inflated) != height * (stride + 1):
        raise AssertionError("unexpected PNG scanline length")

    rows: list[bytes] = []
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = inflated[offset]
        encoded = inflated[offset + 1 : offset + stride + 1]
        decoded = bytearray(stride)
        for index, value in enumerate(encoded):
            left = decoded[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = (
                previous[index - bytes_per_pixel]
                if index >= bytes_per_pixel
                else 0
            )
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                predictor = _paeth_predictor(left, above, upper_left)
            else:
                raise AssertionError(f"unsupported PNG filter: {filter_type}")
            decoded[index] = (value + predictor) & 0xFF
        rows.append(bytes(decoded))
        previous = decoded
        offset += stride + 1
    return width, height, rows


class PackagingTests(unittest.TestCase):
    def test_captured_stop_command_survives_deletion_of_original_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            family = base / "cache" / "howe829" / "codex-speak"
            version_a = make_fake_runtime(family, "0.2.6")
            data_dir = base / "plugin-data"
            self.assertTrue(install_stop_launcher(version_a, data_dir))

            config = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
            captured_command = config["hooks"]["Stop"][0]["hooks"][0]["command"]
            shutil.rmtree(version_a)
            version_b = make_fake_runtime(family, "0.2.7")

            canary = '{"message":"PRIVATE-UPGRADE-CANARY"}\n'
            environment = os.environ.copy()
            environment["PLUGIN_ROOT"] = str(version_a)
            environment["PLUGIN_DATA"] = str(data_dir)
            environment["UNRELATED_HANDOFF_CANARY"] = "preserved-through-handoff"
            completed = subprocess.run(
                captured_command,
                shell=True,
                executable="/bin/sh",
                cwd=base,
                env=environment,
                input=canary,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(
                completed.stdout,
                "env:preserved-through-handoff\n" + canary,
            )
            self.assertEqual(completed.stderr, "")
            self.assertTrue(version_b.is_dir())
            self.assertNotIn("PRIVATE-UPGRADE-CANARY", captured_command)
            self.assertNotIn("PRIVATE-UPGRADE-CANARY", " ".join(completed.args))
            for path in data_dir.rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"PRIVATE-UPGRADE-CANARY", path.read_bytes())

    def test_stop_command_falls_back_to_original_version_hook_without_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            family = base / "cache" / "howe829" / "codex-speak"
            version_a = make_fake_runtime(family, "0.2.6")
            data_dir = base / "plugin-data"
            config = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
            captured_command = config["hooks"]["Stop"][0]["hooks"][0]["command"]
            environment = os.environ.copy()
            environment["PLUGIN_ROOT"] = str(version_a)
            environment["PLUGIN_DATA"] = str(data_dir)
            completed = subprocess.run(
                captured_command,
                shell=True,
                executable="/bin/sh",
                cwd=base,
                env=environment,
                input="fallback input\n",
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(completed.stdout, "fallback input\n")
            self.assertEqual(completed.stderr, "")

    def test_public_marketplace_exposes_codex_speak_from_github(self) -> None:
        marketplace_path = ROOT / ".agents" / "plugins" / "marketplace.json"
        self.assertTrue(marketplace_path.is_file(), marketplace_path)
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        expected = {
            "name": "howe829",
            "interface": {"displayName": "Howe829 Plugins"},
            "plugins": [
                {
                    "name": "codex-speak",
                    "source": {
                        "source": "url",
                        "url": "https://github.com/Howe829/codex-speak.git",
                        "ref": "v0.2.6",
                    },
                    "policy": {
                        "installation": "AVAILABLE",
                        "authentication": "ON_INSTALL",
                    },
                    "category": "Productivity",
                }
            ],
        }
        self.assertEqual(marketplace, expected)
        self.assertEqual(marketplace["plugins"][0]["name"], manifest["name"])
        self.assertEqual(marketplace["plugins"][0]["source"]["ref"], "v0.2.6")
        self.assertEqual(manifest["version"], "0.2.6")

    def test_readme_displays_only_the_production_public_icon(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("![Codex Speak icon](assets/codex-speak-github.png)", readme)
        self.assertNotIn("artwork/concepts/", readme)

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
        self.assertIn(
            "drawingHandler: StatusIcon.makeDrawingHandler(pointSize: pointSize)",
            status_icon,
        )
        self.assertRegex(
            status_icon,
            r"nonisolated private static func makeDrawingHandler\(\s*"
            r"pointSize: CGFloat\s*"
            r"\) -> @Sendable \(NSRect\) -> Bool\s*\{\s*"
            r"\{ \[pointSize\] _ in\s*"
            r"StatusIcon\.drawTemplate\(pointSize: pointSize\)\s*\}\s*\}",
        )
        self.assertIn(
            "nonisolated private static func drawTemplate(pointSize: CGFloat) -> Bool",
            status_icon,
        )
        self.assertIn(
            "nonisolated private static func speakerPath() -> NSBezierPath",
            status_icon,
        )
        self.assertIn(
            "nonisolated private static func nsPoint(_ point: IconPoint) -> NSPoint",
            status_icon,
        )
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

    def test_menu_controller_localizes_every_menu_and_error_string(self) -> None:
        source = (
            ROOT / "menu-bar" / "Sources" / "CodexSpeakMenu" / "MenuController.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("let itemTitles = localization.menuItemTitles", source)
        for key in (
            "errorBridgeStopped",
            "errorClearFailed",
            "errorModeWriteFailed",
            "errorModeReadFailed",
            "errorHeartbeatUnavailable",
            "errorPlaybackRecordFailed",
        ):
            with self.subTest(key=key):
                self.assertIn(f"localization.string(.{key})", source)
        for literal in (
            "Speech bridge stopped",
            "Could not clear pending speeches",
            "Could not change speech mode",
            "Could not read speech mode",
            "Heartbeat unavailable",
            "Could not record playback result",
        ):
            with self.subTest(literal=literal):
                self.assertNotIn(f'showLocalError("{literal}")', source)

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
            r"showLocalError\(localization\.string\(\.errorPlaybackRecordFailed\)\)\s*"
            r"\}\s*"
            r"selectedMode = await coordinator\.selectedMode\s*"
            r"updateCheckmarks\(\)",
        )

    def test_python_plugin_entries_do_not_write_bytecode_into_installed_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = json.loads(
                (ROOT / ".codex-plugin" / "plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            installed_root = (
                Path(temporary)
                / "cache"
                / "howe829"
                / "codex-speak"
                / manifest["version"]
            )
            installed_root.mkdir(parents=True)
            ignore_bytecode = shutil.ignore_patterns("__pycache__", "*.pyc")
            shutil.copytree(
                ROOT / ".codex-plugin",
                installed_root / ".codex-plugin",
                ignore=ignore_bytecode,
            )
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
            stop_sentinel = Path(temporary) / "installed-stop-executed"
            installed_stop = installed_root / "hooks" / "stop.py"
            stop_source = installed_stop.read_text(encoding="utf-8")
            future_import = "from __future__ import annotations\n"
            self.assertTrue(stop_source.startswith(future_import))
            installed_stop.write_text(
                future_import
                + "\nfrom pathlib import Path as _SentinelPath\n"
                + f"_SentinelPath({str(stop_sentinel)!r}).write_text("
                + "'executed', encoding='utf-8')\n"
                + stop_source[len(future_import) :],
                encoding="utf-8",
            )
            data_dir = Path(temporary) / "plugin-data"
            environment = os.environ.copy()
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            environment.pop("PYTHONPYCACHEPREFIX", None)
            environment["PLUGIN_ROOT"] = str(installed_root)
            environment["PLUGIN_DATA"] = str(data_dir)

            commands = (
                ([sys.executable, "-B", str(installed_root / "hooks" / "session_start.py")], None),
                ([sys.executable, "-B", str(data_dir / "runtime-hooks" / "stop_launcher.py")], "{}"),
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
                    if arguments[2:] == [
                        str(data_dir / "runtime-hooks" / "stop_launcher.py")
                    ]:
                        self.assertEqual(
                            stop_sentinel.read_text(encoding="utf-8"),
                            "executed",
                        )

            bytecode = [
                path.relative_to(installed_root)
                for path in installed_root.rglob("*")
                if path.name == "__pycache__" or path.suffix == ".pyc"
            ]
            self.assertEqual(bytecode, [])
            runtime_bytecode = [
                path.relative_to(data_dir / "runtime-hooks")
                for path in (data_dir / "runtime-hooks").rglob("*")
                if path.name == "__pycache__" or path.suffix == ".pyc"
            ]
            self.assertEqual(runtime_bytecode, [])

    def test_manifest_has_exact_identity_and_only_supported_fields(self) -> None:
        manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["name"], "codex-speak")
        self.assertRegex(
            manifest["version"],
            r"^0\.2\.6(?:\+codex\.[a-z0-9-]+)?$",
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

    def test_public_icon_assets_are_deterministic_and_complete(self) -> None:
        renderer = ROOT / "scripts" / "render_icon_assets.swift"
        renderer_source = renderer.read_text(encoding="utf-8")
        github_icon = ROOT / "assets" / "codex-speak-github.png"
        app_icon = ROOT / "menu-bar" / "Resources" / "AppIcon.icns"

        self.assertIn(
            'appendingPathComponent("artwork/codex-speak-app-icon.svg")',
            renderer_source,
        )
        self.assertNotIn("artwork/concepts", renderer_source)
        self.assertIn("func drawArtwork(in context: NSGraphicsContext)", renderer_source)
        self.assertNotIn("NSImage(contentsOf:", renderer_source)
        self.assertNotIn("source.draw(", renderer_source)

        png_header = github_icon.read_bytes()[:24]
        self.assertEqual(png_header[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(png_header[12:16], b"IHDR")
        self.assertEqual(struct.unpack(">II", png_header[16:24]), (1024, 1024))

        icns_header = app_icon.read_bytes()[:8]
        self.assertEqual(icns_header[:4], b"icns")
        self.assertEqual(struct.unpack(">I", icns_header[4:8])[0], app_icon.stat().st_size)
        self.assertGreater(app_icon.stat().st_size, 1024)

    def test_public_icon_renderer_rejects_changed_authoritative_svg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            renderer = temporary_root / "scripts" / "render_icon_assets.swift"
            renderer.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts" / "render_icon_assets.swift", renderer)

            source = temporary_root / "artwork" / "codex-speak-app-icon.svg"
            source.parent.mkdir(parents=True)
            canonical = (
                ROOT / "artwork" / "codex-speak-app-icon.svg"
            ).read_text(encoding="utf-8")
            background_line = next(
                line
                for line in canonical.splitlines()
                if 'id="app-background"' in line
            )
            moved_background = canonical.replace(
                f"{background_line}\n",
                "",
                1,
            ).replace(
                "  </defs>",
                f"{background_line}\n  </defs>",
                1,
            )
            mutations = {
                "gradient-coordinate": canonical.replace(
                    'x2="928"', 'x2="929"', 1
                ),
                "direct-parent": moved_background,
            }

            for mutation, changed in mutations.items():
                with self.subTest(mutation=mutation):
                    self.assertNotEqual(changed, canonical)
                    source.write_text(changed, encoding="utf-8")

                    environment = os.environ.copy()
                    environment["CLANG_MODULE_CACHE_PATH"] = str(
                        temporary_root / "clang-module-cache"
                    )
                    environment["SWIFT_MODULECACHE_PATH"] = str(
                        temporary_root / "swift-module-cache"
                    )
                    result = subprocess.run(
                        [str(renderer)],
                        cwd=temporary_root,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("sourceInvalid", result.stdout + result.stderr)
                    self.assertFalse(
                        (
                            temporary_root
                            / "assets"
                            / "codex-speak-github.png"
                        ).exists()
                    )
                    self.assertFalse(
                        (
                            temporary_root
                            / "menu-bar"
                            / "Resources"
                            / "AppIcon.icns"
                        ).exists()
                    )

    def test_public_icon_direct_renderer_matches_the_vector_master(self) -> None:
        renderer_source = (
            ROOT / "scripts" / "render_icon_assets.swift"
        ).read_text(encoding="utf-8")
        compact_source = re.sub(r"\s+", " ", renderer_source)

        speaker_source = renderer_source.split("func speakerPath() -> CGPath {", 1)[
            1
        ].split("\n}\n\nfunc draw(", 1)[0]
        speaker_points = [
            tuple(float(value) for value in match)
            for match in re.findall(
                r"markPoint\(([0-9.]+), ([0-9.]+)\)", speaker_source
            )
        ]
        self.assertEqual(
            speaker_points,
            [
                (5.5, 5),
                (3.5, 7),
                (4.4, 5),
                (3.5, 5.9),
                (3.5, 17),
                (5.5, 19),
                (3.5, 18.1),
                (4.4, 19),
                (10, 19),
                (18.7, 21.5),
                (20.4, 20.2),
                (19.55, 21.75),
                (20.4, 21.1),
                (20.4, 3.8),
                (18.7, 2.5),
                (20.4, 2.9),
                (19.55, 2.25),
                (10, 5),
            ],
        )
        self.assertIn("let markOrigin = CGFloat(176)", renderer_source)
        self.assertIn("let markScale = CGFloat(28)", renderer_source)
        self.assertIn(
            "CGRect(x: 32, y: 32, width: 960, height: 960)",
            compact_source,
        )
        self.assertIn("cornerWidth: 224, cornerHeight: 224", compact_source)
        self.assertEqual(
            re.findall(
                r"color\((0x[0-9A-F]+), (0x[0-9A-F]+), (0x[0-9A-F]+)\)",
                renderer_source,
            ),
            [
                ("0x26", "0x36", "0xA7"),
                ("0x6D", "0x28", "0xD9"),
                ("0xFF", "0xFF", "0xFF"),
                ("0xC7", "0xF2", "0xFF"),
            ],
        )
        for snippet in (
            "CGPoint(x: 96, y: 944)",
            "CGPoint(x: 928, y: 80)",
            "from: markPoint(4, 19)",
            "to: markPoint(20, 4)",
            "chevron.move(to: markPoint(6.4, 14.6))",
            "chevron.addLine(to: markPoint(9.5, 12))",
            "chevron.addLine(to: markPoint(6.4, 9.4))",
            "context.cgContext.setLineWidth(markScale * 1.8)",
            "x: markOrigin + markScale * 10.8",
            "y: markOrigin + markScale * 8.6",
            "width: markScale * 4",
            "height: markScale * 1.6",
            "cornerWidth: markScale * 0.8",
            "cornerHeight: markScale * 0.8",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, renderer_source)

    def test_public_icon_raster_matches_palette_crop_and_speaker_bounds(self) -> None:
        width, height, rows = _read_png_rgba(
            ROOT / "assets" / "codex-speak-github.png"
        )
        self.assertEqual((width, height), (1024, 1024))

        def rgba_at(x: int, y: int) -> tuple[int, int, int, int]:
            offset = x * 4
            return tuple(rows[y][offset : offset + 4])

        for x, y in ((0, 0), (31, 512), (992, 512), (1023, 1023)):
            with self.subTest(transparent=(x, y)):
                self.assertEqual(rgba_at(x, y)[3], 0)
        for x, y in ((32, 512), (512, 32), (991, 512), (512, 991)):
            with self.subTest(opaque=(x, y)):
                self.assertEqual(rgba_at(x, y)[3], 255)

        for point, expected, tolerance in (
            ((128, 80), (0x26, 0x36, 0xA7), 2),
            ((800, 944), (0x6D, 0x28, 0xD9), 5),
            ((274, 400), (0xFF, 0xFF, 0xFF), 4),
            ((700, 700), (0xC7, 0xF2, 0xFF), 5),
        ):
            with self.subTest(palette=point):
                actual = rgba_at(*point)[:3]
                self.assertLessEqual(
                    max(abs(actual[index] - expected[index]) for index in range(3)),
                    tolerance,
                )

        left_background = rgba_at(273, 512)[:3]
        left_speaker = rgba_at(274, 512)[:3]
        right_speaker = rgba_at(746, 512)[:3]
        right_background = rgba_at(748, 512)[:3]
        self.assertGreater(sum(left_speaker), sum(left_background) + 300)
        self.assertGreater(sum(right_speaker), sum(right_background) + 300)

    def test_public_icon_prompt_cutouts_have_crisp_target_resolution_edges(self) -> None:
        width, height, rows = _read_png_rgba(
            ROOT / "assets" / "codex-speak-github.png"
        )
        self.assertEqual((width, height), (1024, 1024))

        def rgb_at(x: int, y: int) -> tuple[int, int, int]:
            offset = x * 4
            self.assertEqual(rows[y][offset + 3], 255)
            return tuple(rows[y][offset : offset + 3])

        cutout_samples = (
            ("chevron-upper", rgb_at(399, 476), rgb_at(658, 226)),
            ("chevron-lower", rgb_at(399, 548), rgb_at(831, 132)),
            ("cursor", rgb_at(534, 585), rgb_at(880, 252)),
        )
        for cutout, sample, background_reference in cutout_samples:
            with self.subTest(cutout=cutout):
                self.assertLessEqual(
                    max(
                        abs(sample[index] - background_reference[index])
                        for index in range(3)
                    ),
                    2,
                )

        between_chevron_branches = rgb_at(400, 512)
        self.assertGreater(
            sum(
                abs(between_chevron_branches[index] - cutout_samples[0][1][index])
                for index in range(3)
            ),
            300,
        )

        cursor_center = rgb_at(534, 585)
        right_reference = rgb_at(620, 585)
        self.assertGreater(
            sum(abs(cursor_center[index] - right_reference[index]) for index in range(3)),
            300,
        )

        edge_samples = (
            ("right", rgb_at(600, 585), right_reference),
            ("top", rgb_at(534, 550), rgb_at(534, 540)),
            ("bottom", rgb_at(534, 620), rgb_at(534, 630)),
        )
        for edge, outside, reference in edge_samples:
            with self.subTest(edge=edge):
                self.assertLessEqual(
                    max(
                        abs(outside[index] - reference[index])
                        for index in range(3)
                    ),
                    3,
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
                "CFBundleIconFile": "AppIcon",
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
        self.assertTrue(
            (APP / "Contents" / "Resources" / "AppIcon.icns").is_file()
        )

    def test_embedded_helper_contains_exact_menu_localizations(self) -> None:
        for language in ("en", "zh-Hans"):
            source = (
                ROOT
                / "menu-bar"
                / "Resources"
                / f"{language}.lproj"
                / "Localizable.strings"
            )
            packaged = (
                APP
                / "Contents"
                / "Resources"
                / f"{language}.lproj"
                / "Localizable.strings"
            )
            with self.subTest(language=language):
                self.assertTrue(packaged.is_file(), packaged)
                self.assertEqual(packaged.read_bytes(), source.read_bytes())

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

    def test_readme_locks_exact_menu_order_and_public_installation(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "The menu bar follows your macOS preferred language and supports "
            "English and Simplified Chinese.",
            readme,
        )
        exact_menu = """1. `Silent`
2. `Summary`
3. `Full`
4. `Stop Current Speech`
5. `Clear Pending Speeches`
6. `Quit Codex Speak`"""
        self.assertIn(exact_menu, readme)
        for required in (
            "codex plugin marketplace add Howe829/codex-speak --ref main",
            "/plugins",
            "codex plugin add codex-speak@howe829",
            "codex plugin marketplace upgrade howe829",
            "GitHub access",
            "codex plugin marketplace list",
            "0.2.3 or newer",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)
        for forbidden in (
            "codex-speak@personal",
            "~/.agents/plugins/marketplace.json",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, readme)
        self.assertNotRegex(readme, r"/Users/[^/\s]+")
        self.assertNotIn("cachebuster", readme.lower())

    def test_maintainer_release_doc_uses_portable_named_roots(self) -> None:
        path = ROOT / "docs" / "maintainers" / "local-release.md"
        self.assertTrue(path.is_file(), path)
        document = path.read_text(encoding="utf-8")
        for required in (
            "$DEV_PLUGIN_ROOT",
            "$FORMAL_PLUGIN_ROOT",
            "$PLUGIN_CREATOR_ROOT",
            "update_plugin_cachebuster.py",
            "codex plugin add codex-speak@personal",
            "start a new task",
        ):
            with self.subTest(required=required):
                self.assertIn(required, document)
        self.assertNotRegex(document, r"/Users/[^/\s]+")

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
        self.assertIn('mkdir -p "$STAGED_APP/Contents/Resources"', script)
        self.assertIn(
            'cp "$PACKAGE/Resources/AppIcon.icns" "$STAGED_APP/Contents/Resources/AppIcon.icns"',
            script,
        )
        self.assertIn("for localization in en zh-Hans; do", script)
        self.assertIn(
            'source="$PACKAGE/Resources/$localization.lproj/Localizable.strings"',
            script,
        )
        self.assertIn(
            'destination="$STAGED_APP/Contents/Resources/$localization.lproj"',
            script,
        )
        self.assertIn(
            'cp "$source" "$destination/Localizable.strings"',
            script,
        )
        for download_command in ("curl ", "wget ", "git clone", "pip install"):
            self.assertNotIn(download_command, script)


if __name__ == "__main__":
    unittest.main()
