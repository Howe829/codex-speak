# Stable Stop Hook Practical Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the over-engineered descriptor/module-snapshot Stop launcher with the approved lightweight path launcher while preserving real Marketplace-upgrade compatibility, privacy, and the `0.2.6` source candidate.

**Architecture:** Return the launcher and its focused tests to the last lightweight implementation, then add only selection-time validation for the original Marketplace identity and `codex-speak` family. Keep the existing atomic installer and stable Stop command unchanged; execute the selected runtime directly with `python3 -B`, under the documented trust assumption that the current macOS account does not replace plugin files during one hook invocation.

**Tech Stack:** Python 3.10+ standard library, Codex lifecycle hooks, POSIX shell command configuration, `unittest`, existing macOS Swift helper tests, Codex plugin validator, Git.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-17-stable-stop-hook-upgrade-compat-design.md` as the controlling design.
- Trust the current macOS account's Codex-managed cache and `PLUGIN_DATA` during one Stop invocation.
- Do not retain descriptors across `execv`, snapshot Python modules, install a custom import finder, or redirect worker/menu-helper child paths.
- Reject a Marketplace identity or `codex-speak` family that is already a symlink when selection begins.
- Reject symlink candidate roots, manifest directories, hooks directories, manifests, and Stop files.
- Require the original version name and every candidate version to match the supported numeric release grammar.
- Prefer a still-valid original runtime; otherwise select the highest valid direct sibling in the same Marketplace/plugin family.
- No valid runtime or any pre-exec failure writes exactly `{}` plus one newline to stdout, writes nothing to stderr, and exits zero.
- Never read, copy, hash, log, persist, or place hook stdin or speech content in launcher arguments.
- Keep `codex_speak/hook_runtime.py`, `hooks/session_start.py`, and `hooks/hooks.json` behavior unchanged.
- Preserve the stable launcher installer modes (`0700` directory and `0600` file), `fsync`, atomic `os.replace`, source/runtime symlink rejection, and quiet cleanup.
- Preserve the Stop command's `-B` flags, quoted paths, stable-launcher preference, and versioned fallback.
- Preserve source version `0.2.6` and keep `.agents/plugins/marketplace.json` pinned to public `v0.2.5`.
- Do not push, publish, tag, release, reinstall, delete the `0.2.4 -> 0.2.5` compatibility link, or mutate the user's Codex cache.
- Use new commits only; do not rewrite branch history.

---

## File Structure

- Modify `hooks/stop_launcher.py`: reduce it to standalone selection-time validation plus direct `python3 -B` execution.
- Modify `tests/test_stop_launcher.py`: remove active same-account replacement tests and retain/add only the approved selection-time and upgrade behavior.
- Modify `tests/test_packaging.py`: preserve the real upgrade environment canary and make the bytecode launcher check prove that installed Stop executed.
- Modify `tests/test_privacy.py`: retain the formatting correction next to the fixed-command privacy contract.
- Modify `docs/superpowers/plans/2026-07-17-stable-stop-hook-upgrade-compat.md`: remove the superseded descriptor/module-snapshot amendment while preserving the original implementation history.
- Do not modify `codex_speak/hook_runtime.py`, `hooks/session_start.py`, `hooks/hooks.json`, `.codex-plugin/plugin.json`, `README.md`, or `.agents/plugins/marketplace.json`.

---

### Task 1: Restore the reviewed lightweight launcher baseline

**Files:**
- Modify: `hooks/stop_launcher.py`
- Modify: `tests/test_stop_launcher.py`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_privacy.py`
- Modify: `docs/superpowers/plans/2026-07-17-stable-stop-hook-upgrade-compat.md`
- Preserve exactly: `docs/superpowers/specs/2026-07-17-stable-stop-hook-upgrade-compat-design.md`

