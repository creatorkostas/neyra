// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "NeyraMeetingModels",
    platforms: [.macOS(.v15)],
    products: [.executable(name: "neyra-meeting-models", targets: ["MeetingModels"])],
    dependencies: [
        .package(url: "https://github.com/Desert-Ant-Labs/desert-ant-core.git",
                 revision: "9ac125cc4b10696a7ae1d18723fb585b8c025ee1")
    ],
    targets: [
        .target(name: "MeetingProtocol"),
        .executableTarget(name: "MeetingModels", dependencies: ["MeetingProtocol"] +
            ["Align", "Who", "Clear", "Gist", "AudioIO"].map {
                .product(name: $0, package: "desert-ant-core")
            }),
        .testTarget(name: "MeetingProtocolTests", dependencies: ["MeetingProtocol"])
    ]
)
