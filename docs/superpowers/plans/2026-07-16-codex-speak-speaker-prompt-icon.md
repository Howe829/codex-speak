# Codex Speak Speaker-Prompt Icon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the user-selected Codex Speak icon as one speaker/megaphone container with the exact `>_` prompt embedded as negative space across App/GitHub and the macOS menu bar.

**Architecture:** Two deterministic SVG masters share one normalized `24 × 24` bottom-origin geometry, while pure geometry types in `CodexSpeakCore` provide the same values to AppKit drawing in `CodexSpeakMenu`. The menu icon clears the prompt from template-image alpha; a local Swift renderer exports the App/GitHub SVG to PNG and ICNS without reading the Image Gen reference or adding runtime dependencies.

**Tech Stack:** SVG, Python 3.10 `unittest` and `xml.etree.ElementTree`, Swift 6, AppKit, `iconutil`, plist packaging, universal Mach-O assembly, ad-hoc codesigning.

## Global Constraints

- The speaker is one closed silhouette, not a speaker beside a terminal logo.
- The chevron and underscore are two separate negative-space cutouts inside the speaker. Neither cutout is an adjacent or overlaid second logo.
- The prompt is exactly `>_`; the underscore may not be removed, merged into the chevron, replaced with a dot, or hidden at the smallest size.
- The family has no enclosing circle, sound arcs, microphone, waveform bars, OpenAI mark, text label, or extra symbol.
- All mark geometry uses a `24 × 24` bottom-origin canvas.
- At `16 px`, the chevron stroke renders at `1.2 px`, the cursor at approximately `2.67 × 1.07 px`, and the horizontal gap between chevron vertex and cursor at approximately `0.87 px`.
- If `>` and `_` are not both distinct at `16 px`, implementation stops for a geometry revision.
- The App/GitHub background is a linear gradient from deep indigo `#2636A7` to violet `#6D28D9`; the speaker is a linear gradient from white `#FFFFFF` to icy cyan `#C7F2FF`.
- The menu-bar icon is a monochrome macOS template `NSImage` with no background and no enclosing circle.
- Image Gen and the selected raster are not read by build, render, package, or runtime code.
- Runtime requirements remain macOS 13.0 or newer and Python 3.10 or newer.
- Runtime uses only the Python standard library and macOS frameworks.
- Runtime adds no third-party dependency, network service, download, API key, or generated-asset service.

---

### Task 1: Lock the selected concept and ignore local companion state

**Files:**
- Modify: `.gitignore`
- Track: `artwork/concepts/codex-speak-speaker-prompt-variant.png`
- Modify: `docs/superpowers/specs/2026-07-16-codex-speak-icon-design.md`
- Modify: `docs/superpowers/plans/2026-07-16-codex-speak-icon-family.md`
- Create: `docs/superpowers/specs/2026-07-16-codex-speak-speaker-prompt-icon-design.md`
- Create: `docs/superpowers/plans/2026-07-16-codex-speak-speaker-prompt-icon.md`

**Interfaces:**
- Consumes: the already user-approved local concept raster; this task does not invoke Image Gen or revise its composition.
- Produces: a tracked immutable visual reference with SHA-256 `aeb7c9a69acac3d0aa6e89750d1f09a49ebabde99552bbe1911fc43959ccff92`, plus an ignore rule for local `.superpowers/` state.

- [ ] **Step 1: Verify the expected pre-existing local state**

Run:

```bash
git status --short -- .gitignore artwork/concepts/codex-speak-speaker-prompt-variant.png
```

Expected:

```text
 M .gitignore
?? artwork/concepts/codex-speak-speaker-prompt-variant.png
```

Do not overwrite or regenerate the PNG.

- [ ] **Step 2: Verify the selected raster identity and dimensions**

Run:

```bash
shasum -a 256 artwork/concepts/codex-speak-speaker-prompt-variant.png
sips -g pixelWidth -g pixelHeight artwork/concepts/codex-speak-speaker-prompt-variant.png
```

Expected: SHA-256 is exactly
`aeb7c9a69acac3d0aa6e89750d1f09a49ebabde99552bbe1911fc43959ccff92`,
pixel width is `1536`, and pixel height is `1024`. Stop if any value differs.

- [ ] **Step 3: Verify the local-state ignore rule is exact and unique**

The end of `.gitignore` must contain this exact rule once:

```gitignore
.superpowers/
```

Run:

```bash
grep -c '^\.superpowers/$' .gitignore
git check-ignore .superpowers/sdd/implementation-state.md
```

Expected: the first command prints `1`; the second prints
`.superpowers/sdd/implementation-state.md` and exits `0`.

- [ ] **Step 4: Confirm the approved composition is the only reference**

Inspect `artwork/concepts/codex-speak-speaker-prompt-variant.png` and confirm
all of the following before committing: one speaker container, `>` and `_`
inside it, the same mark in App/GitHub and menu-bar examples, no enclosing
circle around the menu mark, and no arcs, microphone, waveform bars, OpenAI
mark, or adjacent symbol. This is a verification of the already approved
selection, not a new approval gate.

- [ ] **Step 5: Preserve the rejected comparison outside tracked artwork**

The unselected three-pulse comparison is not a production or design-history
deliverable. Move it into the ignored SDD state directory without deleting it:

```bash
mkdir -p .superpowers/sdd
mv artwork/concepts/codex-speak-three-pulse.png \
  .superpowers/sdd/rejected-three-pulse.png
```

Expected: `artwork/concepts/` contains only
`codex-speak-speaker-prompt-variant.png`, while the rejected comparison remains
available under ignored local state.

