# Stable Stop Hook Upgrade Compatibility Design

## Status

Approved for implementation on 2026-07-17.

## Problem

Codex records a task's lifecycle-hook command and expands `PLUGIN_ROOT` to the
versioned plugin cache that existed when the task started. A Marketplace
reinstall removes that old cache directory. An already-open task then invokes a
path such as `.../codex-speak/0.2.5/hooks/stop.py`, which no longer exists, even
though the newly installed plugin contains a complete Stop hook.

This is an upgrade-lifecycle problem, not a packaging omission. It has repeated
across multiple Codex Speak versions and marketplaces because every released
Stop command directly references `${PLUGIN_ROOT}/hooks/stop.py`.

## Goals

- Tasks started with the new architecture continue running their Stop hook after
  later Marketplace upgrades delete their original version cache.
- The Stop entry point remains stable across plugin versions without requiring
  users to create compatibility symlinks manually.
- The launcher executes code only from the same plugin and Marketplace cache
  family that the task originally trusted.
- Assistant messages, user input, thread IDs, task titles, and speech text never
  enter launcher files, process arguments, diagnostics, or error output.
- Missing, corrupt, or uninstalled runtime candidates fail quietly
  with a valid empty hook result instead of a Python path error.
- Normal non-upgrade hook behavior, queue privacy, menu-helper startup, v1/v2/v3
  parsing, and Silent/Summary/Full semantics remain unchanged.

## Non-goals

- Changing Codex's global plugin-cache retention policy.
- Making tasks that started before this hook definition was installed
  retroactively adopt the new command. The local `0.2.4 -> 0.2.5` compatibility
  link remains a one-time bridge for the currently open task.
- Supporting migration between different Marketplace identities such as
  `personal` and `howe829`; Codex treats them as different plugin installations.
- Executing hooks from arbitrary repositories, user-selected paths, or network
  locations.
- Publishing, tagging, changing the public Marketplace ref, or reinstalling the
  source candidate as part of implementation.

## Evaluated Approaches

### 1. Stable launcher under `PLUGIN_DATA` — selected

SessionStart atomically installs a standalone launcher into the plugin's stable
data directory. The stored Stop command invokes that launcher instead of a
version-specific cache path. The launcher locates and executes the current
valid Codex Speak cache from the same Marketplace family.

This keeps the hook command small, the launcher independently testable, and the
runtime private. It depends only on the existing lifecycle guarantee that
SessionStart runs before Stop for a task.

### 2. Inline Python resolver in `hooks.json` — rejected

A self-contained `python3 -c` command could locate the current cache without a
bootstrap file. It would survive cache deletion, but the JSON-embedded program
would be difficult to read, quote, audit, test, and evolve safely.

### 3. Upgrade-time compatibility symlinks — rejected as the product fix

Creating `old-version -> new-version` links fixes one machine and one upgrade.
Ordinary Marketplace users do not run a Codex Speak post-install script, so the
same failure would recur publicly. A symlink remains useful only as a temporary
transition aid for tasks created before the stable command exists.

## Architecture

### Packaged launcher

Add `hooks/stop_launcher.py` as a standalone Python-standard-library program.
It must not import `codex_speak`, because the copied launcher runs outside the
versioned plugin tree.

The launcher receives the task's original `PLUGIN_ROOT` and stable
`PLUGIN_DATA` environment from Codex. It does not parse hook stdin. Once it has
selected a valid current Stop hook, it sets `PLUGIN_ROOT` to that current root.
It opens the selected Stop source with no-follow semantics through the already
validated family, candidate, and hooks directory descriptors, marks only that
validated regular-file descriptor inheritable, and uses `os.execv` to replace
itself with a fixed standard-library bootstrap:

```text
python3 -B -c FIXED_BOOTSTRAP VALIDATED_STOP_FD TRUSTED_STOP_PATH
```

The bootstrap consumes and closes the descriptor, compiles that exact opened
source with the trusted Stop path as `__file__`, restores direct-script
`sys.argv` and import-path semantics, and then executes it as `__main__`.
Consequently a rename or symlink replacement after validation cannot change the
executed Stop source, and the descriptor cannot leak into later worker/helper
children. Standard input, standard output, standard error, and every existing
environment value remain attached; only `PLUGIN_ROOT` is intentionally updated.
Speech content never appears in arguments, environment updates, launcher
storage, hashes, diagnostics, or error output.

### Atomic launcher installation

Add `codex_speak/hook_runtime.py` with:

```python
install_stop_launcher(plugin_root: Path, data_dir: Path) -> bool
```

SessionStart calls this before starting the consumer or returning protocol
context. The installer:

1. Reads the packaged `hooks/stop_launcher.py` from the trusted plugin root.
2. Creates `${PLUGIN_DATA}/runtime-hooks` with mode `0700`.
3. Writes a unique temporary file in that directory, applies mode `0600`,
   flushes and fsyncs it, then atomically replaces `stop_launcher.py`.
