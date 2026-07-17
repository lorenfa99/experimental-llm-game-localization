from __future__ import annotations

import tomllib
from pathlib import Path

from .models import PairConfig, ProjectConfig


DEFAULT_MARKERS = ("<<", ">>", "[[", "]]", "((", "))", "##", "#", "@@", "%%", "&&")


def _resolved(base: Path, value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def load_config(path: str | Path) -> ProjectConfig:
    config_path = Path(path).resolve()
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)

    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError("project.toml must contain a [project] table")
    base = config_path.parent
    required_paths = ("source_root", "baseline_root", "release_root", "work_root", "reports_root")
    missing = [name for name in required_paths if name not in project]
    if missing:
        raise ValueError(f"Missing [project] path settings: {', '.join(missing)}")

    default_delimiter = str(project.get("delimiter", "|"))
    if not default_delimiter:
        raise ValueError("The project delimiter cannot be empty")

    raw_pairs = data.get("pairs", [])
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise ValueError("project.toml must declare at least one [[pairs]] table")

    pairs: list[PairConfig] = []
    seen: set[str] = set()
    for raw in raw_pairs:
        fields = tuple(int(value) for value in raw.get("translatable_fields", ()))
        if not fields:
            raise ValueError(f"Pair {raw.get('key')!r} has no translatable_fields")
        if len(set(fields)) != len(fields) or min(fields) < 0:
            raise ValueError(f"Pair {raw.get('key')!r} has invalid translatable_fields")
        labels = tuple(str(value) for value in raw.get("field_labels", ()))
        if labels and len(labels) != len(fields):
            raise ValueError(f"Pair {raw.get('key')!r} field_labels must match translatable_fields")
        if not labels:
            labels = tuple(f"field_{field}" for field in fields)
        key = str(raw["key"])
        if key in seen:
            raise ValueError(f"Duplicate pair key: {key}")
        seen.add(key)
        opaque_reference = str(raw.get("opaque_reference", "source")).lower()
        if opaque_reference not in {"source", "baseline"}:
            raise ValueError(f"Pair {key!r}: opaque_reference must be source or baseline")
        baseline = str(raw["baseline"])
        pairs.append(
            PairConfig(
                key=key,
                source=str(raw["source"]),
                baseline=baseline,
                output=str(raw.get("output", baseline)),
                schema=str(raw.get("schema", "delimited")),
                delimiter=str(raw.get("delimiter", default_delimiter)),
                id_field=int(raw.get("id_field", 0)),
                translatable_fields=fields,
                field_labels=labels,
                confidence=str(raw.get("confidence", "explicit")).lower(),
                opaque_reference=opaque_reference,
            )
        )

    references = tuple(_resolved(base, str(value)) for value in project.get("references", ()))
    markers = tuple(str(value) for value in project.get("markers", DEFAULT_MARKERS))
    if len(set(markers)) != len(markers) or any(not value for value in markers):
        raise ValueError("Protected markers must be non-empty and unique")

    return ProjectConfig(
        config_path=config_path,
        base_dir=base,
        name=str(project.get("name", base.name)),
        source_root=_resolved(base, str(project["source_root"])),
        baseline_root=_resolved(base, str(project["baseline_root"])),
        release_root=_resolved(base, str(project["release_root"])),
        work_root=_resolved(base, str(project["work_root"])),
        reports_root=_resolved(base, str(project["reports_root"])),
        references=references,
        markers=markers,
        locked_values=tuple(str(value) for value in project.get("locked_values", ("", "null"))),
        pairs=tuple(pairs),
    )
