"""Fail a release build when embedded and package versions diverge."""
import os
import re
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parent.parent
project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
project_version = project["project"]["version"]
source = (root / "neyra" / "version.py").read_text(encoding="utf-8")
match = re.search(r'^__version__\\s*=\\s*["\']([^"\']+)["\']', source, re.MULTILINE)
if not match:
    raise SystemExit("Could not read neyra/version.py __version__.")
if match.group(1) != project_version:
    raise SystemExit(f"Version mismatch: pyproject.toml={project_version}, neyra/version.py={match.group(1)}")
tag = os.environ.get("RELEASE_TAG", "").strip()
if tag and tag.removeprefix("v") != project_version:
    raise SystemExit(f"Release tag {tag} does not match project version {project_version}")
print(f"Version metadata is consistent: {project_version}")
