public struct IconPoint: Equatable, Sendable {
    public let x: Double
    public let y: Double

    public init(x: Double, y: Double) {
        self.x = x
        self.y = y
    }
}

public struct IconRect: Equatable, Sendable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double

    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }
}

public enum IconPathCommand: Equatable, Sendable {
    case move(IconPoint)
    case line(IconPoint)
    case cubic(control1: IconPoint, control2: IconPoint, to: IconPoint)
    case close
}

public enum CodexSpeakIconGeometry {
    public static let canvasSize = 24.0
    public static let templatePointSize = 18.0

    public static let speakerContainer: [IconPathCommand] = [
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

    public static let chevronCutout = [
        IconPoint(x: 6.4, y: 14.6),
        IconPoint(x: 9.5, y: 12),
        IconPoint(x: 6.4, y: 9.4),
    ]
    public static let chevronLineWidth = 1.8
    public static let cursorCutout = IconRect(x: 10.8, y: 8.6, width: 4, height: 1.6)
    public static let cursorCornerRadius = 0.8
}
