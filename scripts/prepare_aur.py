"""Generate an AUR recipe and submission archive from an actual Linux release."""
import argparse
import hashlib
import re
import shlex
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "packaging" / "aur"
LOCAL_SOURCES = ("neyra", "neyra.desktop", "neyra.svg", "LICENSE", "Piper-COPYING.txt", "ONNXRuntime-LICENSE.txt")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(version, archive, output):
    version = version.removeprefix("v")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+(?:[a-zA-Z0-9.]*)?", version):
        raise ValueError("version must be an Arch-compatible release number, e.g. 0.1.3")
    archive = Path(archive).resolve()
    # Validate without extracting executable content from the release archive.
    with tarfile.open(archive, "r:gz") as release:
        members = release.getmembers()
        if len(members) != 1 or members[0].name != "Neyra" or not members[0].isfile():
            raise ValueError("Linux release archive must contain only the regular file Neyra")
        if not members[0].mode & 0o111:
            raise ValueError("Neyra must have executable permissions in the release archive")

    output = Path(output).resolve()
    package_dir = output / "neyra-bin"
    if package_dir.exists():
        raise ValueError(f"refusing to overwrite existing package directory: {package_dir}")

    license_files = {"LICENSE": ROOT / "LICENSE",
                     "Piper-COPYING.txt": ROOT / "packaging/licenses/Piper-COPYING.txt",
                     "ONNXRuntime-LICENSE.txt": ROOT / "packaging/licenses/ONNXRuntime-LICENSE.txt"}
    sources = {
        name: license_files.get(name, TEMPLATE / name).read_text(
            encoding="utf-8"
        ).encode("utf-8")
        for name in LOCAL_SOURCES
    }
    release_source = (
        f"neyra-{version}-linux-x86_64.tar.gz::https://github.com/creatorkostas/neyra/"
        f"releases/download/v{version}/Neyra-Linux-x86_64.tar.gz"
    )
    # One metadata definition feeds both PKGBUILD and .SRCINFO.
    metadata = [
        ("pkgver", version),
        ("pkgrel", "1"),
        ("pkgdesc", "Local desktop dictation assistant with Whistle and Voz (prebuilt)"),
        ("arch", ["x86_64"]),
        ("url", "https://github.com/creatorkostas/neyra"),
        ("license", ["MIT", "GPL-3.0-or-later"]),
        ("depends", [
            "glibc", "gcc-libs", "portaudio", "libpulse", "alsa-lib",
            "dbus", "fontconfig", "freetype2", "glib2", "libgl", "libx11", "libxcb",
            "libxext", "libxrender", "libxi", "libxkbcommon", "libxkbcommon-x11",
            "xcb-util-cursor", "xcb-util-image", "xcb-util-keysyms",
            "xcb-util-renderutil", "xcb-util-wm", "zlib", "xclip",
        ]),
        ("optdepends", [
            "playerctl: assistant media playback commands",
            "wireplumber: assistant volume controls through wpctl",
            "libnotify: desktop reminder notifications without a system tray",
            "wl-clipboard: clipboard access on Wayland",
            "wtype: text insertion on supported Wayland compositors",
        ]),
        ("provides", [f"neyra={version}"]),
        ("conflicts", ["neyra"]),
        # Stripping can corrupt Nuitka's appended onefile payload.
        ("options", ["!strip", "!debug"]),
        ("source", [release_source, *LOCAL_SOURCES]),
        ("sha256sums", [
            sha256(archive),
            *(hashlib.sha256(sources[name]).hexdigest() for name in LOCAL_SOURCES),
        ]),
    ]
    pkgbuild = ["pkgname=neyra-bin"]
    srcinfo = ["pkgbase = neyra-bin"]
    for key, value in metadata:
        if isinstance(value, list):
            pkgbuild.append(f"{key}=(" + " ".join(shlex.quote(item) for item in value) + ")")
            srcinfo.extend(f"\t{key} = {item}" for item in value)
        else:
            pkgbuild.append(f"{key}={shlex.quote(value)}")
            srcinfo.append(f"\t{key} = {value}")
    srcinfo.extend(["", "pkgname = neyra-bin", ""])
    rendered = (TEMPLATE / "PKGBUILD.in").read_text(encoding="utf-8").replace(
        "@METADATA@", "\n".join(pkgbuild)
    )
    package_dir.mkdir(parents=True)
    (package_dir / "PKGBUILD").write_text(rendered, encoding="utf-8", newline="\n")
    (package_dir / ".SRCINFO").write_text("\n".join(srcinfo), encoding="utf-8", newline="\n")
    for name, data in sources.items():
        (package_dir / name).write_bytes(data)
    submission = output / f"neyra-bin-{version}-aur.tar.gz"
    with tarfile.open(submission, "w:gz") as bundle:
        for name in ("PKGBUILD", ".SRCINFO", *LOCAL_SOURCES):
            bundle.add(package_dir / name, arcname=f"neyra-bin/{name}")
    return submission


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release version, with optional v prefix")
    parser.add_argument("--archive", type=Path, required=True, help="Exact Linux release tar.gz")
    parser.add_argument("--output", type=Path, required=True, help="Output directory")
    args = parser.parse_args()
    try:
        submission = prepare(args.version, args.archive, args.output)
    except (OSError, ValueError, tarfile.TarError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(submission)


if __name__ == "__main__":
    main()
