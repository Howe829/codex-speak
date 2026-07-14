import Foundation

struct ProcessLaunchRequest: @unchecked Sendable {
    let executableURL: URL
    let arguments: [String]
    let currentDirectoryURL: URL
    let standardInput: Pipe
    let standardOutput: Pipe
    let standardError: Pipe
}

protocol ManagedProcess: AnyObject, Sendable {
    func waitUntilExit() async -> Int32
    func terminate()
}

protocol ProcessLaunching: Sendable {
    func launch(_ request: ProcessLaunchRequest) throws -> any ManagedProcess
}

struct FoundationProcessLauncher: ProcessLaunching {
    func launch(_ request: ProcessLaunchRequest) throws -> any ManagedProcess {
        let process = Process()
        process.executableURL = request.executableURL
        process.arguments = request.arguments
        process.currentDirectoryURL = request.currentDirectoryURL
        process.standardInput = request.standardInput
        process.standardOutput = request.standardOutput
        process.standardError = request.standardError
        let managed = FoundationManagedProcess(process: process)
        try process.run()
        return managed
    }
}

private final class FoundationManagedProcess: ManagedProcess, @unchecked Sendable {
    private let process: Process
    private let lock = NSLock()
    private var status: Int32?
    private var waiters: [CheckedContinuation<Int32, Never>] = []

    init(process: Process) {
        self.process = process
        process.terminationHandler = { [weak self] process in
            self?.finish(with: process.terminationStatus)
        }
    }

    func waitUntilExit() async -> Int32 {
        await withCheckedContinuation { continuation in
            let status = lock.withLock { () -> Int32? in
                if let status = self.status { return status }
                waiters.append(continuation)
                return nil
            }
            if let status { continuation.resume(returning: status) }
        }
    }

    func terminate() {
        if process.isRunning { process.terminate() }
    }

    private func finish(with status: Int32) {
        let waiters = lock.withLock { () -> [CheckedContinuation<Int32, Never>] in
            guard self.status == nil else { return [] }
            self.status = status
            let waiters = self.waiters
            self.waiters.removeAll()
            return waiters
        }
        for waiter in waiters { waiter.resume(returning: status) }
    }
}

private final class PipeReader: @unchecked Sendable {
    private let handle: FileHandle
    init(_ pipe: Pipe) { handle = pipe.fileHandleForReading }

    func readAvailableData() async -> Data {
        await Task.detached { [handle] in handle.availableData }.value
    }
}

public actor BridgeProcess {
    private let pluginRoot: URL
    private let dataDirectory: URL
    private let launcher: any ProcessLaunching
    private let sleep: @Sendable (UInt64) async -> Void
    private var lifecycleID: UUID?
    private var active: (id: UUID, process: any ManagedProcess)?
    private var stopping = false

    public init(pluginRoot: URL, dataDirectory: URL) {
        self.pluginRoot = pluginRoot
        self.dataDirectory = dataDirectory
        launcher = FoundationProcessLauncher()
        sleep = { try? await Task.sleep(nanoseconds: $0) }
    }

    init(
        pluginRoot: URL,
        dataDirectory: URL,
        launcher: any ProcessLaunching,
        sleep: @escaping @Sendable (UInt64) async -> Void
    ) {
        self.pluginRoot = pluginRoot
        self.dataDirectory = dataDirectory
        self.launcher = launcher
        self.sleep = sleep
    }

    public func start(onMessage: @escaping @Sendable (BridgeMessage) -> Void) async throws {
        guard lifecycleID == nil else { return }
        let lifecycleIdentity = UUID()
        lifecycleID = lifecycleIdentity
        defer {
            if lifecycleID == lifecycleIdentity { lifecycleID = nil }
        }
        stopping = false
        repeat {
            let standardInput = Pipe()
            let standardOutput = Pipe()
            let request = ProcessLaunchRequest(
                executableURL: URL(fileURLWithPath: "/usr/bin/python3"),
                arguments: ["-m", "codex_speak.bridge", "watch", "--data-dir", dataDirectory.path],
                currentDirectoryURL: pluginRoot,
                standardInput: standardInput,
                standardOutput: standardOutput,
                standardError: Pipe()
            )
            let process = try launcher.launch(request)
            let identity = UUID()
            active = (identity, process)
            try? standardInput.fileHandleForWriting.close()
            let reader = PipeReader(standardOutput)
            var buffer = Data()
            var sawBusy = false
            var reachedEOF = false
            do {
                while !reachedEOF {
                    let data = await reader.readAvailableData()
                    if data.isEmpty { reachedEOF = true }
                    buffer.append(data)
                    while let newline = buffer.firstIndex(of: 0x0A) {
                        let lineData = Data(buffer[..<newline])
                        buffer.removeSubrange(...newline)
                        let message = try BridgeMessage.decode(data: lineData)
                        if message == .busy { sawBusy = true }
                        onMessage(message)
                    }
                }
                guard buffer.isEmpty else { throw CodexSpeakError.invalidBridgeMessage }
            } catch {
                process.terminate()
                _ = await process.waitUntilExit()
                if active?.id == identity { active = nil }
                throw error
            }
            _ = await process.waitUntilExit()
            if active?.id == identity { active = nil }
            if sawBusy && !stopping {
                await sleep(1_000_000_000)
            } else {
                return
            }
        } while !stopping
    }

    public func stop() {
        stopping = true
        active?.process.terminate()
    }
}
