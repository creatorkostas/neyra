import Foundation
import Align
import AudioIO
import Clear
import Gist
import Who
import MeetingProtocol
#if os(Windows)
import CRT
#elseif canImport(Darwin)
import Darwin
#else
import Glibc
#endif

final class Events: @unchecked Sendable {
    private let lock = NSLock()
    private let output: FileHandle
    private let id: Any?

    init(output: FileHandle, id: Any?) { self.output = output; self.id = id }

    func emit(_ fields: [String: Any]) {
        lock.lock()
        defer { lock.unlock() }
        var fields = fields
        if let id { fields["id"] = id }
        do {
            var data = try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
            data.append(10)
            try output.write(contentsOf: data)
        } catch {
            FileHandle.standardError.write(Data("Could not write bridge event: \(error)\n".utf8))
        }
    }

    func progress(_ message: String) { emit(["event": "progress", "message": message]) }
}

@main
struct MeetingModels {
    static func main() async {
        // Reserve stdout for JSON even if a native runtime writes diagnostics.
        #if os(Windows)
        let descriptor = _dup(1)
        _ = _dup2(2, 1)
        #else
        let descriptor = dup(STDOUT_FILENO)
        _ = dup2(STDERR_FILENO, STDOUT_FILENO)
        #endif
        guard descriptor >= 0 else { exit(1) }
        let output = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        var events = Events(output: output, id: nil)
        do {
            let data = try readRequest(.standardInput)
            let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            if let id = object?["id"] {
                guard id is String || id is NSNumber || id is NSNull else {
                    throw BridgeError("id must be a string, number or null.")
                }
                events = Events(output: output, id: id)
            }
            let request = try Request.parse(data)
            if request.operation == "check" {
                events.emit(["event": "result", "capabilities": ["align", "who", "clear", "gist"],
                             "sdk_version": "4.0.0", "languages": Request.languages])
                return
            }
            guard let path = request.path else { throw BridgeError("Missing path.") }
            let attributes = try FileManager.default.attributesOfItem(atPath: path)
            guard let size = attributes[.size] as? NSNumber,
                  size.int64Value > 0, size.int64Value <= 1_073_741_824 else {
                throw BridgeError("WAV must be nonempty and no larger than 1 GiB.")
            }
            if request.operation == "enhance" {
                guard let destination = request.output_path else { throw BridgeError("Missing output_path.") }
                guard !FileManager.default.fileExists(atPath: destination) else {
                    throw BridgeError("output_path already exists; refusing to overwrite it.")
                }
                events.progress("Loading Clear and cleaning audio. First use downloads model weights.")
                let clear = Clear()
                // Write a sibling temporary file so cancellation cannot leave a partial final WAV.
                let temporary = URL(fileURLWithPath: destination).deletingLastPathComponent()
                    .appendingPathComponent(".neyra-\(UUID().uuidString).wav").path
                defer { try? FileManager.default.removeItem(atPath: temporary) }
                try await clear.enhance(path: path, to: temporary)
                try FileManager.default.moveItem(atPath: temporary, toPath: destination)
                events.emit(["event": "result", "path": destination])
                return
            }
            events.progress("Reading the transcript WAV.")
            let pcm = try WAV.decode(Array(Data(contentsOf: URL(fileURLWithPath: path))))
            guard pcm.sampleRate.isFinite, pcm.sampleRate > 0, pcm.channels == 1, !pcm.samples.isEmpty,
                  pcm.samples.allSatisfy({ $0.isFinite }) else {
                throw BridgeError("analyze requires nonempty, finite, mono WAV audio with a positive sample rate.")
            }
            let words = request.words ?? []
            events.progress("Refining word timestamps with Align. First use downloads model weights.")
            let align = Align()
            let fixed = try await align.refine(words.map {
                WordTiming(text: $0.text, start: $0.start, end: $0.end)
            }, audio: pcm.samples, sampleRate: pcm.sampleRate, languageCode: request.language ?? "en")
            var turns: [[String: Any]] = []
            var speakerCount = 0
            if request.speakers == true {
                events.progress("Labeling speaker turns with Who. First use downloads model weights.")
                let diarization = try await Who().diarize(samples: pcm.samples, sampleRate: pcm.sampleRate)
                speakerCount = diarization.speakerCount
                turns = diarization.turns.map { ["speaker": $0.speaker, "start": $0.start, "end": $0.end] }
            }
            var topics: [[String: Any]] = []
            if request.organize == true {
                events.progress("Finding meeting topics with Gist. First use downloads model weights.")
                let gist = request.language == nil || request.language == "en" ? Gist(variant: .english) : Gist()
                let result = try await gist.classify(words.map(\.text).joined(separator: " "))
                topics = result.map { ["slug": $0.slug, "name": $0.name, "score": $0.score] }
            }
            events.emit(["event": "result", "words": fixed.map {
                ["text": $0.text, "start": $0.start, "end": $0.end, "refined": $0.refined] as [String: Any]
            }, "turns": turns, "topics": topics, "speaker_count": speakerCount])
        } catch {
            events.emit(["event": "error", "message": error.localizedDescription])
            exit(1)
        }
    }
}
