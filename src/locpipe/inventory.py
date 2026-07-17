from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .fileio import file_sha256, read_document
from .models import ProjectConfig


MANIFEST_HEADER = (
    "pair",
    "source",
    "baseline",
    "output",
    "schema",
    "delimiter",
    "translatable_fields",
    "field_labels",
    "id_field",
    "opaque_reference",
    "confidence",
    "source_encoding",
    "source_bom",
    "source_newline",
    "source_final_newline",
    "baseline_encoding",
    "baseline_bom",
    "baseline_newline",
    "baseline_final_newline",
    "source_lines",
    "baseline_lines",
    "source_field_shapes",
    "baseline_field_shapes",
    "source_sha256",
    "baseline_sha256",
)


def _display(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _shape(lines: tuple[str, ...], delimiter: str) -> str:
    counts = Counter(len(line.split(delimiter)) for line in lines)
    return ",".join(f"{fields}x{count}" for fields, count in sorted(counts.items()))


def _write_tsv(path: Path, header: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_inventory(config: ProjectConfig) -> tuple[Path, Path]:
    manifest_rows: list[dict[str, object]] = []
    frozen_rows: list[dict[str, object]] = []
    frozen_seen: set[Path] = set()

    def freeze(role: str, path: Path) -> None:
        resolved = path.resolve()
        if resolved in frozen_seen:
            return
        if not resolved.is_file():
            raise FileNotFoundError(f"Missing {role} file: {resolved}")
        frozen_seen.add(resolved)
        frozen_rows.append({"role": role, "path": _display(resolved, config.base_dir), "sha256": file_sha256(resolved)})

    for pair in config.pairs:
        source_path = config.source_root / pair.source
        baseline_path = config.baseline_root / pair.baseline
        source = read_document(source_path)
        baseline = read_document(baseline_path)
        freeze("source", source_path)
        freeze("baseline", baseline_path)
        manifest_rows.append(
            {
                "pair": pair.key,
                "source": _display(source_path, config.base_dir),
                "baseline": _display(baseline_path, config.base_dir),
                "output": _display(config.release_root / pair.output, config.base_dir),
                "schema": pair.schema,
                "delimiter": pair.delimiter,
                "translatable_fields": ",".join(map(str, pair.translatable_fields)),
                "field_labels": ",".join(pair.field_labels),
                "id_field": pair.id_field,
                "opaque_reference": pair.opaque_reference,
                "confidence": pair.confidence,
                "source_encoding": source.encoding,
                "source_bom": source.bom,
                "source_newline": source.newline,
                "source_final_newline": str(source.final_newline).lower(),
                "baseline_encoding": baseline.encoding,
                "baseline_bom": baseline.bom,
                "baseline_newline": baseline.newline,
                "baseline_final_newline": str(baseline.final_newline).lower(),
                "source_lines": len(source.lines),
                "baseline_lines": len(baseline.lines),
                "source_field_shapes": _shape(source.lines, pair.delimiter),
                "baseline_field_shapes": _shape(baseline.lines, pair.delimiter),
                "source_sha256": file_sha256(source_path),
                "baseline_sha256": file_sha256(baseline_path),
            }
        )

    for reference in config.references:
        freeze("reference", reference)

    manifest = config.work_root / "MANIFEST.tsv"
    fingerprints = config.work_root / "INPUT_SHA256.tsv"
    _write_tsv(manifest, MANIFEST_HEADER, manifest_rows)
    _write_tsv(fingerprints, ("role", "path", "sha256"), frozen_rows)
    return manifest, fingerprints
