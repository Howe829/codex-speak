import Foundation

struct CommandRequest: Sendable {
    let executableURL: URL
    let arguments: [String]
    let currentDirectoryURL: URL
}

struct CommandResult: Sendable {
    let terminationStatus: Int32
    let standardOutput: Data
}

protocol CommandRunning: Sendable {
    func run(_ request: CommandRequest) throws -> CommandResult
}

struct FoundationCommandRunner: CommandRunning {
    func run(_ request: CommandRequest) throws -> CommandResult {
        let process = Process()
        let output = Pipe()
        process.executableURL = request.executableURL
        process.arguments = request.arguments
        process.currentDirectoryURL = request.currentDirectoryURL
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        return CommandResult(
            terminationStatus: process.terminationStatus,
            standardOutput: output.fileHandleForReading.readDataToEndOfFile()
        )
    }
}

public protocol ControlClientProtocol: Sendable {
    func getMode() throws -> SpeechMode
    func setMode(_ mode: SpeechMode) throws
    func clearPending() throws -> Int
}

public struct ControlClient: ControlClientProtocol, Sendable {
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

    public func getMode() throws -> SpeechMode {
        let output = try run(module: "codex_speak.settings", tail: ["get"])
        guard let mode = SpeechMode(rawValue: output) else {
            throw CodexSpeakError.invalidCommandOutput
        }
        return mode
    }

    public func setMode(_ mode: SpeechMode) throws {
        let output = try run(module: "codex_speak.settings", tail: ["set", mode.rawValue])
        guard output == mode.rawValue else { throw CodexSpeakError.invalidCommandOutput }
    }

    public func clearPending() throws -> Int {
        let output = try run(module: "codex_speak.queue", tail: ["clear-pending"])
        guard !output.isEmpty,
              output.allSatisfy(\.isNumber),
              let count = Int(output), count >= 0 else {
            throw CodexSpeakError.invalidCommandOutput
        }
        return count
    }

    private func run(module: String, tail: [String]) throws -> String {
        let request = CommandRequest(
            executableURL: pythonExecutableURL,
            arguments: ["-m", module, "--data-dir", dataDirectory.path] + tail,
            currentDirectoryURL: pluginRoot
        )
        let result = try runner.run(request)
        guard result.terminationStatus == 0,
              var output = String(data: result.standardOutput, encoding: .utf8) else {
            throw CodexSpeakError.commandFailed
        }
        if output.hasSuffix("\n") { output.removeLast() }
        guard !output.contains("\n"), !output.contains("\r") else {
            throw CodexSpeakError.invalidCommandOutput
        }
        return output
    }
}
