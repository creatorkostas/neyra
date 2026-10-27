"""Build one-file or standalone executables with bundled offline Whistle assets."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

def run(*args):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)

def needle(*args):
    run(sys.executable, "-c", "from needle.cli import main; main()", *args)

def prepare_assets():
    model = ASSETS / "model"
    engine = ASSETS / "engine"
    model.mkdir(parents=True, exist_ok=True)
    engine.mkdir(parents=True, exist_ok=True)
    if not list(model.rglob("whistle.cact")):
        needle("download", "whistle", "--out", model)
    if not list(model.rglob("needle3.cact")):
        needle("download", "needle3", "--out", model)
    if not any(x.is_file() and ("needle" in x.name.lower()) and x.suffix.lower() in (".so", ".dll", ".dylib") for x in engine.rglob("*")):
        needle("fetch", "--out", engine)
    from neyra.bundled import configure_bundled_runtime
    configure_bundled_runtime()
    print("Bundled engine:", os.environ["NEEDLE3_LIB_PATH"])
    print("Bundled model:", os.environ["NEEDLE_WHISTLE_WEIGHTS"])

def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--onefile", action="store_true", help="Single self-extracting executable (default)")
    mode.add_argument("--standalone", action="store_true", help="Directory distribution, useful for debugging")
    parser.add_argument("--skip-download", action="store_true", help="Use previously downloaded assets")
    parser.add_argument("--jobs", type=int, help="Parallel compiler jobs (default: all CPU cores; negative: leave that many cores free)")
    args = parser.parse_args()
    if args.jobs == 0:
        parser.error("--jobs must be a nonzero integer")
    if not args.skip_download:
        prepare_assets()
    else:
        from neyra.bundled import configure_bundled_runtime
        configure_bundled_runtime()
    is_win = sys.platform == "win32"
    name = "Neyra.exe" if is_win else "Neyra"
    command = [sys.executable, "-m", "nuitka",
        "--standalone" if args.standalone else "--onefile",
        "--enable-plugin=pyside6",
        "--include-package=piper",
        "--include-package-data=piper",
        # Nuitka's ONNX plugin includes native libraries; package data duplicates versioned .so files.
        "--include-package=onnxruntime",
        "--include-data-dir=packaging/licenses=licenses",
        "--include-package=needle",
        "--include-package=neyra",
        "--include-package-data=soundcard",
        "--output-dir=dist",
        "--assume-yes-for-downloads",
    ]
    if args.jobs is not None:
        command.append(f"--jobs={args.jobs}")
    if sys.platform != "darwin":
        command.append(f"--output-filename={name}")
    # Toolchain installers under assets/tools are development files, not app data.
    for folder in ("model", "engine", "meeting-models"):
        if (ASSETS / folder).is_dir():
            option = "--include-data-dir" if folder == "model" else "--include-raw-dir"
            command.append(f"{option}={ASSETS / folder}=assets/{folder}")
    if is_win:
        command.append("--windows-console-mode=disable")
    elif sys.platform == "darwin":
        command.extend([
            "--macos-create-app-bundle",
            # output-filename overrides the onefile bundle executable path on macOS.
            "--output-folder-name=Neyra",
            "--macos-app-name=Neyra",
            # Nuitka's PortAudio prefix rule also matches Windows DLLs in the wheel.
            "--noinclude-dlls=_sounddevice_data/portaudio-binaries/*.dll",
            "--macos-app-protected-resource=NSMicrophoneUsageDescription:Neyra uses the microphone for local dictation and meeting notes.",
        ])
    command.append(str(ROOT / "run_neyra.py"))
    run(*command)
    print("Build complete. See dist/")

if __name__ == "__main__":
    main()
