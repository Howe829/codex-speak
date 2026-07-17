# Stable Stop Hook Upgrade Compatibility Design

## Status

Simplified design approved in conversation on 2026-07-17. This revision
supersedes the active same-account mutation hardening added during review.

## Problem

Codex records a task's lifecycle-hook command and expands `PLUGIN_ROOT` to the
versioned plugin cache that existed when the task started. A Marketplace
reinstall removes that old cache directory. An already-open task then invokes a
path such as `.../codex-speak/0.2.5/hooks/stop.py`, which no longer exists, even
though the newly installed plugin contains a complete Stop hook.

This is an upgrade-lifecycle problem, not a packaging omission. It has repeated
because released Stop commands directly referenced a version-specific
`${PLUGIN_ROOT}/hooks/stop.py`.

## Goals

- Tasks started with the fixed architecture continue running their Stop hook
  after later Marketplace upgrades delete their original version cache.
- The Stop entry point remains stable across plugin versions without manual
  compatibility symlinks.
- Runtime selection stays within the task's original Marketplace/plugin family.
- Pre-existing symlink layouts, malformed manifests, wrong plugin identities,
  unsupported versions, and missing runtimes fail closed.
- Assistant messages, user input, task titles, IDs, and speech text never enter
  launcher files, process arguments, diagnostics, or error output.
- Missing or invalid runtime candidates produce a valid empty hook result
  instead of a Python path error.
- Queue privacy, menu-helper startup, protocol parsing, and
  Silent/Summary/Full behavior remain unchanged.

## Threat Model

Codex Speak trusts the current macOS account's Codex-managed plugin cache and
plugin-data directory during an individual hook invocation. A process running
as that same account can already modify Codex configuration, installed plugin
code, the stable launcher, and speech runtime data; Codex Speak is not a local
privilege or code-signing boundary against that account.

The design defends against:

- Marketplace upgrades deleting the version directory captured by an open task;
- a symlinked Marketplace identity, plugin family, version root, manifest, or
  Stop file that already exists when selection begins;
- malformed, mismatched, unreadable, nested, or unsupported runtime candidates;
- partial or concurrent SessionStart writes of the stable launcher;
- unavailable runtime state and ordinary pre-exec failures.

The design does not defend against the current account deliberately replacing
plugin files after validation while the same Stop invocation is executing. In
particular, it does not snapshot Python modules, keep an entire runtime open by
descriptor, or redirect worker/menu-helper launches away from the trusted cache.
Those measures add substantial complexity without creating a meaningful trust
boundary against the account that also owns `PLUGIN_DATA`.

## Non-goals

- Changing Codex's global plugin-cache retention policy.
- Retrofitting tasks whose hook command was captured before the fixed release.
- Supporting migration between Marketplace identities such as `personal` and
  `howe829`.
- Defending against active same-account mutation during one hook invocation.
- Copying or retaining a complete versioned plugin runtime under `PLUGIN_DATA`.
- Publishing, tagging, changing the public Marketplace ref, or reinstalling the
  source candidate as part of implementation.

## Evaluated Approaches

### 1. Lightweight stable launcher under `PLUGIN_DATA` — selected

SessionStart atomically installs a standalone launcher in stable private plugin
data. Stop invokes it instead of a version-specific path. The launcher validates
the original cache family at selection time, selects a valid current version,
updates `PLUGIN_ROOT`, and directly executes that version's Stop hook.

This addresses the observed upgrade failure with a small, independently tested
component and keeps ordinary Stop/worker/helper behavior unchanged.

### 2. Versioned full-runtime snapshots under `PLUGIN_DATA` — rejected

SessionStart could copy Python sources, hooks, assets, and the menu helper into a
stable versioned snapshot and run every child from it. That avoids later cache
reopens but adds large copies, retention and cleanup policy, update coordination,
and another mutable same-account code store. The observed upgrade bug does not
justify that operational cost.

### 3. Descriptor execution plus in-memory module snapshots — rejected

A review prototype retained runtime descriptors, executed an opened Stop file,
snapshotted plugin modules, and installed a custom import finder. The launcher
grew from roughly 140 to more than 500 lines yet still could not cover
unqualified imports and worker/menu-helper path launches without redesigning the
whole runtime. This is over-engineering under the selected threat model.

## Architecture

### Packaged launcher

`hooks/stop_launcher.py` is a standalone Python-standard-library program. It
does not import `codex_speak`, because its installed copy runs outside the
versioned plugin tree.

The launcher receives the task's original `PLUGIN_ROOT` and stable
`PLUGIN_DATA`. It never reads hook stdin. It validates the original
Marketplace/plugin family and candidate metadata at selection time, then:

1. chooses the original valid runtime when it still exists;
2. otherwise chooses the highest valid direct sibling version;
3. sets `PLUGIN_ROOT` to the selected root; and
4. replaces itself with `python3 -B SELECTED_ROOT/hooks/stop.py`.

