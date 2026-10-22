"""Build and stage the Windows x64 meeting helper without changing global settings."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, env: dict[str, str], cwd: Path, capture: bool = False) -> str:
    result = subprocess.run(
        args, cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if not capture or result.returncode:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    result.check_returncode()
    return result.stdout or ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swift", help="Path to an existing Swift 6.2+ swift.exe")
    parser.add_argument("--sdk", help="Windows Swift SDK root, if SDKROOT is not set")
    parser.add_argument("--runtime-bin", action="append", default=[], help="Swift runtime DLL directory; repeatable")
    args = parser.parse_args()
    if os.name != "nt" or os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() != "AMD64":
        raise SystemExit("This setup script requires Windows x64.")
    local = ROOT / "assets" / "tools" / "swift-local"
    local_swift = next(local.glob("**/usr/bin/swift.exe"), None) if local.is_dir() else None
    swift = args.swift or shutil.which("swift") or (str(local_swift) if local_swift else None)
    if not swift:
        raise SystemExit("Swift 6.2+ x64 is required. See runtime/meeting-models/README.md; pass --swift to use a local toolchain.")
    swift = str(Path(swift).resolve())
    if local_swift and Path(swift) == local_swift.resolve():
        if not args.sdk:
            sdk = next(local.glob("**/Windows.sdk"), None)
            if sdk:
                args.sdk = str(sdk)
        args.runtime_bin += [str(p.parent) for p in local.glob("**/swiftCore.dll")]
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(Path(swift).parent), *args.runtime_bin, env.get("PATH", "")])
    if args.sdk:
        env["SDKROOT"] = str(Path(args.sdk).resolve())
    version = run([swift, "--version"], env=env, cwd=ROOT, capture=True)
    match = re.search(r"Swift version (\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (6, 2):
        raise SystemExit("Swift 6.2 or later is required: " + version.strip())
    work = ROOT / "assets" / "meeting-models-build"
    work.mkdir(parents=True, exist_ok=True)
    vendor = work / "litert"
    vendor.mkdir(exist_ok=True)
    dll = vendor / "libLiteRt.dll"
    if not dll.exists():
        uv = shutil.which("uv")
        if uv:
            command = [uv, "pip", "install", "--python-platform", "x86_64-pc-windows-msvc",
                       "--python-version", "3.12", "--target", str(work / "wheel"),
                       "--only-binary=:all:", "--no-deps", "ai-edge-litert==2.2.0"]
        else:
            command = [sys.executable, "-m", "pip", "install", "--platform", "win_amd64",
                       "--python-version", "3.12", "--target", str(work / "wheel"),
                       "--only-binary=:all:", "--no-deps", "ai-edge-litert==2.2.0"]
        run(command, env=env, cwd=ROOT)
        shutil.copy2(work / "wheel" / "ai_edge_litert" / dll.name, dll)
    readobj = Path(swift).with_name("llvm-readobj.exe")
    lib = Path(swift).with_name("llvm-lib.exe")
    for tool in (readobj, lib):
        if not tool.is_file():
            raise SystemExit(f"Required Swift tool is missing: {tool}")
    # The shared SDK inference target links ONNX Runtime on Windows even for LiteRT models.
    if not (vendor / "onnxruntime.dll").exists():
        uv = shutil.which("uv")
        installer = [uv, "pip", "install"] if uv else [sys.executable, "-m", "pip", "install"]
        platform_args = ["--python-platform", "x86_64-pc-windows-msvc"] if uv else ["--platform", "win_amd64"]
        run(installer + platform_args + ["--python-version", "3.12", "--target", str(work / "onnx-wheel"),
            "--only-binary=:all:", "--no-deps", "onnxruntime-directml==1.23.0"], env=env, cwd=ROOT)
        for runtime in (work / "onnx-wheel" / "onnxruntime" / "capi").glob("*.dll"):
            shutil.copy2(runtime, vendor / runtime.name)
    for library, runtime_dll in [("LiteRt", dll), ("onnxruntime", vendor / "onnxruntime.dll")]:
        exports = run([str(readobj), "--coff-exports", str(runtime_dll)], env=env, cwd=ROOT, capture=True)
        names = re.findall(r"^\s*Name: (\S+)\s*$", exports, re.MULTILINE)
        if not names:
            raise SystemExit(f"{runtime_dll.name} contains no exports.")
        definition = vendor / f"{library}.def"
        definition.write_text(f"LIBRARY {runtime_dll.name}\nEXPORTS\n" + "\n".join(names) + "\n", encoding="ascii")
        run([str(lib), f"/def:{definition}", "/machine:x64", f"/out:{vendor / (library + '.lib')}", "/nologo"], env=env, cwd=ROOT)
    package = ROOT / "runtime" / "meeting-models"
    build = [swift, "build", "--package-path", str(package), "--scratch-path", str(work / "swift"),
             "-c", "release", "--product", "neyra-meeting-models", "-Xlinker", f"/LIBPATH:{vendor}"]
    run(build, env=env, cwd=ROOT)
    bin_path = Path(run([swift, "build", "--package-path", str(package), "--scratch-path", str(work / "swift"),
                        "-c", "release", "--show-bin-path"], env=env, cwd=ROOT, capture=True).strip())
    run([swift, "test", "--package-path", str(package), "--scratch-path", str(work / "swift"),
         "-c", "release", "--filter", "MeetingProtocolTests", "-Xlinker", f"/LIBPATH:{vendor}"], env=env, cwd=ROOT)
    destination = ROOT / "assets" / "meeting-models"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bin_path / "neyra-meeting-models.exe", destination)
    for runtime in vendor.glob("*.dll"):
        shutil.copy2(runtime, destination / runtime.name)
    for resource in bin_path.glob("*.resources"):
        if resource.is_dir():
            shutil.copytree(resource, destination / resource.name, dirs_exist_ok=True)
    runtime_dirs = [Path(p) for p in args.runtime_bin]
    runtime_dirs += [Path(p) for p in env["PATH"].split(os.pathsep)
                     if p and (Path(p) / "swiftCore.dll").is_file()]
    # Query the actual compiler for runtime paths instead of assuming an install layout.
    target = json.loads(run([swift, "-print-target-info"], env=env, cwd=ROOT, capture=True))
    runtime_dirs += [Path(p) for p in target.get("paths", {}).get("runtimeLibraryPaths", [])]
    for directory in runtime_dirs:
        if not directory.is_dir():
            continue
        # Swift/Foundation/dispatch runtimes and their ICU/XML/network dependencies.
        for runtime in directory.glob("*.dll"):
            if directory == Path(swift).parent:
                continue  # compiler DLLs are not application dependencies
            shutil.copy2(runtime, destination / runtime.name)
    smoke_env = env.copy()
    smoke_env["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
    result = subprocess.run(
        [str(destination / "neyra-meeting-models.exe")], input='{"operation":"check"}\n',
        text=True, capture_output=True, check=True, env=smoke_env,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    events = [json.loads(line) for line in result.stdout.splitlines()]
    if not events or events[-1].get("capabilities") != ["align", "who", "clear", "gist"]:
        raise SystemExit("Helper capability check failed: " + result.stdout + result.stderr)
    print(f"Built and checked {destination / 'neyra-meeting-models.exe'}")


if __name__ == "__main__":
    main()
