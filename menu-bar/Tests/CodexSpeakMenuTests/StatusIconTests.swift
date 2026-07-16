@preconcurrency import AppKit
import Dispatch
import XCTest
@testable import CodexSpeakMenu

final class StatusIconTests: XCTestCase {
    @MainActor
    func testTemplateImageDrawsNonemptyPixelsOffMain() {
        let image = StatusIcon.makeTemplateImage()
        let imageBox = UncheckedSendableBox(image)
        let result = LockedRenderResult()
        let finished = expectation(description: "off-main template render")
        let finishedBox = UncheckedSendableBox(finished)

        DispatchQueue.global(qos: .userInitiated).async {
            result.store(Self.drawsNonemptyPixels(imageBox.value))
            finishedBox.value.fulfill()
        }

        wait(for: [finished], timeout: 5)
        XCTAssertTrue(result.value)
    }

    private nonisolated static func drawsNonemptyPixels(_ image: NSImage) -> Bool {
        guard let bitmap = NSBitmapImageRep(
            bitmapDataPlanes: nil,
            pixelsWide: 36,
            pixelsHigh: 36,
            bitsPerSample: 8,
            samplesPerPixel: 4,
            hasAlpha: true,
            isPlanar: false,
            colorSpaceName: .deviceRGB,
            bytesPerRow: 0,
            bitsPerPixel: 0
        ), let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
            return false
        }

        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }
        NSGraphicsContext.current = context
        NSColor.clear.setFill()
        NSRect(x: 0, y: 0, width: 36, height: 36).fill()
        image.draw(
            in: NSRect(x: 0, y: 0, width: 36, height: 36),
            from: .zero,
            operation: .sourceOver,
            fraction: 1
        )
        context.flushGraphics()

        guard let bytes = bitmap.bitmapData else { return false }
        let byteCount = bitmap.bytesPerRow * bitmap.pixelsHigh
        return (0 ..< byteCount).contains { bytes[$0] != 0 }
    }
}

private final class UncheckedSendableBox<Value>: @unchecked Sendable {
    let value: Value

    init(_ value: Value) {
        self.value = value
    }
}

private final class LockedRenderResult: @unchecked Sendable {
    private let lock = NSLock()
    private var storedValue = false

    var value: Bool {
        lock.withLock { storedValue }
    }

    func store(_ value: Bool) {
        lock.withLock { storedValue = value }
    }
}
