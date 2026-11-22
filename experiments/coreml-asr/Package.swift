// swift-tools-version: 5.10
import PackageDescription
let package = Package(
    name: "PaprikaCoreMLASR",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "paprika-coreml-asr", targets: ["PaprikaCoreMLASR"])],
    dependencies: [.package(path: "../../.tavi/vendor/argmax-oss-swift")],
    targets: [.executableTarget(name: "PaprikaCoreMLASR", dependencies: [
        .product(name: "WhisperKit", package: "argmax-oss-swift")])]
)
