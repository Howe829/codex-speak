# Codex Speak Icon Family Implementation Plan

> **Superseded (2026-07-16):** The user selected the integrated speaker-container
> concept with an embedded `>_` prompt. Use the
> [speaker-prompt design](../specs/2026-07-16-codex-speak-speaker-prompt-icon-design.md)
> and its [implementation plan](2026-07-16-codex-speak-speaker-prompt-icon.md)
> instead of this three-pulse plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an original three-pulse-stair icon family for Codex Speak as a GitHub/App icon and a native monochrome macOS menu-bar icon.

**Architecture:** Image Gen produces one constrained concept board for visual approval, but production assets come from deterministic SVG masters and exact Swift geometry. The menu helper draws a template `NSImage` from shared geometry, while a local Swift renderer exports the app SVG to GitHub PNG and macOS ICNS assets without adding runtime dependencies.

**Tech Stack:** Built-in Image Gen, SVG, Python `unittest` and `xml.etree.ElementTree`, Swift 6, AppKit, `iconutil`, plist packaging, ad-hoc codesigning.

## Global Constraints

- The core mark contains exactly three rounded vertical bars, never five.
- Bar heights and vertical positions are asymmetric and rise from lower left to upper right.
- No terminal chevron, cursor underscore, microphone, speaker cone, radiating arcs, enclosing circle, text, OpenAI knot, or separate secondary symbol is allowed.
- The menu-bar mark is monochrome, close to square, and legible at 16, 18, and 22 pixels on light and dark menu bars.
- The App/GitHub icon uses the unchanged pulse geometry on a deep-indigo-to-violet rounded square and survives circular avatar cropping.
- Image Gen output is a design reference only; deterministic SVG and Swift geometry are the production sources.
- Runtime requirements remain macOS 13.0 or newer, Python 3.10 or newer, and no third-party runtime packages or network service.

---

### Task 1: Generate and approve the constrained concept board

**Files:**
- Create: `artwork/concepts/codex-speak-three-pulse.png`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-16-codex-speak-icon-design.md` and the user-provided ChatGPT Use Voice image as a simplicity reference only.
- Produces: an approved raster concept whose geometry and color treatment guide Tasks 2–4.

- [ ] **Step 1: Ignore local visual-companion state**

Append exactly this line to `.gitignore`:

```gitignore
.superpowers/
```

- [ ] **Step 2: Verify the ignore rule**

Run:

```bash
git check-ignore .superpowers/brainstorm/67249-1784179680/content/icon-directions.html
```

Expected: the command prints the `.superpowers/.../icon-directions.html` path and exits `0`.

- [ ] **Step 3: Generate one focused concept board with built-in Image Gen**

Use the attached ChatGPT image as a **reference image**, not an edit target. Invoke built-in Image Gen with this exact prompt:

```text
Use case: logo-brand
Asset type: Codex Speak icon-family concept board
Primary request: Design one original icon family for Codex Speak using exactly three asymmetric rounded vertical pulse bars. The three bars rise from lower left to upper right, with unequal heights and deliberately offset baselines, and read as one compact rhythmic silhouette.
Reference image: Use only as a reference for simplicity, rounded stroke quality, and clarity at tiny sizes. Do not trace or reproduce its five-bar geometry, spacing, lengths, symmetry, white circle, or overall silhouette.
App/GitHub icon: Place the unchanged three-pulse mark inside a premium macOS rounded square with a restrained deep-indigo-to-violet background. Render the pulse in white with a subtle icy-cyan accent, generous optical padding, and safe circular-avatar cropping.
Menu-bar icon: Show the same three-pulse geometry as a standalone monochrome template mark with no background or container. Preview it at true 16 px, 18 px, and 22 px optical sizes on both light and dark macOS-style menu bars.
Style: crisp vector-like geometry, flat, calm, precise, native macOS character, consistent rounded corners, generous negative space.
Constraints: exactly three bars; one unified mark; no terminal chevron; no cursor underscore; no microphone; no speaker cone; no radiating arcs; no enclosing circle; no text; no OpenAI knot; no third-party trademark; no watermark.
```

Copy the selected generated result to `artwork/concepts/codex-speak-three-pulse.png`, leaving the generated original in place.

- [ ] **Step 4: Run the visual approval gate**

Check the generated board against every Global Constraint, then show it to the user. Do not proceed until the user confirms the concept or gives a single targeted revision. If revised, preserve the exact prompt and change only the rejected visual property.

- [ ] **Step 5: Commit the approved concept and ignore rule**

```bash
git add .gitignore artwork/concepts/codex-speak-three-pulse.png
git commit -m "design: approve codex speak icon concept"
```

---

### Task 2: Create deterministic SVG masters and geometry validation

**Files:**
- Create: `artwork/codex-speak-pulse.svg`
- Create: `artwork/codex-speak-app-icon.svg`
- Create: `tests/test_icon_assets.py`

**Interfaces:**
- Consumes: the approved Task 1 concept for color and optical reference.
- Produces: normalized pulse geometry `(x, y, width, height)` values `(3, 3, 3.2, 7)`, `(10.4, 5.5, 3.2, 11)`, and `(17.8, 7.5, 3.2, 13.5)` on a `24 × 24` canvas; Tasks 3 and 4 must use those values unchanged.

- [ ] **Step 1: Write the failing SVG validation tests**

Create `tests/test_icon_assets.py`:

```python
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"
EXPECTED = [
    (3.0, 3.0, 3.2, 7.0),
    (10.4, 5.5, 3.2, 11.0),
    (17.8, 7.5, 3.2, 13.5),
]


