from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Final, Sequence


_VERSION: Final[int] = 1
_MODES: Final[frozenset[str]] = frozenset({"summary", "full"})


def _is_settings(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"version", "mode"}
        and type(value["version"]) is int
        and value["version"] == _VERSION
        and isinstance(value["mode"], str)
        and value["mode"] in _MODES
    )


def _atomic_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".settings-",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        temporary.unlink(missing_ok=True)
        raise


def save_mode(data_dir: Path, mode: str) -> str:
    if not isinstance(data_dir, Path):
        raise TypeError("data_dir must be a Path")
    if not isinstance(mode, str) or mode not in _MODES:
        raise ValueError("invalid mode")
    _atomic_write(
        data_dir / "settings.json",
        {"version": _VERSION, "mode": mode},
    )
    return mode


def load_mode(data_dir: Path) -> str:
    if not isinstance(data_dir, Path):
        raise TypeError("data_dir must be a Path")
    path = data_dir / "settings.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        value = None
    if _is_settings(value):
        os.chmod(path, 0o600)
        return value["mode"]
    return save_mode(data_dir, "summary")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m codex_speak.settings")
    parser.add_argument("--data-dir", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("get")
    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("mode", choices=sorted(_MODES))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "get":
        mode = load_mode(arguments.data_dir)
    else:
        mode = save_mode(arguments.data_dir, arguments.mode)
    print(mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
