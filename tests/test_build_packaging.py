"""Build/runtime agreement for native libraries and bundled Voz resources."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neyra import stt
from scripts import build


class BuildPackagingTests(unittest.TestCase):
    def build_command(self, root, platform):
        (root / "node_modules").mkdir(exist_ok=True)
        mode = "--standalone" if platform == "darwin" else "--onefile"
        with patch.object(build, "ROOT", root), patch.object(build, "ASSETS", root / "assets"), \
                patch.object(build, "run") as run, patch("neyra.bundled.configure_bundled_runtime"), \
                patch.object(sys, "platform", platform), patch.object(sys, "argv", ["build.py", mode, "--skip-download"]):
            build.main()
        return run.call_args.args

    def test_native_onnx_libraries_are_not_also_included_as_package_data(self):
        with tempfile.TemporaryDirectory() as folder:
            for platform in ("linux", "darwin", "win32"):
                with self.subTest(platform=platform):
                    command = self.build_command(Path(folder), platform)
                    self.assertIn("--include-package=onnxruntime", command)
                    self.assertNotIn("--include-package-data=onnxruntime", command)

    def test_macos_voz_resource_can_be_staged_beside_the_neyra_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            command = self.build_command(root, "darwin")
            bundle = root / "Neyra.app" / "Contents" / "MacOS"
            bundle.mkdir(parents=True)
            (bundle / "neyra").write_bytes(b"executable")
            option = next(arg for arg in command if arg.startswith("--include-data-files=neyra/voz_transcribe.mjs="))
            source, destination = option.split("=", 1)[1].split("=", 1)
            target = bundle / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(build.ROOT / source, target)
            self.assertEqual(target.read_bytes(), (build.ROOT / source).read_bytes())
            self.assertEqual((bundle / "neyra").read_bytes(), b"executable")

            worker = stt.Transcriber()
            self.addCleanup(worker.close)
            with patch.object(stt, "__file__", str(bundle / "neyra" / "stt.py")), \
                    patch.object(stt, "__compiled__", object(), create=True), \
                    patch.object(stt.shutil, "which", return_value="node"), \
                    patch.object(stt.subprocess, "Popen", side_effect=RuntimeError("launch reached")) as launch:
                with self.assertRaisesRegex(RuntimeError, "launch reached"):
                    worker._load_voz()
            self.assertEqual(launch.call_args.args[0], ["node", str(target)])
            self.assertEqual(launch.call_args.kwargs["cwd"], bundle)

    def test_source_voz_runner_remains_in_the_python_package(self):
        worker = stt.Transcriber()
        self.addCleanup(worker.close)
        with patch.object(stt.shutil, "which", return_value="node"), \
                patch.object(stt.subprocess, "Popen", side_effect=RuntimeError("launch reached")) as launch:
            with self.assertRaisesRegex(RuntimeError, "launch reached"):
                worker._load_voz()
        self.assertEqual(launch.call_args.args[0], ["node", str(Path(stt.__file__).resolve().with_name("voz_transcribe.mjs"))])


if __name__ == "__main__":
    unittest.main()
