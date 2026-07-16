#!/usr/bin/env swift
import AppKit
import Foundation

enum IconRenderError: Error {
    case sourceUnavailable(URL)
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

guard let source = NSImage(contentsOf: sourceURL) else {
    throw IconRenderError.sourceUnavailable(sourceURL)
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
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: pixels, height: pixels).fill()
    source.draw(
        in: NSRect(x: 0, y: 0, width: pixels, height: pixels),
        from: .zero,
        operation: .copy,
        fraction: 1
    )
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
