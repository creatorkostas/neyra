import Foundation
import XCTest
@testable import MeetingProtocol

final class RequestTests: XCTestCase {
    func testCheckNeedsNoFileOrModels() throws {
        XCTAssertEqual(try Request.parse(Data(#"{"operation":"check"}"#.utf8)).operation, "check")
    }

    func testAnalyzeAcceptsVozWords() throws {
        for language in Request.languages {
            let data = try JSONSerialization.data(withJSONObject: ["operation": "analyze", "path": "original.wav", "language": language,
                "words": [["text": "Hello", "start": 0.1, "end": 0.4]]])
            let request = try Request.parse(data)
            XCTAssertEqual(request.words?.first?.text, "Hello")
            XCTAssertEqual(request.language, language)
        }
    }

    func testRejectsInvalidInput() {
        for input in [
            #"{"operation":"unknown"}"#,
            #"{"operation":"enhance","path":"same.wav","output_path":"same.wav"}"#,
            #"{"operation":"analyze","path":"a.wav","words":[]}"#,
            #"{"operation":"analyze","path":"a.wav","words":[{"text":"x","start":2,"end":1}]}"#,
            #"{"operation":"analyze","path":"a.wav","language":"sv","words":[{"text":"x","start":0,"end":1}]}"#
        ] {
            XCTAssertThrowsError(try Request.parse(Data(input.utf8)), input)
        }
        XCTAssertThrowsError(try Request.parse(Data(repeating: 32, count: Request.maxBytes + 1)))
    }

    func testReadsOneLineAndAcceptsEOF() throws {
        for text in ["{\"operation\":\"check\"}", "{\"operation\":\"check\"}\nignored"] {
            let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try Data(text.utf8).write(to: url)
            defer { try? FileManager.default.removeItem(at: url) }
            let file = try FileHandle(forReadingFrom: url)
            defer { try? file.close() }
            XCTAssertEqual(try Request.parse(readRequest(file)).operation, "check")
        }
    }
}
