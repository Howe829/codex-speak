import Foundation
import XCTest
@testable import CodexSpeakCore

final class BridgeProcessTests: XCTestCase, @unchecked Sendable {
    func testDecodesReadyBusyAndExactEventWhilePreservingSegmentOrder() throws {
        XCTAssertEqual(try BridgeMessage.decode(line: #"{"type":"ready"}"#), .ready)
        XCTAssertEqual(try BridgeMessage.decode(line: #"{"type":"busy"}"#), .busy)
        XCTAssertEqual(
            try BridgeMessage.decode(
                line: #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"full","status":"silent","segments":["first","second"]}"#
            ),
            .event(
                SpeechEvent(
                    eventID: "0123456789abcdef01234567",
                    mode: .full,
                    status: "silent",
                    segments: ["first", "second"]
                )
            )
        )
    }

    func testRejectsNonJSONMissingExtraAndInvalidEventValues() {
        let invalidLines = [
            "not-json",
            #"{"type":"ready","extra":true}"#,
            #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"full","status":"completed"}"#,
            #"{"type":"event","event_id":"0123456789ABCDEF01234567","mode":"full","status":"completed","segments":["ok"]}"#,
            #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"verbose","status":"completed","segments":["ok"]}"#,
            #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"silent","status":"completed","segments":["must reject"]}"#,
            #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"summary","status":"silent","segments":["ok"]}"#,
            #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"full","status":"private","segments":["ok"]}"#,
            #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"full","status":"completed","segments":[]}"#,
            #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"full","status":"completed","segments":[""]}"#,
            #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"full","status":"completed","segments":["ok"],"extra":true}"#,
        ]
        for line in invalidLines {
            XCTAssertThrowsError(try BridgeMessage.decode(line: line), line)
        }
        let oversizedSegment = String(repeating: "x", count: 601)
        XCTAssertThrowsError(
            try BridgeMessage.decode(
                line: #"{"type":"event","event_id":"0123456789abcdef01234567","mode":"full","status":"completed","segments":["\#(oversizedSegment)"]}"#
            )
        )
        let tooMany = Array(repeating: "x", count: 10_001)
        let data = try! JSONSerialization.data(withJSONObject: [
            "type": "event",
            "event_id": "0123456789abcdef01234567",
            "mode": "full",
            "status": "completed",
            "segments": tooMany,
        ])
        XCTAssertThrowsError(try BridgeMessage.decode(data: data))
    }

    func testAcceptsMaximumSegmentLengthAndCount() throws {
        let segments = Array(repeating: String(repeating: "x", count: 600), count: 10_000)
        let data = try JSONSerialization.data(withJSONObject: [
            "type": "event",
            "event_id": "0123456789abcdef01234567",
            "mode": "full",
            "status": "completed",
            "segments": segments,
        ])
        guard case let .event(event) = try BridgeMessage.decode(data: data) else {
            return XCTFail("expected event")
        }
        XCTAssertEqual(event.segments.count, 10_000)
        XCTAssertEqual(event.segments.first?.count, 600)
    }

    func testSegmentLengthMatchesPythonUnicodeCodePointCount() throws {
        let combiningPair = "e\u{301}"
        let sixHundredScalars = String(repeating: combiningPair, count: 300)
        let sixHundredOneScalars = sixHundredScalars + "e"

        XCTAssertEqual(sixHundredScalars.unicodeScalars.count, 600)
        XCTAssertEqual(sixHundredOneScalars.unicodeScalars.count, 601)
        XCTAssertNoThrow(try decodeEvent(segment: sixHundredScalars))
        XCTAssertThrowsError(try decodeEvent(segment: sixHundredOneScalars))
    }

    func testBridgeUsesFixedArgumentsAndRetriesBusyAfterOneSecond() async throws {
        let launcher = ScriptedProcessLauncher(lines: [
            [#"{"type":"busy"}"#],
            [#"{"type":"ready"}"#],
        ])
        let sleeps = LockedValues<UInt64>()
        let bridge = BridgeProcess(
            pluginRoot: URL(fileURLWithPath: "/plugin"),
            dataDirectory: URL(fileURLWithPath: "/data"),
            pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
            launcher: launcher,
            sleep: { sleeps.append($0) }
        )
        let messages = LockedValues<BridgeMessage>()

        try await bridge.start { messages.append($0) }

        XCTAssertEqual(messages.values, [.busy, .ready])
        XCTAssertEqual(sleeps.values, [1_000_000_000])
        XCTAssertEqual(launcher.requests.count, 2)
        for request in launcher.requests {
            XCTAssertEqual(request.executableURL.path, "/custom/python")
            XCTAssertEqual(
                request.arguments,
                ["-B", "-m", "codex_speak.bridge", "watch", "--data-dir", "/data"]
            )
            XCTAssertEqual(request.currentDirectoryURL.path, "/plugin")
        }
    }

    func testBridgeAcknowledgesEachEventOnlyAfterAsyncHandlerCompletes() async throws {
        let firstID = "000000000000000000000001"
        let secondID = "000000000000000000000002"
        let launcher = ScriptedProcessLauncher(lines: [[
            #"{"type":"ready"}"#,
            #"{"type":"event","event_id":"\#(firstID)","mode":"full","status":"completed","segments":["first"]}"#,
            #"{"type":"event","event_id":"\#(secondID)","mode":"full","status":"completed","segments":["second"]}"#,
        ]])
        let handler = BlockingEventHandler()
        let bridge = BridgeProcess(
            pluginRoot: URL(fileURLWithPath: "/plugin"),
            dataDirectory: URL(fileURLWithPath: "/data"),
            pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
            launcher: launcher,
            sleep: { _ in }
        )

        let task = Task { try await bridge.start { await handler.handle($0) } }
        await handler.waitForFirstEvent()
        let firstHandled = await handler.eventIDs
        XCTAssertEqual(firstHandled, [firstID])

        await handler.releaseFirstEvent()
        try await task.value

        let allHandled = await handler.eventIDs
        XCTAssertEqual(allHandled, [firstID, secondID])
        let acknowledgements = launcher.requests[0].standardInput.fileHandleForReading
            .readDataToEndOfFile()
            .split(separator: 0x0A)
            .map { try! JSONSerialization.jsonObject(with: Data($0)) as! [String: String] }
        XCTAssertEqual(acknowledgements, [
            ["type": "ack", "event_id": firstID],
            ["type": "ack", "event_id": secondID],
        ])
    }

    func testBridgeStopTerminatesOnlyCurrentlyOwnedChild() async throws {
        let process = BlockingManagedProcess()
        let launcher = HoldingProcessLauncher(process: process)
        let bridge = BridgeProcess(
            pluginRoot: URL(fileURLWithPath: "/plugin"),
            dataDirectory: URL(fileURLWithPath: "/data"),
            pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
            launcher: launcher,
            sleep: { _ in }
        )
        let task = Task { try await bridge.start { _ in } }
        await launcher.waitUntilLaunched()

        await bridge.stop()
        _ = try await task.value
        await bridge.stop()

        XCTAssertEqual(process.terminationCount, 1)
    }

    func testConcurrentStartsLaunchOnlyOneOwnedChildAndStopTerminatesIt() async throws {
        let firstProcess = BlockingManagedProcess()
        let secondProcess = BlockingManagedProcess()
        let launcher = ConcurrentHoldingProcessLauncher(processes: [firstProcess, secondProcess])
        let bridge = BridgeProcess(
            pluginRoot: URL(fileURLWithPath: "/plugin"),
            dataDirectory: URL(fileURLWithPath: "/data"),
            pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
            launcher: launcher,
            sleep: { _ in }
        )
        let firstStart = Task { try await bridge.start { _ in } }
        await launcher.waitForLaunchCount(1)
        let secondStart = Task { try await bridge.start { _ in } }
        await launcher.waitForConcurrentStartToSettle()

        await bridge.stop()

        XCTAssertEqual(launcher.requests.count, 1)
        XCTAssertEqual(firstProcess.terminationCount, 1)
        XCTAssertEqual(secondProcess.terminationCount, 0)
        launcher.finishAll()
        try await firstStart.value
        try await secondStart.value
    }

    func testBusyRetryWaitsForFallbackProcessToExit() async throws {
        let busyProcess = BlockingManagedProcess()
        let launcher = SequencedBridgeLauncher(processes: [busyProcess, ImmediateManagedProcess()])
        let bridge = BridgeProcess(
            pluginRoot: URL(fileURLWithPath: "/plugin"),
            dataDirectory: URL(fileURLWithPath: "/data"),
            pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
            launcher: launcher,
            sleep: { _ in }
        )
        let task = Task { try await bridge.start { _ in } }
        await launcher.waitForLaunchCount(1)
        await Task.yield()
        XCTAssertEqual(launcher.requests.count, 1)

        busyProcess.finish(status: 0)
        try await task.value

        XCTAssertEqual(launcher.requests.count, 2)
    }

    func testMalformedNDJSONTerminatesOwnedBridgeBeforeThrowing() async {
        let process = BlockingManagedProcess()
        let launcher = MalformedBridgeLauncher(process: process)
        let bridge = BridgeProcess(
            pluginRoot: URL(fileURLWithPath: "/plugin"),
            dataDirectory: URL(fileURLWithPath: "/data"),
            pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
            launcher: launcher,
            sleep: { _ in }
        )

        do {
            try await bridge.start { _ in }
            XCTFail("expected malformed bridge output to fail")
        } catch {}

        XCTAssertEqual(process.terminationCount, 1)
    }

    func testRealBridgeAndControlSmokeWithCompatibleInterpreter() async throws {
        guard let pythonPath = ProcessInfo.processInfo.environment["CODEX_SPEAK_TEST_PYTHON"] else {
            throw XCTSkip("set CODEX_SPEAK_TEST_PYTHON to run the real runtime smoke")
        }
        let pythonURL = URL(fileURLWithPath: pythonPath)
        guard FileManager.default.isExecutableFile(atPath: pythonURL.path) else {
            throw XCTSkip("CODEX_SPEAK_TEST_PYTHON is not executable")
        }
        let pluginRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let dataDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: dataDirectory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dataDirectory) }

        let control = ControlClient(
            pluginRoot: pluginRoot,
            dataDirectory: dataDirectory,
            pythonExecutableURL: pythonURL
        )
        try control.setMode(.full)
        XCTAssertEqual(try control.getMode(), .full)
        XCTAssertEqual(try control.clearPending(), 0)

        let messages = LockedValues<BridgeMessage>()
        let bridge = BridgeProcess(
            pluginRoot: pluginRoot,
            dataDirectory: dataDirectory,
            pythonExecutableURL: pythonURL
        )
        let bridgeTask = Task { try await bridge.start { messages.append($0) } }
        while messages.values.isEmpty { await Task.yield() }
        await bridge.stop()
        try await bridgeTask.value
        XCTAssertEqual(messages.values, [.ready])
    }

    private func decodeEvent(segment: String) throws -> BridgeMessage {
        let data = try JSONSerialization.data(withJSONObject: [
            "type": "event",
            "event_id": "0123456789abcdef01234567",
            "mode": "full",
            "status": "completed",
            "segments": [segment],
        ])
        return try BridgeMessage.decode(data: data)
    }
}

final class ControlAndDiagnosticsTests: XCTestCase {
    func testControlFailureDiagnosticUsesOnlyFixedMetadata() throws {
        let runner = RecordingCommandRunner(outputs: [""])
        let client = DiagnosticsClient(
            pluginRoot: URL(fileURLWithPath: "/plugin"),
            dataDirectory: URL(fileURLWithPath: "/data"),
            pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
            runner: runner
        )

        try client.recordControlFailure(.queueClearFailed)

        XCTAssertEqual(runner.requests.first?.arguments, [
            "-B", "-m", "codex_speak.diagnostics", "--data-dir", "/data", "record",
            "--event-id", "000000000000000000000000", "--status", "unknown",
            "--result", "failed", "--mode", "unknown", "--segment-count", "0",
            "--duration-ms", "0", "--error-code", "queue_clear_failed",
        ])
    }
    func testControlClientsUseFixedArgumentsAndStrictStdout() throws {
        let runner = RecordingCommandRunner(outputs: ["summary\n", "full\n", "12\n"])
        let client = ControlClient(
            pluginRoot: URL(fileURLWithPath: "/plugin"),
            dataDirectory: URL(fileURLWithPath: "/data"),
            pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
            runner: runner
        )
        XCTAssertEqual(try client.getMode(), .summary)
        try client.setMode(.full)
        XCTAssertEqual(try client.clearPending(), 12)
        XCTAssertEqual(runner.requests.map(\.arguments), [
            ["-B", "-m", "codex_speak.settings", "--data-dir", "/data", "get"],
            ["-B", "-m", "codex_speak.settings", "--data-dir", "/data", "set", "full"],
            ["-B", "-m", "codex_speak.queue", "--data-dir", "/data", "clear-pending"],
        ])
        XCTAssertTrue(runner.requests.allSatisfy { $0.executableURL.path == "/custom/python" })
        XCTAssertTrue(runner.requests.allSatisfy { $0.currentDirectoryURL.path == "/plugin" })
    }

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

    func testControlClientRejectsLooseOrInvalidStdout() {
        for output in [" summary\n", "summary \n", "summary\nextra\n", "-1\n", "+1\n", "1.0\n"] {
            let runner = RecordingCommandRunner(outputs: [output])
            let client = ControlClient(
                pluginRoot: URL(fileURLWithPath: "/plugin"),
                dataDirectory: URL(fileURLWithPath: "/data"),
                pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
                runner: runner
            )
            if output.contains("summary") {
                XCTAssertThrowsError(try client.getMode(), output)
            } else {
                XCTAssertThrowsError(try client.clearPending(), output)
            }
        }
    }

    func testDiagnosticsUsesOnlyFixedMetadataForSpokenCancelledAndStartFailure() throws {
        let runner = RecordingCommandRunner(outputs: ["", "", ""])
        let client = DiagnosticsClient(
            pluginRoot: URL(fileURLWithPath: "/plugin"),
            dataDirectory: URL(fileURLWithPath: "/data"),
            pythonExecutableURL: URL(fileURLWithPath: "/custom/python"),
            runner: runner
        )
        let event = SpeechEvent(
            eventID: "0123456789abcdef01234567",
            mode: .full,
            status: "completed",
            segments: ["PRIVATE SPEECH"]
        )
        try client.record(event: event, result: PlaybackResult(outcome: .spoken, errorCode: nil, completedSegmentCount: 1, durationMilliseconds: 25))
        try client.record(event: event, result: PlaybackResult(outcome: .cancelled, errorCode: nil, completedSegmentCount: 0, durationMilliseconds: 5))
        try client.record(event: event, result: PlaybackResult(outcome: .failed, errorCode: .speechStartFailed, completedSegmentCount: 0, durationMilliseconds: 1))

        let prefix = ["-B", "-m", "codex_speak.diagnostics", "--data-dir", "/data", "record", "--event-id", event.eventID, "--status", "completed", "--result"]
        XCTAssertEqual(runner.requests[0].arguments, prefix + ["spoken", "--mode", "full", "--segment-count", "1", "--duration-ms", "25", "--error-code", "NONE"])
        XCTAssertEqual(runner.requests[1].arguments, prefix + ["cancelled", "--mode", "full", "--segment-count", "0", "--duration-ms", "5", "--error-code", "NONE"])
        XCTAssertEqual(runner.requests[2].arguments, prefix + ["failed", "--mode", "full", "--segment-count", "0", "--duration-ms", "1", "--error-code", "speech_start_failed"])
        XCTAssertTrue(runner.requests.allSatisfy { $0.executableURL.path == "/custom/python" })
        XCTAssertFalse(runner.requests.flatMap(\.arguments).contains("PRIVATE SPEECH"))
    }
}

private final class LockedValues<Value: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [Value] = []
    var values: [Value] { lock.withLock { storage } }
    func append(_ value: Value) { lock.withLock { storage.append(value) } }
}

private actor BlockingEventHandler {
    private var events: [String] = []
    private var released = false

    var eventIDs: [String] { events }

    func handle(_ message: BridgeMessage) async {
        guard case let .event(event) = message else { return }
        events.append(event.eventID)
        if events.count == 1 {
            while !released { await Task.yield() }
        }
    }

    func waitForFirstEvent() async {
        while events.isEmpty { await Task.yield() }
    }

    func releaseFirstEvent() { released = true }
}

private final class ImmediateManagedProcess: ManagedProcess, @unchecked Sendable {
    let terminationStatus: Int32
    init(_ terminationStatus: Int32 = 0) { self.terminationStatus = terminationStatus }
    func waitUntilExit() async -> Int32 { terminationStatus }
    func terminate() {}
}

private final class BlockingManagedProcess: ManagedProcess, @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Int32, Never>?
    private var pendingStatus: Int32?
    private(set) var terminationCount = 0

    func waitUntilExit() async -> Int32 {
        await withCheckedContinuation { continuation in
            lock.withLock {
                if let pendingStatus {
                    continuation.resume(returning: pendingStatus)
                } else {
                    self.continuation = continuation
                }
            }
        }
    }

    func terminate() {
        finish(status: 15, countTermination: true)
    }

    func finish(status: Int32) {
        finish(status: status, countTermination: false)
    }

    private func finish(status: Int32, countTermination: Bool) {
        let continuation = lock.withLock { () -> CheckedContinuation<Int32, Never>? in
            if countTermination { terminationCount += 1 }
            let continuation = self.continuation
            self.continuation = nil
            if continuation == nil { pendingStatus = status }
            return continuation
        }
        continuation?.resume(returning: status)
    }
}

private final class SequencedBridgeLauncher: ProcessLaunching, @unchecked Sendable {
    private let lock = NSLock()
    private var processes: [any ManagedProcess]
    private(set) var requests: [ProcessLaunchRequest] = []
    init(processes: [any ManagedProcess]) { self.processes = processes }
    func launch(_ request: ProcessLaunchRequest) throws -> any ManagedProcess {
        let (process, line) = lock.withLock { () -> (any ManagedProcess, String) in
            requests.append(request)
            let index = requests.count
            return (processes.removeFirst(), index == 1 ? #"{"type":"busy"}"# : #"{"type":"ready"}"#)
        }
        request.standardOutput.fileHandleForWriting.write(Data((line + "\n").utf8))
        try request.standardOutput.fileHandleForWriting.close()
        return process
    }
    func waitForLaunchCount(_ count: Int) async {
        while lock.withLock({ requests.count < count }) { await Task.yield() }
    }
}

private final class MalformedBridgeLauncher: ProcessLaunching, @unchecked Sendable {
    let process: BlockingManagedProcess
    init(process: BlockingManagedProcess) { self.process = process }
    func launch(_ request: ProcessLaunchRequest) throws -> any ManagedProcess {
        request.standardOutput.fileHandleForWriting.write(Data("not-json\n".utf8))
        try request.standardOutput.fileHandleForWriting.close()
        return process
    }
}

private final class ScriptedProcessLauncher: ProcessLaunching, @unchecked Sendable {
    private let lock = NSLock()
    private var lines: [[String]]
    private(set) var requests: [ProcessLaunchRequest] = []
    init(lines: [[String]]) { self.lines = lines }

    func launch(_ request: ProcessLaunchRequest) throws -> any ManagedProcess {
        let lines = lock.withLock { () -> [String] in
            requests.append(request)
            return self.lines.removeFirst()
        }
        for line in lines {
            request.standardOutput.fileHandleForWriting.write(Data((line + "\n").utf8))
        }
        try request.standardOutput.fileHandleForWriting.close()
        return ImmediateManagedProcess()
    }
}

private final class HoldingProcessLauncher: ProcessLaunching, @unchecked Sendable {
    private let process: BlockingManagedProcess
    private let launched = LockedValues<Bool>()
    private var output: Pipe?
    init(process: BlockingManagedProcess) { self.process = process }

    func launch(_ request: ProcessLaunchRequest) throws -> any ManagedProcess {
        output = request.standardOutput
        launched.append(true)
        request.standardOutput.fileHandleForWriting.write(Data("{\"type\":\"ready\"}\n".utf8))
        return ClosingManagedProcess(base: process) { [weak self] in
            try? self?.output?.fileHandleForWriting.close()
        }
    }

    func waitUntilLaunched() async {
        while launched.values.isEmpty { await Task.yield() }
    }
}

private final class ConcurrentHoldingProcessLauncher: ProcessLaunching, @unchecked Sendable {
    private let lock = NSLock()
    private var processes: [BlockingManagedProcess]
    private var outputs: [Pipe] = []
    private(set) var requests: [ProcessLaunchRequest] = []

    init(processes: [BlockingManagedProcess]) {
        self.processes = processes
    }

    func launch(_ request: ProcessLaunchRequest) throws -> any ManagedProcess {
        let process = lock.withLock { () -> BlockingManagedProcess in
            requests.append(request)
            outputs.append(request.standardOutput)
            return processes[requests.count - 1]
        }
        request.standardOutput.fileHandleForWriting.write(Data("{\"type\":\"ready\"}\n".utf8))
        return ClosingManagedProcess(base: process) {
            try? request.standardOutput.fileHandleForWriting.close()
        }
    }

    func waitForLaunchCount(_ count: Int) async {
        while lock.withLock({ requests.count < count }) { await Task.yield() }
    }

    func waitForConcurrentStartToSettle() async {
        for _ in 0..<100 { await Task.yield() }
    }

    func finishAll() {
        let values = lock.withLock { (processes, outputs) }
        for output in values.1 { try? output.fileHandleForWriting.close() }
        for process in values.0 { process.finish(status: 0) }
    }
}

private final class ClosingManagedProcess: ManagedProcess, @unchecked Sendable {
    private let base: BlockingManagedProcess
    private let onTerminate: @Sendable () -> Void
    init(base: BlockingManagedProcess, onTerminate: @escaping @Sendable () -> Void) {
        self.base = base
        self.onTerminate = onTerminate
    }
    func waitUntilExit() async -> Int32 { await base.waitUntilExit() }
    func terminate() { onTerminate(); base.terminate() }
}

private final class RecordingCommandRunner: CommandRunning, @unchecked Sendable {
    private let lock = NSLock()
    private var outputs: [String]
    private(set) var requests: [CommandRequest] = []
    init(outputs: [String]) { self.outputs = outputs }
    func run(_ request: CommandRequest) throws -> CommandResult {
        lock.withLock {
            requests.append(request)
            return CommandResult(terminationStatus: 0, standardOutput: Data(outputs.removeFirst().utf8))
        }
    }
}
