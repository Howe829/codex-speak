// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "CodexSpeakMenu",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "CodexSpeakCore", targets: ["CodexSpeakCore"]),
        .executable(name: "CodexSpeakMenu", targets: ["CodexSpeakMenu"]),
    ],
    targets: [
        .target(name: "CodexSpeakCore"),
        .executableTarget(name: "CodexSpeakMenu", dependencies: ["CodexSpeakCore"]),
        .testTarget(name: "CodexSpeakCoreTests", dependencies: ["CodexSpeakCore"]),
        .testTarget(name: "CodexSpeakMenuTests", dependencies: ["CodexSpeakMenu"]),
    ]
)