- [ ] **Step 6: Commit the selected concept, replacement docs, and ignore rule**

```bash
git add .gitignore artwork/concepts/codex-speak-speaker-prompt-variant.png \
  docs/superpowers/specs/2026-07-16-codex-speak-icon-design.md \
  docs/superpowers/plans/2026-07-16-codex-speak-icon-family.md \
  docs/superpowers/specs/2026-07-16-codex-speak-speaker-prompt-icon-design.md \
  docs/superpowers/plans/2026-07-16-codex-speak-speaker-prompt-icon.md
git commit -m "design: lock speaker prompt icon concept"
```

---

### Task 2: Create deterministic SVG masters and asset tests

**Files:**
- Create: `artwork/codex-speak-speaker-prompt.svg`
- Create: `artwork/codex-speak-app-icon.svg`
- Create: `tests/test_icon_assets.py`

**Interfaces:**
- Consumes: Task 1's concept for visual intent only and the exact `24 × 24` bottom-origin geometry in the design specification.
- Produces: `artwork/codex-speak-speaker-prompt.svg` and
  `artwork/codex-speak-app-icon.svg`, both using the exact container path
  `M 5.5 5 C 4.4 5 3.5 5.9 3.5 7 L 3.5 17 C 3.5 18.1 4.4 19 5.5 19 L 10 19 L 18.7 21.5 C 19.55 21.75 20.4 21.1 20.4 20.2 L 20.4 3.8 C 20.4 2.9 19.55 2.25 18.7 2.5 L 10 5 Z`,
  `>` chevron points `(6.4, 14.6)`, `(9.5, 12)`, `(6.4, 9.4)`, and `_`
  cursor rectangle `(10.8, 8.6, 4.0, 1.6, radius 0.8)`.

- [ ] **Step 1: Write the failing SVG asset tests**

Create `tests/test_icon_assets.py`:

```python
from pathlib import Path
import math
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"
MENU_MASTER = ROOT / "artwork" / "codex-speak-speaker-prompt.svg"
APP_MASTER = ROOT / "artwork" / "codex-speak-app-icon.svg"
CONTAINER_PATH = (
    "M 5.5 5 C 4.4 5 3.5 5.9 3.5 7 "
    "L 3.5 17 C 3.5 18.1 4.4 19 5.5 19 "
    "L 10 19 L 18.7 21.5 "
    "C 19.55 21.75 20.4 21.1 20.4 20.2 "
    "L 20.4 3.8 C 20.4 2.9 19.55 2.25 18.7 2.5 "
    "L 10 5 Z"
)
CHEVRON_PATH = "M 6.4 14.6 L 9.5 12 L 6.4 9.4"
CURSOR_ATTRIBUTES = {
    "x": "10.8",
    "y": "8.6",
    "width": "4",
    "height": "1.6",
    "rx": "0.8",
}


def parsed(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def required(root: ET.Element, xpath: str) -> ET.Element:
    element = root.find(xpath)
    if element is None:
        raise AssertionError(f"missing SVG element: {xpath}")
    return element


def normalized_geometry(path: Path) -> tuple[str, str, dict[str, str]]:
    root = parsed(path)
    container = required(root, f".//{SVG}path[@id='speaker-container']")
    chevron = required(
        root,
        f".//{SVG}mask[@id='prompt-cutout']/{SVG}path[@id='prompt-chevron']",
    )
    cursor = required(
        root,
        f".//{SVG}mask[@id='prompt-cutout']/{SVG}rect[@id='prompt-cursor']",
    )
    cursor_values = {name: cursor.attrib[name] for name in CURSOR_ATTRIBUTES}
    return container.attrib["d"], chevron.attrib["d"], cursor_values


class IconAssetTests(unittest.TestCase):
    def test_both_masters_use_identical_normalized_geometry(self) -> None:
        expected = (CONTAINER_PATH, CHEVRON_PATH, CURSOR_ATTRIBUTES)
        self.assertEqual(normalized_geometry(MENU_MASTER), expected)
        self.assertEqual(normalized_geometry(APP_MASTER), expected)

    def test_prompt_is_two_separate_negative_space_cutouts(self) -> None:
        for path in (MENU_MASTER, APP_MASTER):
            with self.subTest(path=path.name):
                root = parsed(path)
                mask = required(root, f".//{SVG}mask[@id='prompt-cutout']")
                mask_fill = required(
                    mask,
                    f"{SVG}rect[@id='prompt-mask-fill']",
                )
                chevron = required(mask, f"{SVG}path[@id='prompt-chevron']")
                cursor = required(mask, f"{SVG}rect[@id='prompt-cursor']")
                container = required(
                    root,
                    f".//{SVG}path[@id='speaker-container']",
                )
                self.assertEqual(mask.attrib["maskUnits"], "userSpaceOnUse")
                self.assertEqual(mask_fill.attrib["fill"], "#FFFFFF")
                self.assertEqual(chevron.attrib["fill"], "none")
                self.assertEqual(chevron.attrib["stroke"], "#000000")
                self.assertEqual(chevron.attrib["stroke-width"], "1.8")
                self.assertEqual(chevron.attrib["stroke-linecap"], "round")
                self.assertEqual(chevron.attrib["stroke-linejoin"], "round")
                self.assertEqual(cursor.attrib["fill"], "#000000")
                self.assertEqual(container.attrib["mask"], "url(#prompt-cutout)")

    def test_svg_transforms_preserve_bottom_origin_coordinates(self) -> None:
        menu_group = required(
            parsed(MENU_MASTER),
            f".//{SVG}g[@id='integrated-mark']",
        )
        app_group = required(
            parsed(APP_MASTER),
            f".//{SVG}g[@id='integrated-mark']",
        )
        self.assertEqual(
            menu_group.attrib["transform"],
            "translate(0 24) scale(1 -1)",
        )
        self.assertEqual(
            app_group.attrib["transform"],
            "translate(176 848) scale(28 -28)",
        )

    def test_exact_prompt_has_sufficient_separation_at_sixteen_pixels(self) -> None:
        scale = 16 / 24
        self.assertAlmostEqual(1.8 * scale, 1.2, places=6)
        self.assertGreaterEqual(4.0 * scale, 2.66)
        self.assertGreaterEqual(1.6 * scale, 1.06)
        self.assertGreaterEqual((10.8 - 9.5) * scale, 0.86)

    def test_app_mark_is_safe_inside_circular_avatar_crop(self) -> None:
        center = 512.0
        safe_radius = 448.0
        for x in (3.5, 20.4):
            for y in (2.25, 21.75):
                mapped_x = 176 + 28 * x
                mapped_y = 848 - 28 * y
                self.assertLess(
                    math.hypot(mapped_x - center, mapped_y - center),
                    safe_radius,
                )

    def test_app_palette_and_rounded_square_are_exact(self) -> None:
        root = parsed(APP_MASTER)
        background_gradient = required(
            root,
            f".//{SVG}linearGradient[@id='background-gradient']",
        )
        container_gradient = required(
            root,
            f".//{SVG}linearGradient[@id='container-gradient']",
        )
        background = required(root, f".//{SVG}rect[@id='app-background']")
        container = required(root, f".//{SVG}path[@id='speaker-container']")
        menu_container = required(
            parsed(MENU_MASTER),
            f".//{SVG}path[@id='speaker-container']",
        )

        self.assertEqual(
            [
                (stop.attrib["offset"], stop.attrib["stop-color"])
                for stop in background_gradient.findall(f"{SVG}stop")
            ],
            [("0", "#2636A7"), ("1", "#6D28D9")],
        )
        self.assertEqual(
            [
                (stop.attrib["offset"], stop.attrib["stop-color"])
                for stop in container_gradient.findall(f"{SVG}stop")
            ],
            [("0", "#FFFFFF"), ("1", "#C7F2FF")],
        )
        self.assertEqual(
            {name: background.attrib[name] for name in ("x", "y", "width", "height", "rx")},
            {"x": "32", "y": "32", "width": "960", "height": "960", "rx": "224"},
        )
        self.assertEqual(container.attrib["fill"], "url(#container-gradient)")
        self.assertEqual(menu_container.attrib["fill"], "#000000")

    def test_masters_contain_no_prohibited_or_extra_symbol(self) -> None:
        expected_ids = {
            MENU_MASTER: {
                "prompt-cutout",
                "prompt-mask-fill",
                "prompt-chevron",
                "prompt-cursor",
                "integrated-mark",
                "speaker-container",
            },
            APP_MASTER: {
                "background-gradient",
                "container-gradient",
                "prompt-cutout",
                "prompt-mask-fill",
                "prompt-chevron",
                "prompt-cursor",
                "app-background",
                "integrated-mark",
                "speaker-container",
            },
        }
        for path, expected in expected_ids.items():
            with self.subTest(path=path.name):
                root = parsed(path)
                ids = {
                    element.attrib["id"]
                    for element in root.iter()
                    if "id" in element.attrib
                }
                self.assertEqual(ids, expected)
                self.assertEqual(root.findall(f".//{SVG}circle"), [])
                self.assertEqual(root.findall(f".//{SVG}text"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the asset tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_icon_assets -v
```

