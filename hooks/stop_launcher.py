from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys


PLUGIN_NAME = "codex-speak"
MAX_CANDIDATES = 64
MAX_MANIFEST_BYTES = 16_384
VERSION_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:\+codex\.([a-z0-9](?:[a-z0-9-]*[a-z0-9])?))?$"
)


def parse_version(value: str) -> tuple[int, int, int, int, str] | None:
    match = VERSION_PATTERN.fullmatch(value)
    if match is None:
        return None
    major, minor, patch, build = match.groups()
    return (int(major), int(minor), int(patch), int(build is not None), build or "")


def _validated_family(original_root: Path) -> tuple[Path, str] | None:
    original_version = original_root.name
    if parse_version(original_version) is None:
        return None

    family = original_root.parent
    marketplace = family.parent
    try:
        if (
            family.name != PLUGIN_NAME
            or not marketplace.name
            or marketplace.is_symlink()
            or family.is_symlink()
            or not marketplace.is_dir()
            or not family.is_dir()
        ):
            return None
        resolved_marketplace = marketplace.resolve(strict=True)
        resolved_family = family.resolve(strict=True)
        if resolved_family.parent != resolved_marketplace:
            return None
        return resolved_family, original_version
    except (OSError, ValueError):
        return None


def _validate_candidate(
    root: Path, family: Path
) -> tuple[tuple[int, int, int, int, str], Path, Path] | None:
    try:
        if root.parent != family or root.is_symlink() or not root.is_dir():
            return None
        version_key = parse_version(root.name)
        if version_key is None:
            return None

        resolved_family = family.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
        if resolved_root.parent != resolved_family:
            return None

        manifest_dir = root / ".codex-plugin"
        hooks_dir = root / "hooks"
        manifest = manifest_dir / "plugin.json"
        stop_hook = hooks_dir / "stop.py"
        if (
            manifest_dir.is_symlink()
            or hooks_dir.is_symlink()
            or manifest.is_symlink()
            or stop_hook.is_symlink()
            or not manifest.is_file()
            or not stop_hook.is_file()
        ):
            return None

        resolved_manifest_dir = manifest_dir.resolve(strict=True)
        resolved_manifest = manifest.resolve(strict=True)
        expected_manifest_dir = resolved_root / ".codex-plugin"
        expected_manifest = expected_manifest_dir / "plugin.json"
        if (
            resolved_manifest_dir != expected_manifest_dir
            or resolved_manifest != expected_manifest
        ):
            return None
        with manifest.open("rb") as manifest_file:
            content = manifest_file.read(MAX_MANIFEST_BYTES + 1)
        if len(content) > MAX_MANIFEST_BYTES:
            return None
        parsed_manifest = json.loads(content)
        if (
            not isinstance(parsed_manifest, dict)
            or parsed_manifest.get("name") != PLUGIN_NAME
            or not isinstance(parsed_manifest.get("version"), str)
            or parsed_manifest["version"] != root.name
        ):
            return None

        resolved_stop = stop_hook.resolve(strict=True)
        expected_stop = resolved_root / "hooks" / "stop.py"
        if resolved_stop != expected_stop:
            return None
        if resolved_root.parent != resolved_family or resolved_stop.parent != expected_stop.parent:
            return None
        return version_key, resolved_root, resolved_stop
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def select_stop_hook(original_root: Path) -> tuple[Path, Path] | None:
    validated_family = _validated_family(original_root)
    if validated_family is None:
        return None
    family, original_version = validated_family
    original = _validate_candidate(family / original_version, family)
    if original is not None:
        return original[1], original[2]

    try:
        children = list(family.iterdir())
    except OSError:
        return None
    if len(children) > MAX_CANDIDATES:
        return None

    candidates = []
    for child in sorted(children):
        candidate = _validate_candidate(child, family)
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return None
    selected = max(candidates, key=lambda candidate: candidate[0])
    return selected[1], selected[2]


def _write_empty_result() -> int:
    sys.stdout.write("{}\n")
    return 0


def main() -> int:
    try:
        root_value = os.environ.get("PLUGIN_ROOT")
        if not root_value:
            return _write_empty_result()
        selected = select_stop_hook(Path(root_value))
        if selected is None:
            return _write_empty_result()
        selected_root, stop_hook = selected
        validated = _validate_candidate(selected_root, selected_root.parent)
        if validated is None or (validated[1], validated[2]) != selected:
            return _write_empty_result()
        os.environ["PLUGIN_ROOT"] = str(selected_root)
        os.execv(sys.executable, [sys.executable, "-B", str(stop_hook)])
    except BaseException:
        return _write_empty_result()
    return _write_empty_result()


if __name__ == "__main__":
    raise SystemExit(main())
