# Codex Speak Silent Speech Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Codex Speak 0.2.3 with a persistent Silent menu mode that immediately stops current audio, clears pending speech, and prevents all playback until Summary or Full is selected.

**Architecture:** Keep `silent` in the settings/control domain while preserving the existing Summary/Full-only speech-event schema. Python suppresses new Stop-hook events and fallback playback; a new testable Swift coordinator serializes persisted mode changes, stop/clear side effects, startup cleanup, and the final claimed-event playback gate before the AppKit menu delegates to it.

**Tech Stack:** Python 3 standard library and `unittest`; Swift 6, Swift Package Manager, AppKit, Foundation; local universal macOS helper build and ad hoc code signing.

## Global Constraints

- Release version is exactly `0.2.3`; formal Marketplace versions begin with `0.2.3+codex.`.
- Settings schema remains version 1 and accepts exactly `silent`, `summary`, and `full`; missing or invalid settings repair to `summary`.
- Menu order is exactly `Silent`, `Summary`, `Full`, `Stop Current Speech`, `Clear Pending Speeches`, `Quit Codex Speak`.
- Speech payloads, queue envelopes, bridge events, playback diagnostics, and render modes remain Summary/Full-only; forged `mode: silent` speech events are rejected.
- Selecting Silent persists first, then stops current speech, then clears pending entries; write failure preserves playback and the prior mode.
- A successful Silent write followed by readback failure fails safe to local Silent and still performs stop/clear; a successful readback of another trusted mode adopts that mode without Silent side effects.
- A successful Summary/Full write immediately becomes the trusted local selection; successful readback may replace it, while readback failure keeps the requested mode and returns `.readFailed(requestedMode)` for Task 5 to show `Could not read speech mode`.
- Only a successfully persisted later selection supersedes suspended Silent cleanup. A later write failure does not supersede it; a later audible write does, even if its readback fails.
- Silent startup clears pending entries before bridge consumption; claimed native events and fallback events re-check persisted mode immediately before playback.
- Returning to Summary or Full never replays events discarded while Silent was active.
- Silent diagnostics contain fixed metadata only and do not change the diagnostic schema.
- The shipped helper remains exactly `arm64 x86_64`, executable, locally ad hoc signed, and requires macOS 13 or later.

---

## File Structure

- Modify `codex_speak/settings.py`: accept and persist the third control mode without changing schema version.
- Modify `hooks/stop.py`: short-circuit Silent before rendering, enqueueing, or consumer startup.
- Modify `codex_speak/worker.py`: add an injectable per-event persisted-mode check immediately before fallback playback.
- Modify `tests/test_settings.py`, `tests/test_hooks.py`, `tests/test_worker.py`: cover persistence, hook suppression, fallback suppression, and privacy.
- Modify `menu-bar/Sources/CodexSpeakCore/Models.swift`: add Silent as a control mode while explicitly excluding it from decoded speech events.
- Modify `menu-bar/Sources/CodexSpeakCore/ControlClient.swift`: allow the control command to round-trip Silent.
- Create `menu-bar/Sources/CodexSpeakCore/SpeechCoordinator.swift`: own the serialized mode transition, startup cleanup, and final playback gate.
- Modify `menu-bar/Sources/CodexSpeakCore/SpeechPlayer.swift` and `DiagnosticsClient.swift`: conform existing actors/clients to narrow coordinator protocols.
- Create `menu-bar/Tests/CodexSpeakCoreTests/SpeechCoordinatorTests.swift`: exercise success, failure, concurrency boundary, startup, and claimed-event behavior without AppKit.
- Modify `menu-bar/Sources/CodexSpeakCore/PluginEnablement.swift`, `MenuController.swift`, and Swift tests: expose and wire the exact six-item control menu.
- Modify `.codex-plugin/plugin.json`, `README.md`, and packaging/privacy tests: document Silent and assert the 0.2.3 release contract.
- Rebuild `assets/CodexSpeakMenu.app`: embed the new universal, ad hoc-signed Swift helper.

### Task 1: Persistent Silent settings and Stop-hook suppression

**Files:**
- Modify: `codex_speak/settings.py`
- Modify: `hooks/stop.py`
- Test: `tests/test_settings.py`
- Test: `tests/test_hooks.py`

**Interfaces:**
- Consumes: existing `load_mode(data_dir: Path) -> str` and `save_mode(data_dir: Path, mode: str) -> str`.
- Produces: settings values in `{"summary", "full", "silent"}`; `handle_event(...) -> False` in Silent without calling renderer, queue, or consumer.

