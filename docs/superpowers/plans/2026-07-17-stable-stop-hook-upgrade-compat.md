# Stable Stop Hook Upgrade Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Stop hooks captured by new Codex Speak tasks survive later Marketplace upgrades that delete the task's original versioned plugin cache.

**Architecture:** SessionStart atomically copies a standalone standard-library launcher into the stable private `PLUGIN_DATA` directory. The Stop command prefers that launcher; when the original plugin version is gone, the launcher selects the highest valid real Codex Speak sibling from the same Marketplace/plugin cache family and replaces itself with that version's Stop hook while preserving stdin, stdout, and environment.

**Tech Stack:** Python 3.10+ standard library, Codex lifecycle hooks, POSIX shell command configuration, `unittest`, existing macOS Swift helper tests, Codex plugin validator.

## Global Constraints

- Follow the approved design in `docs/superpowers/specs/2026-07-17-stable-stop-hook-upgrade-compat-design.md`.
- The stable launcher imports only the Python standard library and never imports `codex_speak`.
- The launcher never reads, copies, hashes, persists, logs, or places hook stdin in process arguments.
- Candidate discovery stays within direct version children of the original Marketplace/plugin family.
- Reject symlink candidate roots, symlink manifests, symlink hook files, malformed manifests, wrong plugin names, manifest/directory version mismatches, nested paths, and unsupported version strings.
- Candidate versions are numeric `MAJOR.MINOR.PATCH` with an optional formal `+codex.<lowercase-token>` suffix.
- Prefer a still-valid original version. Otherwise select the highest numeric sibling; use the optional build suffix only as a deterministic same-version tie-breaker.
- Recheck resolved containment immediately before `execv`.
- No valid candidate or any pre-exec failure writes exactly `{}` plus one newline to stdout, writes nothing to stderr, and exits zero.
- Install `${PLUGIN_DATA}/runtime-hooks` with mode `0700` and `stop_launcher.py` with mode `0600` using a unique temporary file, `fsync`, and atomic `os.replace`.
- Concurrent SessionStart runs must leave one complete byte-for-byte launcher and no temporary file.
- The Stop command must keep `-B`, quote both paths, prefer the stable launcher, and retain the current versioned Stop hook as its pre-upgrade fallback.
- Existing queue, rendering, protocol, menu-helper, Silent/Summary/Full, privacy, and diagnostics behavior must remain unchanged.
- Prepare source version `0.2.6`; keep `.agents/plugins/marketplace.json` pinned to public `v0.2.5`.
- Do not publish, tag, push, reinstall, delete the current compatibility symlink, or mutate the user's Codex cache while executing this plan.
- Implement every behavior test-first: observe the focused test fail for the intended reason before adding production code.

---

## File Structure

- Create `hooks/stop_launcher.py`: standalone runtime selection and quiet `execv` entry point.
- Create `codex_speak/hook_runtime.py`: private atomic launcher installer.
- Create `tests/test_stop_launcher.py`: resolver, security, quiet-failure, and real-process launcher coverage.
- Create `tests/test_hook_runtime.py`: installation, permissions, idempotence, failure cleanup, and concurrency coverage.
- Modify `hooks/session_start.py`: install the stable launcher before starting the consumer.
- Modify `hooks/hooks.json`: prefer the stable Stop launcher with the versioned fallback.
- Modify `tests/test_hooks.py`: SessionStart ordering/failure isolation and exact command contract.
- Modify `tests/test_packaging.py`: installed-tree, source-version, Marketplace-pin, and upgrade regression coverage.
- Modify `tests/test_privacy.py`: launcher persistence/process-argument privacy assertions and README contract.
- Modify `.codex-plugin/plugin.json`: source candidate version `0.2.6`.
- Modify `README.md`: one-time transition, stable-upgrade behavior, source/release distinction, and troubleshooting.

---

### Task 1: Build the standalone, fail-closed Stop launcher

**Files:**
- Create: `hooks/stop_launcher.py`
- Create: `tests/test_stop_launcher.py`

**Interfaces:**
- Produces: `parse_version(value: str) -> tuple[int, int, int, int, str] | None`.
- Produces: `select_stop_hook(original_root: Path) -> tuple[Path, Path] | None`, returning `(selected_plugin_root, selected_stop_hook)`.
- Produces: `main() -> int`, which either `execv`s the selected hook or emits the exact empty hook result.

