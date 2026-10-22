"""Resolve bundled Cactus model and engine, with no network fallback in frozen builds."""
import os
import sys
from pathlib import Path


def configure_bundled_runtime():
    root = Path(__file__).resolve().parent.parent
    assets = root / "assets"
    if not assets.is_dir():
        return
    if not getattr(sys, "frozen", False) and not (assets / "model").is_dir() and not (assets / "engine").is_dir():
        return
    weights = list((assets / "model").rglob("whistle.cact"))
    if len(weights) != 1:
        raise RuntimeError(f"Expected one bundled whistle.cact under {assets / 'model'}, got {len(weights)}")
    engine_dir = assets / "engine"
    libs = [x for x in engine_dir.rglob("*") if x.is_file() and
            (x.name.lower().startswith("libneedle") and x.suffix in (".so", ".dylib") or
             x.name.lower() in ("needle.dll", "needle3.dll", "libneedle.dll", "libneedle3.dll"))]
    if len(libs) != 1:
        raise RuntimeError(f"Expected one bundled Cactus engine library under {engine_dir}, got {libs}")
    os.environ["NEEDLE_WHISTLE_WEIGHTS"] = str(weights[0])
    os.environ["NEEDLE3_LIB_PATH"] = str(libs[0])
    os.environ["HF_HUB_OFFLINE"] = "1"