- [ ] **Step 1: Write failing persistence and CLI tests**

Add focused cases to `tests/test_settings.py`:

```python
def test_silent_mode_persists_with_version_one_across_loads(self) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        self.assertEqual(save_mode(root, "silent"), "silent")
        self.assertEqual(load_mode(root), "silent")
        self.assertEqual(
            json.loads((root / "settings.json").read_text(encoding="utf-8")),
            {"version": 1, "mode": "silent"},
        )

def test_cli_sets_and_gets_silent(self) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        set_silent = self._run_cli(root, "set", "silent")
        self.assertEqual((set_silent.returncode, set_silent.stdout, set_silent.stderr), (0, "silent\n", ""))
        get_silent = self._run_cli(root, "get")
        self.assertEqual((get_silent.returncode, get_silent.stdout, get_silent.stderr), (0, "silent\n", ""))
```

- [ ] **Step 2: Write the failing Stop-hook test**

Add to `tests/test_hooks.py`, patching renderer and enqueue so the test proves the short circuit occurs before either boundary:

```python
def test_silent_control_mode_does_not_render_enqueue_or_start_consumer(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        data_dir = Path(temporary) / "data"
        payload = {
            "session_id": "silent-session",
            "turn_id": "silent-turn",
            "last_assistant_message": assistant_message("completed", "PRIVATE SPEECH"),
        }
        with patch("hooks.stop.render_speech") as renderer, patch("hooks.stop.enqueue") as enqueue_event:
            result = handle_event(
                payload,
                plugin_root=Path(temporary),
                data_dir=data_dir,
                platform_name="darwin",
                mode_loader=lambda _: "silent",
                start_consumer=lambda *_: self.fail("consumer must not start"),
            )
        self.assertFalse(result)
        renderer.assert_not_called()
        enqueue_event.assert_not_called()
        self.assertFalse((data_dir / "spool").exists())
```

- [ ] **Step 3: Run the focused tests and verify red**

Run:

```bash
python3 -m unittest tests.test_settings.SettingsTests.test_silent_mode_persists_with_version_one_across_loads tests.test_settings.SettingsTests.test_cli_sets_and_gets_silent tests.test_hooks.HookTests.test_silent_control_mode_does_not_render_enqueue_or_start_consumer -v
```

Expected: settings rejects `silent`, and the hook calls `render_speech` with an unsupported mode.

- [ ] **Step 4: Implement the minimal settings and hook gate**

Change the accepted control modes in `codex_speak/settings.py`:

```python
_MODES: Final[frozenset[str]] = frozenset({"silent", "summary", "full"})
```

Split loading from rendering in `hooks/stop.py` so Silent returns before renderer invocation while preserving the existing invalid-settings diagnostic:

```python
try:
    mode = mode_loader(data_dir)
except (OSError, TypeError, ValueError):
    record(
        data_dir,
        event_id=safe_event_id,
        status=parsed.status,
        result="failed",
        mode="unknown",
        error_code="invalid_settings",
    )
    return False
if mode == "silent":
    return False
try:
    speech = render_speech(parsed, mode)
except (TypeError, ValueError):
    record(
        data_dir,
        event_id=safe_event_id,
        status=parsed.status,
        result="failed",
        mode="unknown",
        error_code="invalid_settings",
    )
    return False
```

- [ ] **Step 5: Run focused and adjacent Python tests**

Run:

```bash
python3 -m unittest tests.test_settings tests.test_hooks tests.test_render tests.test_queue -v
```

Expected: all tests pass; render and queue validators still reject Silent because their accepted modes are unchanged.

- [ ] **Step 6: Commit Task 1**

```bash
git add codex_speak/settings.py hooks/stop.py tests/test_settings.py tests/test_hooks.py
git commit -m "feat: suppress stop hook in silent mode"
```

### Task 2: Python fallback final playback gate

**Files:**
- Modify: `codex_speak/worker.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_privacy.py`

**Interfaces:**
- Consumes: `load_mode(data_dir: Path) -> str` from Task 1 and claimed `QueuedEvent` values from `poll_next`.
- Produces: `run_worker(..., mode_loader: Callable[[Path], str] = load_mode) -> int`; Silent events are discarded with metadata only and never invoke `say`.

- [ ] **Step 1: Write a failing per-event Silent worker test**

Add to `tests/test_worker.py`:

