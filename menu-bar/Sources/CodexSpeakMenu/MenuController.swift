@preconcurrency import AppKit
import CodexSpeakCore
import Foundation

@MainActor
final class MenuController: NSObject, NSMenuDelegate {
    static let itemTitles = codexSpeakMenuItemTitles

    private let application: NSApplication
    private let statusItem: NSStatusItem
    private let controlClient: any ControlClientProtocol
    private let diagnosticsClient: DiagnosticsClient
    private let speechPlayer: SpeechPlayer
    private let coordinator: SpeechCoordinator
    private let bridge: BridgeProcess
    private let heartbeat: Heartbeat
    private let configURL: URL
    private let pluginRoot: URL
    private let silentItem: NSMenuItem
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
        let controlClient = ControlClient(
            pluginRoot: pluginRoot,
            dataDirectory: dataDirectory,
            pythonExecutableURL: pythonExecutableURL
        )
        self.controlClient = controlClient
        let diagnosticsClient = DiagnosticsClient(
            pluginRoot: pluginRoot,
            dataDirectory: dataDirectory,
            pythonExecutableURL: pythonExecutableURL
        )
        self.diagnosticsClient = diagnosticsClient
        let speechPlayer = SpeechPlayer()
        self.speechPlayer = speechPlayer
        coordinator = SpeechCoordinator(
            controlClient: controlClient,
            speechPlayer: speechPlayer,
            diagnosticsClient: diagnosticsClient
        )
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
        silentItem = NSMenuItem(title: Self.itemTitles[0], action: #selector(selectSilent), keyEquivalent: "")
        summaryItem = NSMenuItem(title: Self.itemTitles[1], action: #selector(selectSummary), keyEquivalent: "")
        fullItem = NSMenuItem(title: Self.itemTitles[2], action: #selector(selectFull), keyEquivalent: "")
        super.init()

        applyDefaultStatusIcon()
        let menu = NSMenu()
        let stopItem = NSMenuItem(
            title: Self.itemTitles[3],
            action: #selector(stopCurrentSpeech),
            keyEquivalent: ""
        )
        let clearItem = NSMenuItem(
            title: Self.itemTitles[4],
            action: #selector(clearPendingSpeeches),
            keyEquivalent: ""
        )
        let quitItem = NSMenuItem(
            title: Self.itemTitles[5],
            action: #selector(quit),
            keyEquivalent: ""
        )
        for item in [silentItem, summaryItem, fullItem, stopItem, clearItem, quitItem] {
            item.target = self
            menu.addItem(item)
        }
        menu.delegate = self
        statusItem.menu = menu
        updateCheckmarks()
    }

    func menuWillOpen(_ menu: NSMenu) {
        refreshMode()
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
        bridgeTask = Task { [weak self] in
            guard let self else { return }
            await refreshCoordinatorMode()
            do {
                try await bridge.start { [weak self] message in
                    await self?.handle(message)
                }
            } catch {
                showLocalError("Speech bridge stopped")
            }
            if !shuttingDown { await orderlyShutdown() }
        }
    }

    @objc private func selectSilent() {
        selectMode(.silent)
    }

    @objc private func selectSummary() {
        selectMode(.summary)
    }

    @objc private func selectFull() {
        selectMode(.full)
    }

    private func selectMode(_ requestedMode: SpeechMode) {
        Task { [weak self] in
            guard let self else { return }
            let result = await coordinator.selectMode(requestedMode)
            selectedMode = await coordinator.selectedMode
            updateCheckmarks()
            switch result {
            case .applied:
                break
            case .appliedWithQueueClearFailure:
                showLocalError("Could not clear pending speeches")
            case .writeFailed:
                showLocalError("Could not change speech mode")
            case .readFailed, .readFailedFailSafe:
                showLocalError("Could not read speech mode")
            }
        }
    }

    private func refreshMode() {
        Task { [weak self] in
            await self?.refreshCoordinatorMode()
        }
    }

    private func refreshCoordinatorMode() async {
        do {
            let result = try await coordinator.refreshForStartup()
            selectedMode = await coordinator.selectedMode
            updateCheckmarks()
            if case .readyWithQueueClearFailure = result {
                showLocalError("Could not clear pending speeches")
            }
        } catch {
            showLocalError("Could not read speech mode")
        }
    }

    private func updateCheckmarks() {
        silentItem.state = selectedMode == .silent ? .on : .off
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
            try? diagnosticsClient.recordControlFailure(.queueClearFailed)
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

    private func handle(_ message: BridgeMessage) async {
        guard case let .event(event) = message else { return }
        do {
            try await coordinator.handle(event: event)
        } catch {
            showLocalError("Could not record playback result")
        }
        selectedMode = await coordinator.selectedMode
        updateCheckmarks()
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

    private func applyDefaultStatusIcon() {
        statusItem.button?.title = ""
        statusItem.button?.image = StatusIcon.makeTemplateImage()
        statusItem.button?.imagePosition = .imageOnly
        statusItem.button?.toolTip = "Codex Speak"
    }

    private func showLocalError(_ message: String) {
        applyDefaultStatusIcon()
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
        applyDefaultStatusIcon()
        errorTimer = nil
    }
}