def pulse_rectangles(path: Path) -> list[tuple[float, float, float, float]]:
    root = ET.parse(path).getroot()
    group = root.find(f".//{SVG}g[@id='pulse-mark']")
    if group is None:
        raise AssertionError(f"missing pulse-mark in {path}")
    return [
        tuple(float(rect.get(name, "nan")) for name in ("x", "y", "width", "height"))
        for rect in group.findall(f"{SVG}rect")
    ]


class IconAssetTests(unittest.TestCase):
    def test_both_masters_use_exactly_the_same_three_pulse_bars(self) -> None:
        for relative in (
            "artwork/codex-speak-pulse.svg",
            "artwork/codex-speak-app-icon.svg",
        ):
            path = ROOT / relative
            with self.subTest(path=relative):
                self.assertEqual(pulse_rectangles(path), EXPECTED)

    def test_masters_contain_no_reference_circle_or_extra_symbol(self) -> None:
        for path in (ROOT / "artwork").glob("codex-speak-*.svg"):
            root = ET.parse(path).getroot()
            self.assertEqual(root.findall(f".//{SVG}circle"), [], path)
            group = root.find(f".//{SVG}g[@id='pulse-mark']")
            self.assertIsNotNone(group, path)
            self.assertEqual(len(list(group)), 3, path)

    def test_pulse_geometry_is_asymmetric_and_rises(self) -> None:
        bars = pulse_rectangles(ROOT / "artwork/codex-speak-pulse.svg")
        heights = [bar[3] for bar in bars]
        bottoms = [bar[1] for bar in bars]
        tops = [bar[1] + bar[3] for bar in bars]
        self.assertEqual(len(set(heights)), 3)
        self.assertEqual(bottoms, sorted(bottoms))
        self.assertEqual(tops, sorted(tops))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_icon_assets -v
```

Expected: FAIL because the two SVG master files do not exist.

- [ ] **Step 3: Create the monochrome pulse master**

Create `artwork/codex-speak-pulse.svg`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <title>Codex Speak three-pulse mark</title>
  <g id="pulse-mark" transform="translate(0 24) scale(1 -1)" fill="#000000">
    <rect x="3" y="3" width="3.2" height="7" rx="1.6"/>
    <rect x="10.4" y="5.5" width="3.2" height="11" rx="1.6"/>
    <rect x="17.8" y="7.5" width="3.2" height="13.5" rx="1.6"/>
  </g>
</svg>
```