```python
def test_silent_mode_discards_each_claimed_event_without_invoking_say(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        data_dir = Path(temporary) / "data"
        say_path = self._fake_executable(Path(temporary))
        enqueue(
            data_dir,
            summary_payload("completed", "PRIVATE SILENT SPEECH"),
            session_id="silent-session",
            turn_id="silent-turn",
            now=100.0,
        )
        result = run_worker(
            data_dir,
            say_path=say_path,
            mode_loader=lambda _: "silent",
            run_command=lambda *_args, **_kwargs: self.fail("say was invoked"),
            sleep=lambda _: None,
            clock=lambda: 102.0,
            monotonic=lambda: 10.0,
        )
        self.assertEqual(result, 0)
        entries = read_diagnostics(data_dir)
        self.assertEqual(entries[0]["result"], "discarded")
        self.assertEqual(entries[0]["segment_count"], 0)
        self.assertIsNone(entries[0]["error_code"])
        self.assertNotIn("PRIVATE SILENT SPEECH", json.dumps(entries))
        self.assertEqual(list((data_dir / "spool").glob("*.json")), [])
```

- [ ] **Step 2: Write a failing mode-refresh-per-event test**

Add a two-event case proving the loader is called after each claim and an audible-to-Silent transition suppresses only the second event:

```python
def test_worker_refreshes_mode_immediately_before_every_event(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        data_dir = Path(temporary) / "data"
        say_path = self._fake_executable(Path(temporary))
        for index in range(2):
            enqueue(
                data_dir,
                summary_payload("completed", f"speech-{index}"),
                session_id=f"session-{index}",
                turn_id=f"turn-{index}",
                now=100.0 + index / 10,
            )
        modes = iter(("summary", "silent"))
        spoken: list[str] = []
        run_worker(
            data_dir,
            say_path=say_path,
            mode_loader=lambda _: next(modes),
            run_command=lambda arguments, **kwargs: (
                spoken.append(kwargs["input"]) or subprocess.CompletedProcess(arguments, 0)
            ),
            sleep=lambda _: None,
            clock=lambda: 102.0,
            monotonic=lambda: 10.0,
        )
        self.assertEqual(spoken, ["speech-0"])
```

- [ ] **Step 3: Run the new tests and verify red**

Run:

```bash
python3 -m unittest tests.test_worker.WorkerTests.test_silent_mode_discards_each_claimed_event_without_invoking_say tests.test_worker.WorkerTests.test_worker_refreshes_mode_immediately_before_every_event -v
```

Expected: `run_worker` rejects the new `mode_loader` argument.

- [ ] **Step 4: Add the final fallback gate**

Import `load_mode`, add the injectable argument, and place this branch immediately after `event is None` handling and before checking the `say` executable:

```python
from .settings import load_mode

def run_worker(
    data_dir: Path,
    *,
    say_path: Path = Path("/usr/bin/say"),
    run_command: Callable[..., subprocess.CompletedProcess] | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    monotonic: Callable[[], float] | None = None,
    clock_id: str | None = None,
    mode_loader: Callable[[Path], str] = load_mode,
) -> int:
    # existing setup and poll loop
    if mode_loader(data_dir) == "silent":
        record(
            data_dir,
            event_id=event.event_id,
            status=event.status,
            result="discarded",
            mode=event.mode,
        )
        continue
```

- [ ] **Step 5: Run worker and privacy suites**

Run:

```bash
python3 -m unittest tests.test_worker tests.test_privacy -v
```

Expected: all tests pass, `say` sees no Silent event content, and diagnostics contain no speech text.

- [ ] **Step 6: Commit Task 2**

```bash
git add codex_speak/worker.py tests/test_worker.py tests/test_privacy.py
git commit -m "feat: gate fallback playback on silent mode"
```

### Task 3: Strict Swift control/event mode separation

**Files:**
- Modify: `menu-bar/Sources/CodexSpeakCore/Models.swift`
- Modify: `menu-bar/Sources/CodexSpeakCore/ControlClient.swift`
- Modify: `menu-bar/Tests/CodexSpeakCoreTests/BridgeProcessTests.swift`

**Interfaces:**
- Consumes: settings CLI output `silent|summary|full`.
- Produces: `SpeechMode.silent` for control APIs; `BridgeMessage.decode` rejects any event whose decoded mode is `.silent`.

- [ ] **Step 1: Extend control tests and add a forged-event rejection**