**Interfaces:**
- Preserves: `parse_version(value: str) -> tuple[int, int, int, int, str] | None`.
- Preserves: `select_stop_hook(original_root: Path) -> tuple[Path, Path] | None`.
- Preserves: `main() -> int`, which directly calls `os.execv(sys.executable, [sys.executable, "-B", str(stop_hook)])` or emits the empty hook result.
- Removes: descriptor-returning internal APIs, `STOP_BOOTSTRAP`, runtime module snapshots, and `TrustedPluginFinder`.

- [ ] **Step 1: Verify the branch and protected files before changing content**

Run:

```bash
git status --short
git log --oneline -6
git diff --exit-code HEAD -- \
  codex_speak/hook_runtime.py \
  hooks/session_start.py \
  hooks/hooks.json \
  .codex-plugin/plugin.json \
  README.md \
  .agents/plugins/marketplace.json
```

Expected: the worktree is clean; `2e3d680` is in recent history; the protected-file diff exits zero.

- [ ] **Step 2: Create a non-destructive content revert to the lightweight baseline**

Restore only the files changed by the two over-hardening commits to their reviewed contents at `eb27286`:

```bash
git restore --source=eb27286 -- \
  hooks/stop_launcher.py \
  tests/test_stop_launcher.py \
  tests/test_packaging.py \
  tests/test_privacy.py \
  docs/superpowers/plans/2026-07-17-stable-stop-hook-upgrade-compat.md
```

This creates working-tree changes only. It does not move `HEAD`, delete commits, or alter the approved simplified design.

- [ ] **Step 3: Prove the restore is exact and scoped**

Run:

```bash
test "$(git hash-object hooks/stop_launcher.py)" = \
  "$(git rev-parse eb27286:hooks/stop_launcher.py)"
test "$(git hash-object tests/test_stop_launcher.py)" = \
  "$(git rev-parse eb27286:tests/test_stop_launcher.py)"
git diff --exit-code HEAD -- \
  docs/superpowers/specs/2026-07-17-stable-stop-hook-upgrade-compat-design.md \
  codex_speak/hook_runtime.py \
  hooks/session_start.py \
  hooks/hooks.json \
  .codex-plugin/plugin.json \
  README.md \
  .agents/plugins/marketplace.json
wc -l hooks/stop_launcher.py tests/test_stop_launcher.py
! rg -n 'STOP_BOOTSTRAP|TrustedPluginFinder|module_sources|root_descriptor|stop_descriptor' \
  hooks/stop_launcher.py tests/test_stop_launcher.py
```

Expected: both hash comparisons succeed; protected files are unchanged; line counts are `138` and `176`; the final search produces no matches.

- [ ] **Step 4: Run the lightweight focused baseline**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
    tests.test_stop_launcher \
    tests.test_hook_runtime \
    tests.test_packaging.PackagingTests.test_captured_stop_command_survives_deletion_of_original_version \
    tests.test_packaging.PackagingTests.test_stop_command_falls_back_to_original_version_hook_without_launcher \
    -v
```

Expected: all selected tests pass; the real upgrade test still sends stdin through version B; stderr stays empty.

- [ ] **Step 5: Commit the history-preserving simplification**

```bash
git add \
  hooks/stop_launcher.py \
  tests/test_stop_launcher.py \
  tests/test_packaging.py \
  tests/test_privacy.py \
  docs/superpowers/plans/2026-07-17-stable-stop-hook-upgrade-compat.md
