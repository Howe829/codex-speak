# Codex Speak 0.2.3 Final Fix Report

Date: 2026-07-16 (Asia/Shanghai)

Reviewed head: `d5afca776057803d040be9e3414b03846a8616f5`

Findings source: `.superpowers/sdd/final-review-findings.md`

## Outcome

The Important persisted-mode/playback actor window is closed with a
`SpeechPlayer`-owned playback authorization generation. The coordinator
acquires an opaque authorization before its final persisted-mode read and
passes it back when requesting playback. Every `stopCurrent()` increments the
player generation, including an idle stop. `SpeechPlayer` validates the token
before reading the clock, creating pipes, or launching `/usr/bin/say`; a stale
token returns the fixed metadata-only cancelled result with zero completed
segments and zero duration.

Existing behavior remains intact: an active owned process is still terminated,
segment cancellation remains tied to the active playback/process identities,
diagnostics record the same allowlisted `PlaybackResult`, and bridge event
handling still returns after the coordinator/diagnostics path so the existing
ack ordering is unchanged.

## TDD RED / GREEN

Important finding deterministic RED:

```text
swift test --package-path menu-bar --filter SpeechCoordinatorTests.testSilentInvalidatesClaimedEventPausedAfterFinalModeReadBeforePlayerStart
Executed 1 test, 2 failures.
Expected launch count 0, observed 1.
Expected cancelled/0/0 metadata, observed spoken/1/0.
```

The test uses a suspending `SpeechPlaying` gate around the real `SpeechPlayer`.
It pauses the claimed event after the coordinator's final Full read but before
the real player validates/starts. A complete Silent selection performs an idle
`stopCurrent()`, then the test releases the old request and proves zero process
launch plus the exact fixed cancelled result. It uses no timing loop or
probabilistic race repetition.

Important finding focused GREEN:

```text
swift test --package-path menu-bar --filter SpeechCoordinatorTests.testSilentInvalidatesClaimedEventPausedAfterFinalModeReadBeforePlayerStart
Executed 1 test, 0 failures.
```

Diagnostics/checkmark Minor RED:

```text
python3 -m unittest tests.test_packaging.PackagingTests.test_claimed_event_checkmarks_sync_even_when_diagnostics_recording_fails -v
Ran 1 test; FAIL because selectedMode/updateCheckmarks were inside the do block.
```

Diagnostics/checkmark Minor GREEN:

```text
python3 -m unittest tests.test_packaging.PackagingTests.test_claimed_event_checkmarks_sync_even_when_diagnostics_recording_fails -v
Ran 1 test; OK.
```

Focused adjacent GREEN:

```text
swift test --disable-sandbox --package-path menu-bar --filter SpeechCoordinatorTests
Executed 14 tests, 0 failures.
swift test --disable-sandbox --package-path menu-bar --filter SpeechPlayerTests
Executed 5 tests, 0 failures.
python3 -m unittest \
  tests.test_packaging.PackagingTests.test_embedded_helper_is_exactly_universal_and_ad_hoc_signed \
  tests.test_packaging.PackagingTests.test_readme_locks_exact_menu_order_and_marketplace_version_prefix -v
Ran 2 tests; OK.
```

The first adjacent Swift attempt without `--disable-sandbox` hit only nested
SwiftPM sandbox/module-cache permission errors. Re-running with a workspace
module cache and `--disable-sandbox` passed; no code/test failure was hidden.

## Finding disposition

1. **Important — persisted final read vs playback start:** fixed. Player-owned
   authorization/generation, unconditional stop invalidation, pre-launch
   validation, fixed cancellation metadata, and deterministic race coverage
   are present.
2. **Minor — diagnostics failure skips checkmark sync:** fixed. The fixed local
   `Could not record playback result` error remains in `catch`; selected mode
   and all checkmarks synchronize afterward on both success and failure.
3. **Minor — AppKit source-contract coverage:** accepted residual. Exact menu
   order has executable Core coverage, but AppKit checkmark/refresh behavior
   still uses source-contract assertions. Converting `MenuController` into an
   executable injected state-mapping surface would be a broad AppKit refactor
   disproportionate to this Minor review wave. The new failure-path assertion
   strengthens the existing source contract without changing that limitation.
4. **Minor — release contracts:** fixed. Packaging now automatically requires
   `Signature=adhoc`; README coverage locks the exact six-item ordered block and
   permits only the `0.2.3+codex.` Marketplace version prefix.

## Full verification

Helper rebuild after all Swift source changes:

```text
./scripts/build_menu_app.sh
Both arm64 and x86_64 release products built; universal app replaced;
assets/CodexSpeakMenu.app: replacing existing signature; exit 0.
```

Full Swift with the compatible Python 3.13 interpreter and real runtime smoke:

```text
CODEX_SPEAK_TEST_PYTHON=/opt/homebrew/bin/python3.13 \
CLANG_MODULE_CACHE_PATH="$PWD/.build/module-cache" \
SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.build/module-cache" \
swift test --disable-sandbox --package-path menu-bar
Executed 51 tests, 0 failures, 0 skipped.
testRealBridgeAndControlSmokeWithCompatibleInterpreter passed.
```

Full Python:

```text
/opt/homebrew/bin/python3.13 -m unittest discover -s tests -v
Ran 181 tests in 4.208s; OK.
```

Static/package checks (all exited 0):

```text
/opt/homebrew/bin/python3.13 -m compileall -q codex_speak hooks
/opt/homebrew/bin/python3.13 -m json.tool hooks/hooks.json >/dev/null
/opt/homebrew/bin/python3.13 -m json.tool .codex-plugin/plugin.json >/dev/null
git diff --check
lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
  x86_64 arm64
codesign --verify --deep --strict assets/CodexSpeakMenu.app
codesign --display --verbose=4 assets/CodexSpeakMenu.app | check exact line
  Signature=adhoc
```

Shipped helper:

```text
Path: assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
SHA-256: 51a6185330f29fcdf604d0071673649aa3d8e83548ae2ac6edeb64eafb9ce28e
Architectures: x86_64 arm64 (exactly two)
Signature: strict verification passed; Signature=adhoc
```

## Self-review

- Authorization is owned and validated by the same actor that launches speech;
  no coordinator-local boolean is trusted for launch safety.
- Authorization is acquired before `getMode()`, so any stop after that point
  invalidates the claimed event even if no child process exists yet.
- Stale authorization exits before clock access and before launch, making the
  cancelled duration deterministically zero.
- Active cancellation logic, process identity checks, failure codes, segment
  counting, stdin-only speech transport, and diagnostics schema were not
  widened.
- No queue, bridge, hook, renderer, event schema, or Marketplace source was
  changed in this repair wave.

## Remaining concern

The only known residual is the documented AppKit executable-test limitation:
checkmark/refresh wiring is still partly protected by source inspection. There
are no deferred Critical or Important findings. Manual audible UI acceptance
was not repeated in this non-interactive fix wave; automated process-launch,
bridge smoke, package, signature, privacy, and race checks all ran.
