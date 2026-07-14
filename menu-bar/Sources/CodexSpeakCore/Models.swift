import Foundation

public enum SpeechMode: String, Codable, Sendable {
    case summary
    case full
}

public struct SpeechEvent: Equatable, Sendable {
    public let eventID: String
    public let mode: SpeechMode
    public let status: String
    public let segments: [String]

    init(eventID: String, mode: SpeechMode, status: String, segments: [String]) {
        self.eventID = eventID
        self.mode = mode
        self.status = status
        self.segments = segments
    }
}

public enum BridgeMessage: Equatable, Sendable {
    case ready
    case busy
    case event(SpeechEvent)

    public static func decode(line: String) throws -> BridgeMessage {
        guard let data = line.data(using: .utf8) else {
            throw CodexSpeakError.invalidBridgeMessage
        }
        return try decode(data: data)
    }

    public static func decode(data: Data) throws -> BridgeMessage {
        let object: Any
        do {
            object = try JSONSerialization.jsonObject(with: data)
        } catch {
            throw CodexSpeakError.invalidBridgeMessage
        }
        guard let dictionary = object as? [String: Any],
              let type = dictionary["type"] as? String else {
            throw CodexSpeakError.invalidBridgeMessage
        }
        switch type {
        case "ready":
            guard Set(dictionary.keys) == ["type"] else {
                throw CodexSpeakError.invalidBridgeMessage
            }
            return .ready
        case "busy":
            guard Set(dictionary.keys) == ["type"] else {
                throw CodexSpeakError.invalidBridgeMessage
            }
            return .busy
        case "event":
            let requiredKeys: Set<String> = ["type", "event_id", "mode", "status", "segments"]
            guard Set(dictionary.keys) == requiredKeys,
                  let eventID = dictionary["event_id"] as? String,
                  eventID.count == 24,
                  eventID.allSatisfy({ $0.isASCII && ($0.isNumber || ("a"..."f").contains(String($0))) }),
                  let rawMode = dictionary["mode"] as? String,
                  let mode = SpeechMode(rawValue: rawMode),
                  let status = dictionary["status"] as? String,
                  ["completed", "blocked", "action_required", "silent"].contains(status),
                  status != "silent" || mode == .full,
                  let segments = dictionary["segments"] as? [String],
                  (1...10_000).contains(segments.count),
                  segments.allSatisfy({ (1...600).contains($0.count) }) else {
                throw CodexSpeakError.invalidBridgeMessage
            }
            return .event(SpeechEvent(eventID: eventID, mode: mode, status: status, segments: segments))
        default:
            throw CodexSpeakError.invalidBridgeMessage
        }
    }
}

public enum PlaybackOutcome: String, Equatable, Sendable {
    case spoken
    case failed
    case cancelled
}

public enum PlaybackErrorCode: String, Equatable, Sendable {
    case sayFailed = "say_failed"
    case speechStartFailed = "speech_start_failed"
}

public struct PlaybackResult: Equatable, Sendable {
    public let outcome: PlaybackOutcome
    public let errorCode: PlaybackErrorCode?
    public let completedSegmentCount: Int
    public let durationMilliseconds: Int

    public init(
        outcome: PlaybackOutcome,
        errorCode: PlaybackErrorCode?,
        completedSegmentCount: Int,
        durationMilliseconds: Int
    ) {
        self.outcome = outcome
        self.errorCode = errorCode
        self.completedSegmentCount = completedSegmentCount
        self.durationMilliseconds = durationMilliseconds
    }
}

enum CodexSpeakError: Error {
    case invalidBridgeMessage
    case invalidCommandOutput
    case commandFailed
}
