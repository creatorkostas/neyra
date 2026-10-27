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

    def test_build_no_longer_bundles_node(self):
        with tempfile.TemporaryDirectory() as folder:
            for platform in ("linux", "darwin", "win32"):
                command = self.build_command(Path(folder), platform)
                self.assertFalse(any("node_modules" in str(arg) or ".mjs" in str(arg) for arg in command))
                self.assertIn("--include-package=neyra", command)
