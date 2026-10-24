"""Check release package structure without launching audio capture or model loading."""
import argparse
from pathlib import Path
import plistlib
import struct
import tarfile
import zipfile


def check_release(platform, path):
    path = Path(path)
    if platform == "windows":
        with path.open("rb") as executable:
            header = executable.read(64)
            if len(header) != 64 or header[:2] != b"MZ":
                raise ValueError("Windows release is not a PE executable")
            executable.seek(struct.unpack_from("<I", header, 60)[0])
            if executable.read(6) != b"PE\x00\x00\x64\x86":
                raise ValueError("Windows release must be an x86_64 PE executable")
    elif platform == "linux":
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) != 1 or members[0].name != "Neyra" or not members[0].isfile():
                raise ValueError("Linux archive must contain only the regular file Neyra")
            if not members[0].mode & 0o111:
                raise ValueError("Linux executable has lost its executable permission")
            with archive.extractfile(members[0]) as executable:
                header = executable.read(20)
            if (len(header) != 20 or header[:6] != b"\x7fELF\x02\x01"
                    or header[18:20] != b"\x3e\x00"):
                raise ValueError("Linux release must be a 64-bit x86_64 ELF executable")
    elif platform == "macos":
        with zipfile.ZipFile(path) as archive:
            root = "Neyra.app/Contents/"
            info = plistlib.loads(archive.read(root + "Info.plist"))
            name = info.get("CFBundleExecutable", "")
            if not name or Path(name).name != name or "/" in name or "\\" in name:
                raise ValueError("macOS bundle has no valid executable name")
            if not info.get("NSMicrophoneUsageDescription"):
                raise ValueError("macOS bundle has no microphone permission description")
            with archive.open(root + "MacOS/" + name) as executable:
                header = executable.read(8)
            if header != b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01":
                raise ValueError("macOS release must contain an Apple silicon Mach-O executable")
    else:
        raise ValueError(f"Unsupported platform: {platform}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=("windows", "linux", "macos"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        check_release(args.platform, args.path)
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile,
            plistlib.InvalidFileException) as exc:
        parser.exit(1, f"Release check failed: {exc}\n")
    print(f"Release package verified: {args.path}")


if __name__ == "__main__":
    main()
