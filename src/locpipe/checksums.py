from __future__ import annotations

from pathlib import Path

from .fileio import file_sha256
from .models import ProjectConfig


def write_checksums(config: ProjectConfig) -> Path:
    entries: list[tuple[str, str]] = []
    for pair in config.pairs:
        path = config.release_root / pair.output
        if not path.is_file():
            raise FileNotFoundError(f"Missing release output: {path}")
        entries.append((pair.output, file_sha256(path)))
    output = config.release_root / "SHA256SUMS.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{digest}  {name}\n" for name, digest in sorted(entries))
    output.write_text(text, encoding="utf-8", newline="\n")
    return output
