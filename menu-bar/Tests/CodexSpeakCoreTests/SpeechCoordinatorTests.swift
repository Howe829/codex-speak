import Foundation
import XCTest
@testable import CodexSpeakCore

final class SpeechCoordinatorTests: XCTestCase, @unchecked Sendable {
    func testSilentSelectionPersistsReadsStopsThenClears() async {
        let log = OrderedLog()
        let control = ControlSpy(log: log, getActions: [.mode(.silent)])
        let player = SpeechPlayingSpy(log: log)
        let diagnostics = PlaybackRecordingSpy()
        let coordinator = SpeechCoordinator(
            controlClient: control,
            speechPlayer: player,
            diagnosticsClient: diagnostics
        )

        let result = await coordinator.selectMode(.silent)
        let selectedMode = await coordinator.selectedMode

        XCTAssertEqual(result, .applied(.silent))
        XCTAssertEqual(selectedMode, .silent)
        XCTAssertEqual(log.values, ["set:silent", "get", "stop", "clear"])
    }

    func testSilentWriteFailurePreservesPriorModeAndDoesNotStopOrClear() async {
        let log = OrderedLog()
        let control = ControlSpy(log: log, setError: SpyError.failed)
        let player = SpeechPlayingSpy(log: log)
        let coordinator = SpeechCoordinator(
            controlClient: control,
            speechPlayer: player,
            diagnosticsClient: PlaybackRecordingSpy()
        )

        let result = await coordinator.selectMode(.silent)
        let selectedMode = await coordinator.selectedMode

        XCTAssertEqual(result, .writeFailed(.summary))
        XCTAssertEqual(selectedMode, .summary)
        XCTAssertEqual(log.values, ["set:silent"])
        XCTAssertEqual(player.stopCount, 0)
        XCTAssertEqual(control.clearCount, 0)
    }

    func testSilentReadFailureAfterWriteFailsSafeAndStillStopsAndClears() async {
        let log = OrderedLog()
        let control = ControlSpy(log: log, getActions: [.failure])
        let player = SpeechPlayingSpy(log: log)
        let coordinator = SpeechCoordinator(
            controlClient: control,
            speechPlayer: player,
            diagnosticsClient: PlaybackRecordingSpy()
        )

        let result = await coordinator.selectMode(.silent)
        let selectedMode = await coordinator.selectedMode

        XCTAssertEqual(result, .readFailedFailSafe(queueClearFailed: false))
        XCTAssertEqual(selectedMode, .silent)
        XCTAssertEqual(log.values, ["set:silent", "get", "stop", "clear"])
    }

    func testConcurrentTrustedReadbackAdoptsReturnedFullWithoutSilentSideEffects() async {
        let log = OrderedLog()
        let control = ControlSpy(log: log, getActions: [.mode(.full)])
        let player = SpeechPlayingSpy(log: log)
        let coordinator = SpeechCoordinator(
            controlClient: control,
            speechPlayer: player,
            diagnosticsClient: PlaybackRecordingSpy()
        )

        let result = await coordinator.selectMode(.silent)
        let selectedMode = await coordinator.selectedMode

        XCTAssertEqual(result, .applied(.full))
        XCTAssertEqual(selectedMode, .full)
        XCTAssertEqual(log.values, ["set:silent", "get"])
        XCTAssertEqual(player.stopCount, 0)
        XCTAssertEqual(control.clearCount, 0)
    }

    func testQueueClearFailureLeavesSilentActiveAndRecordsFixedFailure() async {
        let log = OrderedLog()
        let canary = "QUEUE_CLEAR_SPEECH_CANARY_49217"
        let control = ControlSpy(
            log: log,
            getActions: [.mode(.silent)],
            clearError: SensitiveSpyError(message: canary)
        )
        let player = SpeechPlayingSpy(log: log)
        let diagnostics = PlaybackRecordingSpy()
        let coordinator = SpeechCoordinator(
            controlClient: control,
            speechPlayer: player,
            diagnosticsClient: diagnostics
        )

        let result = await coordinator.selectMode(.silent)
        let selectedMode = await coordinator.selectedMode

        XCTAssertEqual(result, .appliedWithQueueClearFailure(.silent))
        XCTAssertEqual(selectedMode, .silent)
        XCTAssertEqual(player.stopCount, 1)
        XCTAssertEqual(diagnostics.controlFailures, [.queueClearFailed])
        XCTAssertFalse(diagnostics.metadata.joined().contains(canary))
    }

    func testStartupSilentClearsBeforeReturningForBridgeStart() async throws {
        let log = OrderedLog()
        let control = ControlSpy(log: log, getActions: [.mode(.silent)])
        let coordinator = SpeechCoordinator(
            controlClient: control,
            speechPlayer: SpeechPlayingSpy(log: log),
            diagnosticsClient: PlaybackRecordingSpy()
        )

        let result = try await coordinator.refreshForStartup()
        let selectedMode = await coordinator.selectedMode

        XCTAssertEqual(result, .ready(.silent))
        XCTAssertEqual(selectedMode, .silent)
        XCTAssertEqual(log.values, ["get", "clear"])
    }

