@preconcurrency import AppKit
import Dispatch
import XCTest
@testable import CodexSpeakMenu

final class StatusIconTests: XCTestCase {
    @MainActor
    func testTemplateImagePreservesPromptCutoutsWhenDrawnOffMainAtSixteenPixels() {
        let image = StatusIcon.makeTemplateImage()
        XCTAssertTrue(image.isTemplate)
        XCTAssertEqual(image.size, NSSize(width: 18, height: 18))
        XCTAssertEqual(image.accessibilityDescription, "Codex Speak")

        let imageBox = UncheckedSendableBox(image)
        let result = LockedRenderResult()
        let finished = expectation(description: "off-main template render")
        let finishedBox = UncheckedSendableBox(finished)

        DispatchQueue.global(qos: .userInitiated).async {
            result.store(Self.renderEvidence(imageBox.value))
            finishedBox.value.fulfill()
        }

        wait(for: [finished], timeout: 5)
        guard let evidence = result.value else {
            XCTFail("could not render StatusIcon into a 16 px bitmap")
            return
        }
        XCTAssertGreaterThan(evidence.nontransparentPixels, 20, evidence.description)
        XCTAssertLessThan(evidence.canvasAlpha, 0.05, evidence.description)
        XCTAssertGreaterThan(evidence.leftSpeakerAlpha, 0.9, evidence.description)
        XCTAssertGreaterThan(evidence.rightSpeakerAlpha, 0.9, evidence.description)
        XCTAssertLessThan(evidence.chevronUpperAlpha, 0.25, evidence.description)
        XCTAssertLessThan(evidence.chevronLowerAlpha, 0.25, evidence.description)
        XCTAssertLessThan(evidence.cursorAlpha, 0.25, evidence.description)
        XCTAssertGreaterThan(evidence.promptSeparationAlpha, 0.75, evidence.description)
    }

    private nonisolated static func renderEvidence(
        _ image: NSImage
    ) -> StatusIconRenderEvidence? {
        let pixels = 16
        guard let bitmap = NSBitmapImageRep(
            bitmapDataPlanes: nil,
            pixelsWide: pixels,
            pixelsHigh: pixels,
            bitsPerSample: 8,
            samplesPerPixel: 4,
            hasAlpha: true,
            isPlanar: false,
            colorSpaceName: .deviceRGB,
            bytesPerRow: 0,
            bitsPerPixel: 0
        ), let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
            return nil
        }

        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }
        NSGraphicsContext.current = context
        bitmap.size = NSSize(width: pixels, height: pixels)
        NSColor.clear.setFill()
        NSRect(x: 0, y: 0, width: pixels, height: pixels).fill()
        image.draw(
            in: NSRect(x: 0, y: 0, width: pixels, height: pixels),
            from: .zero,
            operation: .sourceOver,
            fraction: 1
        )
        context.flushGraphics()

        func alpha(x: Int, y: Int) -> CGFloat? {
            bitmap.colorAt(x: x, y: y)?.alphaComponent
        }
        guard
            let canvasAlpha = alpha(x: 0, y: 0),
            let leftSpeakerAlpha = alpha(x: 3, y: 8),
            let rightSpeakerAlpha = alpha(x: 11, y: 8),
            let chevronUpperAlpha = alpha(x: 4, y: 9),
            let chevronLowerAlpha = alpha(x: 4, y: 6),
            let cursorAlpha = alpha(x: 8, y: 9),
            let promptSeparationAlpha = alpha(x: 6, y: 9)
        else {
            return nil
        }
        let nontransparentPixels = (0 ..< pixels).reduce(into: 0) { count, y in
            for x in 0 ..< pixels where (alpha(x: x, y: y) ?? 0) > 0.05 {
                count += 1
            }
        }
        let alphaMap = (0 ..< pixels).reversed().map { y in
            (0 ..< pixels).map { x in
                switch alpha(x: x, y: y) ?? 0 {
                case ..<0.1: " "
                case ..<0.5: "."
                case ..<0.9: "+"
                default: "#"
                }
            }.joined()
        }.joined(separator: "|")
        return StatusIconRenderEvidence(
            nontransparentPixels: nontransparentPixels,
            canvasAlpha: canvasAlpha,
            leftSpeakerAlpha: leftSpeakerAlpha,
            rightSpeakerAlpha: rightSpeakerAlpha,
            chevronUpperAlpha: chevronUpperAlpha,
            chevronLowerAlpha: chevronLowerAlpha,
            cursorAlpha: cursorAlpha,
            promptSeparationAlpha: promptSeparationAlpha,
            alphaMap: alphaMap
        )
    }
}

private struct StatusIconRenderEvidence: Sendable, CustomStringConvertible {
    let nontransparentPixels: Int
    let canvasAlpha: CGFloat
    let leftSpeakerAlpha: CGFloat
    let rightSpeakerAlpha: CGFloat
    let chevronUpperAlpha: CGFloat
    let chevronLowerAlpha: CGFloat
    let cursorAlpha: CGFloat
    let promptSeparationAlpha: CGFloat
    let alphaMap: String

    var description: String {
        "pixels=\(nontransparentPixels) "
            + "canvas=\(canvasAlpha) "
            + "speaker=(\(leftSpeakerAlpha), \(rightSpeakerAlpha)) "
            + "chevron=(\(chevronUpperAlpha), \(chevronLowerAlpha)) "
            + "cursor=\(cursorAlpha) separation=\(promptSeparationAlpha) "
            + "map=\(alphaMap)"
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
    private var storedValue: StatusIconRenderEvidence?

    var value: StatusIconRenderEvidence? {
        lock.withLock { storedValue }
    }

    func store(_ value: StatusIconRenderEvidence?) {
        lock.withLock { storedValue = value }
    }
}
