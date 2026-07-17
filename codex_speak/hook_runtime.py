import os
from pathlib import Path


RUNTIME_HOOK_DIRECTORY = "runtime-hooks"
STOP_LAUNCHER_NAME = "stop_launcher.py"
_MAX_LAUNCHER_BYTES = 65_536
_DIRECTORY_MODE = 0o040000
_REGULAR_FILE_MODE = 0o100000
_FILE_TYPE_MASK = 0o170000
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_OPEN_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _is_regular_file(mode: int) -> bool:
    return mode & _FILE_TYPE_MASK == _REGULAR_FILE_MODE


def _is_directory(mode: int) -> bool:
    return mode & _FILE_TYPE_MASK == _DIRECTORY_MODE


def _read_packaged_launcher(source: Path) -> bytes:
    if not _NO_FOLLOW:
        raise OSError("no-follow source opening is unavailable")

    descriptor = os.open(source, os.O_RDONLY | _NO_FOLLOW)
    try:
        if not _is_regular_file(os.fstat(descriptor).st_mode):
            raise OSError("packaged launcher is not a regular file")

        payload = bytearray()
        while len(payload) < _MAX_LAUNCHER_BYTES + 1:
            chunk = os.read(descriptor, _MAX_LAUNCHER_BYTES + 1 - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        return bytes(payload)
    finally:
        os.close(descriptor)


def _open_runtime_directory(runtime_dir: Path) -> int:
    if not _NO_FOLLOW or not _OPEN_DIRECTORY:
        raise OSError("secure runtime directory opening is unavailable")

    runtime_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor = os.open(runtime_dir, os.O_RDONLY | _OPEN_DIRECTORY | _NO_FOLLOW)
    try:
        if not _is_directory(os.fstat(descriptor).st_mode):
            raise OSError("runtime hook path is not a directory")
        os.fchmod(descriptor, 0o700)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _create_temporary_launcher(runtime_directory_fd: int) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NO_FOLLOW
    for _ in range(32):
        name = f".{STOP_LAUNCHER_NAME}.{os.urandom(16).hex()}"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=runtime_directory_fd)
        except FileExistsError:
            continue
        try:
            os.fchmod(descriptor, 0o600)
            return descriptor, name
        except BaseException:
            try:
                os.close(descriptor)
            except BaseException:
                pass
            try:
                os.unlink(name, dir_fd=runtime_directory_fd)
            except BaseException:
                pass
            raise
    raise OSError("could not create a unique runtime launcher temporary file")


def _write_launcher(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        count = os.write(descriptor, remaining)
        if count <= 0:
            raise OSError("incomplete launcher write")
        remaining = remaining[count:]
    os.fsync(descriptor)


def _normalize_target_permissions(runtime_directory_fd: int) -> None:
    descriptor = os.open(
        STOP_LAUNCHER_NAME,
        os.O_RDONLY | _NO_FOLLOW,
        dir_fd=runtime_directory_fd,
    )
    try:
        if not _is_regular_file(os.fstat(descriptor).st_mode):
            raise OSError("runtime launcher is not a regular file")
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def install_stop_launcher(plugin_root: Path, data_dir: Path) -> bool:
    temporary_name: str | None = None
    temporary_descriptor: int | None = None
    runtime_directory_fd: int | None = None

    try:
        source = plugin_root / "hooks" / STOP_LAUNCHER_NAME
        payload = _read_packaged_launcher(source)
        if not payload or len(payload) > _MAX_LAUNCHER_BYTES:
            return False

        runtime_directory_fd = _open_runtime_directory(
            data_dir / RUNTIME_HOOK_DIRECTORY
        )
        temporary_descriptor, temporary_name = _create_temporary_launcher(
            runtime_directory_fd
        )
        _write_launcher(temporary_descriptor, payload)
        os.close(temporary_descriptor)
        temporary_descriptor = None

        os.replace(
            temporary_name,
            STOP_LAUNCHER_NAME,
            src_dir_fd=runtime_directory_fd,
            dst_dir_fd=runtime_directory_fd,
        )
        temporary_name = None
        _normalize_target_permissions(runtime_directory_fd)
        return True
    except BaseException:
        return False
    finally:
        if temporary_descriptor is not None:
            try:
                os.close(temporary_descriptor)
            except BaseException:
                pass
        if temporary_name is not None and runtime_directory_fd is not None:
            try:
                os.unlink(temporary_name, dir_fd=runtime_directory_fd)
            except BaseException:
                pass
        if runtime_directory_fd is not None:
            try:
                os.close(runtime_directory_fd)
            except BaseException:
                pass
