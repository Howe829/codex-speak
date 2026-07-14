import Foundation
import XCTest
@testable import CodexSpeakCore

final class PluginEnablementTests: XCTestCase {
    func testReadsOnlyExactCodexSpeakPluginTables() throws {
        let url = try temporaryConfig(
            #"""
            [plugins."other@personal"]
            enabled = false

            [plugins."not-codex-speak@personal"]
            enabled = false

            [plugins."codex-speak@personal"]
            enabled = true
            """#
        )

        XCTAssertEqual(readCodexSpeakEnablement(configURL: url), .enabled)
    }

    func testExplicitFalseDisablesPlugin() throws {
        let url = try temporaryConfig(
            #"""
            [plugins."codex-speak@personal"]
            enabled = false
            """#
        )

        XCTAssertEqual(readCodexSpeakEnablement(configURL: url), .disabled)
    }

    func testMissingMalformedAndNonBooleanValuesAreUnknown() throws {
        for contents in [
            "",
            #"[plugins.codex-speak@personal]"#,
            #"[plugins.\"codex-speak@personal\"] enabled = false"#,
            #"""
            [plugins."codex-speak@personal"]
            enabled = "false"
            """#,
            #"""
            [plugins."codex-speak"]
            enabled = false
            """#,
        ] {
            let url = try temporaryConfig(contents)
            XCTAssertEqual(readCodexSpeakEnablement(configURL: url), .unknown, contents)
        }
        XCTAssertEqual(
            readCodexSpeakEnablement(configURL: URL(fileURLWithPath: "/definitely/missing/config.toml")),
            .unknown
        )
    }

    func testDoesNotUseEnabledValueFromFollowingTable() throws {
        let url = try temporaryConfig(
            #"""
            [plugins."codex-speak@personal"]
            name = "Codex Speak"

            [plugins."other@personal"]
            enabled = false
            """#
        )

        XCTAssertEqual(readCodexSpeakEnablement(configURL: url), .unknown)
    }

    func testAllowsTableCommentsButRejectsNestedOrEscapedIdentifiers() throws {
        let commented = try temporaryConfig(
            #"""
            [plugins."codex-speak@personal"] # installed plugin
            enabled = false
            """#
        )
        XCTAssertEqual(readCodexSpeakEnablement(configURL: commented), .disabled)

        for declaration in [
            #"[plugins."codex-speak@personal".settings]"#,
            #"[plugins."codex-speak@personal\"suffix"]"#,
        ] {
            let url = try temporaryConfig("\(declaration)\nenabled = false\n")
            XCTAssertEqual(readCodexSpeakEnablement(configURL: url), .unknown, declaration)
        }
    }

    private func temporaryConfig(_ contents: String) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("config.toml")
        try Data(contents.utf8).write(to: url)
        return url
    }
}
