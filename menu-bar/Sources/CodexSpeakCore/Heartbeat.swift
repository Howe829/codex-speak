import CoreFoundation
import Darwin
import Foundation

private let heartbeatStaleSeconds = 5.0

public enum HeartbeatError: Error, Equatable {
    case invalidBootID
    case invalidProcessID
    case cannotCreateDirectory
    case cannotWrite
}

public final class Heartbeat: @unchecked Sendable {
    public let stateURL: URL
    private let processID: Int32
    private let bootID: String
    private let monotonic: @Sendable () -> Double

    public convenience init(stateURL: URL) throws {
        guard let bootID = currentBootID() else { throw HeartbeatError.invalidBootID }
        try self.init(
            stateURL: stateURL,
            processID: getpid(),
            bootID: bootID,
            monotonic: { Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000_000 }
        )
    }

    public init(
        stateURL: URL,
        processID: Int32,
        bootID: String,
        monotonic: @escaping @Sendable () -> Double
    ) throws {
        guard processID > 0 else { throw HeartbeatError.invalidProcessID }
        guard let normalizedBootID = normalizeBootID(bootID) else {
            throw HeartbeatError.invalidBootID
        }
        self.stateURL = stateURL
        self.processID = processID
        self.bootID = normalizedBootID
        self.monotonic = monotonic
    }

    public func write() throws {
        let directory = stateURL.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o700],
                ofItemAtPath: directory.path
            )
        } catch {
            throw HeartbeatError.cannotCreateDirectory
        }

        let timestamp = monotonic()
        guard timestamp.isFinite, timestamp >= 0 else { throw HeartbeatError.cannotWrite }
        let data: Data
        do {
            data = try JSONSerialization.data(withJSONObject: [
                "version": 1,
                "pid": Int(processID),
                "boot_id": bootID,
                "monotonic": timestamp,
            ])
        } catch {
            throw HeartbeatError.cannotWrite
        }

        let temporaryURL = directory.appendingPathComponent(".helper-state.\(UUID().uuidString).tmp")
        let descriptor = open(temporaryURL.path, O_WRONLY | O_CREAT | O_EXCL, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw HeartbeatError.cannotWrite }
        do {
            let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
            try handle.write(contentsOf: data)
            try handle.synchronize()
            try handle.close()
            guard rename(temporaryURL.path, stateURL.path) == 0 else {
                throw HeartbeatError.cannotWrite
            }
        } catch {
            unlink(temporaryURL.path)
            throw HeartbeatError.cannotWrite
        }
    }

    public func remove() {
        try? FileManager.default.removeItem(at: stateURL)
    }
}

public func normalizeBootID(_ value: String) -> String? {
    let candidate = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let groups = candidate.split(separator: "-", omittingEmptySubsequences: false)
    guard groups.map(\.count) == [8, 4, 4, 4, 12],
          groups.joined().allSatisfy({ $0.isHexDigit }) else { return nil }
    return candidate
}

public func currentBootID() -> String? {
    let bootSessionURL = URL(fileURLWithPath: "/private/var/run/bootSessionMA.txt")
    if let data = try? Data(contentsOf: bootSessionURL),
       let value = String(data: data, encoding: .ascii),
       let normalized = normalizeBootID(value) {
        return normalized
    }

    var size = 0
    guard sysctlbyname("kern.bootsessionuuid", nil, &size, nil, 0) == 0, size > 1 else { return nil }
    var bytes = [CChar](repeating: 0, count: size)
    guard sysctlbyname("kern.bootsessionuuid", &bytes, &size, nil, 0) == 0 else { return nil }
    let content = bytes.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }
    return normalizeBootID(String(decoding: content, as: UTF8.self))
}

public func readCurrentHeartbeat(
    stateURL: URL,
    currentBootID: String,
    now: Double,
    expectedProcessID: Int? = nil
) -> Int? {
    guard let normalizedBootID = normalizeBootID(currentBootID), now.isFinite,
          let data = try? Data(contentsOf: stateURL),
          let object = try? JSONSerialization.jsonObject(with: data),
          let dictionary = object as? [String: Any],
          Set(dictionary.keys) == ["version", "pid", "boot_id", "monotonic"],
          let version = jsonInteger(dictionary["version"]), version == 1,
          let processID = jsonInteger(dictionary["pid"]), processID > 0,
          expectedProcessID == nil || expectedProcessID == processID,
          let storedBootID = dictionary["boot_id"] as? String,
          normalizeBootID(storedBootID) == normalizedBootID,
          let timestamp = jsonDouble(dictionary["monotonic"]), timestamp.isFinite else {
        return nil
    }
    let age = now - timestamp
    guard age >= 0, age <= heartbeatStaleSeconds else { return nil }
    return processID
}

private func jsonInteger(_ value: Any?) -> Int? {
    guard let number = value as? NSNumber,
          CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
    let double = number.doubleValue
    guard double.isFinite, double.rounded() == double,
          double >= Double(Int.min), double <= Double(Int.max) else { return nil }
    return Int(double)
}

private func jsonDouble(_ value: Any?) -> Double? {
    guard let number = value as? NSNumber,
          CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
    return number.doubleValue
}
