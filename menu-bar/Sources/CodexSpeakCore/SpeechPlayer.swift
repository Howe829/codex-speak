import Foundation

public actor SpeechPlayer {
    private let launcher: any ProcessLaunching
    private let sayExecutableURL: URL
    private let clock: @Sendable () -> UInt64
    private var activePlaybackID: UUID?
    private var activeProcess: (id: UUID, process: any ManagedProcess)?
    private var cancellationRequested = false

    public init() {
        launcher = FoundationProcessLauncher()
        sayExecutableURL = URL(fileURLWithPath: "/usr/bin/say")
        clock = { DispatchTime.now().uptimeNanoseconds }
    }

    init(
        launcher: any ProcessLaunching,
        sayExecutableURL: URL = URL(fileURLWithPath: "/usr/bin/say"),
        clock: @escaping @Sendable () -> UInt64
    ) {
        self.launcher = launcher
        self.sayExecutableURL = sayExecutableURL
        self.clock = clock
    }

    public func play(event: SpeechEvent) async -> PlaybackResult {
        let started = clock()
        guard activePlaybackID == nil else {
            return result(.failed, .speechStartFailed, 0, since: started)
        }
        let playbackID = UUID()
        activePlaybackID = playbackID
        cancellationRequested = false
        var completed = 0
        var outcome = PlaybackOutcome.spoken
        var errorCode: PlaybackErrorCode?

        for segment in event.segments {
            if cancellationRequested { break }
            let standardInput = Pipe()
            let request = ProcessLaunchRequest(
                executableURL: sayExecutableURL,
                arguments: [],
                currentDirectoryURL: URL(fileURLWithPath: "/"),
                standardInput: standardInput,
                standardOutput: Pipe(),
                standardError: Pipe()
            )
            let process: any ManagedProcess
            do {
                process = try launcher.launch(request)
            } catch {
                outcome = .failed
                errorCode = .speechStartFailed
                break
            }
            let processID = UUID()
            activeProcess = (processID, process)
            do {
                try standardInput.fileHandleForWriting.write(contentsOf: Data(segment.utf8))
                try standardInput.fileHandleForWriting.close()
            } catch {
                process.terminate()
                _ = await process.waitUntilExit()
                if activeProcess?.id == processID { activeProcess = nil }
                outcome = .failed
                errorCode = .sayFailed
                break
            }
            let status = await process.waitUntilExit()
            if activeProcess?.id == processID { activeProcess = nil }
            if cancellationRequested {
                outcome = .cancelled
                errorCode = nil
                break
            }
            guard status == 0 else {
                outcome = .failed
                errorCode = .sayFailed
                break
            }
            completed += 1
        }

        if cancellationRequested {
            outcome = .cancelled
            errorCode = nil
        }
        if activePlaybackID == playbackID { activePlaybackID = nil }
        activeProcess = nil
        return result(outcome, errorCode, completed, since: started)
    }

    public func stopCurrent() {
        guard activePlaybackID != nil else { return }
        cancellationRequested = true
        activeProcess?.process.terminate()
    }

    private func result(
        _ outcome: PlaybackOutcome,
        _ errorCode: PlaybackErrorCode?,
        _ completed: Int,
        since started: UInt64
    ) -> PlaybackResult {
        let ended = clock()
        let elapsed = ended >= started ? ended - started : 0
        return PlaybackResult(
            outcome: outcome,
            errorCode: errorCode,
            completedSegmentCount: completed,
            durationMilliseconds: Int(elapsed / 1_000_000)
        )
    }
}