In `BridgeProcessTests.swift`, add `mode: silent` to invalid event lines and update the control test to round-trip Silent:

```swift
#"{"type":"event","event_id":"0123456789abcdef01234567","mode":"silent","status":"completed","segments":["must reject"]}"#,
```

```swift
func testControlClientAcceptsSilentWithoutMakingItAValidSpeechEventMode() throws {
    let runner = RecordingCommandRunner(outputs: ["silent\n", "silent\n"])
    let client = ControlClient(
        pluginRoot: URL(fileURLWithPath: "/plugin"),
        dataDirectory: URL(fileURLWithPath: "/data"),
        pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
        runner: runner
    )
    XCTAssertEqual(try client.getMode(), .silent)
    try client.setMode(.silent)
    XCTAssertEqual(runner.requests.map(\.arguments), [
        ["-B", "-m", "codex_speak.settings", "--data-dir", "/data", "get"],
        ["-B", "-m", "codex_speak.settings", "--data-dir", "/data", "set", "silent"],
    ])
    XCTAssertThrowsError(try BridgeMessage.decode(
        line: #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"silent","status":"completed","segments":["must reject"]}"#
    ))
}
```

- [ ] **Step 2: Run the focused Swift test and verify red**

Run:

```bash
swift test --package-path menu-bar --filter 'BridgeProcessTests|ControlAndDiagnosticsTests'
```

Expected: `.silent` does not exist.

- [ ] **Step 3: Add Silent to the control enum and preserve event validation**

Update `SpeechMode`:

```swift
public enum SpeechMode: String, Codable, Sendable {
    case silent
    case summary
    case full
}
```

In the event decoder, require an audible event mode after raw-value decoding:

```swift
let rawMode = dictionary["mode"] as? String,
let mode = SpeechMode(rawValue: rawMode),
mode == .summary || mode == .full,
```

Keep the existing `status != "silent" || mode == .full` rule unchanged. No Python queue, bridge, renderer, or diagnostic mode set changes in this task.

- [ ] **Step 4: Run Swift and Python schema-boundary tests**

Run:

```bash
swift test --package-path menu-bar --filter 'BridgeProcessTests|ControlAndDiagnosticsTests'
python3 -m unittest tests.test_queue tests.test_render tests.test_diagnostics -v
```

Expected: all tests pass; only the control path accepts Silent.

- [ ] **Step 5: Commit Task 3**

```bash
git add menu-bar/Sources/CodexSpeakCore/Models.swift menu-bar/Sources/CodexSpeakCore/ControlClient.swift menu-bar/Tests/CodexSpeakCoreTests/BridgeProcessTests.swift
git commit -m "feat: add silent control mode"
```

### Task 4: Testable Swift mode and playback coordinator

**Files:**
- Create: `menu-bar/Sources/CodexSpeakCore/SpeechCoordinator.swift`
- Modify: `menu-bar/Sources/CodexSpeakCore/SpeechPlayer.swift`
- Modify: `menu-bar/Sources/CodexSpeakCore/DiagnosticsClient.swift`
- Create: `menu-bar/Tests/CodexSpeakCoreTests/SpeechCoordinatorTests.swift`

**Interfaces:**
- Consumes: `ControlClientProtocol`, `SpeechPlayer`, `DiagnosticsClient`, and `SpeechEvent`.
- Produces: `SpeechCoordinator.selectedMode`, `refreshForStartup()`, `selectMode(_:)`, `handle(event:)`; result enums tell AppKit which fixed local error to show.

- [ ] **Step 1: Write coordinator test doubles and transition tests**

Create `SpeechCoordinatorTests.swift` with actor-safe spies implementing these exact protocols:

```swift
protocol SpeechPlaying: Sendable {
    func play(event: SpeechEvent) async -> PlaybackResult
    func stopCurrent() async
}

protocol PlaybackRecording: Sendable {
    func record(event: SpeechEvent, result: PlaybackResult) throws
    func recordControlFailure(_ errorCode: ControlErrorCode) throws
}
```

Cover these exact assertions:

