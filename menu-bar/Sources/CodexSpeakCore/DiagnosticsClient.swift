import Foundation

public struct DiagnosticsClient: PlaybackRecording, Sendable {
    private let pluginRoot: URL
    private let dataDirectory: URL
    private let pythonExecutableURL: URL
    private let runner: any CommandRunning

    public init(pluginRoot: URL, dataDirectory: URL, pythonExecutableURL: URL) {
        self.pluginRoot = pluginRoot
        self.dataDirectory = dataDirectory
        self.pythonExecutableURL = pythonExecutableURL
        runner = FoundationCommandRunner()
    }

    init(
        pluginRoot: URL,
        dataDirectory: URL,
        pythonExecutableURL: URL,
        runner: any CommandRunning
    ) {
        self.pluginRoot = pluginRoot
        self.dataDirectory = dataDirectory
        self.pythonExecutableURL = pythonExecutableURL
        self.runner = runner
    }

    public func record(event: SpeechEvent, result: PlaybackResult) throws {
        try run(arguments: [
            "--event-id", event.eventID,
            "--status", event.status,
            "--result", result.outcome.rawValue,
            "--mode", event.mode.rawValue,
            "--segment-count", String(result.completedSegmentCount),
            "--duration-ms", String(result.durationMilliseconds),
            "--error-code", result.errorCode?.rawValue ?? "NONE",
        ])
    }

    public func recordControlFailure(_ errorCode: ControlErrorCode) throws {
        try run(arguments: [
            "--event-id", "000000000000000000000000",
            "--status", "unknown",
            "--result", "failed",
            "--mode", "unknown",
            "--segment-count", "0",
            "--duration-ms", "0",
            "--error-code", errorCode.rawValue,
        ])
    }

    private func run(arguments: [String]) throws {
        let request = CommandRequest(
            executableURL: pythonExecutableURL,
            arguments: [
                "-B", "-m", "codex_speak.diagnostics",
                "--data-dir", dataDirectory.path,
                "record",
            ] + arguments,
            currentDirectoryURL: pluginRoot
        )
        let commandResult = try runner.run(request)
        guard commandResult.terminationStatus == 0,
              commandResult.standardOutput.isEmpty else {
            throw CodexSpeakError.commandFailed
        }
    }
}

public enum ControlErrorCode: String, Sendable {
    case queueClearFailed = "queue_clear_failed"
}
