"""Focused portable checks. Run: python packaging/aur/check_generator.py."""
import hashlib
import io
import runpy
import shlex
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
prepare = runpy.run_path(str(ROOT / "scripts" / "prepare_aur.py"))["prepare"]


class GeneratorChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "Neyra-Linux-x86_64.tar.gz"

    def archive_with(self, name="Neyra", mode=0o755):
        payload = b"synthetic release executable\n"
        with tarfile.open(self.archive, "w:gz") as archive:
            entry = tarfile.TarInfo(name)
            entry.size = len(payload)
            entry.mode = mode
            archive.addfile(entry, io.BytesIO(payload))

    def test_release_metadata_and_submission(self):
        self.archive_with()
        submission = prepare("v1.2.3", self.archive, self.root / "out")
        package = self.root / "out" / "neyra-bin"
        recipe = (package / "PKGBUILD").read_text(encoding="utf-8")
        metadata = {}
        for line in (package / ".SRCINFO").read_text(encoding="utf-8").splitlines():
            if " = " in line:
                key, value = line.strip().split(" = ", 1)
                metadata.setdefault(key, []).append(value)
        for key, values in metadata.items():
            if key == "pkgbase":
                continue
            line = next(line for line in recipe.splitlines() if line.startswith(key + "="))
            value = line.split("=", 1)[1]
            actual = shlex.split(value[1:-1] if value.startswith("(") else value)
            self.assertEqual(values, actual, key)
        self.assertEqual(metadata["pkgver"], ["1.2.3"])
        self.assertEqual(metadata["sha256sums"][0], hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertIn("/releases/download/v1.2.3/Neyra-Linux-x86_64.tar.gz", metadata["source"][0])
        for source, digest in zip(metadata["source"][1:], metadata["sha256sums"][1:]):
            data = (package / source).read_bytes()
            self.assertEqual(digest, hashlib.sha256(data).hexdigest())
            self.assertNotIn(b"\r\n", data)
        self.assertNotIn("SKIP", recipe)
        self.assertIn('exec /opt/neyra/Neyra "$@"', (package / "neyra").read_text())
        with tarfile.open(submission, "r:gz") as archive:
            self.assertEqual(set(archive.getnames()), {
                "neyra-bin/PKGBUILD", "neyra-bin/.SRCINFO", "neyra-bin/neyra",
                "neyra-bin/neyra.desktop", "neyra-bin/neyra.svg", "neyra-bin/LICENSE",
            })
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            prepare("1.2.3", self.archive, self.root / "out")

    def test_invalid_version_leaves_no_output(self):
        with self.assertRaises(ValueError):
            prepare("1.2;bad", self.archive, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_rejects_wrong_layout_or_permissions(self):
        for name, mode in (("../Neyra", 0o755), ("Neyra", 0o644)):
            with self.subTest(name=name, mode=mode):
                self.archive_with(name, mode)
                with self.assertRaises(ValueError):
                    prepare("1.2.3", self.archive, self.root / "out")
                self.assertFalse((self.root / "out").exists())


if __name__ == "__main__":
    unittest.main()
