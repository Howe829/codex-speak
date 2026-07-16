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
    case readFailedFailSafe(queueClearFailed: Bool)
}

public enum StartupModeResult: Equatable, Sendable {
    case ready(SpeechMode)
    case readyWithQueueClearFailure(SpeechMode)
}

public actor SpeechCoordinator {
    private let controlClient: any ControlClientProtocol
    private let speechPlayer: any SpeechPlaying
    private let diagnosticsClient: any PlaybackRecording
    private var modeSelectionGeneration: UInt64 = 0
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
        modeSelectionGeneration &+= 1
        let selectionGeneration = modeSelectionGeneration
        let priorMode = selectedMode
        do {
            try controlClient.setMode(requestedMode)
        } catch {
            return .writeFailed(priorMode)
        }

        if requestedMode != .silent {
            do {
                selectedMode = try controlClient.getMode()
                return .applied(selectedMode)
            } catch {
                selectedMode = priorMode
                return .writeFailed(priorMode)
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
        guard selectionGeneration == modeSelectionGeneration else {
            return .applied(selectedMode)
        }
        do {
            _ = try controlClient.clearPending()
            return readbackFailed ? .readFailedFailSafe(queueClearFailed: false) : .applied(.silent)
        } catch {
            try? diagnosticsClient.recordControlFailure(.queueClearFailed)
            return readbackFailed
                ? .readFailedFailSafe(queueClearFailed: true)
                : .appliedWithQueueClearFailure(.silent)
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