Expected: `ERROR` because `artwork/codex-speak-speaker-prompt.svg` and
`artwork/codex-speak-app-icon.svg` do not exist. Do not weaken the assertions.

- [ ] **Step 3: Create the deterministic monochrome SVG master**

Create `artwork/codex-speak-speaker-prompt.svg`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <title>Codex Speak speaker prompt mark</title>
  <defs>
    <mask id="prompt-cutout" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
      <rect id="prompt-mask-fill" x="0" y="0" width="24" height="24" fill="#FFFFFF"/>
      <path id="prompt-chevron" d="M 6.4 14.6 L 9.5 12 L 6.4 9.4" fill="none" stroke="#000000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <rect id="prompt-cursor" x="10.8" y="8.6" width="4" height="1.6" rx="0.8" fill="#000000"/>
    </mask>
  </defs>
  <g id="integrated-mark" transform="translate(0 24) scale(1 -1)">
    <path id="speaker-container" d="M 5.5 5 C 4.4 5 3.5 5.9 3.5 7 L 3.5 17 C 3.5 18.1 4.4 19 5.5 19 L 10 19 L 18.7 21.5 C 19.55 21.75 20.4 21.1 20.4 20.2 L 20.4 3.8 C 20.4 2.9 19.55 2.25 18.7 2.5 L 10 5 Z" fill="#000000" mask="url(#prompt-cutout)"/>
  </g>
