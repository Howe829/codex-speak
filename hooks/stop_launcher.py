from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys


PLUGIN_NAME = "codex-speak"
MAX_CANDIDATES = 64
MAX_MANIFEST_BYTES = 16_384
VERSION_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:\+codex\.([a-z0-9](?:[a-z0-9-]*[a-z0-9])?))?$"
)
STOP_BOOTSTRAP = (
    "import os\n"
    "import sys\n"
    "descriptor = int(sys.argv[1])\n"
    "source_path = sys.argv[2]\n"
    "try:\n"
    "    with os.fdopen(descriptor, 'rb', closefd=True) as source_file:\n"
    "        source = source_file.read()\n"
    "    code = compile(source, source_path, 'exec')\n"
    "except BaseException:\n"
    "    try:\n"
    "        os.close(descriptor)\n"
    "    except OSError:\n"
    "        pass\n"
    "    sys.stdout.write('{}\\n')\n"
    "    raise SystemExit(0)\n"
    "sys.argv = [source_path]\n"
    "sys.path[0] = os.path.dirname(source_path)\n"
    "namespace = globals()\n"
    "namespace.update(\n"
    "    __name__='__main__',\n"
    "    __file__=source_path,\n"
    "    __cached__=None,\n"
    "    __package__=None,\n"
    "    __spec__=None,\n"
    ")\n"
    "exec(code, namespace, namespace)\n"
)


def parse_version(value: str) -> tuple[int, int, int, int, str] | None:
    match = VERSION_PATTERN.fullmatch(value)
    if match is None:
        return None
    major, minor, patch, build = match.groups()
    return (int(major), int(minor), int(patch), int(build is not None), build or "")