- [ ] **Step 1: Add Marketplace-cache fixture helpers and failing resolver tests**

Create `tests/test_stop_launcher.py` with imports and helpers that build only temporary cache trees:

```python
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from hooks.stop_launcher import main, parse_version, select_stop_hook


def create_runtime(
    family: Path,
    version: str,
    *,
    manifest_name: str = "codex-speak",
    manifest_version: str | None = None,
    stop_source: str = "print('{}')\n",
) -> Path:
    root = family / version
    (root / ".codex-plugin").mkdir(parents=True)
    (root / "hooks").mkdir()
    manifest = {
        "name": manifest_name,
        "version": manifest_version if manifest_version is not None else version,
    }
    (root / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (root / "hooks" / "stop.py").write_text(stop_source, encoding="utf-8")
    return root
```

Add tests covering the accepted version grammar and selection order:

```python
class StopLauncherTests(unittest.TestCase):
    def test_parse_version_accepts_only_supported_numeric_release_builds(self) -> None:
        self.assertEqual(parse_version("0.2.6"), (0, 2, 6, 0, ""))
        self.assertEqual(
            parse_version("0.2.6+codex.20260717010101"),
            (0, 2, 6, 1, "20260717010101"),
        )
        for value in (
            "v0.2.6",
            "0.2",
            "0.2.6.1",
            "00.2.6",
            "0.02.6",
            "0.2.6+other.build",
            "0.2.6+codex.UPPER",
            "0.2.6+codex.a/b",
            "../0.2.6",
        ):
            with self.subTest(value=value):
                self.assertIsNone(parse_version(value))

    def test_prefers_valid_original_root_even_when_newer_sibling_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            family = Path(temporary) / "howe829" / "codex-speak"
            original = create_runtime(family, "0.2.6")
            create_runtime(family, "0.2.7")
            self.assertEqual(
                select_stop_hook(original),
                (original.resolve(), (original / "hooks" / "stop.py").resolve()),
            )

    def test_selects_highest_valid_sibling_after_original_is_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            family = Path(temporary) / "howe829" / "codex-speak"
            original = family / "0.2.5"
            create_runtime(family, "0.2.6")
            selected = create_runtime(family, "0.3.0")
            self.assertEqual(
                select_stop_hook(original),
                (selected.resolve(), (selected / "hooks" / "stop.py").resolve()),
            )

    def test_formal_build_is_a_deterministic_same_release_tiebreaker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            family = Path(temporary) / "howe829" / "codex-speak"
            original = family / "0.2.5"
            create_runtime(family, "0.2.6")
            selected = create_runtime(family, "0.2.6+codex.z2")
            create_runtime(family, "0.2.6+codex.a1")
            self.assertEqual(select_stop_hook(original)[0], selected.resolve())
```

- [ ] **Step 2: Add failing rejection and quiet-failure tests**

Add tests that create wrong-name, version-mismatch, malformed, nested, and symlink candidates. Use `@unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")` on symlink cases. Assert every invalid tree returns `None` and never selects a candidate outside `family.resolve()`.

Include these explicit cases:

```python
def test_rejects_wrong_name_mismatched_manifest_malformed_and_nested(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        family = Path(temporary) / "howe829" / "codex-speak"
        original = family / "0.2.5"
        create_runtime(family, "0.2.6", manifest_name="other-plugin")
        create_runtime(family, "0.2.7", manifest_version="0.2.8")
        malformed = create_runtime(family, "0.2.8")
        (malformed / ".codex-plugin" / "plugin.json").write_text("{", encoding="utf-8")
        create_runtime(family / "nested", "9.0.0")
        self.assertIsNone(select_stop_hook(original))

@unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
def test_rejects_symlink_root_manifest_and_stop_hook(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        family = base / "howe829" / "codex-speak"
        original = family / "0.2.5"
        outside = create_runtime(base / "outside", "9.0.0")
        family.mkdir(parents=True)
        (family / "0.2.6").symlink_to(outside, target_is_directory=True)
        manifest_link = create_runtime(family, "0.2.7")
        (manifest_link / ".codex-plugin" / "plugin.json").unlink()
        (manifest_link / ".codex-plugin" / "plugin.json").symlink_to(
            outside / ".codex-plugin" / "plugin.json"
        )
        stop_link = create_runtime(family, "0.2.8")
        (stop_link / "hooks" / "stop.py").unlink()
        (stop_link / "hooks" / "stop.py").symlink_to(
            outside / "hooks" / "stop.py"
        )
        self.assertIsNone(select_stop_hook(original))

def test_main_emits_only_empty_hook_result_when_no_runtime_is_valid(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        stdout = io.StringIO()
        stderr = io.StringIO()
        missing = Path(temporary) / "howe829" / "codex-speak" / "0.2.5"
        with (
            patch.dict(os.environ, {"PLUGIN_ROOT": str(missing)}, clear=True),
            patch("hooks.stop_launcher.sys.stdout", stdout),
            patch("hooks.stop_launcher.sys.stderr", stderr),
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(stdout.getvalue(), "{}\n")
        self.assertEqual(stderr.getvalue(), "")
```

