import { Voz } from "@desert-ant-labs/voz";
import * as ort from "onnxruntime-node";
import readline from "node:readline";
import { availableParallelism } from "node:os";

const emit = (event) => process.stdout.write(`${JSON.stringify(event)}\n`);

// The SDK reports completed files, which can say 100% before the largest file
// arrives. Report bytes as that file streams, and abort stalled connections.
const fetchModel = globalThis.fetch;
globalThis.fetch = async (url, options = {}) => {
  if (new URL(url).hostname !== "huggingface.co") return fetchModel(url, options);
  const controller = new AbortController();
  let timer;
  const watch = () => {
    clearTimeout(timer);
    timer = setTimeout(() => controller.abort(new Error("Model download stalled. Check your connection and retry.")), 60000);
    timer.unref();
  };
  watch();
  try {
    const response = await fetchModel(url, {
      ...options,
      signal: options.signal ? AbortSignal.any([options.signal, controller.signal]) : controller.signal,
    });
    if (!response.ok || !response.body) {
      clearTimeout(timer);
      return response;
    }
    let loaded = 0, lastReport = 0;
    const total = Number(response.headers.get("content-length")) || 0;
    const file = new URL(url).pathname.split("/").pop();
    const reader = response.body.getReader();
    const stream = new ReadableStream({
      async pull(target) {
        try {
          const { done, value } = await reader.read();
          if (done) {
            clearTimeout(timer);
            emit({ event: "download", file, loaded, total });
            target.close();
            return;
          }
          loaded += value.byteLength;
          watch();
          if (Date.now() - lastReport > 500) {
            emit({ event: "download", file, loaded, total });
            lastReport = Date.now();
          }
          target.enqueue(value);
        } catch (error) {
          clearTimeout(timer);
          target.error(error);
        }
      },
      cancel(reason) { clearTimeout(timer); return reader.cancel(reason); },
    });
    return new Response(stream, { status: response.status, statusText: response.statusText, headers: response.headers });
  } catch (error) {
    clearTimeout(timer);
    throw error;
  }
};

try {
  const voz = await Voz.load({
    ort: {
      ...ort,
      InferenceSession: {
        create: (model, options) => ort.InferenceSession.create(model, {
          ...options,
          intraOpNumThreads: Math.min(4, availableParallelism()),
          interOpNumThreads: 1,
          logSeverityLevel: 3,
        }),
      },
    },
    onProgress: () => emit({ event: "loading" }),
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
