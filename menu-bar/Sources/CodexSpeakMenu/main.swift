@preconcurrency import AppKit
import CodexSpeakCore
import Darwin
import Foundation

private func codexConfigURL() -> URL {
    if let codexHome = ProcessInfo.processInfo.environment["CODEX_HOME"],
       NSString(string: codexHome).isAbsolutePath {
        return URL(fileURLWithPath: codexHome, isDirectory: true)
            .appendingPathComponent("config.toml")
    }
    return FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".codex", isDirectory: true)
        .appendingPathComponent("config.toml")
}

let arguments: StrictMenuArguments
do {
    arguments = try StrictMenuArguments.parse(Array(CommandLine.arguments.dropFirst()))
} catch {
    FileHandle.standardError.write(
        Data("usage: CodexSpeakMenu --plugin-root ABSOLUTE --data-dir ABSOLUTE --python-executable ABSOLUTE\n".utf8)
    )
    exit(2)
}

let application = NSApplication.shared
application.setActivationPolicy(.accessory)
let pluginRoot = URL(fileURLWithPath: arguments.pluginRootPath, isDirectory: true)
let dataDirectory = URL(fileURLWithPath: arguments.dataDirectoryPath, isDirectory: true)
let pythonExecutableURL = URL(fileURLWithPath: arguments.pythonExecutablePath)
let controller: MenuController
do {
    controller = try MenuController(
        application: application,
        pluginRoot: pluginRoot,
        dataDirectory: dataDirectory,
        pythonExecutableURL: pythonExecutableURL,
        configURL: codexConfigURL()
    )
    try controller.start()
} catch {
    exit(1)
}
withExtendedLifetime(controller) {
    application.run()
}