git commit -m "revert: simplify stable stop launcher handoff"
```

Expected: one new commit records the content revert; commits `56681dc` and `275aca7` remain in history.

---

### Task 2: Validate the Marketplace family at selection time

**Files:**
- Modify: `hooks/stop_launcher.py`
- Modify: `tests/test_stop_launcher.py`

**Interfaces:**
- Produces: `_validated_family(original_root: Path) -> tuple[Path, str] | None`, returning `(resolved_family, original_version_name)` only for a supported original version under a real `codex-speak` directory and a real Marketplace identity directory.
- Updates: `select_stop_hook(original_root: Path) -> tuple[Path, Path] | None` to use `_validated_family` before validating or scanning candidates.
- Preserves: `_validate_candidate(root: Path, family: Path)` and direct `os.execv` semantics.

- [ ] **Step 1: Add failing tests for unsupported origins and pre-existing ancestor symlinks**

Add these methods to `StopLauncherTests` in `tests/test_stop_launcher.py`:

```python
    def test_rejects_unsupported_original_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            family = base / "howe829" / "codex-speak"
            create_runtime(family, "0.2.6")
            self.assertIsNone(select_stop_hook(family / "current"))

    def test_rejects_wrong_plugin_family_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            wrong_family = base / "howe829" / "renamed-plugin"
            create_runtime(wrong_family, "0.2.6")
            self.assertIsNone(select_stop_hook(wrong_family / "0.2.5"))

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_rejects_preexisting_symlinked_marketplace_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            cache = base / "cache"
            outside_marketplace = base / "outside-marketplace"
            create_runtime(outside_marketplace / "codex-speak", "0.2.6")
            cache.mkdir()
            marketplace = cache / "howe829"
            marketplace.symlink_to(outside_marketplace, target_is_directory=True)

            self.assertIsNone(
                select_stop_hook(marketplace / "codex-speak" / "0.2.5")
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlinks")
    def test_rejects_preexisting_cross_marketplace_family_symlink_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            marketplace = base / "cache" / "howe829"
            outside_family = base / "outside-marketplace" / "codex-speak"
            create_runtime(outside_family, "0.2.6")
            marketplace.mkdir(parents=True)
            family = marketplace / "codex-speak"
            family.symlink_to(outside_family, target_is_directory=True)
            original = family / "0.2.5"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch.dict(os.environ, {"PLUGIN_ROOT": str(original)}, clear=True),
                patch("hooks.stop_launcher.sys.stdout", stdout),
                patch("hooks.stop_launcher.sys.stderr", stderr),
                patch("hooks.stop_launcher.os.execv") as execute,
            ):
                self.assertEqual(main(), 0)

            execute.assert_not_called()
            self.assertEqual(stdout.getvalue(), "{}\n")
            self.assertEqual(stderr.getvalue(), "")
```

These tests cover state that exists before selection. They do not replace files after validation.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest tests.test_stop_launcher -v
```

Expected: the four new tests fail because the lightweight baseline follows ancestor symlinks and scans valid siblings even when the original version or family name is unsupported; the older tests pass.

- [ ] **Step 3: Add the minimal family validator**

Insert this function after `parse_version` in `hooks/stop_launcher.py`:

```python
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
```

Replace the opening of `select_stop_hook` with:

```python
def select_stop_hook(original_root: Path) -> tuple[Path, Path] | None:
    validated_family = _validated_family(original_root)
    if validated_family is None:
        return None
    family, original_version = validated_family
    original = _validate_candidate(family / original_version, family)
    if original is not None:
        return original[1], original[2]
```

Leave the existing bounded direct-child scan, candidate validation, final containment recheck, environment update, and direct `os.execv` call unchanged.

- [ ] **Step 4: Run the focused launcher and upgrade tests and verify GREEN**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
    tests.test_stop_launcher \
    tests.test_packaging.PackagingTests.test_captured_stop_command_survives_deletion_of_original_version \
    -v
```

Expected: all selected tests pass; version A deletion still selects version B; pre-existing Marketplace/family symlinks fail with exactly `{}` and empty stderr.

- [ ] **Step 5: Confirm the launcher remains lightweight and standalone**

Run:

```bash
wc -l hooks/stop_launcher.py
! rg -n 'STOP_BOOTSTRAP|TrustedPluginFinder|module_sources|import codex_speak|from codex_speak' \
  hooks/stop_launcher.py
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m py_compile hooks/stop_launcher.py
git diff --check
```

Expected: the launcher remains below 180 lines; the search produces no matches; compilation and diff check succeed.

- [ ] **Step 6: Commit the selection-time validation**

```bash
git add hooks/stop_launcher.py tests/test_stop_launcher.py
git commit -m "fix: validate stable stop cache family"
```

---

### Task 3: Restore the useful packaging regression coverage

**Files:**
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_privacy.py`

