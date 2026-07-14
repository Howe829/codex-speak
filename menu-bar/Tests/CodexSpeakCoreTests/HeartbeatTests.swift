import Foundation
import XCTest
@testable import CodexSpeakCore

final class HeartbeatTests: XCTestCase {
    private let bootID = "abcdef12-3456-7890-abcd-ef1234567890"

    func testNormalizesBootIdentity() {
        XCTAssertEqual(
            normalizeBootID("ABCDEF12-3456-7890-ABCD-EF1234567890\n"),
            bootID
        )
        XCTAssertNil(normalizeBootID("not-a-boot-id"))
        XCTAssertNil(normalizeBootID("prefix-ABCDEF12-3456-7890-ABCD-EF1234567890"))
    }

    func testWritesVersionOneCurrentPIDBootIdentityAndMonotonicTimeAtomicallyWithPrivateMode() throws {
        let directory = temporaryDirectory()
        let stateURL = directory.appendingPathComponent("helper-state.json")
        let heartbeat = try Heartbeat(
            stateURL: stateURL,
            processID: 4321,
            bootID: "ABCDEF12-3456-7890-ABCD-EF1234567890",
            monotonic: { 456.25 }
        )

        try heartbeat.write()

        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: stateURL)) as? [String: Any]
        )
        XCTAssertEqual(Set(object.keys), ["version", "pid", "boot_id", "monotonic"])
        XCTAssertEqual(object["version"] as? Int, 1)
        XCTAssertEqual(object["pid"] as? Int, 4321)
        XCTAssertEqual(object["boot_id"] as? String, bootID)
        XCTAssertEqual(object["monotonic"] as? Double, 456.25)

        let attributes = try FileManager.default.attributesOfItem(atPath: stateURL.path)
        XCTAssertEqual((attributes[.posixPermissions] as? NSNumber)?.intValue, 0o600)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: directory.path), ["helper-state.json"])
    }

    func testRejectsStaleFutureAndOtherBootHeartbeat() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, pid: 4321, bootID: bootID, monotonic: 100)

        XCTAssertEqual(readCurrentHeartbeat(stateURL: stateURL, currentBootID: bootID, now: 105), 4321)
        XCTAssertNil(readCurrentHeartbeat(stateURL: stateURL, currentBootID: bootID, now: 105.001))
        XCTAssertNil(readCurrentHeartbeat(stateURL: stateURL, currentBootID: bootID, now: 99.999))
        XCTAssertNil(
            readCurrentHeartbeat(
                stateURL: stateURL,
                currentBootID: "00000000-0000-0000-0000-000000000000",
                now: 101
            )
        )
    }

    func testRejectsWrongVersionPIDAndUnexpectedFields() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        for object: [String: Any] in [
            ["version": 2, "pid": 4321, "boot_id": bootID, "monotonic": 100.0],
            ["version": 1, "pid": 0, "boot_id": bootID, "monotonic": 100.0],
            ["version": 1, "pid": 4321, "boot_id": bootID, "monotonic": 100.0, "extra": true],
        ] {
            try JSONSerialization.data(withJSONObject: object).write(to: stateURL)
            XCTAssertNil(readCurrentHeartbeat(stateURL: stateURL, currentBootID: bootID, now: 101))
        }
    }

    func testRemoveDeletesHeartbeatWithoutSignalingRecordedPID() throws {
        let stateURL = temporaryDirectory().appendingPathComponent("helper-state.json")
        try writeState(to: stateURL, pid: Int.max, bootID: bootID, monotonic: 100)
        let heartbeat = try Heartbeat(
            stateURL: stateURL,
            processID: 4321,
            bootID: bootID,
            monotonic: { 101 }
        )

        heartbeat.remove()

        XCTAssertFalse(FileManager.default.fileExists(atPath: stateURL.path))
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
            "version": 1,
            "pid": pid,
            "boot_id": bootID,
            "monotonic": monotonic,
        ])
        try data.write(to: url)
    }
}