</svg>
```

- [ ] **Step 4: Create the deterministic App/GitHub SVG master**

Create `artwork/codex-speak-app-icon.svg`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <title>Codex Speak app icon</title>
  <defs>
    <linearGradient id="background-gradient" x1="96" y1="80" x2="928" y2="944" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#2636A7"/>
      <stop offset="1" stop-color="#6D28D9"/>
    </linearGradient>
    <linearGradient id="container-gradient" x1="4" y1="19" x2="20" y2="4" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="1" stop-color="#C7F2FF"/>
    </linearGradient>
    <mask id="prompt-cutout" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
      <rect id="prompt-mask-fill" x="0" y="0" width="24" height="24" fill="#FFFFFF"/>
      <path id="prompt-chevron" d="M 6.4 14.6 L 9.5 12 L 6.4 9.4" fill="none" stroke="#000000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <rect id="prompt-cursor" x="10.8" y="8.6" width="4" height="1.6" rx="0.8" fill="#000000"/>
    </mask>
  </defs>
  <rect id="app-background" x="32" y="32" width="960" height="960" rx="224" fill="url(#background-gradient)"/>
  <g id="integrated-mark" transform="translate(176 848) scale(28 -28)">
    <path id="speaker-container" d="M 5.5 5 C 4.4 5 3.5 5.9 3.5 7 L 3.5 17 C 3.5 18.1 4.4 19 5.5 19 L 10 19 L 18.7 21.5 C 19.55 21.75 20.4 21.1 20.4 20.2 L 20.4 3.8 C 20.4 2.9 19.55 2.25 18.7 2.5 L 10 5 Z" fill="url(#container-gradient)" mask="url(#prompt-cutout)"/>
  </g>
</svg>
```

- [ ] **Step 5: Run the deterministic asset tests**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_icon_assets -v
```

Expected: all `7` tests PASS. If the `16 px` separation test fails, stop and
revise the specification and both masters together; do not remove the cursor
or lower the asserted thresholds.

- [ ] **Step 6: Commit the SVG masters and tests**

```bash
git add artwork/codex-speak-speaker-prompt.svg artwork/codex-speak-app-icon.svg tests/test_icon_assets.py
git commit -m "feat: add speaker prompt icon masters"
```

---

### Task 3: Draw the AppKit menu template icon and integrate it

**Files:**
- Create: `menu-bar/Sources/CodexSpeakCore/IconGeometry.swift`
- Create: `menu-bar/Sources/CodexSpeakMenu/StatusIcon.swift`
- Create: `menu-bar/Tests/CodexSpeakCoreTests/IconGeometryTests.swift`
- Modify: `menu-bar/Sources/CodexSpeakMenu/MenuController.swift`
- Modify: `tests/test_packaging.py`
- Verify unchanged: `menu-bar/Package.swift` (SwiftPM automatically includes new source and test files in the existing `CodexSpeakCore`, `CodexSpeakMenu`, and `CodexSpeakCoreTests` targets.)

**Interfaces:**
- Consumes: Task 2's normalized geometry and the existing `CodexSpeakCore` dependency of the `CodexSpeakMenu` executable target.
- Produces: `IconPoint`, `IconRect`, `IconPathCommand`, `CodexSpeakIconGeometry.speakerContainer: [IconPathCommand]`, `CodexSpeakIconGeometry.chevronCutout: [IconPoint]`, `CodexSpeakIconGeometry.cursorCutout: IconRect`, and `StatusIcon.makeTemplateImage() -> NSImage`; `MenuController` uses the template image in both normal and transient-error states.

- [ ] **Step 1: Write the failing Swift geometry and packaging tests**

Create `menu-bar/Tests/CodexSpeakCoreTests/IconGeometryTests.swift`:

```swift
import XCTest
@testable import CodexSpeakCore

final class IconGeometryTests: XCTestCase {
    func testSpeakerContainerIsTheExactSingleClosedPath() {
        XCTAssertEqual(
            CodexSpeakIconGeometry.speakerContainer,
            [
                .move(IconPoint(x: 5.5, y: 5)),
                .cubic(
                    control1: IconPoint(x: 4.4, y: 5),
                    control2: IconPoint(x: 3.5, y: 5.9),
                    to: IconPoint(x: 3.5, y: 7)
                ),
                .line(IconPoint(x: 3.5, y: 17)),
                .cubic(
                    control1: IconPoint(x: 3.5, y: 18.1),
                    control2: IconPoint(x: 4.4, y: 19),
                    to: IconPoint(x: 5.5, y: 19)
                ),
                .line(IconPoint(x: 10, y: 19)),
                .line(IconPoint(x: 18.7, y: 21.5)),
                .cubic(
                    control1: IconPoint(x: 19.55, y: 21.75),
                    control2: IconPoint(x: 20.4, y: 21.1),
                    to: IconPoint(x: 20.4, y: 20.2)
                ),
                .line(IconPoint(x: 20.4, y: 3.8)),
                .cubic(
                    control1: IconPoint(x: 20.4, y: 2.9),
                    control2: IconPoint(x: 19.55, y: 2.25),
                    to: IconPoint(x: 18.7, y: 2.5)
                ),
                .line(IconPoint(x: 10, y: 5)),
                .close,
            ]
        )
        XCTAssertEqual(
            CodexSpeakIconGeometry.speakerContainer.filter { $0 == .close }.count,
            1
        )
    }

    func testPromptUsesSeparateChevronAndCursorCutouts() {
        XCTAssertEqual(
            CodexSpeakIconGeometry.chevronCutout,
            [
                IconPoint(x: 6.4, y: 14.6),
                IconPoint(x: 9.5, y: 12),
                IconPoint(x: 6.4, y: 9.4),
            ]
        )
        XCTAssertEqual(CodexSpeakIconGeometry.chevronLineWidth, 1.8)
        XCTAssertEqual(
            CodexSpeakIconGeometry.cursorCutout,
            IconRect(x: 10.8, y: 8.6, width: 4, height: 1.6)
        )
        XCTAssertEqual(CodexSpeakIconGeometry.cursorCornerRadius, 0.8)
        XCTAssertGreaterThan(
            CodexSpeakIconGeometry.cursorCutout.x,
            CodexSpeakIconGeometry.chevronCutout.map(\.x).max()!
        )
    }