- [ ] **Step 4: Create the App/GitHub SVG master**

Create `artwork/codex-speak-app-icon.svg`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <title>Codex Speak app icon</title>
  <defs>
    <linearGradient id="background" x1="128" y1="96" x2="896" y2="928" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#2636A7"/>
      <stop offset="1" stop-color="#5A24B8"/>
    </linearGradient>
    <linearGradient id="pulse" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="1" stop-color="#BCEFFF"/>
    </linearGradient>
  </defs>
  <rect x="32" y="32" width="960" height="960" rx="220" fill="url(#background)"/>
  <g id="pulse-mark" transform="translate(176 848) scale(28 -28)" fill="url(#pulse)">
    <rect x="3" y="3" width="3.2" height="7" rx="1.6"/>
    <rect x="10.4" y="5.5" width="3.2" height="11" rx="1.6"/>
    <rect x="17.8" y="7.5" width="3.2" height="13.5" rx="1.6"/>
  </g>
</svg>
```

- [ ] **Step 5: Run the SVG tests to verify they pass**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_icon_assets -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Commit the masters and validation**

```bash
git add artwork/codex-speak-pulse.svg artwork/codex-speak-app-icon.svg tests/test_icon_assets.py
git commit -m "feat: add codex speak icon masters"
```

---

### Task 3: Replace the text status item with the native template icon

**Files:**
- Create: `menu-bar/Sources/CodexSpeakCore/IconGeometry.swift`
- Create: `menu-bar/Sources/CodexSpeakMenu/StatusIcon.swift`
- Modify: `menu-bar/Sources/CodexSpeakMenu/MenuController.swift`
- Create: `menu-bar/Tests/CodexSpeakCoreTests/IconGeometryTests.swift`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: Task 2's exact normalized geometry.
- Produces: `CodexSpeakIconGeometry.bars: [PulseBar]` and `StatusIcon.makeTemplateImage() -> NSImage`; `MenuController` uses the template image for normal state and restores it after transient errors.

- [ ] **Step 1: Write the failing Swift geometry test**

Create `menu-bar/Tests/CodexSpeakCoreTests/IconGeometryTests.swift`:

```swift
import XCTest
@testable import CodexSpeakCore

final class IconGeometryTests: XCTestCase {
    func testThreePulseGeometryIsAsymmetricAndRises() {
        let bars = CodexSpeakIconGeometry.bars
        XCTAssertEqual(bars.count, 3)
        XCTAssertEqual(bars.map(\.height), [7, 11, 13.5])
        XCTAssertEqual(bars.map(\.y), [3, 5.5, 7.5])
        XCTAssertEqual(bars.map { $0.y + $0.height }, [10, 16.5, 21])
        XCTAssertEqual(Set(bars.map(\.height)).count, 3)
    }

    func testGeometryFitsTwentyFourPointCanvasWithPadding() {
        for bar in CodexSpeakIconGeometry.bars {
            XCTAssertGreaterThanOrEqual(bar.x, 3)
            XCTAssertGreaterThanOrEqual(bar.y, 3)
            XCTAssertLessThanOrEqual(bar.x + bar.width, 21)
            XCTAssertLessThanOrEqual(bar.y + bar.height, 21)
            XCTAssertEqual(bar.cornerRadius, 1.6)
        }
    }
}
```

Extend `tests/test_packaging.py` with:

```python
    def test_menu_uses_template_image_instead_of_text_glyph(self) -> None:
        source = (
            ROOT / "menu-bar" / "Sources" / "CodexSpeakMenu" / "MenuController.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("applyDefaultStatusIcon()", source)
        self.assertIn("StatusIcon.makeTemplateImage()", source)
        self.assertNotIn('title = "◖))"', source)
```

- [ ] **Step 2: Run focused tests to verify they fail**

Run:

```bash
swift test --package-path menu-bar --filter IconGeometryTests
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_packaging.PackagingTests.test_menu_uses_template_image_instead_of_text_glyph -v
```

Expected: Swift build fails because `CodexSpeakIconGeometry` is missing; Python assertion fails because the text glyph remains.

- [ ] **Step 3: Implement shared geometry**

Create `menu-bar/Sources/CodexSpeakCore/IconGeometry.swift`:

```swift
public struct PulseBar: Equatable, Sendable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double
    public let cornerRadius: Double

    public init(x: Double, y: Double, width: Double, height: Double, cornerRadius: Double) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.cornerRadius = cornerRadius
    }
}