```swift
func testSilentSelectionPersistsReadsStopsThenClears() async {
    // Script control operations as set(silent), get(silent), clear; spy player records stop.
    // Assert result == .applied(.silent), selectedMode == .silent,
    // and the shared ordered log is ["set:silent", "get", "stop", "clear"].
}

func testSilentWriteFailurePreservesPriorModeAndDoesNotStopOrClear() async {
    // Make setMode throw. Assert .writeFailed(.summary), selectedMode remains summary,
    // and neither player.stopCurrent nor clearPending is called.
}

func testSilentReadFailureAfterWriteFailsSafeAndStillStopsAndClears() async {
    // setMode succeeds and getMode throws. Assert .readFailedFailSafe(queueClearFailed: false),
    // selectedMode == .silent, and ordered log ends with stop then clear.
}

func testConcurrentTrustedReadbackAdoptsReturnedFullWithoutSilentSideEffects() async {
    // setMode(.silent), getMode() returns .full. Assert .applied(.full), no stop, no clear.
}

func testQueueClearFailureLeavesSilentActiveAndRecordsFixedFailure() async {
    // clearPending throws. Assert .appliedWithQueueClearFailure(.silent), one stop,
    // one recordControlFailure(.queueClearFailed), and no speech string in spy metadata.
}

func testAudibleReadbackFailureTrustsSuccessfullyPersistedRequestedMode() async {
    // setMode(.full) succeeds and getMode() throws. Assert .readFailed(.full),
    // selectedMode and persisted mode remain full, with no Silent side effects.
}

func testAudibleReadbackFailureSupersedesSuspendedSilentCleanup() async {
    // Suspend Silent in stopCurrent, then persist Full and fail its readback.
    // Assert Full returns .readFailed(.full), stale Silent returns .applied(.full),
    // and no stale clear or queue-clear diagnostic occurs.
}

func testFailedAudibleWriteDoesNotSupersedeSuspendedSilentCleanup() async {
    // Suspend a confirmed Silent selection, then fail setMode(.full).
    // Assert Silent still clears once and completes as .applied(.silent).
}
```

- [ ] **Step 2: Write startup and claimed-event tests**

Add cases:

```swift
func testStartupSilentClearsBeforeReturningForBridgeStart() async throws {
    // getMode returns silent; assert refreshForStartup() == .ready(.silent)
    // and log is ["get", "clear"].
}

func testClaimedEventInSilentIsCancelledWithoutPlayback() async throws {
    // getMode returns silent. Call handle(event: privateEvent).
    // Assert player.play was not called and diagnostics received
    // PlaybackResult(outcome: .cancelled, errorCode: nil,
    //                completedSegmentCount: 0, durationMilliseconds: 0).
}

func testClaimedEventInAudibleModePlaysAndRecordsResult() async throws {
    // getMode returns full. Assert one play and the exact returned PlaybackResult is recorded.
}
```

- [ ] **Step 3: Run the coordinator tests and verify red**

Run:

```bash
swift test --package-path menu-bar --filter SpeechCoordinatorTests
```

Expected: the coordinator file and its protocols/results do not exist.

- [ ] **Step 4: Implement coordinator protocols and results**

Create `SpeechCoordinator.swift` with these public result contracts:

```swift
public protocol SpeechPlaying: Sendable {
    func play(event: SpeechEvent) async -> PlaybackResult
    func stopCurrent() async
}

public protocol PlaybackRecording: Sendable {
    func record(event: SpeechEvent, result: PlaybackResult) throws
    func recordControlFailure(_ errorCode: ControlErrorCode) throws
}

public enum ModeSelectionResult: Equatable, Sendable {
    case applied(SpeechMode)
    case appliedWithQueueClearFailure(SpeechMode)
    case writeFailed(SpeechMode)
    case readFailed(SpeechMode)
    case readFailedFailSafe(queueClearFailed: Bool)
}

public enum StartupModeResult: Equatable, Sendable {
    case ready(SpeechMode)
    case readyWithQueueClearFailure(SpeechMode)
}
```

Implement `public actor SpeechCoordinator` with stored `controlClient`, `speechPlayer`, `diagnosticsClient`, and `selectedMode = .summary`. Its methods use these exact rules:

