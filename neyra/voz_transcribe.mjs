import { Voz } from "@desert-ant-labs/voz";
import * as ort from "onnxruntime-node";
import readline from "node:readline";

const emit = (event) => process.stdout.write(`${JSON.stringify(event)}\n`);

try {
  const voz = await Voz.load({
    ort,
    onProgress: (fraction) => emit({ event: "loading", fraction }),
  });
  emit({ event: "ready" });

  const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of input) {
    try {
      const request = JSON.parse(line);
      if (request.stop) break;
      const result = await voz.transcribe(request.path, {
        onProgress: (fraction) => emit({ event: "transcribing", fraction }),
      });
      emit({ event: "result", text: result.text || "" });
    } catch (error) {
      emit({ event: "error", message: error?.stack || String(error) });
    }
  }
} catch (error) {
  emit({ event: "fatal", message: error?.stack || String(error) });
  process.exitCode = 1;
}