public enum CodexSpeakIconGeometry {
    public static let canvasSize = 24.0
    public static let bars = [
        PulseBar(x: 3, y: 3, width: 3.2, height: 7, cornerRadius: 1.6),
        PulseBar(x: 10.4, y: 5.5, width: 3.2, height: 11, cornerRadius: 1.6),
        PulseBar(x: 17.8, y: 7.5, width: 3.2, height: 13.5, cornerRadius: 1.6),
    ]
}
```

- [ ] **Step 4: Implement the AppKit template image**

Create `menu-bar/Sources/CodexSpeakMenu/StatusIcon.swift`:

```swift
import AppKit
import CodexSpeakCore

enum StatusIcon {
    @MainActor
    static func makeTemplateImage() -> NSImage {
        let canvas = CodexSpeakIconGeometry.canvasSize
        let size = NSSize(width: canvas, height: canvas)
        let image = NSImage(size: size, flipped: false) { _ in
            NSColor.black.setFill()
            for bar in CodexSpeakIconGeometry.bars {
                let rect = NSRect(x: bar.x, y: bar.y, width: bar.width, height: bar.height)
                NSBezierPath(
                    roundedRect: rect,
                    xRadius: bar.cornerRadius,
                    yRadius: bar.cornerRadius
                ).fill()
            }
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = "Codex Speak"
        return image
    }
}
```

- [ ] **Step 5: Integrate normal and error status images**

In `MenuController.init`, replace the text title assignment with:

```swift
        applyDefaultStatusIcon()
        statusItem.button?.toolTip = "Codex Speak"
```

Replace `showLocalError` and `clearLocalError`, and add `applyDefaultStatusIcon`:

```swift
    private func applyDefaultStatusIcon() {
        statusItem.button?.title = ""
        statusItem.button?.image = StatusIcon.makeTemplateImage()
        statusItem.button?.imagePosition = .imageOnly
        statusItem.button?.toolTip = "Codex Speak"
    }

    private func showLocalError(_ message: String) {
        statusItem.button?.title = ""
        statusItem.button?.image = NSImage(
            systemSymbolName: "exclamationmark.triangle.fill",
            accessibilityDescription: message
        )
        statusItem.button?.image?.isTemplate = true
        statusItem.button?.toolTip = message
        errorTimer?.invalidate()
        errorTimer = Timer(
            timeInterval: 2,
            target: self,
            selector: #selector(clearLocalError),
            userInfo: nil,
            repeats: false
        )
        if let errorTimer { RunLoop.main.add(errorTimer, forMode: .common) }
    }

