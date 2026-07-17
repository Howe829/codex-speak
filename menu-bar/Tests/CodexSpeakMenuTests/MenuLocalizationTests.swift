import Foundation
import XCTest
@testable import CodexSpeakMenu

final class MenuLocalizationTests: XCTestCase {
    func testEnglishMenuHasExactOrder() throws {
        XCTAssertEqual(
            try localization("en").menuItemTitles,
            [
                "Silent",
                "Summary",
                "Full",
                "Stop Current Speech",
                "Clear Pending Speeches",
                "Quit Codex Speak",
            ]
        )
    }

    func testSimplifiedChineseMenuHasExactOrder() throws {
        XCTAssertEqual(
            try localization("zh-Hans").menuItemTitles,
            [
                "静音",
                "摘要",
                "全文",
                "停止当前朗读",
                "清除待朗读内容",
                "退出 Codex Speak",
            ]
        )
    }

    func testEveryKeyResolvesInBothLanguages() throws {
        let english = try localization("en")
        let chinese = try localization("zh-Hans")
        for key in MenuLocalization.Key.allCases {
            XCTAssertNotEqual(english.string(key), key.rawValue)
            XCTAssertNotEqual(chinese.string(key), key.rawValue)
        }
        XCTAssertEqual(chinese.string(.errorBridgeStopped), "语音桥接已停止")
        XCTAssertEqual(chinese.string(.errorClearFailed), "无法清除待朗读内容")
        XCTAssertEqual(chinese.string(.errorModeWriteFailed), "无法更改朗读模式")
        XCTAssertEqual(chinese.string(.errorModeReadFailed), "无法读取朗读模式")
        XCTAssertEqual(chinese.string(.errorHeartbeatUnavailable), "心跳不可用")
        XCTAssertEqual(chinese.string(.errorPlaybackRecordFailed), "无法记录播放结果")
    }

    func testMissingResourcesFallBackToReadableEnglish() {
        let localization = MenuLocalization(bundle: Bundle(for: Self.self))
        for key in MenuLocalization.Key.allCases {
            XCTAssertEqual(localization.string(key), key.englishFallback)
        }
    }

    private func localization(_ language: String) throws -> MenuLocalization {
        let resources = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("Resources")
            .appendingPathComponent("\(language).lproj")
        return MenuLocalization(bundle: try XCTUnwrap(Bundle(url: resources)))
    }
}