**Interfaces:**
- Preserves: `make_fake_runtime(family: Path, version: str) -> Path`.
- Strengthens: the real upgrade regression to prove unrelated environment values cross the direct `execv` handoff.
- Strengthens: the installed-entry bytecode test to prove the installed Stop hook actually executed.
- Changes no production interface.

- [ ] **Step 1: Restore the real-upgrade environment canary**

In `make_fake_runtime`, add the environment echo immediately before stdin passthrough:

```python
        "environment_canary = os.environ.get('UNRELATED_HANDOFF_CANARY')\n"
        "if environment_canary is not None:\n"
        "    sys.stdout.write(f'env:{environment_canary}\\n')\n"
```

In `test_captured_stop_command_survives_deletion_of_original_version`, set and assert it:

```python
            environment["UNRELATED_HANDOFF_CANARY"] = "preserved-through-handoff"
```

```python
            self.assertEqual(
                completed.stdout,
                "env:preserved-through-handoff\n" + canary,
            )
```

- [ ] **Step 2: Make the installed-launcher bytecode test prove Stop execution**

At the start of `test_python_plugin_entries_do_not_write_bytecode_into_installed_tree`, derive the cache version from the source manifest:

```python
            manifest = json.loads(
                (ROOT / ".codex-plugin" / "plugin.json").read_text(
                    encoding="utf-8"
                )
            )
```

Use `manifest["version"]` instead of the hard-coded `"0.2.5"` directory component. After copying `hooks`, instrument the installed Stop file without moving its future import:

```python
            stop_sentinel = Path(temporary) / "installed-stop-executed"
            installed_stop = installed_root / "hooks" / "stop.py"
            stop_source = installed_stop.read_text(encoding="utf-8")
            future_import = "from __future__ import annotations\n"
            self.assertTrue(stop_source.startswith(future_import))
            installed_stop.write_text(
                future_import
                + "\nfrom pathlib import Path as _SentinelPath\n"
                + f"_SentinelPath({str(stop_sentinel)!r}).write_text("
                + "'executed', encoding='utf-8')\n"
                + stop_source[len(future_import) :],
                encoding="utf-8",
            )
```

After each subprocess call, assert the stable-launcher invocation ran that installed Stop hook:

```python
                    if arguments[2:] == [
                        str(data_dir / "runtime-hooks" / "stop_launcher.py")
                    ]:
                        self.assertEqual(
                            stop_sentinel.read_text(encoding="utf-8"),
                            "executed",
                        )
```

- [ ] **Step 3: Restore the privacy-test method separator**

Add one blank line between the final assertion in `test_installed_stable_launcher_is_static_and_stop_command_is_fixed` and the next `def` in `tests/test_privacy.py`. Do not change assertions or runtime behavior.

- [ ] **Step 4: Run the strengthened regressions**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest \
    tests.test_packaging.PackagingTests.test_captured_stop_command_survives_deletion_of_original_version \
    tests.test_packaging.PackagingTests.test_python_plugin_entries_do_not_write_bytecode_into_installed_tree \
    tests.test_privacy.PrivacyAndPackagingTests.test_installed_stable_launcher_is_static_and_stop_command_is_fixed \
    -v
```

Expected: all three tests pass; the environment canary and stdin survive; the installed Stop sentinel exists; installed and runtime trees contain no bytecode.

- [ ] **Step 5: Commit the regression-only restoration**

```bash
git add tests/test_packaging.py tests/test_privacy.py
git commit -m "test: preserve stable stop handoff coverage"
```

---

### Task 4: Verify and review the `0.2.6` source candidate

**Files:**
- Verify: all source, tests, documentation, manifest, and Marketplace files.
- Modify only if a failing regression proves a defect within the approved threat model.

**Interfaces:**
- Produces: a clean, reviewed `0.2.6` source candidate.
- Preserves: public Marketplace ref `v0.2.5` and the current local compatibility link.

- [ ] **Step 1: Run the full Python suite outside the restricted sandbox**

Run with the already approved unrestricted Python test command because macOS `kern.bootsessionuuid` is unavailable in the restricted sandbox:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m unittest discover -s tests -v
```

