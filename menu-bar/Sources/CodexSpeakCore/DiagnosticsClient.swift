import Foundation

public struct DiagnosticsClient: Sendable {
    private let pluginRoot: URL
    private let dataDirectory: URL
    private let runner: any CommandRunning

    public init(pluginRoot: URL, dataDirectory: URL) {
        self.pluginRoot = pluginRoot
        self.dataDirectory = dataDirectory
        runner = FoundationCommandRunner()
    }

    init(pluginRoot: URL, dataDirectory: URL, runner: any CommandRunning) {
        self.pluginRoot = pluginRoot
        self.dataDirectory = dataDirectory
        self.runner = runner
    }

    public func record(event: SpeechEvent, result: PlaybackResult) throws {
        let request = CommandRequest(
            executableURL: URL(fileURLWithPath: "/usr/bin/python3"),
            arguments: [
                "-m", "codex_speak.diagnostics",
                "--data-dir", dataDirectory.path,
                "record",
                "--event-id", event.eventID,
                "--status", event.status,
                "--result", result.outcome.rawValue,
                "--mode", event.mode.rawValue,
                "--segment-count", String(result.completedSegmentCount),
                "--duration-ms", String(result.durationMilliseconds),
                "--error-code", result.errorCode?.rawValue ?? "NONE",
            ],
            currentDirectoryURL: pluginRoot
        )
        let commandResult = try runner.run(request)
        guard commandResult.terminationStatus == 0,
              commandResult.standardOutput.isEmpty else {
            throw CodexSpeakError.commandFailed
        }
    }
}
