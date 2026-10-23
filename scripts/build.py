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
    args = parser.parse_args()
    if not args.skip_download:
        prepare_assets()
    else:
        from neyra.bundled import configure_bundled_runtime
        configure_bundled_runtime()
    is_win = sys.platform == "win32"
    name = "Neyra.exe" if is_win else "Neyra"
    node_modules = ROOT / "node_modules"
    if not node_modules.is_dir():
        raise RuntimeError("Voz dependencies are missing. Run `npm ci` before building.")
    command = [sys.executable, "-m", "nuitka",
        "--standalone" if args.standalone else "--onefile",
        "--enable-plugin=pyside6",
        "--include-package=needle",
        "--include-package=neyra",
        "--include-package-data=soundcard",
        "--include-data-files=neyra/voz_transcribe.mjs=neyra/voz_transcribe.mjs",
        f"--include-raw-dir={node_modules}=node_modules",
        "--output-dir=dist", f"--output-filename={name}",
        "--assume-yes-for-downloads",
    ]
    # Toolchain installers under assets/tools are development files, not app data.
    for folder in ("model", "engine", "meeting-models"):
        if (ASSETS / folder).is_dir():
            option = "--include-data-dir" if folder == "model" else "--include-raw-dir"
            command.append(f"{option}={ASSETS / folder}=assets/{folder}")
    if is_win:
        command.append("--windows-console-mode=disable")
    command.append(str(ROOT / "run_neyra.py"))
    run(*command)
    print("Build complete. See dist/")

if __name__ == "__main__":
    main()