    func testExactPromptRemainsDistinctAtSixteenPixels() {
        let scale = 16.0 / CodexSpeakIconGeometry.canvasSize
        let stroke = CodexSpeakIconGeometry.chevronLineWidth * scale
        let cursorWidth = CodexSpeakIconGeometry.cursorCutout.width * scale
        let cursorHeight = CodexSpeakIconGeometry.cursorCutout.height * scale
        let gap = (
            CodexSpeakIconGeometry.cursorCutout.x
                - CodexSpeakIconGeometry.chevronCutout[1].x
        ) * scale

        XCTAssertEqual(stroke, 1.2, accuracy: 0.001)
        XCTAssertEqual(cursorWidth, 2.666_667, accuracy: 0.001)
        XCTAssertEqual(cursorHeight, 1.066_667, accuracy: 0.001)
        XCTAssertEqual(gap, 0.866_667, accuracy: 0.001)
        XCTAssertGreaterThanOrEqual(stroke, 1.19)
        XCTAssertGreaterThanOrEqual(cursorHeight, 1.06)
        XCTAssertGreaterThanOrEqual(gap, 0.86)
    }
}
```

Add this complete test method to `PackagingTests` in `tests/test_packaging.py`:

```python
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
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
swift test --package-path menu-bar --filter IconGeometryTests
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_packaging.PackagingTests.test_menu_uses_one_template_mark_with_alpha_prompt_cutouts -v
```

Expected: the Swift build fails because `CodexSpeakIconGeometry` is missing;
the Python test fails because `StatusIcon.swift` is missing and the controller
still uses text glyphs.

- [ ] **Step 3: Implement the pure shared geometry**

Create `menu-bar/Sources/CodexSpeakCore/IconGeometry.swift`:

```swift
public struct IconPoint: Equatable, Sendable {
    public let x: Double
    public let y: Double

    public init(x: Double, y: Double) {
        self.x = x
        self.y = y
    }
}

public struct IconRect: Equatable, Sendable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double

    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }
}

public enum IconPathCommand: Equatable, Sendable {
    case move(IconPoint)
    case line(IconPoint)
    case cubic(control1: IconPoint, control2: IconPoint, to: IconPoint)
    case close
}

public enum CodexSpeakIconGeometry {
    public static let canvasSize = 24.0
    public static let templatePointSize = 18.0

    public static let speakerContainer: [IconPathCommand] = [
        .move(IconPoint(x: 5.5, y: 5)),
        .cubic(
            control1: IconPoint(x: 4.4, y: 5),
            control2: IconPoint(x: 3.5, y: 5.9),
            to: IconPoint(x: 3.5, y: 7)
        ),
        .line(IconPoint(x: 3.5, y: 17)),
        .cubic(
            control1: IconPoint(x: 3.5, y: 18.1),
            control2: IconPoint(x: 4.4, y: 19),
            to: IconPoint(x: 5.5, y: 19)
        ),
        .line(IconPoint(x: 10, y: 19)),
        .line(IconPoint(x: 18.7, y: 21.5)),
        .cubic(
            control1: IconPoint(x: 19.55, y: 21.75),
            control2: IconPoint(x: 20.4, y: 21.1),
            to: IconPoint(x: 20.4, y: 20.2)
        ),
        .line(IconPoint(x: 20.4, y: 3.8)),
        .cubic(
            control1: IconPoint(x: 20.4, y: 2.9),
            control2: IconPoint(x: 19.55, y: 2.25),
            to: IconPoint(x: 18.7, y: 2.5)
        ),
        .line(IconPoint(x: 10, y: 5)),
        .close,
    ]

    public static let chevronCutout = [
        IconPoint(x: 6.4, y: 14.6),
        IconPoint(x: 9.5, y: 12),
        IconPoint(x: 6.4, y: 9.4),
    ]
    public static let chevronLineWidth = 1.8
    public static let cursorCutout = IconRect(x: 10.8, y: 8.6, width: 4, height: 1.6)
    public static let cursorCornerRadius = 0.8
}
```

- [ ] **Step 4: Implement AppKit drawing with true alpha cutouts**

Create `menu-bar/Sources/CodexSpeakMenu/StatusIcon.swift`:

```swift
import AppKit
import CodexSpeakCore

