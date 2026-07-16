#!/usr/bin/env swift
import AppKit
import Foundation

enum IconRenderError: Error {
    case sourceUnavailable(URL)
    case gradientUnavailable
    case bitmapUnavailable(Int)
    case graphicsContextUnavailable(Int)
    case pngUnavailable(Int)
    case iconutilFailed(Int32)
}

let fileManager = FileManager.default
let root = URL(
    fileURLWithPath: fileManager.currentDirectoryPath,
    isDirectory: true
)
let sourceURL = root.appendingPathComponent("artwork/codex-speak-app-icon.svg")
let githubURL = root.appendingPathComponent("assets/codex-speak-github.png")
let iconsetURL = root.appendingPathComponent(".build/CodexSpeak.iconset", isDirectory: true)
let icnsURL = root.appendingPathComponent("menu-bar/Resources/AppIcon.icns")

guard fileManager.fileExists(atPath: sourceURL.path) else {
    throw IconRenderError.sourceUnavailable(sourceURL)
}

let masterSize = CGFloat(1024)
let markOrigin = CGFloat(176)
let markScale = CGFloat(28)
let gradientOptions: NSGradient.DrawingOptions = [
    .drawsBeforeStartingLocation,
    .drawsAfterEndingLocation,
]

func color(_ red: Int, _ green: Int, _ blue: Int) -> NSColor {
    NSColor(
        srgbRed: CGFloat(red) / 255,
        green: CGFloat(green) / 255,
        blue: CGFloat(blue) / 255,
        alpha: 1
    )
}

guard
    let backgroundGradient = NSGradient(
        starting: color(0x26, 0x36, 0xA7),
        ending: color(0x6D, 0x28, 0xD9)
    ),
    let containerGradient = NSGradient(
        starting: color(0xFF, 0xFF, 0xFF),
        ending: color(0xC7, 0xF2, 0xFF)
    )
else {
    throw IconRenderError.gradientUnavailable
}

func markPoint(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
    CGPoint(x: markOrigin + markScale * x, y: markOrigin + markScale * y)
}

func speakerPath() -> CGPath {
    let path = CGMutablePath()
    path.move(to: markPoint(5.5, 5))
    path.addCurve(
        to: markPoint(3.5, 7),
        control1: markPoint(4.4, 5),
        control2: markPoint(3.5, 5.9)
    )
    path.addLine(to: markPoint(3.5, 17))
    path.addCurve(
        to: markPoint(5.5, 19),
        control1: markPoint(3.5, 18.1),
        control2: markPoint(4.4, 19)
    )
    path.addLine(to: markPoint(10, 19))
    path.addLine(to: markPoint(18.7, 21.5))
    path.addCurve(
        to: markPoint(20.4, 20.2),
        control1: markPoint(19.55, 21.75),
        control2: markPoint(20.4, 21.1)
    )
    path.addLine(to: markPoint(20.4, 3.8))
    path.addCurve(
        to: markPoint(18.7, 2.5),
        control1: markPoint(20.4, 2.9),
        control2: markPoint(19.55, 2.25)
    )
    path.addLine(to: markPoint(10, 5))
    path.closeSubpath()
    return path
}

func draw(
    _ gradient: NSGradient,
    from start: CGPoint,
    to end: CGPoint,
    clippedTo path: CGPath,
    in context: NSGraphicsContext
) {
    context.cgContext.saveGState()
    context.cgContext.addPath(path)
    context.cgContext.clip()
    gradient.draw(from: start, to: end, options: gradientOptions)
    context.cgContext.restoreGState()
}

func drawArtwork(in context: NSGraphicsContext) {
    let backgroundPath = CGPath(
        roundedRect: CGRect(x: 32, y: 32, width: 960, height: 960),
        cornerWidth: 224,
        cornerHeight: 224,
        transform: nil
    )
    let backgroundStart = CGPoint(x: 96, y: 944)
    let backgroundEnd = CGPoint(x: 928, y: 80)
    draw(
        backgroundGradient,
        from: backgroundStart,
        to: backgroundEnd,
        clippedTo: backgroundPath,
        in: context
    )

    draw(
        containerGradient,
        from: markPoint(4, 19),
        to: markPoint(20, 4),
        clippedTo: speakerPath(),
        in: context
    )

    let chevron = CGMutablePath()
    chevron.move(to: markPoint(6.4, 14.6))
    chevron.addLine(to: markPoint(9.5, 12))
    chevron.addLine(to: markPoint(6.4, 9.4))

    context.cgContext.saveGState()
    context.cgContext.addPath(chevron)
    context.cgContext.setLineWidth(markScale * 1.8)
    context.cgContext.setLineCap(.round)
    context.cgContext.setLineJoin(.round)
    context.cgContext.replacePathWithStrokedPath()
    context.cgContext.addPath(
        CGPath(
            roundedRect: CGRect(
                x: markOrigin + markScale * 10.8,
                y: markOrigin + markScale * 8.6,
                width: markScale * 4,
                height: markScale * 1.6
            ),
            cornerWidth: markScale * 0.8,
            cornerHeight: markScale * 0.8,
            transform: nil
        )
    )
    context.cgContext.clip()
    backgroundGradient.draw(
        from: backgroundStart,
        to: backgroundEnd,
        options: gradientOptions
    )
    context.cgContext.restoreGState()
}

func render(pixels: Int, to outputURL: URL) throws {
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
    ) else {
        throw IconRenderError.bitmapUnavailable(pixels)
    }
    bitmap.size = NSSize(width: pixels, height: pixels)
    guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        throw IconRenderError.graphicsContextUnavailable(pixels)
    }

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    context.shouldAntialias = true
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: pixels, height: pixels).fill()
    let outputScale = CGFloat(pixels) / masterSize
    context.cgContext.scaleBy(x: outputScale, y: outputScale)
    drawArtwork(in: context)
    NSGraphicsContext.restoreGraphicsState()

    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw IconRenderError.pngUnavailable(pixels)
    }
    try fileManager.createDirectory(
        at: outputURL.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try data.write(to: outputURL, options: .atomic)
}

try? fileManager.removeItem(at: iconsetURL)
try fileManager.createDirectory(at: iconsetURL, withIntermediateDirectories: true)
try fileManager.createDirectory(
    at: icnsURL.deletingLastPathComponent(),
    withIntermediateDirectories: true
)

let iconsetExports = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]
for (pixels, filename) in iconsetExports {
    try render(pixels: pixels, to: iconsetURL.appendingPathComponent(filename))
}
try render(pixels: 1024, to: githubURL)

let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["-c", "icns", iconsetURL.path, "-o", icnsURL.path]
try iconutil.run()
iconutil.waitUntilExit()
guard iconutil.terminationStatus == 0 else {
    throw IconRenderError.iconutilFailed(iconutil.terminationStatus)
}
