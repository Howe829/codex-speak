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
