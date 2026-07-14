@preconcurrency import AppKit
import CodexSpeakCore
import Foundation

@MainActor
final class MenuController: NSObject {
    static let itemTitles = codexSpeakMenuItemTitles

    private let application: NSApplication
    private let statusItem: NSStatusItem
    private let controlClient: any ControlClientProtocol
    private let diagnosticsClient: DiagnosticsClient
    private let speechPlayer: SpeechPlayer
    private let bridge: BridgeProcess
    private let heartbeat: Heartbeat
    private let configURL: URL
    private let pluginRoot: URL
    private let summaryItem: NSMenuItem
    private let fullItem: NSMenuItem
    private var selectedMode = SpeechMode.summary
    private var heartbeatTimer: Timer?
    private var enablementTimer: Timer?
    private var errorTimer: Timer?
    private var bridgeTask: Task<Void, Never>?
    private var shuttingDown = false

    init(
        application: NSApplication = .shared,
        pluginRoot: URL,
        dataDirectory: URL,
        pythonExecutableURL: URL,
        helperIdentity: String,
        helperToken: String,
        configURL: URL
    ) throws {
        self.application = application
        controlClient = ControlClient(
            pluginRoot: pluginRoot,
            dataDirectory: dataDirectory,
            pythonExecutableURL: pythonExecutableURL
        )
        diagnosticsClient = DiagnosticsClient(
            pluginRoot: pluginRoot,
            dataDirectory: dataDirectory,
            pythonExecutableURL: pythonExecutableURL
        )
        speechPlayer = SpeechPlayer()
        bridge = BridgeProcess(
            pluginRoot: pluginRoot,
            dataDirectory: dataDirectory,
            pythonExecutableURL: pythonExecutableURL
        )
        heartbeat = try Heartbeat(
            stateURL: dataDirectory.appendingPathComponent("helper-state.json"),
            identity: helperIdentity,
            token: helperToken
        )
        self.configURL = configURL
        self.pluginRoot = pluginRoot
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        summaryItem = NSMenuItem(title: Self.itemTitles[0], action: #selector(selectSummary), keyEquivalent: "")
        fullItem = NSMenuItem(title: Self.itemTitles[1], action: #selector(selectFull), keyEquivalent: "")
        super.init()

        statusItem.button?.title = "◖))"
        statusItem.button?.toolTip = "Codex Speak"
        let menu = NSMenu()
        let stopItem = NSMenuItem(
            title: Self.itemTitles[2],
            action: #selector(stopCurrentSpeech),
            keyEquivalent: ""
        )
        let clearItem = NSMenuItem(
            title: Self.itemTitles[3],
            action: #selector(clearPendingSpeeches),
            keyEquivalent: ""
        )
        let quitItem = NSMenuItem(
            title: Self.itemTitles[4],
            action: #selector(quit),
            keyEquivalent: ""
        )
        for item in [summaryItem, fullItem, stopItem, clearItem, quitItem] {
            item.target = self
            menu.addItem(item)
        }
        statusItem.menu = menu
        updateCheckmarks()
    }

    func start() throws {
        try heartbeat.write()
        heartbeatTimer = Timer(
            timeInterval: 2,
            target: self,
            selector: #selector(writeHeartbeat),
            userInfo: nil,
            repeats: true
        )
        enablementTimer = Timer(
            timeInterval: 2,
            target: self,
            selector: #selector(checkEnablement),
            userInfo: nil,
            repeats: true
        )
        if let heartbeatTimer { RunLoop.main.add(heartbeatTimer, forMode: .common) }
        if let enablementTimer { RunLoop.main.add(enablementTimer, forMode: .common) }
        refreshMode()
        bridgeTask = Task { [weak self] in
            guard let self else { return }
            do {
                try await bridge.start { [weak self] message in
                    Task { @MainActor [weak self] in self?.handle(message) }
                }
            } catch {
                showLocalError("Speech bridge stopped")
            }
            if !shuttingDown { await orderlyShutdown() }
        }
    }

    @objc private func selectSummary() {
        selectMode(.summary)
    }

    @objc private func selectFull() {
        selectMode(.full)
    }

    private func selectMode(_ requestedMode: SpeechMode) {
        let priorMode = selectedMode
        do {
            try controlClient.setMode(requestedMode)
            selectedMode = try controlClient.getMode()
            updateCheckmarks()
        } catch {
            selectedMode = priorMode
            updateCheckmarks()
            showLocalError("Could not change speech mode")
        }
    }

    private func refreshMode() {
        do {
            selectedMode = try controlClient.getMode()
            updateCheckmarks()
        } catch {
            showLocalError("Could not read speech mode")
        }
    }

    private func updateCheckmarks() {
        summaryItem.state = selectedMode == .summary ? .on : .off
        fullItem.state = selectedMode == .full ? .on : .off
    }

    @objc private func stopCurrentSpeech() {
        Task { await speechPlayer.stopCurrent() }
    }

    @objc private func clearPendingSpeeches() {
        do {
            _ = try controlClient.clearPending()
        } catch {
            showLocalError("Could not clear pending speeches")
        }
    }

    @objc private func quit() {
        Task { await orderlyShutdown() }
    }

    @objc private func writeHeartbeat() {
        if shouldTerminateHelper(pluginRootURL: pluginRoot, configURL: configURL) {
            Task { await orderlyShutdown() }
            return
        }
        do {
            try heartbeat.write()
        } catch {
            showLocalError("Heartbeat unavailable")
            Task { await orderlyShutdown() }
        }
    }

    @objc private func checkEnablement() {
        if shouldTerminateHelper(pluginRootURL: pluginRoot, configURL: configURL) {
            Task { await orderlyShutdown() }
        }
    }

    private func handle(_ message: BridgeMessage) {
        guard case let .event(event) = message else { return }
        Task {
            let result = await speechPlayer.play(event: event)
            do {
                try diagnosticsClient.record(event: event, result: result)
            } catch {
                showLocalError("Could not record playback result")
            }
        }
    }

    private func orderlyShutdown() async {
        guard !shuttingDown else { return }
        shuttingDown = true
        heartbeatTimer?.invalidate()
        enablementTimer?.invalidate()
        errorTimer?.invalidate()
        await speechPlayer.stopCurrent()
        await bridge.stop()
        heartbeat.remove()
        application.terminate(nil)
    }

    private func showLocalError(_ message: String) {
        statusItem.button?.title = "!"
        statusItem.button?.toolTip = message
        errorTimer?.invalidate()
        errorTimer = Timer(
            timeInterval: 2,
            target: self,
            selector: #selector(clearLocalError),
            userInfo: nil,
            repeats: false
        )
        if let errorTimer { RunLoop.main.add(errorTimer, forMode: .common) }
    }

    @objc private func clearLocalError() {
        statusItem.button?.title = "◖))"
        statusItem.button?.toolTip = "Codex Speak"
        errorTimer = nil
    }
}
