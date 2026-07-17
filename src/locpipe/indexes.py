from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from .fileio import read_document
from .models import ProjectConfig


def _write(path: Path, header: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_indexes(config: ProjectConfig, min_length: int = 12) -> tuple[Path, Path]:
    repeated: dict[str, list[str]] = defaultdict(list)
    sequences: dict[str, list[str]] = defaultdict(list)
    sequence_re = re.compile(r"^(.*?)(\d+)$")

    for pair in config.pairs:
        source = read_document(config.source_root / pair.source)
        for line_no, line in enumerate(source.lines, 1):
            fields = line.split(pair.delimiter)
            row_id = fields[pair.id_field] if pair.id_field < len(fields) else ""
            match = sequence_re.match(row_id)
            if match and match.group(1):
                sequences[f"{pair.key}:{match.group(1)}"].append(f"{pair.key}:{line_no}:{row_id}")
            for field in pair.translatable_fields:
                if field >= len(fields):
                    continue
                value = fields[field].strip()
                if len(value) >= min_length:
                    repeated[value].append(f"{pair.key}:{line_no}:{field}:{row_id}")

    repeated_rows = [
        {"count": len(locations), "source_text": text, "locations": ";".join(locations)}
        for text, locations in repeated.items()
        if len(locations) > 1
    ]
    repeated_rows.sort(key=lambda row: (-int(row["count"]), str(row["source_text"])))
    sequence_rows = [
        {"count": len(locations), "sequence": name, "locations": ";".join(locations)}
        for name, locations in sequences.items()
        if len(locations) >= 3
    ]
    sequence_rows.sort(key=lambda row: (str(row["sequence"]), -int(row["count"])))

    repeated_path = config.reports_root / "REPEATED_SOURCE.tsv"
    sequences_path = config.reports_root / "SEQUENCE_CANDIDATES.tsv"
    _write(repeated_path, ("count", "source_text", "locations"), repeated_rows)
    _write(sequences_path, ("count", "sequence", "locations"), sequence_rows)
    return repeated_path, sequences_path
