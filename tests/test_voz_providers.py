import unittest
from unittest.mock import patch

from neyra.voz import CPU_PROVIDER, select_provider, session_providers

OPENVINO = ['OpenVINOExecutionProvider', CPU_PROVIDER]
WINDOWS = ['WebGpuExecutionProvider', CPU_PROVIDER]
MACOS = ['CoreMLExecutionProvider', CPU_PROVIDER]


class ProviderSelectionTests(unittest.TestCase):
    def test_auto_picks_the_platform_provider(self):
        self.assertEqual(select_provider(OPENVINO, platform='linux', requested='', device='auto'), 'OpenVINOExecutionProvider')
        self.assertEqual(select_provider(WINDOWS, platform='win32', requested='', device='auto'), 'WebGpuExecutionProvider')
        self.assertEqual(select_provider(MACOS, platform='darwin', requested='', device='auto'), 'CoreMLExecutionProvider')
        webgpu = ['WebGpuExecutionProvider', CPU_PROVIDER]
        self.assertEqual(select_provider(webgpu, platform='linux', requested='', device='auto'), 'WebGpuExecutionProvider')

    def test_auto_without_a_gpu_provider_uses_cpu(self):
        self.assertIsNone(select_provider([CPU_PROVIDER], platform='linux', requested='', device='auto'))

    def test_cpu_device_disables_acceleration(self):
        self.assertIsNone(select_provider(OPENVINO, platform='linux', requested='', device='cpu'))

    def test_webgpu_is_used_when_it_is_the_only_build(self):
        available = ['WebGpuExecutionProvider', CPU_PROVIDER]
        self.assertEqual(select_provider(available, platform='linux', requested='', device='auto'), 'WebGpuExecutionProvider')
        self.assertEqual(select_provider(available, platform='linux', requested='', device='webgpu'), 'WebGpuExecutionProvider')

    def test_linux_prefers_the_shipped_webgpu_build(self):
        available = ['WebGpuExecutionProvider', 'OpenVINOExecutionProvider', CPU_PROVIDER]
        self.assertEqual(select_provider(available, platform='linux', requested='', device='auto'), 'WebGpuExecutionProvider')

    def test_optional_openvino_build_is_used_when_it_is_the_only_one(self):
        available = ['OpenVINOExecutionProvider', CPU_PROVIDER]
        self.assertEqual(select_provider(available, platform='linux', requested='', device='auto'), 'OpenVINOExecutionProvider')

    def test_explicit_provider_wins_over_the_device_setting(self):
        self.assertEqual(select_provider(OPENVINO, platform='linux', requested='OpenVINOExecutionProvider', device='cpu'),
                         'OpenVINOExecutionProvider')

    def test_unknown_or_invalid_settings_fail(self):
        with self.assertRaises(ValueError):
            select_provider(OPENVINO, platform='linux', requested='BogusProvider', device='auto')
        with self.assertRaises(ValueError):
            select_provider(OPENVINO, platform='linux', requested='', device='turbo')

    def test_environment_selects_the_provider(self):
        with patch.dict('os.environ', {'NEYRA_VOZ_DEVICE': 'cpu'}, clear=False):
            self.assertIsNone(select_provider(OPENVINO, platform='linux'))
        with patch.dict('os.environ', {'NEYRA_VOZ_ONNX_PROVIDER': 'WebGpuExecutionProvider'}, clear=False):
            self.assertEqual(select_provider(WINDOWS, platform='win32'), 'WebGpuExecutionProvider')

    def test_directml_build_still_works_for_benchmarks(self):
        available = ['DmlExecutionProvider', CPU_PROVIDER]
        self.assertEqual(select_provider(available, platform='win32', requested='', device='auto'), 'DmlExecutionProvider')

    def test_encoder_uses_the_gpu_with_a_cpu_fallback(self):
        providers = session_providers('WebGpuExecutionProvider', 'encoder')
        self.assertEqual(providers[0][0], 'WebGpuExecutionProvider')
        self.assertEqual(providers[1], CPU_PROVIDER)

    def test_decoder_stays_on_cpu(self):
        self.assertEqual(session_providers('OpenVINOExecutionProvider', 'decoder'), [CPU_PROVIDER])
        self.assertEqual(session_providers(None, 'encoder'), [CPU_PROVIDER])

    def test_openvino_requests_automatic_device_selection(self):
        with patch('neyra.voz.cache_directory', return_value=__import__('pathlib').Path('/tmp/neyra-test-cache')):
            providers = session_providers('OpenVINOExecutionProvider', 'encoder', device='auto')
        self.assertEqual(providers[0][1]['device_type'], 'AUTO')
        self.assertIn('cache_dir', providers[0][1])

    def test_explicit_gpu_device_forces_openvino_gpu(self):
        with patch('neyra.voz.cache_directory', return_value=__import__('pathlib').Path('/tmp/neyra-test-cache')):
            providers = session_providers('OpenVINOExecutionProvider', 'encoder', device='gpu')
        self.assertEqual(providers[0][1]['device_type'], 'GPU')


if __name__ == '__main__':
    unittest.main()