```swift
public actor SpeechCoordinator {
    private let controlClient: any ControlClientProtocol
    private let speechPlayer: any SpeechPlaying
    private let diagnosticsClient: any PlaybackRecording
    private var modeSelectionRequestGeneration: UInt64 = 0
    private var latestSuccessfullyPersistedSelectionGeneration: UInt64 = 0
    public private(set) var selectedMode = SpeechMode.summary

    public init(
        controlClient: any ControlClientProtocol,
        speechPlayer: any SpeechPlaying,
        diagnosticsClient: any PlaybackRecording
    ) {
        self.controlClient = controlClient
        self.speechPlayer = speechPlayer
        self.diagnosticsClient = diagnosticsClient
    }

public func refreshForStartup() throws -> StartupModeResult {
    selectedMode = try controlClient.getMode()
    guard selectedMode == .silent else { return .ready(selectedMode) }
    do {
        _ = try controlClient.clearPending()
        return .ready(.silent)
    } catch {
        try? diagnosticsClient.recordControlFailure(.queueClearFailed)
        return .readyWithQueueClearFailure(.silent)
    }
}

public func selectMode(_ requestedMode: SpeechMode) async -> ModeSelectionResult {
    modeSelectionRequestGeneration &+= 1
    let selectionGeneration = modeSelectionRequestGeneration
    let priorMode = selectedMode
    do { try controlClient.setMode(requestedMode) }
    catch { return .writeFailed(priorMode) }
    latestSuccessfullyPersistedSelectionGeneration = selectionGeneration

    if requestedMode != .silent {
        selectedMode = requestedMode
        do {
            selectedMode = try controlClient.getMode()
            return .applied(selectedMode)
        } catch {
            return .readFailed(requestedMode)
        }
    }

    do {
        let confirmedMode = try controlClient.getMode()
        selectedMode = confirmedMode
        guard confirmedMode == .silent else { return .applied(confirmedMode) }
    } catch {
        selectedMode = .silent
        return await stopAndClear(
            readbackFailed: true,
            selectionGeneration: selectionGeneration
        )
    }
    return await stopAndClear(
        readbackFailed: false,
        selectionGeneration: selectionGeneration
    )
}

private func stopAndClear(
    readbackFailed: Bool,
    selectionGeneration: UInt64
) async -> ModeSelectionResult {
    await speechPlayer.stopCurrent()
    guard selectionGeneration == latestSuccessfullyPersistedSelectionGeneration else {
        return .applied(selectedMode)
    }
    do {
        _ = try controlClient.clearPending()
        return readbackFailed ? .readFailedFailSafe(queueClearFailed: false) : .applied(.silent)
    } catch {
        try? diagnosticsClient.recordControlFailure(.queueClearFailed)
        return readbackFailed ? .readFailedFailSafe(queueClearFailed: true) : .appliedWithQueueClearFailure(.silent)
    }
}

public func handle(event: SpeechEvent) async throws {
    let persistedMode = try controlClient.getMode()
    selectedMode = persistedMode
    let result: PlaybackResult
    if persistedMode == .silent {
        result = PlaybackResult(
            outcome: .cancelled,
            errorCode: nil,
            completedSegmentCount: 0,
            durationMilliseconds: 0
        )
    } else {
        result = await speechPlayer.play(event: event)
    }
    try diagnosticsClient.record(event: event, result: result)
}
}
```

Make `SpeechPlayer` conform to `SpeechPlaying` and `DiagnosticsClient` conform to `PlaybackRecording` in their declarations; their existing method bodies remain unchanged.

- [ ] **Step 5: Run coordinator and all Swift tests**

Run:

```bash
swift test --package-path menu-bar --filter SpeechCoordinatorTests
swift test --package-path menu-bar
```

Expected: all tests pass, including the ordered stop/clear and claimed-event no-play assertions.

- [ ] **Step 6: Commit Task 4**

```bash
git add menu-bar/Sources/CodexSpeakCore/SpeechCoordinator.swift menu-bar/Sources/CodexSpeakCore/SpeechPlayer.swift menu-bar/Sources/CodexSpeakCore/DiagnosticsClient.swift menu-bar/Tests/CodexSpeakCoreTests/SpeechCoordinatorTests.swift
git commit -m "feat: coordinate silent playback gates"
```

### Task 5: Six-item AppKit menu and lifecycle wiring

