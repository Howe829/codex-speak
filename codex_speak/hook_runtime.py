import os
from pathlib import Path
import tempfile


RUNTIME_HOOK_DIRECTORY = "runtime-hooks"
STOP_LAUNCHER_NAME = "stop_launcher.py"
_MAX_LAUNCHER_BYTES = 65_536


def _read_packaged_launcher(source: Path) -> bytes:
    with source.open("rb") as handle:
        return handle.read(_MAX_LAUNCHER_BYTES + 1)


def install_stop_launcher(plugin_root: Path, data_dir: Path) -> bool:
    temporary_path: Path | None = None
    descriptor: int | None = None

    try:
        source = plugin_root / "hooks" / STOP_LAUNCHER_NAME
        if source.is_symlink():
            return False
        payload = _read_packaged_launcher(source)
        if not payload or len(payload) > _MAX_LAUNCHER_BYTES:
            return False

        runtime_dir = data_dir / RUNTIME_HOOK_DIRECTORY
        runtime_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        if runtime_dir.is_symlink():
            return False
        runtime_dir.chmod(0o700)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{STOP_LAUNCHER_NAME}.", dir=runtime_dir
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "wb")
        descriptor = None
        with handle:
            if handle.write(payload) != len(payload):
                raise OSError("incomplete launcher write")
            handle.flush()
            os.fsync(handle.fileno())

        target = runtime_dir / STOP_LAUNCHER_NAME
        os.replace(temporary_path, target)
        temporary_path = None
        target.chmod(0o600)
        return True
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except BaseException:
                pass
        return False
