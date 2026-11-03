"""Create a private local handoff ZIP with a consistent SQLite backup.

Excludes original pak, cooked asset tree, credentials, local config, venv, downloads,
reference checkout, and other checkpoints. Does not upload or commit anything.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path

ROOT = Path.cwd()


def checkpoint(root: Path, output: Path):
    root, output = root.resolve(), output.resolve()
    if not output.is_relative_to(root):
        raise ValueError("Private checkpoint output must stay inside the project")
    if output.exists():
        raise ValueError("Checkpoint already exists; choose a new filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = []
    directories = ["locpipe", "prompts", "scripts", "tests", "docs", "style", "glossary", ".agents", ".codex", ".claude/commands", ".github", "data/sources", "data/context", "data/inventory", "reports"]
    for directory in directories:
        base = root / directory
        if base.exists():
            files.extend(p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo"))
    for name in ["README.md", "AGENTS.md", "HANDOFF.md", "config.toml", "pyproject.toml",
                 ".gitignore", ".gitattributes", "tools/tools.lock.json", "tools/THIRD-PARTY.md",
                 "data/overrides.json", "work/questions.md"]:
        if (root / name).is_file():
            files.append(root / name)
    # Preserve unfinished work and accepted-result archives; never copy the reference repo.
    for directory in ("work/packets", "work/results", "work/research", "work/prompts", "work/worker-context", "work/orchestration", "work/lqa", "work/provenance", "backups"):
        base = root / directory
        if base.exists():
            files.extend(p for p in base.rglob("*") if p.is_file())
    hashes = {}
    temporary_root = root / "work/checkpoint-tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="locpipe-checkpoint-", dir=temporary_root) as tmp:
        backup = Path(tmp) / "localization.sqlite"
        source = root / "data/localization.sqlite"
        if source.exists():
            with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(backup)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Database backup failed integrity check")
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as z:
            for p in sorted(set(files)):
                name = p.relative_to(root).as_posix()
                data = p.read_bytes()
                z.writestr(name, data)
                hashes[name] = hashlib.sha256(data).hexdigest()
            if backup.exists():
                data = backup.read_bytes()
                z.writestr("data/localization.sqlite", data)
                hashes["data/localization.sqlite"] = hashlib.sha256(data).hexdigest()
            z.writestr("CHECKPOINT.json", json.dumps({"private_game_derived_bundle": True, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": hashes, "recovery": "Extract privately to a new project directory and run locpipe --project <directory> doctor/status. Install the matching toolkit version. Restore game-specific extracted context only from the matching authorized source."}, indent=2))
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None:
            raise ValueError("Checkpoint ZIP CRC check failed")
    return {"path": str(output), "files": len(hashes), "size": output.stat().st_size, "private": True}


if __name__ == "__main__":
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "work/checkpoints" / ("locpipe-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + ".zip")
    print(json.dumps(checkpoint(ROOT, out), indent=2))
