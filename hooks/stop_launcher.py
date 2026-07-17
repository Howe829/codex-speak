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
STOP_BOOTSTRAP = """\
import importlib.util
import os
import stat
import sys

MAX_MODULES = 256
MAX_MODULE_BYTES = 1_048_576
MAX_TOTAL_MODULE_BYTES = 8_388_608
PLUGIN_PACKAGES = ("codex_speak", "hooks")
root_descriptor = int(sys.argv[1])
stop_descriptor = int(sys.argv[2])
root_path = sys.argv[3]
source_path = sys.argv[4]
module_sources = {}
total_module_bytes = 0


def close_descriptor(descriptor):
    if descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError:
            pass


def read_source(descriptor):
    chunks = []
    remaining = MAX_MODULE_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    source = b"".join(chunks)
    if len(source) > MAX_MODULE_BYTES:
        raise OSError
    return source


def open_source(name, directory_descriptor):
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW,
        dir_fd=directory_descriptor,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError
        return read_source(descriptor)
    finally:
        close_descriptor(descriptor)


def collect_package(directory_descriptor, package_name, logical_directory, depth):
    global total_module_bytes
    if depth > 16:
        raise OSError
    entries = os.listdir(directory_descriptor)
    if len(entries) + len(module_sources) > MAX_MODULES:
        raise OSError
    try:
        package_source = open_source("__init__.py", directory_descriptor)
    except FileNotFoundError:
        return
    total_module_bytes += len(package_source)
    if total_module_bytes > MAX_TOTAL_MODULE_BYTES:
        raise OSError
    module_sources[package_name] = (
        package_source,
        os.path.join(logical_directory, "__init__.py"),
        True,
    )
    for entry in sorted(entries):
        if entry == "__init__.py":
            continue
        entry_stat = os.stat(
            entry,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if stat.S_ISREG(entry_stat.st_mode) and entry.endswith(".py"):
            source = open_source(entry, directory_descriptor)
            total_module_bytes += len(source)
            if (
                len(module_sources) >= MAX_MODULES
                or total_module_bytes > MAX_TOTAL_MODULE_BYTES
            ):
                raise OSError
            module_sources[package_name + "." + entry[:-3]] = (
                source,
                os.path.join(logical_directory, entry),
                False,
            )
        elif stat.S_ISDIR(entry_stat.st_mode):
            child_descriptor = os.open(
                entry,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_descriptor,
            )
            try:
                collect_package(
                    child_descriptor,
                    package_name + "." + entry,
                    os.path.join(logical_directory, entry),
                    depth + 1,
                )
            finally:
                close_descriptor(child_descriptor)


class TrustedPluginFinder:
    def find_spec(self, fullname, path=None, target=None):
        entry = module_sources.get(fullname)
        if entry is not None:
            return importlib.util.spec_from_loader(
                fullname,
                self,
                origin=entry[1],
                is_package=entry[2],
            )
        if any(
            fullname == package or fullname.startswith(package + ".")
            for package in PLUGIN_PACKAGES
        ):
            raise ModuleNotFoundError(fullname)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source, logical_path, is_package = module_sources[module.__name__]
        module.__file__ = logical_path
        if is_package:
            module.__path__ = [os.path.dirname(logical_path)]
        exec(compile(source, logical_path, "exec"), module.__dict__, module.__dict__)


try:
    if not stat.S_ISDIR(os.fstat(root_descriptor).st_mode):
        raise OSError
    if not stat.S_ISREG(os.fstat(stop_descriptor).st_mode):
        raise OSError
    with os.fdopen(stop_descriptor, "rb", closefd=True) as source_file:
        source = source_file.read()
    stop_descriptor = -1
    for package in PLUGIN_PACKAGES:
        try:
            package_descriptor = os.open(
                package,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root_descriptor,
            )
        except FileNotFoundError:
            continue
        try:
            collect_package(
                package_descriptor,
                package,
                os.path.join(root_path, package),
                0,
            )
        finally:
            close_descriptor(package_descriptor)
    code = compile(source, source_path, "exec")
except BaseException:
    close_descriptor(stop_descriptor)
    close_descriptor(root_descriptor)
    sys.stdout.write("{}\\n")
    raise SystemExit(0)

close_descriptor(root_descriptor)
root_descriptor = -1
for loaded_name in tuple(sys.modules):
    if any(
        loaded_name == package or loaded_name.startswith(package + ".")
        for package in PLUGIN_PACKAGES
    ):
        del sys.modules[loaded_name]
sys.meta_path.insert(0, TrustedPluginFinder())
sys.argv = [source_path]
sys.path[0] = os.path.dirname(source_path)
namespace = globals()
namespace.update(
    __name__="__main__",
    __file__=source_path,
    __cached__=None,
    __package__=None,
    __spec__=None,
)
exec(code, namespace, namespace)
"""


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
    marketplace = family.parent
    marketplace_parent = marketplace.parent
    parent_descriptor = marketplace_descriptor = family_descriptor = -1
    try:
        if not marketplace.name or not family.name:
            raise OSError
        parent_descriptor = os.open(
            marketplace_parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        if not _matches_open_path(
            marketplace_parent,
            parent_descriptor,
            directory=True,
        ):
            raise OSError
        marketplace_descriptor = os.open(
            marketplace.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_descriptor,
        )
        if not _matches_open_entry(
            marketplace.name,
            parent_descriptor,
            marketplace_descriptor,
            directory=True,
        ) or not _matches_open_path(
            marketplace,
            marketplace_descriptor,
            directory=True,
        ):
            raise OSError
        family_descriptor = os.open(
            family.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=marketplace_descriptor,
        )
        if not _matches_open_entry(
            family.name,
            marketplace_descriptor,
            family_descriptor,
            directory=True,
        ):
            raise OSError
        resolved_family = family.resolve(strict=True)
        if not _matches_open_path(
            marketplace,
            marketplace_descriptor,
            directory=True,
        ) or not _matches_open_path(
            family,
            family_descriptor,
            directory=True,
        ):
            raise OSError
        selected_family_descriptor = family_descriptor
        family_descriptor = -1
        return selected_family_descriptor, resolved_family
    except (OSError, ValueError):
        return None
    finally:
        for descriptor in (
            family_descriptor,
            marketplace_descriptor,
            parent_descriptor,
        ):
            if descriptor >= 0:
                os.close(descriptor)


def _validate_candidate(
    name: str,
    family: Path,
    family_descriptor: int,
) -> tuple[tuple[int, int, int, int, str], Path, Path, int, int] | None:
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
        selected_root_descriptor = root_descriptor
        selected_stop_descriptor = stop_descriptor
        root_descriptor = -1
        stop_descriptor = -1
        return (
            version_key,
            root,
            root / "hooks" / "stop.py",
            selected_root_descriptor,
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


def _open_selected_stop(original_root: Path) -> tuple[Path, Path, int, int] | None:
    family = original_root.parent
    opened_family = _open_family(family)
    if opened_family is None:
        return None
    family_descriptor, family = opened_family
    candidates: list[
        tuple[tuple[int, int, int, int, str], Path, Path, int, int]
    ] = []
    try:
        original = _validate_candidate(
            original_root.name, family, family_descriptor
        )
        if original is not None:
            return original[1], original[2], original[3], original[4]

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
        return selected[1], selected[2], selected[3], selected[4]
    except OSError:
        return None
    finally:
        for candidate in candidates:
            os.close(candidate[3])
            os.close(candidate[4])
        os.close(family_descriptor)


def select_stop_hook(original_root: Path) -> tuple[Path, Path] | None:
    selected = _open_selected_stop(original_root)
    if selected is None:
        return None
    selected_root, stop_hook, root_descriptor, stop_descriptor = selected
    os.close(root_descriptor)
    os.close(stop_descriptor)
    return selected_root, stop_hook


def _write_empty_result() -> int:
    sys.stdout.write("{}\n")
    return 0


def _exec_stop_hook(
    selected_root: Path,
    stop_hook: Path,
    root_descriptor: int,
    stop_descriptor: int,
) -> None:
    if not stat.S_ISDIR(os.fstat(root_descriptor).st_mode):
        raise OSError
    if not stat.S_ISREG(os.fstat(stop_descriptor).st_mode):
        raise OSError
    os.set_inheritable(root_descriptor, True)
    os.set_inheritable(stop_descriptor, True)
    os.environ["PLUGIN_ROOT"] = str(selected_root)
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-B",
            "-c",
            STOP_BOOTSTRAP,
            str(root_descriptor),
            str(stop_descriptor),
            str(selected_root),
            str(stop_hook),
        ],
    )


def main() -> int:
    root_descriptor = -1
    stop_descriptor = -1
    try:
        root_value = os.environ.get("PLUGIN_ROOT")
        if not root_value:
            return _write_empty_result()
        selected = _open_selected_stop(Path(root_value))
        if selected is None:
            return _write_empty_result()
        selected_root, stop_hook, root_descriptor, stop_descriptor = selected
        _exec_stop_hook(
            selected_root,
            stop_hook,
            root_descriptor,
            stop_descriptor,
        )
    except BaseException:
        return _write_empty_result()
    finally:
        if root_descriptor >= 0:
            try:
                os.close(root_descriptor)
            except OSError:
                pass
        if stop_descriptor >= 0:
            try:
                os.close(stop_descriptor)
            except OSError:
                pass
    return _write_empty_result()


if __name__ == "__main__":
    raise SystemExit(main())
