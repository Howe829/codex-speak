import XCTest
@testable import CodexSpeakCore

final class MenuConfigurationTests: XCTestCase {
    func testAcceptsExactlyOneAbsoluteValueForEachRequiredFlagInEitherOrder() throws {
        XCTAssertEqual(
            try StrictMenuArguments.parse([
                "--plugin-root", "/tmp/plugin",
                "--data-dir", "/tmp/data",
                "--python-executable", "/usr/bin/true",
            ]),
            StrictMenuArguments(
                pluginRootPath: "/tmp/plugin",
                dataDirectoryPath: "/tmp/data",
                pythonExecutablePath: "/usr/bin/true"
            )
        )
        XCTAssertEqual(
            try StrictMenuArguments.parse([
                "--python-executable", "/usr/bin/true",
                "--data-dir", "/tmp/data",
                "--plugin-root", "/tmp/plugin",
            ]),
            StrictMenuArguments(
                pluginRootPath: "/tmp/plugin",
                dataDirectoryPath: "/tmp/data",
                pythonExecutablePath: "/usr/bin/true"
            )
        )
    }

    func testRejectsMissingRelativeNonExecutableDuplicateAndExtraArguments() throws {
        let nonExecutable = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        try Data().write(to: nonExecutable)
        defer { try? FileManager.default.removeItem(at: nonExecutable) }
        let invalidArguments = [
            ["--plugin-root", "/tmp/plugin", "--data-dir", "/tmp/data"],
            ["--plugin-root", "relative", "--data-dir", "/tmp/data", "--python-executable", "/usr/bin/true"],
            ["--plugin-root", "/tmp/plugin", "--data-dir", "relative", "--python-executable", "/usr/bin/true"],
            ["--plugin-root", "/tmp/plugin", "--data-dir", "/tmp/data", "--python-executable", "python3"],
            ["--plugin-root", "/tmp/plugin", "--data-dir", "/tmp/data", "--python-executable", nonExecutable.path],
            ["--plugin-root", "/tmp/one", "--plugin-root", "/tmp/two", "--data-dir", "/tmp/data", "--python-executable", "/usr/bin/true"],
            ["--plugin-root", "/tmp/plugin", "--data-dir", "/tmp/data", "--python-executable", "/usr/bin/true", "extra"],
            ["--plugin-root", "/tmp/plugin", "--data-dir", "/tmp/data", "--python-executable", "/usr/bin/true", "--unknown", "value"],
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