**Files:**
- Modify: `menu-bar/Sources/CodexSpeakCore/PluginEnablement.swift`
- Modify: `menu-bar/Sources/CodexSpeakMenu/MenuController.swift`
- Modify: `menu-bar/Tests/CodexSpeakCoreTests/MenuConfigurationTests.swift`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_privacy.py`

**Interfaces:**
- Consumes: `SpeechCoordinator` and its result enums from Task 4.
- Produces: exact menu order, three mutually exclusive checkmarks, startup cleanup before `bridge.start`, and fixed local errors for mode read/write and queue clear failures.

- [ ] **Step 1: Change exact-menu and documentation-contract tests to six items**

Update `MenuConfigurationTests.swift`:

```swift
func testMenuHasExactSixItemsInOrder() {
    XCTAssertEqual(codexSpeakMenuItemTitles, [
        "Silent",
        "Summary",
        "Full",
        "Stop Current Speech",
        "Clear Pending Speeches",
        "Quit Codex Speak",
    ])
}
```

Update menu-title expectations in `tests/test_privacy.py` and add packaging source assertions that `silentItem`, `summaryItem`, and `fullItem` each compare against the selected mode in `updateCheckmarks()`.

- [ ] **Step 2: Run menu contract tests and verify red**

Run:

```bash
swift test --package-path menu-bar --filter MenuConfigurationTests
python3 -m unittest tests.test_packaging tests.test_privacy -v
```

Expected: the current five-item order fails and the Silent menu source is absent.

- [ ] **Step 3: Add the menu title and coordinator wiring**

Set `codexSpeakMenuItemTitles` to the exact six strings. In `MenuController`:

```swift
private let coordinator: SpeechCoordinator
private let silentItem: NSMenuItem
private let summaryItem: NSMenuItem
private let fullItem: NSMenuItem
private var selectedMode = SpeechMode.summary
```

Construct all three mode items at indexes 0, 1, and 2, shift action item indexes to 3, 4, and 5, and add them in exact order. Add:

```swift
@objc private func selectSilent() { selectMode(.silent) }
@objc private func selectSummary() { selectMode(.summary) }
@objc private func selectFull() { selectMode(.full) }

private func selectMode(_ requestedMode: SpeechMode) {
    Task { [weak self] in
        guard let self else { return }
        let result = await coordinator.selectMode(requestedMode)
        selectedMode = await coordinator.selectedMode
        updateCheckmarks()
        switch result {
        case .applied:
            break
        case .appliedWithQueueClearFailure:
            showLocalError("Could not clear pending speeches")
        case .writeFailed:
            showLocalError("Could not change speech mode")
        case .readFailed, .readFailedFailSafe:
            showLocalError("Could not read speech mode")
        }
    }
}

