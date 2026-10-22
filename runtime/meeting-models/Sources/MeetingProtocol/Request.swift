import Foundation

public struct BridgeError: LocalizedError {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

public struct InputWord: Decodable, Sendable {
    public let text: String
    public let start: Double
    public let end: Double
}

public struct Request: Decodable, Sendable {
    public let operation: String
    public let path: String?
    public let output_path: String?
    public let words: [InputWord]?
    public let speakers: Bool?
    public let organize: Bool?
    public let language: String?

    public static let maxBytes = 16 * 1024 * 1024
    public static let languages = ["en", "es", "fr", "it", "pt", "de", "ja", "ko", "zh"]

    public static func parse(_ data: Data) throws -> Request {
        guard data.count <= maxBytes else { throw BridgeError("Request exceeds 16 MiB.") }
        let request = try JSONDecoder().decode(Request.self, from: data)
        guard ["check", "enhance", "analyze"].contains(request.operation) else {
            throw BridgeError("Unknown operation. Use check, enhance or analyze.")
        }
        guard request.operation != "check" else { return request }
        guard let path = request.path, !path.isEmpty, path.utf8.count <= 32_768 else {
            throw BridgeError("A valid WAV path is required.")
        }
        guard request.language == nil || languages.contains(request.language!) else {
            throw BridgeError("Align supports en, es, fr, it, pt, de, ja, ko and zh.")
        }
        if request.operation == "enhance" {
            guard let output = request.output_path, !output.isEmpty,
                  output.utf8.count <= 32_768,
                  URL(fileURLWithPath: path).standardizedFileURL != URL(fileURLWithPath: output).standardizedFileURL else {
                throw BridgeError("A distinct output_path is required.")
            }
        } else {
            guard let words = request.words, !words.isEmpty, words.count <= 200_000 else {
                throw BridgeError("analyze requires 1 to 200000 transcript words.")
            }
            for word in words {
                guard !word.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                      word.text.utf8.count <= 4096, word.start.isFinite, word.end.isFinite,
                      word.start >= 0, word.end >= word.start, word.end <= 10_000_000 else {
                    throw BridgeError("Invalid word text or timestamps.")
                }
            }
        }
        return request
    }
}

// Read only one bounded JSON line. EOF without a newline is also accepted.
public func readRequest(_ handle: FileHandle) throws -> Data {
    var data = Data()
    while let chunk = try handle.read(upToCount: 4096), !chunk.isEmpty {
        let line = chunk.prefix { $0 != 10 }
        guard data.count + line.count <= Request.maxBytes else {
            throw BridgeError("Request exceeds 16 MiB.")
        }
        data.append(contentsOf: line)
        if line.count != chunk.count { break }
    }
    guard !data.isEmpty else { throw BridgeError("Expected a JSON request on stdin.") }
    return data
}