Add a candidate-count test with more than the declared scan limit. Assert the
resolver fails closed with `None` instead of inspecting a partial set or
throwing.

Patch `hooks.stop_launcher.os.execv` to raise `OSError` for an otherwise valid
candidate and assert `main()` returns zero, stdout is exactly `"{}\n"`, and
stderr is empty. This directly covers the pre-exec failure contract.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest tests.test_stop_launcher -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'hooks.stop_launcher'`. This confirms the new tests fail because the launcher does not exist.

- [ ] **Step 4: Implement the smallest standalone resolver and entry point**

Create `hooks/stop_launcher.py`. Keep top-level imports limited to `json`, `os`, `pathlib`, `re`, and `sys`. Define constants for plugin identity, bounded manifest size, bounded candidate count, and the exact version regex.

Use this structure:

```python
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
```

Implement a private `_validate_candidate(root, family)` that:

1. Rejects a non-direct child, symlink, non-directory, or unsupported directory name.
2. Resolves `family` and `root`, requiring `resolved_root.parent == resolved_family`.
3. Rejects symlink/missing manifest and Stop hook files.
4. Rejects manifests larger than `MAX_MANIFEST_BYTES`, invalid JSON, non-dicts, wrong names, or non-exact string versions.
5. Resolves the hook and requires it to equal `resolved_root / "hooks" / "stop.py"` after resolution.
6. Returns `(version_key, resolved_root, resolved_stop)` only after a final containment recheck.

Implement `select_stop_hook` so it first validates the original root. When that
fails, enumerate the direct family children once. If their count exceeds
`MAX_CANDIDATES`, fail closed with `None`; never inspect only a partial set.
Sort and validate every child in the accepted bounded set, then choose
`max(..., key=version_key)`. Do not recurse.

Read manifest content with a binary file handle and
`read(MAX_MANIFEST_BYTES + 1)` rather than an unbounded `read_bytes()` call.
Before `execv`, call the candidate validator once more and require the same
resolved root and Stop path so containment is rechecked at the execution
boundary.

Implement quiet output and `execv`:

```python
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
        os.environ["PLUGIN_ROOT"] = str(selected_root)
        os.execv(sys.executable, [sys.executable, "-B", str(stop_hook)])
    except BaseException:
        return _write_empty_result()
    return _write_empty_result()
```

Do not print diagnostics or exception text.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run the focused command from Step 3.

Expected: all `tests.test_stop_launcher` tests PASS, with no stderr.

- [ ] **Step 6: Commit Task 1**

```bash
git add hooks/stop_launcher.py tests/test_stop_launcher.py
git commit -m "feat: add stable stop runtime launcher"
```

---

### Task 2: Install the launcher atomically in private plugin data

**Files:**
- Create: `codex_speak/hook_runtime.py`
- Create: `tests/test_hook_runtime.py`

**Interfaces:**
- Produces: `RUNTIME_HOOK_DIRECTORY = "runtime-hooks"` and `STOP_LAUNCHER_NAME = "stop_launcher.py"`.
- Produces: `install_stop_launcher(plugin_root: Path, data_dir: Path) -> bool`.

- [ ] **Step 1: Add failing byte-exact, permissions, and idempotence tests**

Create `tests/test_hook_runtime.py` with this helper, then add the tests below:

```python
def make_plugin(base: Path, payload: bytes) -> Path:
    plugin_root = base / "plugin"
    source = plugin_root / "hooks" / "stop_launcher.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    return plugin_root
