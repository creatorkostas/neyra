// Validate the bridge's installed SDK/native API without downloading any model.
import assert from "node:assert/strict";
import { Voz } from "@desert-ant-labs/voz";
import * as ort from "onnxruntime-node";

assert.equal(typeof Voz.load, "function", "Voz.load is required by the bridge");
assert.equal(typeof Voz.prototype.transcribe, "function", "Voz.transcribe is required by the bridge");
assert.equal(typeof ort.InferenceSession.create, "function", "Native ONNX session creation is required");
console.log("Voz and native ONNX runtime imports and bridge APIs passed.");