private func updateCheckmarks() {
    silentItem.state = selectedMode == .silent ? .on : .off
    summaryItem.state = selectedMode == .summary ? .on : .off
    fullItem.state = selectedMode == .full ? .on : .off
}
```

Replace direct event playback with `try await coordinator.handle(event:)`. In `start()`, call `refreshForStartup()` and apply its returned mode before creating `bridgeTask`; if it returns `.readyWithQueueClearFailure`, show the fixed queue-clear error but still start the bridge. Keep the manual Stop and Clear items delegating to the existing player/control operations.

For a claimed-event handling error, keep the bridge alive, acknowledge the event through the existing handler return, and show `Could not record playback result`; never retry or replay that claimed event. Both `.readFailed(requestedMode)` for Summary/Full and `.readFailedFailSafe` for Silent show `Could not read speech mode`. If Silent queue clearing also fails, its fixed `queue_clear_failed` diagnostic remains the additional evidence without replacing the read error.

- [ ] **Step 4: Run menu, coordinator, packaging, and privacy tests**

Run:

```bash
swift test --package-path menu-bar
python3 -m unittest tests.test_packaging tests.test_privacy -v
```

Expected: all tests pass; bridge startup occurs only after persisted mode refresh and Silent startup clearing.

- [ ] **Step 5: Commit Task 5**

```bash
git add menu-bar/Sources/CodexSpeakCore/PluginEnablement.swift menu-bar/Sources/CodexSpeakMenu/MenuController.swift menu-bar/Tests/CodexSpeakCoreTests/MenuConfigurationTests.swift tests/test_packaging.py tests/test_privacy.py
git commit -m "feat: add silent mode to menu bar"
```

### Task 6: Release metadata, helper rebuild, and full verification

**Files:**
- Modify: `.codex-plugin/plugin.json`
- Modify: `README.md`
- Modify: `tests/test_packaging.py`
- Rebuild: `assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu`
- Rebuild: `assets/CodexSpeakMenu.app/Contents/_CodeSignature/CodeResources`

**Interfaces:**
- Consumes: completed Python and Swift Silent implementation.
- Produces: release-ready 0.2.3 plugin tree with universal signed helper and documented Silent semantics.

- [ ] **Step 1: Write the failing 0.2.3 and README acceptance assertions**

Change `test_manifest_has_exact_identity_and_only_supported_fields` to expect `0.2.3`. Extend the README required phrases in `tests/test_privacy.py` with:

```python
"Silent",
"immediately stops current speech",
"clears pending speech",
"persists across restarts",
```

- [ ] **Step 2: Run release-contract tests and verify red**

Run:

```bash
python3 -m unittest tests.test_packaging tests.test_privacy -v
```

Expected: the manifest is still 0.2.2 and README lacks the full Silent behavior contract.

- [ ] **Step 3: Update manifest and README**

Set `.codex-plugin/plugin.json` to:

```json
"version": "0.2.3"
```

Document the six menu items and state plainly that Silent immediately stops current speech, clears pending speech, suppresses future events, persists across restarts, and does not replay discarded events after returning to Summary or Full. Update the maintainer version check from `0.2.2+codex.` to `0.2.3+codex.`.

- [ ] **Step 4: Run the complete source test matrix before rebuilding**

Run:

```bash
python3 -m unittest discover -s tests -v
swift test --package-path menu-bar
python3 -m compileall -q codex_speak hooks
python3 -m json.tool hooks/hooks.json >/dev/null
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
git diff --check
```

Expected: all Python and Swift tests pass; compilation, JSON validation, and whitespace checks exit 0.

- [ ] **Step 5: Rebuild and verify the shipped helper**

Run:

```bash
./scripts/build_menu_app.sh
lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
codesign --verify --deep --strict assets/CodexSpeakMenu.app
```

Expected: build succeeds; architectures are exactly `arm64 x86_64`; strict code-sign verification exits 0.

- [ ] **Step 6: Rerun packaging and full regression tests against the rebuilt asset**

Run:

```bash
python3 -m unittest discover -s tests -v
swift test --package-path menu-bar
git diff --check
git status --short
```

Expected: all tests pass; status contains only intentional 0.2.3 source, documentation, test, and rebuilt helper changes plus pre-existing ignored workflow artifacts.

- [ ] **Step 7: Perform the manual acceptance sequence**

Run the locally built helper against a temporary plugin-data directory, then verify in order:

1. Select Full and start a response long enough to speak.
2. Select Silent and confirm current audio stops immediately.
3. Confirm pending spool entries are cleared.
4. Produce multiple Codex responses and confirm no audio plays.
5. Restart the helper and confirm Silent remains checked and still suppresses audio.
6. Select Summary, then Full, and confirm only new eligible events play.
7. Confirm diagnostics contain fixed metadata only and no response text.

- [ ] **Step 8: Commit Task 6**

```bash
git add .codex-plugin/plugin.json README.md tests/test_packaging.py tests/test_privacy.py assets/CodexSpeakMenu.app
git commit -m "chore: prepare codex speak 0.2.3"
```

### Task 7: Independent review and release handoff

**Files:**
- Review: all changes since `d5dbfc7`
- Verify: complete repository test and release matrix

**Interfaces:**
- Consumes: Tasks 1-6 commits.
- Produces: reviewed release candidate and an explicit formal-install decision; this task does not mutate the formal Marketplace source without separate authorization.

- [ ] **Step 1: Request requirements and code-quality review**

Use `superpowers:requesting-code-review` against the full range from `d5dbfc7` to `HEAD`. Require the reviewer to check Silent/control versus speech-event separation, write/read failure semantics, actor race closure, privacy, startup ordering, and regression risk.

- [ ] **Step 2: Address every Critical or Important finding with a red-green test cycle**

For each accepted finding, first add a failing focused test, run it to verify the failure, implement the smallest correction, rerun the focused and adjacent suites, and commit with a finding-specific message. Do not defer any Critical or Important issue.

- [ ] **Step 3: Run verification-before-completion**

Use `superpowers:verification-before-completion`, then rerun:

```bash
python3 -m unittest discover -s tests -v
swift test --package-path menu-bar
python3 -m compileall -q codex_speak hooks
python3 -m json.tool hooks/hooks.json >/dev/null
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
lipo -archs assets/CodexSpeakMenu.app/Contents/MacOS/CodexSpeakMenu
codesign --verify --deep --strict assets/CodexSpeakMenu.app
git diff --check
git status --short
```

Expected: every command exits 0, architectures are exactly `arm64 x86_64`, and only intentional changes remain.

- [ ] **Step 4: Hand off the verified candidate**

Report the final commit, Python/Swift test counts, helper architectures/signature state, manual Silent acceptance result, and any residual low-severity findings. Ask for explicit authorization before syncing or installing a formal `0.2.3+codex.<timestamp>` Marketplace version.