@MainActor
enum StatusIcon {
    static func makeTemplateImage() -> NSImage {
        let pointSize = CGFloat(CodexSpeakIconGeometry.templatePointSize)
        let image = NSImage(
            size: NSSize(width: pointSize, height: pointSize),
            flipped: false
        ) { _ in
            NSGraphicsContext.saveGraphicsState()
            defer { NSGraphicsContext.restoreGraphicsState() }

            let scale = pointSize / CGFloat(CodexSpeakIconGeometry.canvasSize)
            let transform = NSAffineTransform()
            transform.scaleX(by: scale, yBy: scale)
            transform.concat()

            NSColor.black.setFill()
            speakerPath().fill()

            NSGraphicsContext.current?.compositingOperation = .clear
            NSColor.clear.setStroke()
            let chevron = NSBezierPath()
            let points = CodexSpeakIconGeometry.chevronCutout
            chevron.move(to: nsPoint(points[0]))
            chevron.line(to: nsPoint(points[1]))
            chevron.line(to: nsPoint(points[2]))
            chevron.lineWidth = CGFloat(CodexSpeakIconGeometry.chevronLineWidth)
            chevron.lineCapStyle = .round
            chevron.lineJoinStyle = .round
            chevron.stroke()

            NSColor.clear.setFill()
            let cursor = CodexSpeakIconGeometry.cursorCutout
            NSBezierPath(
                roundedRect: NSRect(
                    x: CGFloat(cursor.x),
                    y: CGFloat(cursor.y),
                    width: CGFloat(cursor.width),
                    height: CGFloat(cursor.height)
                ),
                xRadius: CGFloat(CodexSpeakIconGeometry.cursorCornerRadius),
                yRadius: CGFloat(CodexSpeakIconGeometry.cursorCornerRadius)
            ).fill()
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = "Codex Speak"
        return image
    }

    private static func speakerPath() -> NSBezierPath {
        let path = NSBezierPath()
        for command in CodexSpeakIconGeometry.speakerContainer {
            switch command {
            case let .move(point):
                path.move(to: nsPoint(point))
            case let .line(point):
                path.line(to: nsPoint(point))
            case let .cubic(control1, control2, point):
                path.curve(
                    to: nsPoint(point),
                    controlPoint1: nsPoint(control1),
                    controlPoint2: nsPoint(control2)
                )
            case .close:
                path.close()
            }
        }
        return path
    }

    private static func nsPoint(_ point: IconPoint) -> NSPoint {
        NSPoint(x: CGFloat(point.x), y: CGFloat(point.y))
    }
}
```

- [ ] **Step 5: Replace both normal and transient text states with the mark**

In `MenuController.init`, replace:

```swift
        statusItem.button?.title = "◖))"
        statusItem.button?.toolTip = "Codex Speak"
```

with:

```swift
        applyDefaultStatusIcon()
```

Replace `showLocalError` and `clearLocalError`, and add
`applyDefaultStatusIcon`, using this complete block:

```swift
    private func applyDefaultStatusIcon() {
        statusItem.button?.title = ""
        statusItem.button?.image = StatusIcon.makeTemplateImage()
        statusItem.button?.imagePosition = .imageOnly
        statusItem.button?.toolTip = "Codex Speak"
    }

