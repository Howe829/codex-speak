import Foundation
import XCTest
@testable import CodexSpeakCore

final class HeartbeatTests: XCTestCase {
    private let bootID = "abcdef12-3456-7890-abcd-ef1234567890"
    private let identity = String(repeating: "a", count: 64)
    private let token = String(repeating: "1", count: 64)

    func testNormalizesBootIdentity() {
        XCTAssertEqual(
            normalizeBootID("ABCDEF12-3456-7890-ABCD-EF1234567890\n"),
            bootID
        )
        XCTAssertNil(normalizeBootID("not-a-boot-id"))
    }

    func testStartingReservationBecomesVersionThreeRunningHeartbeat() throws {
        let directory = temporaryDirectory()
        let stateURL = directory.appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, phase: "starting", pid: 0)
        let heartbeat = try makeHeartbeat(stateURL: stateURL, monotonic: 101)

        try heartbeat.write()

        let object = try readObject(stateURL)
        XCTAssertEqual(
            Set(object.keys),
            ["version", "phase", "pid", "boot_id", "monotonic", "identity", "token"]
        )
        XCTAssertEqual(object["version"] as? Int, 3)
        XCTAssertEqual(object["phase"] as? String, "running")
        XCTAssertEqual(object["pid"] as? Int, 4321)
        XCTAssertEqual(object["boot_id"] as? String, bootID)
        XCTAssertEqual(object["monotonic"] as? Double, 101)
        XCTAssertEqual(object["identity"] as? String, identity)
        XCTAssertEqual(object["token"] as? String, token)
        XCTAssertEqual(
            Set(try FileManager.default.contentsOfDirectory(atPath: directory.path)),
            [".helper-state.lock", "helper-state.json"]
        )
        let attributes = try FileManager.default.attributesOfItem(atPath: stateURL.path)
        XCTAssertEqual((attributes[.posixPermissions] as? NSNumber)?.intValue, 0o600)
    }

    func testUnconfirmedReservationIsNotActiveAndUnreservedWriterIsRejected() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, phase: "starting", pid: 0)

        XCTAssertNil(
            readCurrentHeartbeat(
                stateURL: stateURL,
                currentBootID: bootID,
                expectedIdentity: identity,
                expectedToken: token,
                now: 101
            )
        )

        let other = try Heartbeat(
            stateURL: stateURL,
            processID: 9876,
            bootID: bootID,
            identity: identity,
            token: String(repeating: "2", count: 64),
            monotonic: { 101 }
        )
        XCTAssertThrowsError(try other.write()) { error in
            XCTAssertEqual(error as? HeartbeatError, .ownershipConflict)
        }
    }

    func testRunningOwnerRefreshesButFreshOtherOwnerCannotOverwrite() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, phase: "starting", pid: 0, monotonic: 100)
        let heartbeat = try makeHeartbeat(stateURL: stateURL, monotonic: 101)
        try heartbeat.write()
        try heartbeat.write()

        XCTAssertEqual(
            readCurrentHeartbeat(
                stateURL: stateURL,
                currentBootID: bootID,
                expectedIdentity: identity,
                expectedToken: token,
                now: 101,
                expectedProcessID: 4321
            ),
            4321
        )

        let other = try Heartbeat(
            stateURL: stateURL,
            processID: 9876,
            bootID: bootID,
            identity: String(repeating: "b", count: 64),
            token: String(repeating: "2", count: 64),
            monotonic: { 102 }
        )
        XCTAssertThrowsError(try other.write()) { error in
            XCTAssertEqual(error as? HeartbeatError, .ownershipConflict)
        }
    }

    func testRejectsStaleFutureWrongTokenOldVersionAndUnexpectedFields() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, phase: "running", pid: 4321, monotonic: 100)
        XCTAssertEqual(readCurrent(stateURL, now: 105), 4321)
        XCTAssertNil(readCurrent(stateURL, now: 105.001))
        XCTAssertNil(readCurrent(stateURL, now: 99.999))
        XCTAssertNil(
            readCurrentHeartbeat(
                stateURL: stateURL,
                currentBootID: bootID,
                expectedIdentity: identity,
                expectedToken: String(repeating: "2", count: 64),
                now: 101
            )
        )
        for object: [String: Any] in [
            ["version": 2, "pid": 4321, "boot_id": bootID, "monotonic": 100.0, "identity": identity],
            ["version": 3, "phase": "running", "pid": 4321, "boot_id": bootID, "monotonic": 100.0, "identity": identity, "token": token, "extra": true],
        ] {
            try JSONSerialization.data(withJSONObject: object).write(to: stateURL)
            XCTAssertNil(readCurrent(stateURL, now: 101))
        }
    }

    func testRemoveDeletesOnlyMatchingRunningToken() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, phase: "running", pid: 4321)
        let heartbeat = try makeHeartbeat(stateURL: stateURL, monotonic: 101)
        heartbeat.remove()
        XCTAssertFalse(FileManager.default.fileExists(atPath: stateURL.path))

        try writeState(
            to: stateURL,
            phase: "running",
            pid: 9876,
            identity: identity,
            token: String(repeating: "2", count: 64)
        )
        heartbeat.remove()
        XCTAssertTrue(FileManager.default.fileExists(atPath: stateURL.path))
    }

    func testRemoveWaitsForLockThenPreservesReplacement() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, phase: "running", pid: 4321)
        let heartbeat = try makeHeartbeat(stateURL: stateURL, monotonic: 101)
        let started = DispatchSemaphore(value: 0)
        let finished = DispatchSemaphore(value: 0)
        let replacementToken = String(repeating: "2", count: 64)

        try withHelperStateLock(stateURL: stateURL) {
            DispatchQueue.global().async {
                started.signal()
                heartbeat.remove()
                finished.signal()
            }
            XCTAssertEqual(started.wait(timeout: .now() + 1), .success)
            XCTAssertEqual(finished.wait(timeout: .now() + 0.1), .timedOut)
            try writeState(
                to: stateURL,
                phase: "starting",
                pid: 0,
                token: replacementToken
            )
        }

        XCTAssertEqual(finished.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(try readObject(stateURL)["token"] as? String, replacementToken)
    }

    private func makeHeartbeat(stateURL: URL, monotonic: Double) throws -> Heartbeat {
        try Heartbeat(
            stateURL: stateURL,
            processID: 4321,
            bootID: bootID,
            identity: identity,
            token: token,
            monotonic: { monotonic }
        )
    }

    private func readCurrent(_ stateURL: URL, now: Double) -> Int? {
        readCurrentHeartbeat(
            stateURL: stateURL,
            currentBootID: bootID,
            expectedIdentity: identity,
            expectedToken: token,
            now: now
        )
    }

    private func temporaryDirectory() -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try! FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return directory
    }

    private func readObject(_ url: URL) throws -> [String: Any] {
        try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any]
        )
    }

    private func writeState(
        to url: URL,
        phase: String,
        pid: Int,
        bootID: String? = nil,
        monotonic: Double = 100,
        identity: String? = nil,
        token: String? = nil
    ) throws {
        let data = try JSONSerialization.data(withJSONObject: [
            "version": 3,
            "phase": phase,
            "pid": pid,
            "boot_id": bootID ?? self.bootID,
            "monotonic": monotonic,
            "identity": identity ?? self.identity,
            "token": token ?? self.token,
        ])
        try data.write(to: url, options: .atomic)
    }
}
