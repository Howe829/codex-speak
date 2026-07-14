import Foundation
import XCTest
@testable import CodexSpeakCore

final class SpeechPlayerTests: XCTestCase, @unchecked Sendable {
    func testSpeaksSegmentsInOrderUsingFreshStdinAndNoSpeechArguments() async {
        let launcher = SpeechLauncher(statuses: [0, 0, 0])
        let player = SpeechPlayer(launcher: launcher, clock: IncrementingClock(values: [1_000_000, 26_000_000]).now)
        let canaries = ["SUCCESS_STDIN_CANARY_10391", "SUCCESS_STDIN_CANARY_21419", "SUCCESS_STDIN_CANARY_32717"]

        let result = await player.play(event: event(canaries))

        XCTAssertEqual(result, PlaybackResult(outcome: .spoken, errorCode: nil, completedSegmentCount: 3, durationMilliseconds: 25))
        XCTAssertEqual(launcher.stdinStrings, canaries)
        XCTAssertEqual(launcher.requests.map(\.arguments), [[], [], []])
        XCTAssertTrue(launcher.requests.allSatisfy { request in
            canaries.allSatisfy { !request.arguments.joined().contains($0) }
        })
        XCTAssertTrue(launcher.requests.allSatisfy { $0.executableURL.path == "/usr/bin/say" })
        XCTAssertEqual(Set(launcher.requests.map { ObjectIdentifier($0.standardInput) }).count, 3)
    }

    func testFailureStopsRemainingSegmentsAndReturnsOnlyFixedMetadata() async {
        let launcher = SpeechLauncher(statuses: [1, 0])
        let player = SpeechPlayer(launcher: launcher, clock: IncrementingClock(values: [0, 4_000_000]).now)

        let firstCanary = "FAILURE_STDIN_CANARY_43891"
        let skippedCanary = "FAILURE_SKIPPED_CANARY_54293"
        let result = await player.play(event: event([firstCanary, skippedCanary]))

        XCTAssertEqual(result, PlaybackResult(outcome: .failed, errorCode: .sayFailed, completedSegmentCount: 0, durationMilliseconds: 4))
        XCTAssertEqual(launcher.stdinStrings, [firstCanary])
        XCTAssertEqual(launcher.requests[0].arguments, [])
        XCTAssertFalse(launcher.requests[0].arguments.joined().contains(firstCanary))
        XCTAssertFalse(launcher.requests[0].arguments.joined().contains(skippedCanary))
        XCTAssertEqual(Mirror(reflecting: result).children.count, 4)
        XCTAssertFalse(String(reflecting: result).contains(firstCanary))
        XCTAssertFalse(String(reflecting: result).contains(skippedCanary))
    }

    func testLaunchFailureUsesFixedCodeAndDoesNotExposeRawError() async {
        let launcher = SpeechLauncher(statuses: [], launchError: SensitiveError())
        let player = SpeechPlayer(launcher: launcher, clock: IncrementingClock(values: [0, 1_000_000]).now)

        let result = await player.play(event: event(["SECRET"]))

        XCTAssertEqual(result, PlaybackResult(outcome: .failed, errorCode: .speechStartFailed, completedSegmentCount: 0, durationMilliseconds: 1))
        XCTAssertFalse(String(reflecting: result).contains("sensitive raw failure"))
    }

    func testCancellationTerminatesOwnedChildSkipsRemainderAndIdleStopSignalsNothing() async {
        let process = BlockingSpeechProcess()
        let launcher = SpeechLauncher(processes: [process])
        let player = SpeechPlayer(launcher: launcher, clock: IncrementingClock(values: [0, 8_000_000]).now)
        let firstCanary = "CANCEL_STDIN_CANARY_19373"
        let skippedCanary = "CANCEL_SKIPPED_CANARY_28411"
        let task = Task { await player.play(event: self.event([firstCanary, skippedCanary])) }
        await launcher.waitForLaunchCount(1)

        await player.stopCurrent()
        let result = await task.value
        await player.stopCurrent()

        XCTAssertEqual(result, PlaybackResult(outcome: .cancelled, errorCode: nil, completedSegmentCount: 0, durationMilliseconds: 8))
        XCTAssertEqual(process.terminationCount, 1)
        XCTAssertEqual(launcher.stdinStrings, [firstCanary])
        XCTAssertEqual(launcher.requests.count, 1)
        XCTAssertEqual(launcher.requests[0].arguments, [])
        XCTAssertFalse(launcher.requests[0].arguments.joined().contains(firstCanary))
        XCTAssertFalse(launcher.requests[0].arguments.joined().contains(skippedCanary))
    }

    func testIdleStopNeverSignalsCompletedStaleChild() async {
        let process = SpeechImmediateProcess(status: 0)
        let launcher = SpeechLauncher(processes: [process])
        let player = SpeechPlayer(launcher: launcher, clock: IncrementingClock(values: [0, 1_000_000]).now)
        _ = await player.play(event: event(["done"]))

        await player.stopCurrent()

        XCTAssertEqual(process.terminationCount, 0)
    }

    private func event(_ segments: [String]) -> SpeechEvent {
        SpeechEvent(
            eventID: "0123456789abcdef01234567",
            mode: .full,
            status: "completed",
            segments: segments
        )
    }
}

private struct SensitiveError: Error, CustomStringConvertible {
    var description: String { "sensitive raw failure" }
}

private final class IncrementingClock: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [UInt64]
    init(values: [UInt64]) { self.values = values }
    func now() -> UInt64 { lock.withLock { values.removeFirst() } }
}

private class SpeechImmediateProcess: ManagedProcess, @unchecked Sendable {
    let status: Int32
    private let lock = NSLock()
    private(set) var terminationCount = 0
    init(status: Int32) { self.status = status }
    func waitUntilExit() async -> Int32 { status }
    func terminate() { lock.withLock { terminationCount += 1 } }
}

private final class BlockingSpeechProcess: SpeechImmediateProcess, @unchecked Sendable {
    private let continuationLock = NSLock()
    private var continuation: CheckedContinuation<Int32, Never>?
    private var pending = false
    init() { super.init(status: 15) }
    override func waitUntilExit() async -> Int32 {
        await withCheckedContinuation { continuation in
            continuationLock.withLock {
                if pending { continuation.resume(returning: 15) }
                else { self.continuation = continuation }
            }
        }
    }
    override func terminate() {
        super.terminate()
        let continuation = continuationLock.withLock { () -> CheckedContinuation<Int32, Never>? in
            let value = self.continuation
            self.continuation = nil
            if value == nil { pending = true }
            return value
        }
        continuation?.resume(returning: 15)
    }
}

private final class SpeechLauncher: ProcessLaunching, @unchecked Sendable {
    private let lock = NSLock()
    private var processes: [any ManagedProcess]
    private let launchError: Error?
    private(set) var requests: [ProcessLaunchRequest] = []
    init(statuses: [Int32], launchError: Error? = nil) {
        self.processes = statuses.map(SpeechImmediateProcess.init(status:))
        self.launchError = launchError
    }
    init(processes: [any ManagedProcess]) {
        self.processes = processes
        self.launchError = nil
    }
    func launch(_ request: ProcessLaunchRequest) throws -> any ManagedProcess {
        try lock.withLock {
            requests.append(request)
            if let launchError { throw launchError }
            return processes.removeFirst()
        }
    }
    var stdinStrings: [String] {
        requests.map {
            String(data: $0.standardInput.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)!
        }
    }
    func waitForLaunchCount(_ count: Int) async {
        while lock.withLock({ requests.count < count }) { await Task.yield() }
    }
}