Standard input, output, error, and unrelated environment values remain attached.
The launcher introduces no assistant or speech content into argv or storage.

The final path execution intentionally relies on the trusted-current-account
assumption. It is not an atomic handoff against a concurrent same-account path
replacement.

### Atomic launcher installation

`codex_speak/hook_runtime.py` exposes:

```python
install_stop_launcher(plugin_root: Path, data_dir: Path) -> bool
```

SessionStart calls it before starting the consumer. The installer copies the
fixed packaged launcher into `${PLUGIN_DATA}/runtime-hooks/stop_launcher.py`
using a private `0700` directory, a unique `0600` temporary file, `fsync`, and
atomic `os.replace`. It rejects symlinked source/runtime paths, cleans only its
own temporary file, and returns `False` silently on failure.

Concurrent SessionStart runs leave one complete launcher, never a partial file.

### Stable Stop command

The Stop command prefers the stable launcher and retains the original path as a
pre-upgrade fallback:

```sh
if [ -f "${PLUGIN_DATA}/runtime-hooks/stop_launcher.py" ]; then
  python3 -B "${PLUGIN_DATA}/runtime-hooks/stop_launcher.py"
else
  python3 -B "${PLUGIN_ROOT}/hooks/stop.py"
fi
```

Both paths are quoted and bytecode generation stays disabled.

## Runtime Selection

At selection time the launcher:

1. Requires a supported numeric version name for the original root.
2. Rejects a pre-existing symlink at the Marketplace identity, `codex-speak`
   family, original/candidate version root, manifest, or Stop file.
3. Resolves the Marketplace identity and family and verifies their expected
   parent/child containment.
4. Accepts the original runtime first when its manifest and Stop hook are valid.
5. Otherwise inspects only a bounded set of direct family children; it never
   recurses or crosses to another Marketplace directory.
6. Requires manifest name `codex-speak` and a manifest version exactly matching
   the directory name.
7. Selects the highest numeric release, using formal `+codex.*` only as a
   deterministic same-release tie-breaker.
8. Rechecks resolved containment before direct execution.

The launcher performs no network access.

## Failure Handling and Privacy

- No valid runtime or any pre-exec failure writes exactly `{}` plus newline,
  writes nothing to stderr, and exits zero.
- The launcher never reads, logs, hashes, copies, or persists hook stdin.
- Persistent launcher code is fixed source only; it contains no dynamic task or
  speech data.
- Diagnostics contain no cache paths, raw exceptions, messages, IDs, titles, or
  speech.
- The fallback preserves current behavior if launcher installation failed before
  an upgrade.

## Transition Semantics

The architecture applies only to tasks whose SessionStart and stored Stop
definition come from the fixed release. It cannot rewrite commands captured by
older tasks. Therefore:

- the local `0.2.4 -> 0.2.5` link remains until pre-fix tasks close;
- the first fixed release establishes forward compatibility;
- tasks started on that release survive later ordinary Marketplace replacement;
- public guidance tells users to start a new task immediately after installing
  the first fixed release.

## Branch Simplification

Implementation uses new non-destructive revert/fix commits; it does not rewrite
published or reviewed history. The simplification removes only the last two
active-mutation hardening commits. It preserves the stable launcher, atomic
installer, SessionStart/Stop wiring, upgrade regression, privacy tests, and
`0.2.6` candidate documentation. Small packaging sentinel and formatting fixes
from the reverted commits are reapplied explicitly.

## Testing

### Unit and integration tests

- Atomic/private/idempotent/concurrent launcher installation and failure cleanup.
- Original-runtime preference and newer-sibling selection after original deletion.
- Rejection of pre-existing symlink Marketplace identities, families, version
  roots, manifests, and Stop files.
- Rejection of wrong names, mismatched versions, malformed manifests, nested
  paths, unsupported versions, and candidate-count overflow.
- Exact empty-result behavior on missing runtime and `execv` failure.
- Stable shell fallback when the launcher is absent.
- Static installed launcher content, private-data canaries, environment
  preservation, and bytecode-free installed/runtime trees.

Tests intentionally do not simulate file replacement after validation; that is
outside the selected threat model.

### Real-process upgrade regression

1. Seed version A and install the stable launcher.
2. Capture the configured Stop command as an open task would.
3. Delete version A and create valid version B.
4. Invoke the captured command with `PLUGIN_ROOT` still pointing to version A.
5. Assert version B receives stdin unchanged, retains an unrelated environment
   canary, returns expected stdout with empty stderr, and persists no message
   canary.

### Regression gates

- Full Python suite outside the restricted execution sandbox when macOS boot
  identity is required.
- Swift menu-helper tests with warnings as errors.
- Plugin validator, hook JSON validation, diff check, and source-tree bytecode
  scan.
- Source version remains `0.2.6`; Marketplace remains `v0.2.5` until explicit
  publication authorization.