    func testClaimedEventInSilentIsCancelledWithoutPlayback() async throws {
        let log = OrderedLog()
        let control = ControlSpy(log: log, getActions: [.mode(.silent)])
        let player = SpeechPlayingSpy(log: log)
        let diagnostics = PlaybackRecordingSpy()
        let coordinator = SpeechCoordinator(
            controlClient: control,
            speechPlayer: player,
            diagnosticsClient: diagnostics
        )
        let claimedEvent = event(segments: ["PRIVATE_CLAIMED_SPEECH_31983"])

        try await coordinator.handle(event: claimedEvent)

        XCTAssertEqual(player.playCount, 0)
        XCTAssertEqual(diagnostics.records, [
            RecordedPlayback(
                event: claimedEvent,
                result: PlaybackResult(
                    outcome: .cancelled,
                    errorCode: nil,
                    completedSegmentCount: 0,
                    durationMilliseconds: 0
                )
            ),
        ])
    }

    func testClaimedEventInAudibleModePlaysAndRecordsResult() async throws {
        let log = OrderedLog()
        let control = ControlSpy(log: log, getActions: [.mode(.full)])
        let playbackResult = PlaybackResult(
            outcome: .spoken,
            errorCode: nil,
            completedSegmentCount: 1,
            durationMilliseconds: 23
        )
        let player = SpeechPlayingSpy(log: log, playbackResult: playbackResult)
        let diagnostics = PlaybackRecordingSpy()
        let coordinator = SpeechCoordinator(
            controlClient: control,
            speechPlayer: player,
            diagnosticsClient: diagnostics
        )
        let claimedEvent = event(segments: ["audible"])

        try await coordinator.handle(event: claimedEvent)

        XCTAssertEqual(player.playCount, 1)
        XCTAssertEqual(diagnostics.records, [RecordedPlayback(event: claimedEvent, result: playbackResult)])
    }

    private func event(segments: [String]) -> SpeechEvent {
        SpeechEvent(
            eventID: "0123456789abcdef01234567",
            mode: .full,
            status: "completed",
            segments: segments
        )
    }
}

private enum SpyError: Error {
    case failed
}

private struct SensitiveSpyError: Error, CustomStringConvertible {
    let message: String
    var description: String { message }
}

private final class OrderedLog: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [String] = []

    func append(_ value: String) {
        lock.withLock { storage.append(value) }
    }

    var values: [String] {
        lock.withLock { storage }
    }
}

private final class ControlSpy: ControlClientProtocol, @unchecked Sendable {
    enum GetAction {
        case mode(SpeechMode)
        case failure
    }

    private let lock = NSLock()
    private let log: OrderedLog
    private var getActions: [GetAction]
    private let setError: Error?
    private let clearError: Error?
    private var clearCalls = 0

    init(
        log: OrderedLog,
        getActions: [GetAction] = [],
        setError: Error? = nil,
        clearError: Error? = nil
    ) {
        self.log = log
        self.getActions = getActions
        self.setError = setError
        self.clearError = clearError
    }

    func getMode() throws -> SpeechMode {
        log.append("get")
        let action = lock.withLock { getActions.removeFirst() }
        switch action {
        case let .mode(mode): return mode
        case .failure: throw SpyError.failed
        }
    }

    func setMode(_ mode: SpeechMode) throws {
        log.append("set:\(mode.rawValue)")
        if let setError { throw setError }
    }

    func clearPending() throws -> Int {
        log.append("clear")
        try lock.withLock {
            clearCalls += 1
            if let clearError { throw clearError }
        }
        return 0
    }

    var clearCount: Int {
        lock.withLock { clearCalls }
    }
}

private final class SpeechPlayingSpy: SpeechPlaying, @unchecked Sendable {
    private let lock = NSLock()
    private let log: OrderedLog
    private let playbackResult: PlaybackResult
    private var plays = 0
    private var stops = 0

    init(
        log: OrderedLog,
        playbackResult: PlaybackResult = PlaybackResult(
            outcome: .spoken,
            errorCode: nil,
            completedSegmentCount: 0,
            durationMilliseconds: 0
        )
    ) {
        self.log = log
        self.playbackResult = playbackResult
    }

    func play(event: SpeechEvent) async -> PlaybackResult {
        lock.withLock { plays += 1 }
        log.append("play")
        return playbackResult
    }

    func stopCurrent() async {
        lock.withLock { stops += 1 }
        log.append("stop")
    }

    var playCount: Int { lock.withLock { plays } }
    var stopCount: Int { lock.withLock { stops } }
}

private struct RecordedPlayback: Equatable {
    let event: SpeechEvent
    let result: PlaybackResult
}

private final class PlaybackRecordingSpy: PlaybackRecording, @unchecked Sendable {
    private let lock = NSLock()
    private var storedRecords: [RecordedPlayback] = []
    private var storedControlFailures: [ControlErrorCode] = []
    private var storedMetadata: [String] = []

    func record(event: SpeechEvent, result: PlaybackResult) throws {
        lock.withLock { storedRecords.append(RecordedPlayback(event: event, result: result)) }
    }

    func recordControlFailure(_ errorCode: ControlErrorCode) throws {
        lock.withLock {
            storedControlFailures.append(errorCode)
            storedMetadata.append(errorCode.rawValue)
        }
    }

    var records: [RecordedPlayback] { lock.withLock { storedRecords } }
    var controlFailures: [ControlErrorCode] { lock.withLock { storedControlFailures } }
    var metadata: [String] { lock.withLock { storedMetadata } }
}
