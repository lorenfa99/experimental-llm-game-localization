"""Portable repak integration. All extraction and packaging stay inside the project."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path, PurePosixPath

from .config import Config, HarnessError, file_hash, read_json


def safe_name(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise HarnessError("Label must be 1–64 letters, digits, underscores or hyphens")
    return name


def safe_entry(name: str):
    p = PurePosixPath(name.replace("\\", "/"))
    if not name or p.is_absolute() or ".." in p.parts or ":" in name:
        raise HarnessError(f"Unsafe pak entry: {name!r}")
    return p


def repak(cfg: Config, *args, binary=False):
    exe = cfg.path(cfg["tools"]["repak"])
    if not exe.is_file():
        raise HarnessError("repak is missing. Run python scripts/bootstrap_tools.py only when the optional Unreal tool is authorized.")
    lock = read_json(cfg.root / "tools/tools.lock.json", {})
    expected = lock.get("windows_exe_sha256") if os.name == "nt" else None
    if expected and file_hash(exe) != expected:
        raise HarnessError("repak executable hash differs from tools/tools.lock.json")
    r = subprocess.run([str(exe), *map(str, args)], capture_output=True)
    if r.returncode:
        raise HarnessError(r.stderr.decode("utf-8", errors="replace").strip() or "repak failed")
    return r.stdout if binary else r.stdout.decode("utf-8-sig").strip()


def discover(cfg):
    install_dir = cfg["game"].get("steam_install_dir")
    if not install_dir:
        raise HarnessError("Set game.steam_install_dir for discovery, or provide an explicit game root")
    safe_entry(install_dir)
    if len(PurePosixPath(install_dir).parts) != 1:
        raise HarnessError("steam_install_dir must name one Steam common directory")
    roots = []
    for base in [Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam", Path("C:/Program Files/Steam")]:
        if not base.is_dir():
            continue
        roots.append(base)
        vdf = base / "steamapps/libraryfolders.vdf"
        if vdf.exists():
            roots.extend(Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8")))
    found = []
    for library in dict.fromkeys(roots):
        common = library / "steamapps/common"
        if common.is_dir():
            found.extend(str(p) for p in common.iterdir() if p.is_dir() and p.name.casefold() == install_dir.casefold())
    return sorted(set(found))


def list_paks(cfg: Config, game: Path):
    pak_dir = game / cfg["game"]["pak_relative"]
    if list(pak_dir.glob("*.utoc")) or list(pak_dir.glob("*.ucas")):
        raise HarnessError("IoStore detected (.utoc/.ucas). This adapter only supports .pak; inspect the full-game format before proceeding.")
    paths = sorted(pak_dir.glob("*.pak"))
    # Do not import a fan overlay as native game text.
    if any(p.name.endswith("_P.pak") for p in paths):
        raise HarnessError("Patch/mod _P.pak detected. Inspect/remove overlays before capturing a vanilla baseline.")
    if len(paths) != 1:
        raise HarnessError(f"Expected one vanilla pak; found {len(paths)}. Multi-pak mount precedence needs explicit adapter support.")
    info = repak(cfg, "info", paths[0])
    if "encrypted index: true" in info:
        raise HarnessError("Encrypted pak index: authorized game-specific keys/tooling required; no extraction attempted.")
    entries = repak(cfg, "list", paths[0]).splitlines()
    for name in entries:
        safe_entry(name)
    return paths, entries, info


def extract_pak(cfg: Config, pak: Path, output: Path):
    output = output.resolve()
    if not output.is_relative_to(cfg.root):
        raise HarnessError("Extraction output must stay inside the project")
    output.mkdir(parents=True, exist_ok=True)
    return repak(cfg, "unpack", pak, "-o", output, "-f", "-i", cfg["game"]["project_dir"], "-i", "Engine/Content/Localization", "-i", "Engine/Content/Slate/Fonts")
