import Foundation

public enum PluginEnablement: Equatable, Sendable {
    case enabled
    case disabled
    case unknown
}

public let codexSpeakMenuItemTitles = [
    "Summary",
    "Full",
    "Stop Current Speech",
    "Clear Pending Speeches",
    "Quit Codex Speak",
]

public struct StrictMenuArguments: Equatable, Sendable {
    public let pluginRootPath: String
    public let dataDirectoryPath: String
    public let pythonExecutablePath: String
    public let helperIdentity: String

    public init(
        pluginRootPath: String,
        dataDirectoryPath: String,
        pythonExecutablePath: String,
        helperIdentity: String
    ) {
        self.pluginRootPath = pluginRootPath
        self.dataDirectoryPath = dataDirectoryPath
        self.pythonExecutablePath = pythonExecutablePath
        self.helperIdentity = helperIdentity
    }

    public static func parse(_ arguments: [String]) throws -> StrictMenuArguments {
        guard arguments.count == 8 else { throw StrictMenuArgumentError.invalid }
        var values: [String: String] = [:]
        var index = 0
        while index < arguments.count {
            let flag = arguments[index]
            guard flag == "--plugin-root"
                    || flag == "--data-dir"
                    || flag == "--python-executable"
                    || flag == "--helper-identity",
                  values[flag] == nil else { throw StrictMenuArgumentError.invalid }
            let value = arguments[index + 1]
            guard flag == "--helper-identity"
                    || NSString(string: value).isAbsolutePath else {
                throw StrictMenuArgumentError.invalid
            }
            values[flag] = value
            index += 2
        }
        guard let pluginRoot = values["--plugin-root"],
              let dataDirectory = values["--data-dir"],
              let pythonExecutable = values["--python-executable"],
              let helperIdentity = values["--helper-identity"],
              isValidHelperIdentity(helperIdentity),
              isExecutableFile(atPath: pythonExecutable) else {
            throw StrictMenuArgumentError.invalid
        }
        return StrictMenuArguments(
            pluginRootPath: pluginRoot,
            dataDirectoryPath: dataDirectory,
            pythonExecutablePath: pythonExecutable,
            helperIdentity: helperIdentity
        )
    }
}

private func isValidHelperIdentity(_ value: String) -> Bool {
    value.utf8.count == 64
        && value.utf8.allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102)
        }
}

private func isExecutableFile(atPath path: String) -> Bool {
    var isDirectory = ObjCBool(false)
    return FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory)
        && !isDirectory.boolValue
        && FileManager.default.isExecutableFile(atPath: path)
}

private enum StrictMenuArgumentError: Error {
    case invalid
}

public func readCodexSpeakEnablement(configURL: URL) -> PluginEnablement {
    guard let data = try? Data(contentsOf: configURL),
          let contents = String(data: data, encoding: .utf8) else {
        return .unknown
    }

    var insideCodexSpeakTable = false
    var result = PluginEnablement.unknown
    for rawLine in contents.split(separator: "\n", omittingEmptySubsequences: false) {
        let line = rawLine.trimmingCharacters(in: .whitespaces)
        if line.hasPrefix("[") {
            insideCodexSpeakTable = isCodexSpeakPluginTable(line)
            continue
        }
        guard insideCodexSpeakTable,
              let value = parseEnabledLine(line) else { continue }
        if value == false { return .disabled }
        result = .enabled
    }
    return result
}

public func shouldTerminateHelper(pluginRootURL: URL, configURL: URL) -> Bool {
    var isDirectory = ObjCBool(false)
    guard FileManager.default.fileExists(
        atPath: pluginRootURL.path,
        isDirectory: &isDirectory
    ), isDirectory.boolValue else {
        return true
    }
    return readCodexSpeakEnablement(configURL: configURL) == .disabled
}

private func isCodexSpeakPluginTable(_ line: String) -> Bool {
    let declaration = line.split(
        separator: "#",
        maxSplits: 1,
        omittingEmptySubsequences: false
    )[0].trimmingCharacters(in: .whitespaces)
    let prefix = #"[plugins.""#
    let suffix = #""]"#
    guard declaration.hasPrefix(prefix), declaration.hasSuffix(suffix) else { return false }
    let identifierStart = declaration.index(declaration.startIndex, offsetBy: prefix.count)
    let identifierEnd = declaration.index(declaration.endIndex, offsetBy: -suffix.count)
    let identifier = declaration[identifierStart..<identifierEnd]
    return identifier.hasPrefix("codex-speak@")
        && identifier.count > "codex-speak@".count
        && !identifier.contains("\"")
        && !identifier.contains("\\")
}

private func parseEnabledLine(_ line: String) -> Bool? {
    let uncommented = line.split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false)[0]
    let pieces = uncommented.split(separator: "=", omittingEmptySubsequences: false)
    guard pieces.count == 2,
          pieces[0].trimmingCharacters(in: .whitespaces) == "enabled" else { return nil }
    switch pieces[1].trimmingCharacters(in: .whitespaces) {
    case "true": return true
    case "false": return false
    default: return nil
    }
}
