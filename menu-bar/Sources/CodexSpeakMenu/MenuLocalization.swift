import Foundation

struct MenuLocalization {
    enum Key: String, CaseIterable {
        case menuModeSilent = "menu.mode.silent"
        case menuModeSummary = "menu.mode.summary"
        case menuModeFull = "menu.mode.full"
        case menuActionStop = "menu.action.stop"
        case menuActionClear = "menu.action.clear"
        case menuActionQuit = "menu.action.quit"
        case errorBridgeStopped = "error.bridge_stopped"
        case errorClearFailed = "error.clear_failed"
        case errorModeWriteFailed = "error.mode_write_failed"
        case errorModeReadFailed = "error.mode_read_failed"
        case errorHeartbeatUnavailable = "error.heartbeat_unavailable"
        case errorPlaybackRecordFailed = "error.playback_record_failed"

        var englishFallback: String {
            switch self {
            case .menuModeSilent: "Silent"
            case .menuModeSummary: "Summary"
            case .menuModeFull: "Full"
            case .menuActionStop: "Stop Current Speech"
            case .menuActionClear: "Clear Pending Speeches"
            case .menuActionQuit: "Quit Codex Speak"
            case .errorBridgeStopped: "Speech bridge stopped"
            case .errorClearFailed: "Could not clear pending speeches"
            case .errorModeWriteFailed: "Could not change speech mode"
            case .errorModeReadFailed: "Could not read speech mode"
            case .errorHeartbeatUnavailable: "Heartbeat unavailable"
            case .errorPlaybackRecordFailed: "Could not record playback result"
            }
        }
    }

    private let bundle: Bundle

    init(bundle: Bundle = .main) {
        self.bundle = bundle
    }

    func string(_ key: Key) -> String {
        bundle.localizedString(
            forKey: key.rawValue,
            value: key.englishFallback,
            table: nil
        )
    }

    var menuItemTitles: [String] {
        [
            .menuModeSilent,
            .menuModeSummary,
            .menuModeFull,
            .menuActionStop,
            .menuActionClear,
            .menuActionQuit,
        ].map(string)
    }
}
