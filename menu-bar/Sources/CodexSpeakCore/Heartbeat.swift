import CoreFoundation
import Darwin
import Foundation

private let heartbeatStaleSeconds = 5.0

public enum HeartbeatError: Error, Equatable {
    case invalidBootID
    case invalidProcessID
    case cannotCreateDirectory
    case cannotWrite
    case ownershipConflict
}

public func withHelperStateLock<Result>(
    stateURL: URL,
    _ body: () throws -> Result
) throws -> Result {
    let lockURL = stateURL.deletingLastPathComponent()
        .appendingPathComponent(".helper-state.lock")
    let descriptor = open(lockURL.path, O_RDWR | O_CREAT | O_CLOEXEC, S_IRUSR | S_IWUSR)
    guard descriptor >= 0 else { throw HeartbeatError.cannotWrite }
    guard fchmod(descriptor, S_IRUSR | S_IWUSR) == 0 else {
        close(descriptor)
        throw HeartbeatError.cannotWrite
    }
    guard flock(descriptor, LOCK_EX) == 0 else {
        close(descriptor)
        throw HeartbeatError.cannotWrite
    }
    defer {
        flock(descriptor, LOCK_UN)
        close(descriptor)
    }
    return try body()
}

public final class Heartbeat: @unchecked Sendable {
    public let stateURL: URL
    private let processID: Int32
    private let bootID: String
    private let identity: String
    private let token: String
    private let monotonic: @Sendable () -> Double

    public convenience init(stateURL: URL, identity: String, token: String) throws {
        guard let bootID = currentBootID() else { throw HeartbeatError.invalidBootID }
        try self.init(
            stateURL: stateURL,
            processID: getpid(),
            bootID: bootID,
            identity: identity,
            token: token,
            monotonic: { Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000_000 }
        )
    }

    public init(
        stateURL: URL,
        processID: Int32,
        bootID: String,
        identity: String,
        token: String,
        monotonic: @escaping @Sendable () -> Double
    ) throws {
        guard processID > 0 else { throw HeartbeatError.invalidProcessID }
        guard let normalizedBootID = normalizeBootID(bootID) else {
            throw HeartbeatError.invalidBootID
        }
        guard normalizeFixedHex(identity) != nil, normalizeFixedHex(token) != nil else {
            throw HeartbeatError.cannotWrite
        }
        self.stateURL = stateURL
        self.processID = processID
        self.bootID = normalizedBootID
        self.identity = identity
        self.token = token
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

        try withHelperStateLock(stateURL: stateURL) {
            let timestamp = monotonic()
            guard timestamp.isFinite, timestamp >= 0,
                  let owner = readFreshHeartbeatUnlocked(
                      stateURL: stateURL,
                      currentBootID: bootID,
                      now: timestamp
                  ), owner.identity == identity, owner.token == token,
                  (owner.phase == .starting && owner.processID == 0)
                    || (owner.phase == .running && owner.processID == Int(processID)) else {
                throw HeartbeatError.ownershipConflict
            }
            let data: Data
            do {
                data = try JSONSerialization.data(withJSONObject: [
                    "version": 3,
                    "phase": "running",
                    "pid": Int(processID),
                    "boot_id": bootID,
                    "monotonic": timestamp,
                    "identity": identity,
                    "token": token,
                ])
            } catch {
                throw HeartbeatError.cannotWrite
            }
            try atomicWrite(data, to: stateURL)
        }
    }

    public func remove() {
        try? withHelperStateLock(stateURL: stateURL) {
            guard let owner = readStoredOwnerUnlocked(stateURL: stateURL),
                  owner.phase == .running,
                  owner.processID == Int(processID),
                  owner.identity == identity,
                  owner.token == token else {
                return
            }
            try? FileManager.default.removeItem(at: stateURL)
        }
    }
}

private func atomicWrite(_ data: Data, to stateURL: URL) throws {
    let directory = stateURL.deletingLastPathComponent()
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

private func normalizeFixedHex(_ value: String) -> String? {
    guard value.utf8.count == 64,
          value.utf8.allSatisfy({
              ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102)
          }) else { return nil }
    return value
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
    expectedIdentity: String,
    expectedToken: String,
    now: Double,
    expectedProcessID: Int? = nil
) -> Int? {
    guard let normalizedBootID = normalizeBootID(currentBootID), now.isFinite,
          normalizeFixedHex(expectedIdentity) != nil,
          normalizeFixedHex(expectedToken) != nil else {
        return nil
    }
    let owner = try? withHelperStateLock(stateURL: stateURL) {
        readFreshHeartbeatUnlocked(
            stateURL: stateURL,
            currentBootID: normalizedBootID,
            now: now
        )
    }
    guard let owner,
          owner.phase == .running,
          owner.identity == expectedIdentity,
          owner.token == expectedToken,
          expectedProcessID == nil || expectedProcessID == owner.processID else {
        return nil
    }
    return owner.processID
}

private enum HelperPhase: String {
    case starting
    case running
}

private struct StoredOwner {
    let phase: HelperPhase
    let processID: Int
    let bootID: String
    let monotonic: Double
    let identity: String
    let token: String
}

private func readStoredOwnerUnlocked(stateURL: URL) -> StoredOwner? {
    guard let data = try? Data(contentsOf: stateURL),
          let object = try? JSONSerialization.jsonObject(with: data),
          let dictionary = object as? [String: Any],
          Set(dictionary.keys) == ["version", "phase", "pid", "boot_id", "monotonic", "identity", "token"],
          let version = jsonInteger(dictionary["version"]), version == 3,
          let rawPhase = dictionary["phase"] as? String,
          let phase = HelperPhase(rawValue: rawPhase),
          let processID = jsonInteger(dictionary["pid"]),
          (phase == .starting && processID == 0) || (phase == .running && processID > 0),
          let storedBootID = dictionary["boot_id"] as? String,
          let normalizedBootID = normalizeBootID(storedBootID),
          let storedIdentity = dictionary["identity"] as? String,
          let normalizedIdentity = normalizeFixedHex(storedIdentity),
          let storedToken = dictionary["token"] as? String,
          let normalizedToken = normalizeFixedHex(storedToken),
          let timestamp = jsonDouble(dictionary["monotonic"]), timestamp.isFinite else {
        return nil
    }
    return StoredOwner(
        phase: phase,
        processID: processID,
        bootID: normalizedBootID,
        monotonic: timestamp,
        identity: normalizedIdentity,
        token: normalizedToken
    )
}

private func readFreshHeartbeatUnlocked(
    stateURL: URL,
    currentBootID: String,
    now: Double
) -> StoredOwner? {
    guard let normalizedBootID = normalizeBootID(currentBootID), now.isFinite,
          let owner = readStoredOwnerUnlocked(stateURL: stateURL),
          owner.bootID == normalizedBootID else {
        return nil
    }
    let age = now - owner.monotonic
    guard age >= 0, age <= heartbeatStaleSeconds else { return nil }
    return owner
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
