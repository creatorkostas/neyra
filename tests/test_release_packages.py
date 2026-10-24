"""Release checks reject broken archives and binaries for the wrong platform."""
import io
from pathlib import Path
import plistlib
import struct
import tarfile
import tempfile
import unittest
import zipfile

from scripts.check_release import check_release


class ReleasePackages(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "package"

    def test_windows_requires_x64_pe(self):
        header = bytearray(64)
        header[:2] = b"MZ"
        struct.pack_into("<I", header, 60, 64)
        self.path.write_bytes(header + b"PE\x00\x00\x64\x86")
        check_release("windows", self.path)
        self.path.write_bytes(header + b"PE\x00\x00\x4c\x01")
        with self.assertRaises(ValueError):
            check_release("windows", self.path)

    def linux_archive(self, mode=0o755, extra=False):
        header = bytearray(20)
        header[:6] = b"\x7fELF\x02\x01"
        header[18:20] = b"\x3e\x00"
        with tarfile.open(self.path, "w:gz") as archive:
            member = tarfile.TarInfo("Neyra")
            member.mode = mode
            member.size = len(header)
            archive.addfile(member, io.BytesIO(header))
            if extra:
                archive.addfile(tarfile.TarInfo("unexpected"))

    def test_linux_requires_executable_and_exact_archive_contents(self):
        self.linux_archive()
        check_release("linux", self.path)
        for options in ({"mode": 0o644}, {"extra": True}):
            self.linux_archive(**options)
            with self.assertRaises(ValueError):
                check_release("linux", self.path)

    def mac_archive(self, microphone=True, arm=True):
        info = {"CFBundleExecutable": "Neyra"}
        if microphone:
            info["NSMicrophoneUsageDescription"] = "Local dictation"
        with zipfile.ZipFile(self.path, "w") as archive:
            archive.writestr("Neyra.app/Contents/Info.plist", plistlib.dumps(info))
            archive.writestr("Neyra.app/Contents/MacOS/Neyra",
                             b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01" if arm else b"wrong cpu")

    def test_macos_requires_arm_executable_and_microphone_description(self):
        self.mac_archive()
        check_release("macos", self.path)
        for options in ({"microphone": False}, {"arm": False}):
            self.mac_archive(**options)
            with self.assertRaises(ValueError):
                check_release("macos", self.path)


if __name__ == "__main__":
    unittest.main()
