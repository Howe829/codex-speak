import XCTest
@testable import CodexSpeakCore

final class MenuConfigurationTests: XCTestCase {
    func testAcceptsExactlyOneAbsoluteValueForEachRequiredFlagInEitherOrder() throws {
        XCTAssertEqual(
            try StrictMenuArguments.parse([
                "--plugin-root", "/tmp/plugin",
                "--data-dir", "/tmp/data",
            ]),
            StrictMenuArguments(pluginRootPath: "/tmp/plugin", dataDirectoryPath: "/tmp/data")
        )
        XCTAssertEqual(
            try StrictMenuArguments.parse([
                "--data-dir", "/tmp/data",
                "--plugin-root", "/tmp/plugin",
            ]),
            StrictMenuArguments(pluginRootPath: "/tmp/plugin", dataDirectoryPath: "/tmp/data")
        )
    }

    func testRejectsMissingRelativeDuplicateAndExtraArguments() {
        let invalidArguments = [
            ["--plugin-root", "/tmp/plugin"],
            ["--plugin-root", "relative", "--data-dir", "/tmp/data"],
            ["--plugin-root", "/tmp/plugin", "--data-dir", "relative"],
            ["--plugin-root", "/tmp/one", "--plugin-root", "/tmp/two", "--data-dir", "/tmp/data"],
            ["--plugin-root", "/tmp/plugin", "--data-dir", "/tmp/data", "extra"],
            ["--plugin-root", "/tmp/plugin", "--data-dir", "/tmp/data", "--unknown", "value"],
        ]
        for arguments in invalidArguments {
            XCTAssertThrowsError(try StrictMenuArguments.parse(arguments), arguments.joined(separator: " "))
        }
    }

    func testMenuHasExactFiveItemsInOrder() {
        XCTAssertEqual(
            codexSpeakMenuItemTitles,
            [
                "Summary",
                "Full",
                "Stop Current Speech",
                "Clear Pending Speeches",
                "Quit Codex Speak",
            ]
        )
    }
}