Expected: every Python test passes; only explicitly conditional platform skips are acceptable.

- [ ] **Step 2: Run Swift and static regression gates**

Run:

```bash
swift test --package-path menu-bar -Xswiftc -warnings-as-errors
PYTHONPYCACHEPREFIX=/private/tmp/codex-speak-pycache \
  python3 -m compileall -q hooks codex_speak tests
python3 -m json.tool hooks/hooks.json
git diff --check
test -z "$(rg --files -g '*.pyc')"
```

Expected: Swift tests pass with warnings as errors; compilation and JSON parsing exit zero; diff check is clean; the bytecode search prints nothing.

- [ ] **Step 3: Run the official plugin validator**

Run:

```bash
export REPO_ROOT="$(pwd)"
export PLUGIN_CREATOR_ROOT="${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator"
PYTHONDONTWRITEBYTECODE=1 /private/tmp/codex-plugin-validator/bin/python \
  "$PLUGIN_CREATOR_ROOT/scripts/validate_plugin.py" \
  "$REPO_ROOT"
```

Expected: the validator exits zero and reports the plugin valid.

- [ ] **Step 4: Verify the release boundary and protected local state**

Run:

```bash
python3 -c 'import json; print(json.load(open(".codex-plugin/plugin.json"))["version"])'
python3 -c 'import json; print(json.load(open(".agents/plugins/marketplace.json"))["plugins"][0]["source"]["ref"])'
git status --short --branch
git log --oneline --decorate -12
git diff origin/main...HEAD --stat
```

Expected: source prints `0.2.6`; Marketplace prints `v0.2.5`; only approved spec, plans, implementation, tests, README, and manifest changes differ from `origin/main`; no release or installation state changed.

- [ ] **Step 5: Request a final review using the practical threat model**

Invoke `superpowers:requesting-code-review`. Give the reviewer these explicit boundaries:

```text
Review the stable Stop hook upgrade fix against the approved practical threat model.
The current macOS account's Codex cache and PLUGIN_DATA are trusted during one hook invocation.
Pre-existing Marketplace/family/version/manifest/Stop symlinks must fail closed.
Active same-account replacement after validation, descriptor handoff, module snapshots,
and worker/menu-helper path redirection are intentional non-goals.
Focus on the observed upgrade lifecycle, selection containment, quiet failure, privacy,
atomic installation, real-process upgrade regression, and release-boundary correctness.
```

Expected: the review evaluates the approved architecture rather than reopening the rejected active-mutation design.

- [ ] **Step 6: Process review findings and rerun affected gates**

Use `superpowers:receiving-code-review` for every finding. For a valid in-scope defect, first add a focused failing regression, then make the smallest correction, run the focused test, and rerun Steps 1–4. Reject findings that require active same-account mutation defenses and cite the approved non-goal.

If a valid fix changes files, commit only those reviewed changes:

```bash
git add hooks/stop_launcher.py tests/test_stop_launcher.py tests/test_packaging.py tests/test_privacy.py
git commit -m "fix: close stable stop review gaps"
```

Do not create an empty commit.

- [ ] **Step 7: Apply verification-before-completion and hand off**

Invoke `superpowers:verification-before-completion`, rerun any evidence that became stale, and report:

- the lightweight launcher size and direct-execution architecture;
- the real version-A deletion to version-B execution result;
- the full Python, Swift, JSON, compilation, validator, privacy, and bytecode results;
- source `0.2.6` versus public Marketplace `v0.2.5`;
- that push, tag, release, Marketplace update, reinstall, and compatibility-link removal were not performed.
