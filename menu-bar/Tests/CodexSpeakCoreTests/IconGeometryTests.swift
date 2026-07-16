import XCTest
@testable import CodexSpeakCore

final class IconGeometryTests: XCTestCase {
    func testSpeakerContainerIsTheExactSingleClosedPath() {
        XCTAssertEqual(
            CodexSpeakIconGeometry.speakerContainer,
            [
                .move(IconPoint(x: 5.5, y: 5)),
                .cubic(
                    control1: IconPoint(x: 4.4, y: 5),
                    control2: IconPoint(x: 3.5, y: 5.9),
                    to: IconPoint(x: 3.5, y: 7)
                ),
                .line(IconPoint(x: 3.5, y: 17)),
                .cubic(
                    control1: IconPoint(x: 3.5, y: 18.1),
                    control2: IconPoint(x: 4.4, y: 19),
                    to: IconPoint(x: 5.5, y: 19)
                ),
                .line(IconPoint(x: 10, y: 19)),
                .line(IconPoint(x: 18.7, y: 21.5)),
                .cubic(
                    control1: IconPoint(x: 19.55, y: 21.75),
                    control2: IconPoint(x: 20.4, y: 21.1),
                    to: IconPoint(x: 20.4, y: 20.2)
                ),
                .line(IconPoint(x: 20.4, y: 3.8)),
                .cubic(
                    control1: IconPoint(x: 20.4, y: 2.9),
                    control2: IconPoint(x: 19.55, y: 2.25),
                    to: IconPoint(x: 18.7, y: 2.5)
                ),
                .line(IconPoint(x: 10, y: 5)),
                .close,
            ]
        )
        XCTAssertEqual(
            CodexSpeakIconGeometry.speakerContainer.filter { $0 == .close }.count,
            1
        )
    }

    func testPromptUsesSeparateChevronAndCursorCutouts() {
        XCTAssertEqual(
            CodexSpeakIconGeometry.chevronCutout,
            [
                IconPoint(x: 6.4, y: 14.6),
                IconPoint(x: 9.5, y: 12),
                IconPoint(x: 6.4, y: 9.4),
            ]
        )
        XCTAssertEqual(CodexSpeakIconGeometry.chevronLineWidth, 1.8)
        XCTAssertEqual(
            CodexSpeakIconGeometry.cursorCutout,
            IconRect(x: 10.8, y: 8.6, width: 4, height: 1.6)
        )
        XCTAssertEqual(CodexSpeakIconGeometry.cursorCornerRadius, 0.8)
        XCTAssertGreaterThan(
            CodexSpeakIconGeometry.cursorCutout.x,
            CodexSpeakIconGeometry.chevronCutout.map(\.x).max()!
        )
    }

    func testExactPromptRemainsDistinctAtSixteenPixels() {
        let scale = 16.0 / CodexSpeakIconGeometry.canvasSize
        let stroke = CodexSpeakIconGeometry.chevronLineWidth * scale
        let cursorWidth = CodexSpeakIconGeometry.cursorCutout.width * scale
        let cursorHeight = CodexSpeakIconGeometry.cursorCutout.height * scale
        let gap = (
            CodexSpeakIconGeometry.cursorCutout.x
                - CodexSpeakIconGeometry.chevronCutout[1].x
        ) * scale

        XCTAssertEqual(stroke, 1.2, accuracy: 0.001)
        XCTAssertEqual(cursorWidth, 2.666_667, accuracy: 0.001)
        XCTAssertEqual(cursorHeight, 1.066_667, accuracy: 0.001)
        XCTAssertEqual(gap, 0.866_667, accuracy: 0.001)
        XCTAssertGreaterThanOrEqual(stroke, 1.19)
        XCTAssertGreaterThanOrEqual(cursorHeight, 1.06)
        XCTAssertGreaterThanOrEqual(gap, 0.86)
    }
}