```

```python
class HookRuntimeTests(unittest.TestCase):
    def test_installs_packaged_launcher_byte_for_byte_with_private_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plugin_root = base / "plugin"
            source = plugin_root / "hooks" / "stop_launcher.py"
            source.parent.mkdir(parents=True)
            payload = b"#!/usr/bin/env python3\nprint('{}')\n"
            source.write_bytes(payload)
            data_dir = base / "data"

            self.assertTrue(install_stop_launcher(plugin_root, data_dir))

            runtime_dir = data_dir / "runtime-hooks"
            target = runtime_dir / "stop_launcher.py"
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(runtime_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(list(runtime_dir.iterdir()), [target])

    def test_reinstall_is_idempotent_and_repairs_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plugin_root = make_plugin(base, b"launcher-v1\n")
            data_dir = base / "data"
            self.assertTrue(install_stop_launcher(plugin_root, data_dir))
            target = data_dir / "runtime-hooks" / "stop_launcher.py"
            target.chmod(0o644)
            self.assertTrue(install_stop_launcher(plugin_root, data_dir))
            self.assertEqual(target.read_bytes(), b"launcher-v1\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
```

- [ ] **Step 2: Add failing atomic-failure cleanup and concurrency tests**

Patch `codex_speak.hook_runtime.os.replace` to raise `OSError` and assert:

- the function returns `False`;
- an existing complete target remains unchanged;
- no filename beginning with `.stop_launcher.py.` remains;
- stdout/stderr stay empty.

Add `ThreadPoolExecutor(max_workers=8)` coverage that runs 32 installations concurrently and asserts every result is `True`, the final target is byte-exact, permissions are private, and no temporary file remains.

Add missing/unreadable-source and symlinked-source/runtime-directory coverage
that returns `False` without creating a partial target or exposing a raw
path/error. Do not require a privileged unreadable-file test; patch the module's
source-opening helper for deterministic cross-environment behavior.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest tests.test_hook_runtime -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'codex_speak.hook_runtime'`.

- [ ] **Step 4: Implement the atomic installer**

Create `codex_speak/hook_runtime.py` using only `os`, `pathlib`, and `tempfile`.

Implementation sequence inside `install_stop_launcher`:

1. Resolve the packaged source as `plugin_root / "hooks" / STOP_LAUNCHER_NAME`,
   reject a symlink source, and read at most 65,537 bytes through a binary file
   handle.
2. Reject empty source and cap it at 65,536 bytes.
3. Create `data_dir / RUNTIME_HOOK_DIRECTORY` with parents and mode `0700`,
   reject it if it is a symlink, then explicitly `chmod(0o700)` to repair an
   existing directory.
4. Create a unique same-directory temporary file with `tempfile.mkstemp(prefix=f".{STOP_LAUNCHER_NAME}.", dir=runtime_dir)`.
5. Apply `os.fchmod(fd, 0o600)`, write all bytes through `os.fdopen(fd, "wb")`, flush, and `os.fsync` before close.
6. Atomically `os.replace(temp_path, target)` and `target.chmod(0o600)`.
7. On any `BaseException`, close a still-open descriptor, unlink only the known temporary path with `missing_ok=True`, and return `False` without printing.
8. Return `True` only after replacement and permission normalization succeed.

Do not compare or log dynamic plugin data. Always replace, so a newer release refreshes the stable launcher even if a previous launcher exists.

- [ ] **Step 5: Run focused and launcher tests and verify GREEN**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest tests.test_hook_runtime tests.test_stop_launcher -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add codex_speak/hook_runtime.py tests/test_hook_runtime.py
git commit -m "feat: install stable stop launcher atomically"
```

---

### Task 3: Wire SessionStart and prove a captured Stop command survives upgrade

**Files:**
- Modify: `hooks/session_start.py`
- Modify: `hooks/hooks.json`
- Modify: `tests/test_hooks.py`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_privacy.py`

**Interfaces:**
- Changes: `ensure_started(plugin_root, data_dir, *, install_launcher=install_stop_launcher, start_consumer=ensure_consumer) -> None`.
- Changes: the exact configured Stop shell command.
- Preserves: SessionStart output and Stop hook JSON contracts.

- [ ] **Step 1: Add failing SessionStart ordering and failure-isolation tests**

In `tests/test_hooks.py`, add `ensure_started` to the existing imports from
`hooks.session_start`, then add tests with injected callables:

```python
def test_session_start_installs_launcher_before_starting_consumer(self) -> None:
    calls = []
    ensure_started(
        Path("/plugin"),
        Path("/data"),
        install_launcher=lambda root, data: calls.append(("install", root, data)) or True,
        start_consumer=lambda root, data: calls.append(("consumer", root, data)),
    )
    self.assertEqual(
        calls,
        [
            ("install", Path("/plugin"), Path("/data")),
            ("consumer", Path("/plugin"), Path("/data")),
        ],
    )

def test_session_start_launcher_failure_does_not_block_consumer_or_context(self) -> None:
    started = []
    ensure_started(
        Path("/plugin"),
        Path("/data"),
        install_launcher=lambda root, data: (_ for _ in ()).throw(OSError("private")),
        start_consumer=lambda root, data: started.append((root, data)),
    )
    self.assertEqual(started, [(Path("/plugin"), Path("/data"))])
```

Update `test_hook_config_registers_default_session_start_and_stop_commands` to require exactly:

```python
expected_stop = (
    'if [ -f "${PLUGIN_DATA}/runtime-hooks/stop_launcher.py" ]; then '
    'python3 -B "${PLUGIN_DATA}/runtime-hooks/stop_launcher.py"; '
    'else python3 -B "${PLUGIN_ROOT}/hooks/stop.py"; fi'
)
self.assertEqual(stop_command, expected_stop)
self.assertIn("PLUGIN_DATA", stop_command)
self.assertNotIn("PLUGIN_DATA", session_command)
```

Also assert the command contains exactly two `python3 -B` invocations and no unquoted launcher/root path.

- [ ] **Step 2: Add the failing real-process upgrade regression**

In `tests/test_packaging.py`, import `install_stop_launcher` from
`codex_speak.hook_runtime` and add this helper for Marketplace-like version
roots. The generated Stop fixture validates that the launcher replaced
`PLUGIN_ROOT`, then echoes stdin unchanged:

```python
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
        "sys.stdout.write(sys.stdin.read())\n",
        encoding="utf-8",
    )
    return root
```

Add this scenario:

```python
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
        self.assertEqual(completed.stdout, canary)
        self.assertEqual(completed.stderr, "")
        self.assertTrue(version_b.is_dir())
        self.assertNotIn("PRIVATE-UPGRADE-CANARY", captured_command)
        self.assertNotIn("PRIVATE-UPGRADE-CANARY", " ".join(completed.args))
        for path in data_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"PRIVATE-UPGRADE-CANARY", path.read_bytes())
```

The fake Stop fixture must not embed the canary. Ensure the test's only expected copy of the canary is the subprocess pipe and captured stdout.

- [ ] **Step 3: Add shell-fallback and installed-tree tests**

Add a packaging test that leaves `${PLUGIN_DATA}/runtime-hooks/stop_launcher.py` absent, keeps the original version's fake `hooks/stop.py`, runs the exact configured command, and verifies the versioned fallback receives stdin and returns expected stdout with empty stderr.

Extend `test_python_plugin_entries_do_not_write_bytecode_into_installed_tree` so its copied package runs:

1. SessionStart with both `PLUGIN_ROOT` and `PLUGIN_DATA` set.
2. The installed stable launcher using a minimal valid installed manifest/version family.
3. The ordinary installed Stop hook.

Assert no `__pycache__` or `.pyc` appears in either the installed plugin tree or runtime-hook directory.

In `tests/test_privacy.py`, add an assertion that the installed stable launcher is byte-for-byte equal to packaged static source and contains none of the test canaries, thread IDs, task titles, or speech text. Assert the exact Stop command has no hook input interpolation and only fixed environment paths.

- [ ] **Step 4: Run focused tests and verify RED**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
    tests.test_hooks \
    tests.test_packaging \
    tests.test_privacy \
    -v
```

Expected: FAIL because SessionStart does not call the installer and `hooks.json` still points directly to `${PLUGIN_ROOT}/hooks/stop.py`.

- [ ] **Step 5: Wire SessionStart without coupling launcher failure to consumer startup**

In `hooks/session_start.py`:

```python
from codex_speak.helper import ensure_consumer
from codex_speak.hook_runtime import install_stop_launcher
```

Change `ensure_started` to accept the injected installer. Run it first in its own `try/except BaseException`, then run the consumer in a separate existing `try/except BaseException`. A failed launcher install must not skip consumer startup or SessionStart context output.

- [ ] **Step 6: Replace the configured Stop command**

Set `hooks/hooks.json` Stop command to the exact one-line shell command from Step 1:

```text
if [ -f "${PLUGIN_DATA}/runtime-hooks/stop_launcher.py" ]; then python3 -B "${PLUGIN_DATA}/runtime-hooks/stop_launcher.py"; else python3 -B "${PLUGIN_ROOT}/hooks/stop.py"; fi
```

Do not change the SessionStart command or hook registration structure.

- [ ] **Step 7: Run focused integration tests and verify GREEN**

Run the command from Step 4, then:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
    tests.test_hook_runtime \
    tests.test_stop_launcher \
    tests.test_hooks \
    tests.test_packaging \
    tests.test_privacy \
    -v
```

Expected: all focused tests PASS; the real subprocess upgrade test returns the exact input through version B, no stderr, and no persisted canary.

- [ ] **Step 8: Commit Task 3**

```bash
git add \
  hooks/session_start.py \
  hooks/hooks.json \
  tests/test_hooks.py \
  tests/test_packaging.py \
  tests/test_privacy.py
git commit -m "fix: keep stop hooks alive across upgrades"
```

---

### Task 4: Prepare the 0.2.6 source candidate and document the transition boundary

**Files:**
- Modify: `.codex-plugin/plugin.json`
- Modify: `README.md`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_privacy.py`

**Interfaces:**
- Changes: source manifest version from `0.2.5` to `0.2.6`.
- Preserves: public Marketplace ref `v0.2.5` until an explicit release instruction.

- [ ] **Step 1: Add failing source/release and README contract tests**

Update the manifest version assertion in `tests/test_packaging.py` to:

```python
self.assertRegex(
    manifest["version"],
    r"^0\.2\.6(?:\+codex\.[a-z0-9-]+)?$",
)
```

Keep the public Marketplace expected ref exactly `v0.2.5`, and add an explicit assertion that the source version and Marketplace tag intentionally differ during candidate preparation:

```python
self.assertEqual(marketplace["plugins"][0]["source"]["ref"], "v0.2.5")
self.assertTrue(manifest["version"].startswith("0.2.6"))
```

Replace the old README token assertions with requirements for all of:

- `source candidate is version 0.2.6`;
- `Marketplace release remains version 0.2.5`;
- `runtime-hooks/stop_launcher.py`;
- `same Marketplace and plugin cache family`;
- `start a new task` for the one-time transition into the first fixed release;
- tasks started on the fixed release survive later upgrades;
- pre-fix open tasks cannot be retroactively repaired by the new hook definition;
- no speech content is stored in the launcher;
- missing valid runtime fails with an empty hook result.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest tests.test_packaging tests.test_privacy -v
```

Expected: FAIL because the manifest and README still describe `0.2.5` as the current repository release and do not document stable upgrade behavior.

- [ ] **Step 3: Update the source version and README**

Change `.codex-plugin/plugin.json` to `0.2.6`.

In `README.md`:

1. State that the repository source candidate is `0.2.6` while the public Marketplace release/ref remains `0.2.5` until separately published.
2. Explain that SessionStart installs a private fixed launcher under plugin data and Stop prefers it.
3. Explain that the launcher considers only real, valid direct version siblings from the same Marketplace/plugin cache family.
4. State the one-time boundary plainly: tasks opened before installing the first fixed release keep their captured old command and must be replaced with a new task; tasks opened on the fixed release survive subsequent Marketplace cache replacement.
5. Clarify that hook stdin/speech text is piped directly to the selected Stop process and is never written into launcher files, argv, or diagnostics.
6. Add troubleshooting for a missing valid runtime: reinstall the plugin and start a new task; the launcher itself returns an empty hook result instead of exposing a Python path error.
7. Do not claim `0.2.6` is already published or installed.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2.

Expected: all packaging/privacy tests PASS, the source manifest is `0.2.6`, and Marketplace remains pinned to `v0.2.5`.

- [ ] **Step 5: Commit Task 4**

```bash
git add .codex-plugin/plugin.json README.md tests/test_packaging.py tests/test_privacy.py
git commit -m "chore: prepare codex speak 0.2.6 candidate"
```

---

### Task 5: Run full regression, validation, and source-candidate review

**Files:**
- Review only: all files changed by Tasks 1-4
- Modify only if a test or review finds an in-scope defect; use a new failing regression test before fixing it.

- [ ] **Step 1: Run all Python tests and bytecode-isolated compilation**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m compileall -q hooks codex_speak tests
python3 -m json.tool hooks/hooks.json
```

Expected: all Python tests PASS; compilation exits zero; hook JSON parses successfully; no bytecode appears in the repository.

- [ ] **Step 2: Run the Swift menu-helper regression suite**

```bash
swift test --package-path menu-bar -Xswiftc -warnings-as-errors
```

Expected: all Swift tests PASS with no warnings promoted to errors.

- [ ] **Step 3: Run the official plugin validator**

Use the existing validated environment when available. Otherwise create the disposable validator environment documented in README, then run:

```bash
export REPO_ROOT="$(pwd)"
export PLUGIN_CREATOR_ROOT="${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator"
/private/tmp/codex-plugin-validator/bin/python \
  "$PLUGIN_CREATOR_ROOT/scripts/validate_plugin.py" \
  "$REPO_ROOT"
```

Expected: validator exits zero and reports the plugin valid.

- [ ] **Step 4: Re-run the real upgrade and security-focused tests independently**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
    tests.test_stop_launcher \
    tests.test_hook_runtime \
    tests.test_packaging.PackagingTests.test_captured_stop_command_survives_deletion_of_original_version \
    -v
```

Expected: PASS with exact stdout, empty stderr, unchanged stdin delivery, same-family selection, rejected symlink candidates, private modes, and no canary persistence.

- [ ] **Step 5: Inspect the final diff and repository state**

```bash
git diff --check
git status --short --branch
git log --oneline --decorate -8
git diff origin/main...HEAD -- \
  hooks/stop_launcher.py \
  codex_speak/hook_runtime.py \
  hooks/session_start.py \
  hooks/hooks.json \
  tests/test_stop_launcher.py \
  tests/test_hook_runtime.py \
  tests/test_hooks.py \
  tests/test_packaging.py \
  tests/test_privacy.py \
  .codex-plugin/plugin.json \
  README.md
```

Expected:

- `git diff --check` is clean.
- Only approved plan/spec and implementation files differ from `origin/main`.
- Source candidate is `0.2.6`; Marketplace stays `v0.2.5`.
- No tag, push, reinstall, cache deletion, or Marketplace mutation occurred.
- The temporary local `0.2.4 -> 0.2.5` compatibility link remains untouched for pre-fix tasks.

- [ ] **Step 6: Apply verification-before-completion and review against the design**

Use `superpowers:verification-before-completion`. Re-read the approved design and confirm every goal, non-goal, transition constraint, privacy rule, selection rule, failure behavior, and regression gate has direct code/test evidence.

If review finds a defect, add a failing regression test, make the smallest fix, rerun the focused test, then repeat all verification commands affected by the change.

- [ ] **Step 7: Record any review-only fix in a final commit**

Only when Step 6 required changes:

```bash
git add \
  hooks/stop_launcher.py \
  codex_speak/hook_runtime.py \
  hooks/session_start.py \
  hooks/hooks.json \
  tests/test_stop_launcher.py \
  tests/test_hook_runtime.py \
  tests/test_hooks.py \
  tests/test_packaging.py \
  tests/test_privacy.py \
  .codex-plugin/plugin.json \
  README.md
git commit -m "test: harden stable stop upgrade compatibility"
```

Do not create an empty commit.

- [ ] **Step 8: Hand off the source candidate**

Report:

- the stable launcher and real upgrade-regression outcome;
- the `0.2.6` source candidate / `v0.2.5` public-release split;
- full Python, Swift, JSON, compilation, and plugin-validator results;
- that publication, push, release creation, Marketplace refresh, and reinstall remain separate user-authorized actions.
