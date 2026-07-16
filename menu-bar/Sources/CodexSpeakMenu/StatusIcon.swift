import AppKit
import CodexSpeakCore

@MainActor
enum StatusIcon {
    static func makeTemplateImage() -> NSImage {
        let pointSize = CGFloat(CodexSpeakIconGeometry.templatePointSize)
        let image = NSImage(
            size: NSSize(width: pointSize, height: pointSize),
            flipped: false
        ) { [pointSize] _ in
            StatusIcon.drawTemplate(pointSize: pointSize)
        }
        image.isTemplate = true
        image.accessibilityDescription = "Codex Speak"
        return image
    }

    nonisolated private static func drawTemplate(pointSize: CGFloat) -> Bool {
        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }

        let scale = pointSize / CGFloat(CodexSpeakIconGeometry.canvasSize)
        let transform = NSAffineTransform()
        transform.scaleX(by: scale, yBy: scale)
        transform.concat()

        NSColor.black.setFill()
        speakerPath().fill()

        NSGraphicsContext.current?.compositingOperation = .clear
        NSColor.clear.setStroke()
        let chevron = NSBezierPath()
        let points = CodexSpeakIconGeometry.chevronCutout
        chevron.move(to: nsPoint(points[0]))
        chevron.line(to: nsPoint(points[1]))
        chevron.line(to: nsPoint(points[2]))
        chevron.lineWidth = CGFloat(CodexSpeakIconGeometry.chevronLineWidth)
        chevron.lineCapStyle = .round
        chevron.lineJoinStyle = .round
        chevron.stroke()

        NSColor.clear.setFill()
        let cursor = CodexSpeakIconGeometry.cursorCutout
        NSBezierPath(
            roundedRect: NSRect(
                x: CGFloat(cursor.x),
                y: CGFloat(cursor.y),
                width: CGFloat(cursor.width),
                height: CGFloat(cursor.height)
            ),
            xRadius: CGFloat(CodexSpeakIconGeometry.cursorCornerRadius),
            yRadius: CGFloat(CodexSpeakIconGeometry.cursorCornerRadius)
        ).fill()
        return true
    }

    nonisolated private static func speakerPath() -> NSBezierPath {
        let path = NSBezierPath()
        for command in CodexSpeakIconGeometry.speakerContainer {
            switch command {
            case let .move(point):
                path.move(to: nsPoint(point))
            case let .line(point):
                path.line(to: nsPoint(point))
            case let .cubic(control1, control2, point):
                path.curve(
                    to: nsPoint(point),
                    controlPoint1: nsPoint(control1),
                    controlPoint2: nsPoint(control2)
                )
            case .close:
                path.close()
            }
        }
        return path
    }

    nonisolated private static func nsPoint(_ point: IconPoint) -> NSPoint {
        NSPoint(x: CGFloat(point.x), y: CGFloat(point.y))
    }
}
