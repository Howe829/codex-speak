import Foundation
import XCTest
@testable import CodexSpeakCore

final class HeartbeatTests: XCTestCase {
    private let bootID = "abcdef12-3456-7890-abcd-ef1234567890"
    private let identity = String(repeating: "a", count: 64)

    func testNormalizesBootIdentity() {
        XCTAssertEqual(
            normalizeBootID("ABCDEF12-3456-7890-ABCD-EF1234567890\n"),
            bootID
        )
        XCTAssertNil(normalizeBootID("not-a-boot-id"))
        XCTAssertNil(normalizeBootID("prefix-ABCDEF12-3456-7890-ABCD-EF1234567890"))
    }

    func testWritesVersionTwoCurrentPIDBootAndHashedIdentityAtomicallyWithPrivateMode() throws {
        let directory = temporaryDirectory()
        let stateURL = directory.appendingPathComponent("helper-state.json")
        let heartbeat = try Heartbeat(
            stateURL: stateURL,
            processID: 4321,
            bootID: "ABCDEF12-3456-7890-ABCD-EF1234567890",
            identity: identity,
            monotonic: { 456.25 }
        )

        try heartbeat.write()

        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: stateURL)) as? [String: Any]
        )
        XCTAssertEqual(Set(object.keys), ["version", "pid", "boot_id", "monotonic", "identity"])
        XCTAssertEqual(object["version"] as? Int, 2)
        XCTAssertEqual(object["pid"] as? Int, 4321)
        XCTAssertEqual(object["boot_id"] as? String, bootID)
        XCTAssertEqual(object["monotonic"] as? Double, 456.25)
        XCTAssertEqual(object["identity"] as? String, identity)

        let attributes = try FileManager.default.attributesOfItem(atPath: stateURL.path)
        XCTAssertEqual((attributes[.posixPermissions] as? NSNumber)?.intValue, 0o600)
        XCTAssertEqual(
            Set(try FileManager.default.contentsOfDirectory(atPath: directory.path)),
            [".helper-state.lock", "helper-state.json"]
        )
    }

    func testRejectsStaleFutureAndOtherBootHeartbeat() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, pid: 4321, bootID: bootID, monotonic: 100)

        XCTAssertEqual(readCurrentHeartbeat(stateURL: stateURL, currentBootID: bootID, expectedIdentity: identity, now: 105), 4321)
        XCTAssertNil(readCurrentHeartbeat(stateURL: stateURL, currentBootID: bootID, expectedIdentity: identity, now: 105.001))
        XCTAssertNil(readCurrentHeartbeat(stateURL: stateURL, currentBootID: bootID, expectedIdentity: identity, now: 99.999))
        XCTAssertNil(
            readCurrentHeartbeat(
                stateURL: stateURL,
                currentBootID: "00000000-0000-0000-0000-000000000000",
                expectedIdentity: identity,
                now: 101
            )
        )
    }

    func testRejectsWrongVersionPIDAndUnexpectedFields() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        for object: [String: Any] in [
            ["version": 1, "pid": 4321, "boot_id": bootID, "monotonic": 100.0],
            ["version": 2, "pid": 0, "boot_id": bootID, "monotonic": 100.0, "identity": identity],
            ["version": 2, "pid": 4321, "boot_id": bootID, "monotonic": 100.0, "identity": identity, "extra": true],
            ["version": 2, "pid": 4321, "boot_id": bootID, "monotonic": 100.0, "identity": String(repeating: "b", count: 64)],
        ] {
            try JSONSerialization.data(withJSONObject: object).write(to: stateURL)
            XCTAssertNil(readCurrentHeartbeat(stateURL: stateURL, currentBootID: bootID, expectedIdentity: identity, now: 101))
        }
    }

    func testRemoveDeletesHeartbeatWithoutSignalingRecordedPID() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, pid: 4321, bootID: bootID, monotonic: 100)
        let heartbeat = try Heartbeat(
            stateURL: stateURL,
            processID: 4321,
            bootID: bootID,
            identity: identity,
            monotonic: { 101 }
        )

        heartbeat.remove()

        XCTAssertFalse(FileManager.default.fileExists(atPath: stateURL.path))
    }

    func testRemoveDoesNotDeleteReplacementHeartbeatFromOtherIdentity() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        let heartbeat = try Heartbeat(
            stateURL: stateURL,
            processID: 4321,
            bootID: bootID,
            identity: identity,
            monotonic: { 101 }
        )
        let replacementIdentity = String(repeating: "b", count: 64)
        let data = try JSONSerialization.data(withJSONObject: [
            "version": 2,
            "pid": 9876,
            "boot_id": bootID,
            "monotonic": 101.0,
            "identity": replacementIdentity,
        ])
        try data.write(to: stateURL)

        heartbeat.remove()

        XCTAssertTrue(FileManager.default.fileExists(atPath: stateURL.path))
    }

    func testFreshOtherOwnerCannotBeOverwrittenAndCanBeTakenAfterRemoval() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        let oldHeartbeat = try Heartbeat(
            stateURL: stateURL,
            processID: 4321,
            bootID: bootID,
            identity: identity,
            monotonic: { 100 }
        )
        let replacementIdentity = String(repeating: "b", count: 64)
        let newHeartbeat = try Heartbeat(
            stateURL: stateURL,
            processID: 9876,
            bootID: bootID,
            identity: replacementIdentity,
            monotonic: { 101 }
        )
        try oldHeartbeat.write()

        XCTAssertThrowsError(try newHeartbeat.write()) { error in
            XCTAssertEqual(error as? HeartbeatError, .ownershipConflict)
        }
        XCTAssertEqual(
            readCurrentHeartbeat(
                stateURL: stateURL,
                currentBootID: bootID,
                expectedIdentity: identity,
                now: 101
            ),
            4321
        )

        oldHeartbeat.remove()
        try newHeartbeat.write()

        XCTAssertEqual(
            readCurrentHeartbeat(
                stateURL: stateURL,
                currentBootID: bootID,
                expectedIdentity: replacementIdentity,
                now: 101
            ),
            9876
        )
    }

    func testRemoveWaitsForStateLockThenPreservesReplacement() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        let heartbeat = try Heartbeat(
            stateURL: stateURL,
            processID: 4321,
            bootID: bootID,
            identity: identity,
            monotonic: { 100 }
        )
        try heartbeat.write()
        let started = DispatchSemaphore(value: 0)
        let finished = DispatchSemaphore(value: 0)
        let replacementIdentity = String(repeating: "b", count: 64)

        try withHelperStateLock(stateURL: stateURL) {
            DispatchQueue.global().async {
                started.signal()
                heartbeat.remove()
                finished.signal()
            }
            XCTAssertEqual(started.wait(timeout: .now() + 1), .success)
            XCTAssertEqual(finished.wait(timeout: .now() + 0.1), .timedOut)
            let replacement = try JSONSerialization.data(withJSONObject: [
                "version": 2,
                "pid": 9876,
                "boot_id": bootID,
                "monotonic": 101.0,
                "identity": replacementIdentity,
            ])
            try replacement.write(to: stateURL, options: .atomic)
        }

        XCTAssertEqual(finished.wait(timeout: .now() + 1), .success)
        XCTAssertEqual(
            readCurrentHeartbeat(
                stateURL: stateURL,
                currentBootID: bootID,
                expectedIdentity: replacementIdentity,
                now: 101
            ),
            9876
        )
    }

    private func temporaryDirectory() -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try! FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return directory
    }

    private func writeState(to url: URL, pid: Int, bootID: String, monotonic: Double) throws {
        let data = try JSONSerialization.data(withJSONObject: [
            "version": 2,
            "pid": pid,
            "boot_id": bootID,
            "monotonic": monotonic,
            "identity": identity,
        ])
        try data.write(to: url)
    }
}