    private func showLocalError(_ message: String) {
        applyDefaultStatusIcon()
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

The tooltip still reports transient errors, but the menu-bar image never
changes to an extra `!` or system symbol.

- [ ] **Step 6: Run focused and full menu-helper tests**

Run:

```bash
swift test --package-path menu-bar --filter IconGeometryTests
swift test --package-path menu-bar -Xswiftc -warnings-as-errors
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_packaging.PackagingTests.test_menu_uses_one_template_mark_with_alpha_prompt_cutouts -v
```

Expected: `IconGeometryTests` runs `3` passing tests, the full Swift suite
passes with warnings treated as errors, and the focused packaging test PASSes.
If the `16 px` test fails, stop; do not simplify `>_`.

- [ ] **Step 7: Commit the menu-bar geometry and integration**

```bash
git add menu-bar/Sources/CodexSpeakCore/IconGeometry.swift \
  menu-bar/Sources/CodexSpeakMenu/StatusIcon.swift \
  menu-bar/Sources/CodexSpeakMenu/MenuController.swift \
  menu-bar/Tests/CodexSpeakCoreTests/IconGeometryTests.swift \
  tests/test_packaging.py
git commit -m "feat: integrate speaker prompt menu icon"
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
- Rebuild: `assets/CodexSpeakMenu.app`

**Interfaces:**
- Consumes: `artwork/codex-speak-app-icon.svg` from Task 2 and the existing two-architecture local build/signing flow.
- Produces: executable `scripts/render_icon_assets.swift`, a `1024 × 1024` `assets/codex-speak-github.png`, a valid `menu-bar/Resources/AppIcon.icns`, and a signed universal helper containing `Contents/Resources/AppIcon.icns` with `CFBundleIconFile = AppIcon`.

- [ ] **Step 1: Write failing renderer, asset, metadata, and copy assertions**

Add `struct` to the imports in `tests/test_packaging.py`:

```python
import struct
```

Add this complete test method to `PackagingTests`:

```python
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

        png_header = github_icon.read_bytes()[:24]
        self.assertEqual(png_header[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(png_header[12:16], b"IHDR")
        self.assertEqual(struct.unpack(">II", png_header[16:24]), (1024, 1024))

        icns_header = app_icon.read_bytes()[:8]
        self.assertEqual(icns_header[:4], b"icns")
        self.assertEqual(struct.unpack(">I", icns_header[4:8])[0], app_icon.stat().st_size)
        self.assertGreater(app_icon.stat().st_size, 1024)
```

Replace `test_embedded_helper_has_exact_metadata_and_is_executable` with this
complete method so the exact-dictionary expectation includes the new key:

```python
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
```

Add these two assertions to
`test_build_script_is_local_and_builds_both_release_architectures`:

```python
        self.assertIn('mkdir -p "$STAGED_APP/Contents/Resources"', script)
        self.assertIn(
            'cp "$PACKAGE/Resources/AppIcon.icns" "$STAGED_APP/Contents/Resources/AppIcon.icns"',
            script,
        )
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest \
  tests.test_packaging.PackagingTests.test_public_icon_assets_are_deterministic_and_complete \
  tests.test_packaging.PackagingTests.test_embedded_helper_has_exact_metadata_and_is_executable \
  tests.test_packaging.PackagingTests.test_build_script_is_local_and_builds_both_release_architectures -v
```

Expected: the asset test errors because the renderer and exported files do
not exist; the metadata test fails because `CFBundleIconFile` and the bundled
ICNS are absent; the build-script test fails because it does not copy the
resource.

- [ ] **Step 3: Create the deterministic local Swift renderer**

Create `scripts/render_icon_assets.swift` with executable mode `0755`:

```swift
#!/usr/bin/env swift
import AppKit
import Foundation

enum IconRenderError: Error {
    case sourceUnavailable(URL)
    case bitmapUnavailable(Int)
    case graphicsContextUnavailable(Int)
    case pngUnavailable(Int)
    case iconutilFailed(Int32)
}

let fileManager = FileManager.default
let root = URL(
    fileURLWithPath: fileManager.currentDirectoryPath,
    isDirectory: true
)
let sourceURL = root.appendingPathComponent("artwork/codex-speak-app-icon.svg")
let githubURL = root.appendingPathComponent("assets/codex-speak-github.png")
let iconsetURL = root.appendingPathComponent(".build/CodexSpeak.iconset", isDirectory: true)
let icnsURL = root.appendingPathComponent("menu-bar/Resources/AppIcon.icns")

guard let source = NSImage(contentsOf: sourceURL) else {
    throw IconRenderError.sourceUnavailable(sourceURL)
}

func render(pixels: Int, to outputURL: URL) throws {
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
    ) else {
        throw IconRenderError.bitmapUnavailable(pixels)
    }
    bitmap.size = NSSize(width: pixels, height: pixels)
    guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        throw IconRenderError.graphicsContextUnavailable(pixels)
    }

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: pixels, height: pixels).fill()
    source.draw(
        in: NSRect(x: 0, y: 0, width: pixels, height: pixels),
        from: .zero,
        operation: .copy,
        fraction: 1
    )
    NSGraphicsContext.restoreGraphicsState()

    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw IconRenderError.pngUnavailable(pixels)
    }
    try fileManager.createDirectory(
        at: outputURL.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try data.write(to: outputURL, options: .atomic)
}

try? fileManager.removeItem(at: iconsetURL)
try fileManager.createDirectory(at: iconsetURL, withIntermediateDirectories: true)
try fileManager.createDirectory(
    at: icnsURL.deletingLastPathComponent(),
    withIntermediateDirectories: true
)

let iconsetExports = [
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
for (pixels, filename) in iconsetExports {
    try render(pixels: pixels, to: iconsetURL.appendingPathComponent(filename))
}
try render(pixels: 1024, to: githubURL)

let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["-c", "icns", iconsetURL.path, "-o", icnsURL.path]
try iconutil.run()
iconutil.waitUntilExit()
guard iconutil.terminationStatus == 0 else {
    throw IconRenderError.iconutilFailed(iconutil.terminationStatus)
}
```

Run:

```bash
chmod 755 scripts/render_icon_assets.swift
```

Expected: `ls -l scripts/render_icon_assets.swift` begins with
`-rwxr-xr-x`.

- [ ] **Step 4: Render and validate the public assets**

Run from the repository root:

```bash
scripts/render_icon_assets.swift
sips -g pixelWidth -g pixelHeight assets/codex-speak-github.png
python3 -c 'import struct; from pathlib import Path; p=Path("menu-bar/Resources/AppIcon.icns"); h=p.read_bytes()[:8]; assert h[:4] == b"icns"; assert struct.unpack(">I", h[4:])[0] == p.stat().st_size'
```

Expected: the PNG reports `pixelWidth: 1024` and `pixelHeight: 1024`; the ICNS
validation exits `0`. Inspect the `16 × 16` iconset representation before
continuing. If either `>` or `_` is absent or merged, stop and return to Task 2.

- [ ] **Step 5: Add the exact bundle icon metadata**

Replace `menu-bar/Resources/Info.plist` with:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>en</string>
	<key>CFBundleDisplayName</key>
	<string>Codex Speak</string>
	<key>CFBundleExecutable</key>
	<string>CodexSpeakMenu</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>CFBundleIdentifier</key>
	<string>com.howard.codex-speak.menu</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>Codex Speak</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>LSMinimumSystemVersion</key>
	<string>13.0</string>
	<key>LSUIElement</key>
	<true/>
</dict>
</plist>
```

- [ ] **Step 6: Copy the ICNS before assembling and signing the helper**

Replace `scripts/build_menu_app.sh` with this complete script, preserving its
executable mode:

```bash
#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE="$ROOT/menu-bar"
BUILD_ROOT="$ROOT/.build/menu-app"
APP="$ROOT/assets/CodexSpeakMenu.app"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/codex-speak-menu.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT

export CLANG_MODULE_CACHE_PATH="$BUILD_ROOT/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$BUILD_ROOT/module-cache"

build_arch() {
    local architecture="$1"
    local scratch="$BUILD_ROOT/$architecture"
    swift build \
        --disable-sandbox \
        --package-path "$PACKAGE" \
        --scratch-path "$scratch" \
        --configuration release \
        --arch "$architecture" \
        --product CodexSpeakMenu
}

build_arch arm64
build_arch x86_64

ARM64_BINARY="$BUILD_ROOT/arm64/arm64-apple-macosx/release/CodexSpeakMenu"
X86_64_BINARY="$BUILD_ROOT/x86_64/x86_64-apple-macosx/release/CodexSpeakMenu"
STAGED_APP="$STAGING/CodexSpeakMenu.app"

mkdir -p "$STAGED_APP/Contents/MacOS"
cp "$PACKAGE/Resources/Info.plist" "$STAGED_APP/Contents/Info.plist"
mkdir -p "$STAGED_APP/Contents/Resources"
cp "$PACKAGE/Resources/AppIcon.icns" "$STAGED_APP/Contents/Resources/AppIcon.icns"
lipo -create "$ARM64_BINARY" "$X86_64_BINARY" \
    -output "$STAGED_APP/Contents/MacOS/CodexSpeakMenu"
chmod 755 "$STAGED_APP/Contents/MacOS/CodexSpeakMenu"

mkdir -p "$ROOT/assets"
rm -rf "$APP"
mv "$STAGED_APP" "$APP"

cd "$ROOT"
codesign --force --deep --sign - "assets/CodexSpeakMenu.app"
codesign --verify --deep --strict "assets/CodexSpeakMenu.app"
```

- [ ] **Step 7: Rebuild and run focused packaging verification**

Run:

```bash
scripts/build_menu_app.sh
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest \
  tests.test_packaging.PackagingTests.test_public_icon_assets_are_deterministic_and_complete \
  tests.test_packaging.PackagingTests.test_embedded_helper_has_exact_metadata_and_is_executable \
  tests.test_packaging.PackagingTests.test_build_script_is_local_and_builds_both_release_architectures -v
lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
codesign --verify --deep --strict assets/CodexSpeakMenu.app
```

Expected: all `3` focused tests PASS; architectures are exactly `arm64` and
`x86_64` in either order; strict codesign verification exits `0`.

- [ ] **Step 8: Commit exports, metadata, and the rebuilt helper**

```bash
git add scripts/render_icon_assets.swift assets/codex-speak-github.png \
  menu-bar/Resources/AppIcon.icns menu-bar/Resources/Info.plist \
  scripts/build_menu_app.sh tests/test_packaging.py assets/CodexSpeakMenu.app
git commit -m "feat: package speaker prompt app icon"
```

---

### Task 5: Document the icon and run full verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: the committed deterministic masters, template-image integration, exported public asset, packaged universal helper, and existing local verification workflow from Tasks 1–4.
- Produces: a README that displays the production GitHub icon and a release-grade verification result; this task does not publish a GitHub avatar, release, Marketplace update, or plugin reinstall without separate authorization.

- [ ] **Step 1: Add the failing README production-asset test**

Add this complete method to `PackagingTests` in `tests/test_packaging.py`:

```python
    def test_readme_displays_only_the_production_public_icon(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("![Codex Speak icon](assets/codex-speak-github.png)", readme)
        self.assertNotIn("artwork/concepts/", readme)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_packaging.PackagingTests.test_readme_displays_only_the_production_public_icon -v
```

Expected: FAIL because `README.md` does not yet reference
`assets/codex-speak-github.png`.

- [ ] **Step 3: Display the production icon in README**

Insert this exact line immediately below `# Codex Speak` in `README.md`:

```markdown
![Codex Speak icon](assets/codex-speak-github.png)
```

The top of the README becomes:

```markdown
# Codex Speak

![Codex Speak icon](assets/codex-speak-github.png)

Codex Speak is a local macOS Codex Plugin that speaks turn outcomes with the
system `say` command. It can announce concise outcome summaries or read the
complete visible response, while a private menu bar helper provides playback
controls without adding commands to the conversation.
```

- [ ] **Step 4: Run the focused README test**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest tests.test_packaging.PackagingTests.test_readme_displays_only_the_production_public_icon -v
```

Expected: PASS.

- [ ] **Step 5: Regenerate and run complete automated verification**

Run from the repository root:

```bash
scripts/render_icon_assets.swift
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-icon-pycache \
  python3 -m compileall -q hooks codex_speak tests
python3 -m json.tool hooks/hooks.json >/dev/null
swift test --package-path menu-bar -Xswiftc -warnings-as-errors
scripts/build_menu_app.sh
lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
codesign --verify --deep --strict assets/CodexSpeakMenu.app
plutil -extract CFBundleIconFile raw assets/CodexSpeakMenu.app/Contents/Info.plist
git diff --check
git status --short
```

Expected: all Python and Swift tests PASS; compilation and JSON checks exit
`0`; renderer and helper build exit `0`; architectures are exactly `arm64`
and `x86_64` in either order; strict codesign verification exits `0`;
`plutil` prints `AppIcon`; `git diff --check` prints nothing; and status lists
only `README.md`, `tests/test_packaging.py`, and deterministic regenerated
assets if byte output changed. Any regenerated production asset must be
inspected and included in the Task 5 commit; the concept PNG must remain
unchanged at its locked SHA-256.

- [ ] **Step 6: Run the required visual legibility gate**

Inspect the actual App/GitHub PNG at square and circular crop, then inspect the
actual template `NSImage` in the running menu helper on light and dark macOS
appearances at `16`, `18`, and `22 px`. Confirm all of the following:

```text
speaker container: one compact silhouette
chevron cutout: distinct at 16, 18, and 22 px
cursor cutout: distinct at 16, 18, and 22 px
light appearance: template tint correct, both cutouts transparent
dark appearance: template tint correct, both cutouts transparent
prohibited additions: none
circular crop: integrated mark unclipped and balanced
```

Expected: every line passes. If the exact `>_` is not legible at `16 px`, stop
without committing Task 5 and revise the deterministic geometry in Tasks 2
and 3 together. Do not hide or remove the underscore.

- [ ] **Step 7: Commit documentation and any deterministic rebuild output**

```bash
git add README.md tests/test_packaging.py assets/codex-speak-github.png \
  menu-bar/Resources/AppIcon.icns assets/CodexSpeakMenu.app
git commit -m "docs: display speaker prompt icon"
```

- [ ] **Step 8: Confirm the implementation branch is clean**

Run:

```bash
git status --short
```

Expected: no output. Report the completed local assets and verification
results. Leave GitHub avatar publication, release publication, Marketplace
cachebuster changes, and plugin reinstall for separately authorized work.
