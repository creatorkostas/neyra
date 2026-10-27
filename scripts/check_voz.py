"""Check Python Voz runtime availability without downloading model weights."""
import onnxruntime
from neyra.voz import VozEngine
assert callable(VozEngine.transcribe)
assert 'CPUExecutionProvider' in onnxruntime.get_available_providers()
print('Python Voz and ONNX Runtime', onnxruntime.__version__, 'available (weights not loaded).')