4. Normalizes permissions even when identical content is already installed.
5. Cleans temporary files and returns `False` on any failure without emitting
   raw paths or errors.

Concurrent SessionStart hooks may race, but `os.replace` guarantees that Stop
sees either one complete launcher or another complete launcher, never partial
content.

### Stable Stop command

Change the Stop command in `hooks/hooks.json` to prefer the stable launcher and
fall back to the current versioned Stop hook if SessionStart could not install
it:

```sh
if [ -f "${PLUGIN_DATA}/runtime-hooks/stop_launcher.py" ]; then
  python3 -B "${PLUGIN_DATA}/runtime-hooks/stop_launcher.py"
else
  python3 -B "${PLUGIN_ROOT}/hooks/stop.py"
fi
```

Both paths remain quoted. The command contains no assistant content and keeps
bytecode generation disabled.

## Runtime Selection

The launcher follows this order:

1. If the task's original real, non-symlink Stop hook still exists and its
   manifest is valid, execute it. This preserves exact-version behavior when
   Codex later begins retaining old caches.
2. Open the original version directory's parent using
   `O_DIRECTORY | O_NOFOLLOW`, validate the opened directory identity against
   the family path, and enumerate only its direct children through that anchored
   descriptor. A symlinked family or an identity change fails closed.
3. Ignore symlink roots, non-directories, unreadable entries, version names
   outside the supported numeric release/build format, manifests with a name
   other than `codex-speak`, manifest versions that differ from the directory
   name, and symlinked or missing Stop hook files.
4. Select the highest valid numeric version. A formal `+codex.*` build is used
   only as a deterministic tie-breaker within the same numeric version.
5. Open and validate candidate directories, manifests, hooks directories, and
   the Stop regular file relative to their already-open parent descriptors.
   Recheck the family identity before handoff, then execute only the opened Stop
   descriptor rather than reopening its path.

The scan never crosses to another Marketplace directory and performs no
network access.

## Failure Handling and Privacy

- If no valid runtime exists, write exactly `{}` plus a newline and exit zero.
- If family opening, candidate inspection, descriptor handoff, or `execv`
  fails, do the same without writing stderr.
- The launcher never reads, logs, hashes, copies, or persists hook stdin.
- The only persistent code is the fixed launcher source itself, protected by
  the existing private plugin-data directory.
- No diagnostic contains cache paths, raw exceptions, hook messages, thread
  identifiers, titles, or speech.
- The versioned fallback preserves current behavior when launcher installation
  fails before any upgrade; after a cache deletion, the stable launcher is the
  compatibility boundary.

## Transition Semantics

This architecture becomes effective for tasks whose SessionStart and stored
Stop definition come from the new release. It cannot rewrite hook commands
already captured by older tasks. Therefore:

- the current local `0.2.4 -> 0.2.5` link remains until all pre-fix tasks close;
- the first release containing this design establishes forward compatibility;
- tasks started on that release must survive the next upgrade without any link;
- public upgrade guidance still tells users to start a new task immediately
  after installing the first fixed release.

## Testing

### Unit tests

- Launcher installation is atomic, private, idempotent, byte-for-byte exact,
  and leaves no temporary files after success or failure.
- Concurrent installers always leave one complete valid launcher.
- The resolver accepts the original valid root, then accepts a newer valid
  sibling after the original is deleted.
- It rejects symlink families/roots/hooks, family identity changes, wrong names,
  mismatched versions, malformed manifests, nested paths, and unsupported
  version strings.
- A deterministic cross-Marketplace family-symlink regression proves that no
  external runtime is selected or executed.
- A deterministic post-validation replacement regression proves that the
  originally opened Stop source executes and that its inherited descriptor is
  closed before Stop code can start children.
- Missing or fully invalid runtime state produces only the empty hook result.

### Real-process upgrade regression

Create a temporary Marketplace-like cache and stable plugin-data directory:

1. Seed version A and run SessionStart installation.
2. Capture the stable Stop command as an old task would.
3. Delete version A and create version B.
4. Invoke the captured command with `PLUGIN_ROOT` still pointing to version A.
5. Assert version B's Stop hook receives stdin unchanged, retains an unrelated
   environment canary, and produces the expected stdout, with no stderr and no
   message content in argv, environment updates, or files.

Also verify the shell fallback when no stable launcher exists.

### Regression gates

- Existing Python hook, privacy, queue, rendering, protocol, packaging, and
  worker suites.
- Swift menu-helper tests with warnings treated as errors.
- Plugin validator, hook JSON validation, and bytecode-free compilation.
- A packaged-cache smoke proving SessionStart creates the stable launcher and a
  simulated subsequent upgrade still executes Stop.

## Versioning and Release Boundary

Prepare source version `0.2.6`. Update README migration and troubleshooting
language to distinguish the one-time transition from forward-compatible future
upgrades. Keep `.agents/plugins/marketplace.json` pinned to released `v0.2.5`
until a separate explicit publish/install instruction.
