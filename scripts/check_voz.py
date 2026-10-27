"""Check Python Voz runtime availability without downloading model weights."""
import onnxruntime as ort
from neyra.voz import PROVIDER_LABELS, VozEngine, select_provider
assert callable(VozEngine.transcribe)
available = ort.get_available_providers()
assert 'CPUExecutionProvider' in available, available
provider = select_provider(available)
print('Python Voz and ONNX Runtime', ort.__version__, 'available (weights not loaded).')
print('Execution providers:', ', '.join(available))
print('Selected Voz provider:', PROVIDER_LABELS.get(provider, 'CPU'))
