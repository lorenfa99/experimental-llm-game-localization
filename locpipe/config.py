from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class HarnessError(Exception):
    """An actionable error; the CLI reports target without a traceback."""


def digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


class Config:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root).resolve()
        self.values = tomllib.loads((self.root / "config.toml").read_text(encoding="utf-8-sig"))
        local = self.root / "config.local.toml"
        if local.exists():
            for section, values in tomllib.loads(local.read_text(encoding="utf-8-sig")).items():
                self.values.setdefault(section, {}).update(values)
        for name in ("source_culture", "target_culture"):
            value = self["project"].get(name)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
                raise HarnessError(f"project.{name} must be a culture code without path components")
        for name in ("project_dir", "localization_target"):
            value = self["game"].get(name)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
                raise HarnessError(f"game.{name} must be a single safe path component")
        filename = self["build"]["filename"]
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", filename):
            raise HarnessError("build.filename must be a single safe filename")
        for name in ("max_units", "max_words", "batch_packets", "batch_max_input_bytes"):
            value = self["packets"][name]
            if type(value) is not int or value <= 0:
                raise HarnessError(f"packets.{name} must be a positive integer")

    def __getitem__(self, key):
        return self.values[key]

    def path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else self.root / p

    def game_root(self, override: str | None = None) -> Path:
        value = override or self["game"].get("root")
        if not value:
            raise HarnessError("No game root. Run `locpipe discover`, then pass --game-root or set config.local.toml.")
        root = self.path(value).resolve()
        if not (root / self["game"]["pak_relative"]).is_dir():
            raise HarnessError(f"Missing game Paks directory under {root}")
        return root

    def require_translation(self):
        if self["project"]["preparation_only"]:
            raise HarnessError("PREPARATION ONLY: target edits, linguistic packets and release builds are disabled. Await the owner's instruction to start translation.")

    def contract_hash(self) -> str:
        names = ["config.toml", "style/style-guide.md", "style/characters.json", "glossary/glossary.json", "docs/MULTILINGUAL-REFERENCES.md", "data/overrides.json"]
        return digest(json.dumps({name: file_hash(self.root / name) for name in names if (self.root / name).exists()}, sort_keys=True) + json.dumps(self.values, sort_keys=True))
