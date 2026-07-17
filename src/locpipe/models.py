from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PairConfig:
    key: str
    source: str
    baseline: str
    output: str
    schema: str
    delimiter: str
    id_field: int
    translatable_fields: tuple[int, ...]
    field_labels: tuple[str, ...]
    confidence: str
    opaque_reference: str


@dataclass(frozen=True)
class ProjectConfig:
    config_path: Path
    base_dir: Path
    name: str
    source_root: Path
    baseline_root: Path
    release_root: Path
    work_root: Path
    reports_root: Path
    references: tuple[Path, ...]
    markers: tuple[str, ...]
    locked_values: tuple[str, ...]
    pairs: tuple[PairConfig, ...]

    def pair(self, key: str) -> PairConfig:
        for pair in self.pairs:
            if pair.key == key:
                return pair
        raise KeyError(key)


@dataclass(frozen=True)
class Issue:
    pair: str
    file: str
    line: int | str
    field: int | str
    code: str
    detail: str
