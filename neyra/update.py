"""Check and install Neyra's latest stable GitHub release."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .version import __version__

REPOSITORY = "creatorkostas/neyra"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
USER_AGENT = "Neyra-Updater"


def is_packaged() -> bool:
    return "__compiled__" in globals() or getattr(sys, "frozen", False)


def _version_tuple(value: str):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", value.strip())
    if not match:
        raise ValueError(f"Unsupported release version: {value}")
    return tuple(int(part) for part in match.groups())


def _request_json(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("GitHub returned an unexpectedly large release manifest.")
    result = json.loads(payload.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("GitHub returned an invalid release manifest.")
    return result


def asset_name_for_platform() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in ("amd64", "x86_64"):
        return "Neyra.exe"
    if sys.platform.startswith("linux") and machine in ("x86_64", "amd64"):
        return "Neyra-Linux-x86_64.tar.gz"
    if sys.platform == "darwin" and machine in ("arm64", "aarch64"):
        return "Neyra-macOS-AppleSilicon.zip"
    raise RuntimeError(f"Automatic updates are not available for {sys.platform}/{machine}.")


def latest_release() -> dict:
    release = _request_json(LATEST_RELEASE_URL)
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("GitHub did not return a published stable release.")
    tag = release.get("tag_name")
    latest = _version_tuple(tag or "")
    current = _version_tuple(__version__)
    if latest <= current:
        return {"available": False, "current": __version__, "latest": tag}
    expected_name = asset_name_for_platform()
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("The release has no downloadable assets.")
    asset = next((item for item in assets if item.get("name") == expected_name), None)
    if asset is None:
        raise RuntimeError(f"Release {tag} has no package for this computer ({expected_name}).")
    digest = asset.get("digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError(f"Release asset {expected_name} has no valid SHA-256 digest.")
    url = asset.get("browser_download_url")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        raise ValueError("The release asset has an unexpected download URL.")
    return {
        "available": True, "current": __version__, "latest": tag,
        "name": expected_name, "url": url, "digest": digest.split(":", 1)[1].lower(),
        "release_url": release.get("html_url", ""),
        "notes": release.get("body", "") if isinstance(release.get("body"), str) else "",
    }


def _download_verified(release: dict, destination: Path) -> Path:
    request = urllib.request.Request(release["url"], headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if digest.hexdigest() != release["digest"]:
        destination.unlink(missing_ok=True)
        raise ValueError("The downloaded update failed its SHA-256 verification.")
    return destination


def _application_target() -> Path:
    executable = Path(sys.argv[0]).resolve()
    if sys.platform == "darwin":
        for parent in executable.parents:
            if parent.name.endswith(".app"):
                return parent
    return executable


def _stage_directory(target: Path) -> Path:
    parent = target.parent
    if sys.platform.startswith("linux") and str(parent) in ("/usr/bin", "/usr/local/bin", "/bin"):
        raise PermissionError("Package-managed Linux installations must be updated with their package manager.")
    if not os.access(parent, os.W_OK):
        raise PermissionError(f"Neyra cannot update this installation because {parent} is not writable.")
    return Path(tempfile.mkdtemp(prefix=".neyra-update-", dir=parent))


def _extract_update(archive: Path, stage: Path, name: str) -> Path:
    if name == "Neyra.exe":
        return archive
    if name == "Neyra-Linux-x86_64.tar.gz":
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            candidates = [m for m in members if m.name == "Neyra" and m.isfile()]
            if len(candidates) != 1 or len(members) != 1:
                raise ValueError("The Linux update archive has an unexpected layout.")
            extracted = bundle.extractfile(candidates[0])
            if extracted is None:
                raise ValueError("The Linux update archive is missing its executable.")
            target = stage / "Neyra"
            with extracted, target.open("wb") as output:
                shutil.copyfileobj(extracted, output)
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            return target
    if name == "Neyra-macOS-AppleSilicon.zip":
        if sys.platform != "darwin":
            raise RuntimeError("The macOS package can only be installed on macOS.")
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                parts = Path(info.filename).parts
                if (not parts or parts[0] not in ("Neyra.app", "__MACOSX")
                        or ".." in parts or info.filename.startswith("/")):
                    raise ValueError("The macOS update archive has an unexpected layout.")
        subprocess.run(["ditto", "-x", "-k", str(archive), str(stage)], check=True, timeout=180)
        result = stage / "Neyra.app"
        if not result.is_dir():
            raise ValueError("The macOS update archive did not contain Neyra.app.")
        return result
    raise RuntimeError(f"Unsupported release asset: {name}")


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _start_windows_helper(staged: Path, target: Path) -> None:
    helper = staged.parent / "apply-update.ps1"
    script = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$target = {_ps_quote(str(target))}",
        f"$staged = {_ps_quote(str(staged))}",
        f"$ownerPid = {os.getpid()}",
        "while (Get-Process -Id $ownerPid -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 400 }",
        "$backup = $target + '.neyra-backup'",
        "try {",
        "  if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }",
        "  Move-Item -LiteralPath $target -Destination $backup -Force",
        "  Move-Item -LiteralPath $staged -Destination $target -Force",
        "  Start-Process -FilePath $target",
        "  Remove-Item -LiteralPath $backup -Force",
        "} catch {",
        "  if ((Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $target)) { Move-Item -LiteralPath $backup -Destination $target -Force }",
        "  throw",
        "}",
    ])
    helper.write_text(script, encoding="utf-8")
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True,
    )


def _start_unix_helper(staged: Path, target: Path) -> None:
    helper = staged.parent / "apply-update.sh"
    pid = os.getpid()
    launch = f"open -a {shlex.quote(str(target))}" if target.name.endswith(".app") else f"nohup {shlex.quote(str(target))} >/dev/null 2>&1 &"
    script = "\n".join([
        "#!/bin/sh",
        f"owner_pid={pid}",
        "while kill -0 \"$owner_pid\" 2>/dev/null; do sleep 0.4; done",
        f"target={shlex.quote(str(target))}",
        f"staged={shlex.quote(str(staged))}",
        "backup=\"$target.neyra-backup\"",
        "rm -rf \"$backup\"",
        "mv \"$target\" \"$backup\" || exit 1",
        "if ! mv \"$staged\" \"$target\"; then mv \"$backup\" \"$target\"; exit 1; fi",
        launch,
        "rm -rf \"$backup\"",
        f"rm -rf {shlex.quote(str(helper.parent))}",
    ])
    helper.write_text(script, encoding="utf-8")
    helper.chmod(0o700)
    subprocess.Popen(["/bin/sh", str(helper)], start_new_session=True, close_fds=True)


class UpdateCheckThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.completed.emit(latest_release())
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDownloadThread(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release

    def run(self):
        stage = None
        try:
            target = _application_target()
            stage = _stage_directory(target)
            archive = stage / self.release["name"]
            _download_verified(self.release, archive)
            staged = _extract_update(archive, stage, self.release["name"])
            if staged == archive:
                staged = stage / ("Neyra.exe" if sys.platform == "win32" else "Neyra")
                archive.replace(staged)
            self.completed.emit(str(staged))
        except Exception as exc:
            if stage:
                shutil.rmtree(stage, ignore_errors=True)
            self.failed.emit(str(exc))


def apply_staged_update(staged_path: str) -> None:
    staged = Path(staged_path).resolve()
    if not staged.exists():
        raise ValueError("The staged update is missing.")
    target = _application_target()
    if sys.platform == "win32":
        _start_windows_helper(staged, target)
    else:
        _start_unix_helper(staged, target)
