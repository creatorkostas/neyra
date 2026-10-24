# Third-party notices

Neyra source files retain their existing MIT license. Distributed builds also
include third-party software under its own licenses.

- **Piper 1.8**: GNU General Public License, version 3 or later. See
  `packaging/licenses/Piper-COPYING.txt` and the [upstream source](https://github.com/OHF-Voice/piper1-gpl).
- **ONNX Runtime**: MIT license. See `packaging/licenses/ONNXRuntime-LICENSE.txt`
  and the [upstream source](https://github.com/microsoft/onnxruntime).

The build script includes these license texts in the app's `licenses` directory.
Piper voice weights download separately on first use. The default voice is
[en_US-lessac-medium](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/medium);
its model card describes the voice's attribution and licensing.