    @objc private func clearLocalError() {
        applyDefaultStatusIcon()
        errorTimer = nil
    }
```

- [ ] **Step 6: Run focused and full Swift tests**

Run:

```bash
swift test --package-path menu-bar --filter IconGeometryTests
swift test --package-path menu-bar -Xswiftc -warnings-as-errors
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_packaging.PackagingTests.test_menu_uses_template_image_instead_of_text_glyph -v
```

Expected: all commands PASS.

- [ ] **Step 7: Commit the menu-bar icon integration**

```bash
git add menu-bar/Sources/CodexSpeakCore/IconGeometry.swift \
  menu-bar/Sources/CodexSpeakMenu/StatusIcon.swift \
  menu-bar/Sources/CodexSpeakMenu/MenuController.swift \
  menu-bar/Tests/CodexSpeakCoreTests/IconGeometryTests.swift \
  tests/test_packaging.py
git commit -m "feat: add codex speak menu bar icon"
```

---

### Task 4: Export and package the App/GitHub icon

**Files:**
- Create: `scripts/render_icon_assets.swift`
- Create: `assets/codex-speak-github.png`
- Create: `menu-bar/Resources/AppIcon.icns`
- Modify: `menu-bar/Resources/Info.plist`
- Modify: `scripts/build_menu_app.sh`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `artwork/codex-speak-app-icon.svg` from Task 2.
- Produces: a `1024 × 1024` GitHub PNG, a valid macOS `AppIcon.icns`, and a signed helper bundle containing `Contents/Resources/AppIcon.icns` with `CFBundleIconFile = AppIcon`.

- [ ] **Step 1: Write failing packaging assertions**

Add these assertions to `test_embedded_helper_has_exact_metadata_and_is_executable` in `tests/test_packaging.py`:

```python
        self.assertEqual(metadata["CFBundleIconFile"], "AppIcon")
        self.assertTrue((APP / "Contents" / "Resources" / "AppIcon.icns").is_file())
```

Also add this entry to the exact metadata dictionary asserted by the same test:

```python
                "CFBundleIconFile": "AppIcon",
```

Add a new test:

```python
    def test_public_icon_assets_are_reproducible_and_present(self) -> None:
        renderer = ROOT / "scripts" / "render_icon_assets.swift"
        github_icon = ROOT / "assets" / "codex-speak-github.png"
        app_icon = ROOT / "menu-bar" / "Resources" / "AppIcon.icns"
        self.assertTrue(renderer.is_file())
        self.assertGreater(github_icon.stat().st_size, 1024)
        self.assertGreater(app_icon.stat().st_size, 1024)
```

- [ ] **Step 2: Run packaging tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_packaging.PackagingTests.test_public_icon_assets_are_reproducible_and_present tests.test_packaging.PackagingTests.test_embedded_helper_has_exact_metadata_and_is_executable -v
```

Expected: FAIL because renderer and packaged icon assets are absent.

- [ ] **Step 3: Create the deterministic AppKit renderer**

Create executable `scripts/render_icon_assets.swift`:

```swift
#!/usr/bin/env swift
import AppKit
import Foundation

enum RenderError: Error {
    case sourceUnavailable
    case bitmapUnavailable
    case pngUnavailable
    case iconutilFailed(Int32)
}

let root = URL(fileURLWithPath: FileManager.default.currentDirectory, isDirectory: true)
let sourceURL = root.appendingPathComponent("artwork/codex-speak-app-icon.svg")
let githubURL = root.appendingPathComponent("assets/codex-speak-github.png")
let iconsetURL = root.appendingPathComponent(".build/CodexSpeak.iconset", isDirectory: true)
let icnsURL = root.appendingPathComponent("menu-bar/Resources/AppIcon.icns")

guard let source = NSImage(contentsOf: sourceURL) else { throw RenderError.sourceUnavailable }

func render(pixels: Int, to output: URL) throws {
    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: pixels,
        pixelsHigh: pixels,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else { throw RenderError.bitmapUnavailable }
    bitmap.size = NSSize(width: pixels, height: pixels)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSGraphicsContext.current?.imageInterpolation = .high
    source.draw(
        in: NSRect(x: 0, y: 0, width: pixels, height: pixels),
        from: .zero,
        operation: .copy,
        fraction: 1
    )
    NSGraphicsContext.restoreGraphicsState()
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw RenderError.pngUnavailable
    }
    try FileManager.default.createDirectory(
        at: output.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try data.write(to: output, options: .atomic)
}

try? FileManager.default.removeItem(at: iconsetURL)
try FileManager.default.createDirectory(at: iconsetURL, withIntermediateDirectories: true)

let exports = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]
for (pixels, filename) in exports {
    try render(pixels: pixels, to: iconsetURL.appendingPathComponent(filename))
}
try render(pixels: 1024, to: githubURL)

let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["-c", "icns", iconsetURL.path, "-o", icnsURL.path]
try iconutil.run()
iconutil.waitUntilExit()
guard iconutil.terminationStatus == 0 else {
    throw RenderError.iconutilFailed(iconutil.terminationStatus)
}
```

Run `chmod 755 scripts/render_icon_assets.swift`.

- [ ] **Step 4: Render the production assets**

Run from the repository root:

```bash
scripts/render_icon_assets.swift
sips -g pixelWidth -g pixelHeight assets/codex-speak-github.png
iconutil -c iconset menu-bar/Resources/AppIcon.icns -o /private/tmp/CodexSpeakIcon.iconset
```

Expected: GitHub PNG reports `1024 × 1024`; `iconutil` extracts a complete iconset without error.

- [ ] **Step 5: Package the ICNS asset**

Add to `menu-bar/Resources/Info.plist`:

```xml
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
```

In `scripts/build_menu_app.sh`, immediately after copying `Info.plist`, add:

```bash
mkdir -p "$STAGED_APP/Contents/Resources"
cp "$PACKAGE/Resources/AppIcon.icns" "$STAGED_APP/Contents/Resources/AppIcon.icns"
```

- [ ] **Step 6: Rebuild the helper and verify packaging**

Run:

```bash
scripts/build_menu_app.sh
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_packaging -v
codesign --verify --deep --strict assets/CodexSpeakMenu.app
```

Expected: packaging tests PASS and strict codesign verification exits `0`.

- [ ] **Step 7: Commit the exported assets and packaging**

```bash
git add scripts/render_icon_assets.swift assets/codex-speak-github.png \
  menu-bar/Resources/AppIcon.icns menu-bar/Resources/Info.plist \
  scripts/build_menu_app.sh tests/test_packaging.py assets/CodexSpeakMenu.app
git commit -m "feat: package codex speak app icon"
```

---

### Task 5: Document the brand asset and run release-grade verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: completed assets and packaged helper from Tasks 1–4.
- Produces: a public README preview and a verified repository ready for the normal release/reinstall workflow; this task does not publish or change the GitHub repository avatar without separate user authorization.

- [ ] **Step 1: Add a failing README assertion**

Add to `tests/test_packaging.py`:

```python
    def test_readme_displays_the_public_icon_asset(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("![Codex Speak icon](assets/codex-speak-github.png)", readme)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_packaging.PackagingTests.test_readme_displays_the_public_icon_asset -v
```

Expected: FAIL because README does not yet reference the icon.

- [ ] **Step 3: Add the README icon preview**

Insert immediately below `# Codex Speak`:

```markdown
![Codex Speak icon](assets/codex-speak-github.png)
```

- [ ] **Step 4: Run complete verification**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m compileall -q hooks codex_speak tests
python3 -m json.tool hooks/hooks.json >/dev/null
swift test --package-path menu-bar -Xswiftc -warnings-as-errors
scripts/build_menu_app.sh
lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
codesign --verify --deep --strict assets/CodexSpeakMenu.app
git diff --check
git status --short
```

Expected: all Python and Swift tests PASS; JSON and compilation checks exit `0`; helper architectures are exactly `arm64 x86_64` in either order; codesign passes; `git diff --check` is empty; only the intended README and test files remain modified before commit.

- [ ] **Step 5: Commit the documentation and final verification lock**

```bash
git add README.md tests/test_packaging.py
git commit -m "docs: display codex speak icon"
```

- [ ] **Step 6: Present the finished assets for user acceptance**

Show `assets/codex-speak-github.png` and a screenshot of the actual running menu-bar icon on both light and dark appearances. Report that GitHub avatar publication and formal plugin reinstall remain separate actions requiring explicit user authorization.