def _same_object(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _matches_open_path(path: Path, descriptor: int, *, directory: bool) -> bool:
    try:
        path_stat = os.stat(path, follow_symlinks=False)
        opened_stat = os.fstat(descriptor)
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        return expected_type(path_stat.st_mode) and expected_type(
            opened_stat.st_mode
        ) and _same_object(path_stat, opened_stat)
    except OSError:
        return False


def _matches_open_entry(
    name: str, parent_descriptor: int, descriptor: int, *, directory: bool
) -> bool:
    try:
        entry_stat = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        opened_stat = os.fstat(descriptor)
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        return expected_type(entry_stat.st_mode) and expected_type(
            opened_stat.st_mode
        ) and _same_object(entry_stat, opened_stat)
    except OSError:
        return False


def _open_family(family: Path) -> tuple[int, Path] | None:
    descriptor = -1
    try:
        before = os.stat(family, follow_symlinks=False)
        if not stat.S_ISDIR(before.st_mode):
            return None
        descriptor = os.open(
            family,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        opened = os.fstat(descriptor)
        after = os.stat(family, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not _same_object(before, opened)
            or not _same_object(opened, after)
        ):
            os.close(descriptor)
            return None
        return descriptor, family.resolve(strict=True)
    except (OSError, ValueError):
        if descriptor >= 0:
            os.close(descriptor)
        return None


def _validate_candidate(
    name: str,
    family: Path,
    family_descriptor: int,
) -> tuple[tuple[int, int, int, int, str], Path, Path, int] | None:
    root_descriptor = manifest_dir_descriptor = hooks_descriptor = -1
    manifest_descriptor = stop_descriptor = -1
    try:
        if Path(name).name != name:
            return None
        version_key = parse_version(name)
        if version_key is None:
            return None
        root_descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=family_descriptor,
        )
        if not _matches_open_entry(
            name, family_descriptor, root_descriptor, directory=True
        ):
            return None
        manifest_dir_descriptor = os.open(
            ".codex-plugin",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_descriptor,
        )
        hooks_descriptor = os.open(
            "hooks",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_descriptor,
        )
        if not _matches_open_entry(
            ".codex-plugin",
            root_descriptor,
            manifest_dir_descriptor,
            directory=True,
        ) or not _matches_open_entry(
            "hooks", root_descriptor, hooks_descriptor, directory=True
        ):
            return None
        manifest_descriptor = os.open(
            "plugin.json",
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=manifest_dir_descriptor,
        )
        stop_descriptor = os.open(
            "stop.py",
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=hooks_descriptor,
        )
        if not _matches_open_entry(
            "plugin.json",
            manifest_dir_descriptor,
            manifest_descriptor,
            directory=False,
        ) or not _matches_open_entry(
            "stop.py", hooks_descriptor, stop_descriptor, directory=False
        ):
            return None
        content = os.read(manifest_descriptor, MAX_MANIFEST_BYTES + 1)
        if len(content) > MAX_MANIFEST_BYTES:
            return None
        parsed_manifest = json.loads(content)
        if (
            not isinstance(parsed_manifest, dict)
            or parsed_manifest.get("name") != PLUGIN_NAME
            or not isinstance(parsed_manifest.get("version"), str)
            or parsed_manifest["version"] != name
        ):
            return None
        if not _matches_open_entry(
            name, family_descriptor, root_descriptor, directory=True
        ) or not _matches_open_path(family, family_descriptor, directory=True):
            return None
        root = family / name
        selected_stop_descriptor = stop_descriptor
        stop_descriptor = -1
        return (
            version_key,
            root,
            root / "hooks" / "stop.py",
            selected_stop_descriptor,
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    finally:
        for descriptor in (
            stop_descriptor,
            manifest_descriptor,
            hooks_descriptor,
            manifest_dir_descriptor,
            root_descriptor,
        ):
            if descriptor >= 0:
                os.close(descriptor)


def _open_selected_stop(original_root: Path) -> tuple[Path, Path, int] | None:
    family = original_root.parent
    opened_family = _open_family(family)
    if opened_family is None:
        return None
    family_descriptor, family = opened_family
    candidates: list[tuple[tuple[int, int, int, int, str], Path, Path, int]] = []
    try:
        original = _validate_candidate(
            original_root.name, family, family_descriptor
        )
        if original is not None:
            return original[1], original[2], original[3]

        children = os.listdir(family_descriptor)
        if len(children) > MAX_CANDIDATES:
            return None
        for child in sorted(children):
            candidate = _validate_candidate(child, family, family_descriptor)
            if candidate is not None:
                candidates.append(candidate)
        if not candidates or not _matches_open_path(
            family, family_descriptor, directory=True
        ):
            return None
        selected = max(candidates, key=lambda candidate: candidate[0])
        candidates.remove(selected)
        return selected[1], selected[2], selected[3]
    except OSError:
        return None
    finally:
        for candidate in candidates:
            os.close(candidate[3])
        os.close(family_descriptor)


def select_stop_hook(original_root: Path) -> tuple[Path, Path] | None:
    selected = _open_selected_stop(original_root)
    if selected is None:
        return None
    selected_root, stop_hook, stop_descriptor = selected
    os.close(stop_descriptor)
    return selected_root, stop_hook


def _write_empty_result() -> int:
    sys.stdout.write("{}\n")
    return 0


def _exec_stop_hook(selected_root: Path, stop_hook: Path, descriptor: int) -> None:
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        raise OSError
    os.set_inheritable(descriptor, True)
    os.environ["PLUGIN_ROOT"] = str(selected_root)
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-B",
            "-c",
            STOP_BOOTSTRAP,
            str(descriptor),
            str(stop_hook),
        ],
    )


def main() -> int:
    stop_descriptor = -1
    try:
        root_value = os.environ.get("PLUGIN_ROOT")
        if not root_value:
            return _write_empty_result()
        selected = _open_selected_stop(Path(root_value))
        if selected is None:
            return _write_empty_result()
        selected_root, stop_hook, stop_descriptor = selected
        _exec_stop_hook(selected_root, stop_hook, stop_descriptor)
    except BaseException:
        return _write_empty_result()
    finally:
        if stop_descriptor >= 0:
            try:
                os.close(stop_descriptor)
            except OSError:
                pass
    return _write_empty_result()


if __name__ == "__main__":
    raise SystemExit(main())
