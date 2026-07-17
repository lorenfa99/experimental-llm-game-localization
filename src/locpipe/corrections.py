from __future__ import annotations

import csv
import json
from pathlib import Path

from .fileio import read_document, write_like
from .models import PairConfig, ProjectConfig


CHANGE_HEADER = ("file", "line", "id", "field", "source", "old_target", "new_target", "category", "reason")


def load_jsonl(path: str | Path) -> list[dict]:
    records: list[dict] = []
    for line_no, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return records


def _label(pair: PairConfig, field: int) -> str:
    return pair.field_labels[pair.translatable_fields.index(field)]


def _existing_changes(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _write_changes(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CHANGE_HEADER, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _apply_pair(config: ProjectConfig, pair: PairConfig, records: list[dict]) -> list[dict[str, object]]:
    source = read_document(config.source_root / pair.source)
    baseline = read_document(config.baseline_root / pair.baseline)
    if len(source.lines) != len(baseline.lines):
        raise ValueError(f"{pair.key}: source and baseline line counts differ")
    source_lines = list(source.lines)
    target_lines = list(baseline.lines)
    changes: list[dict[str, object]] = []

    structural = [record for record in records if record.get("operation") == "restore_schema_from_source"]
    if len(structural) > 1:
        raise ValueError(f"{pair.key}: duplicate restore_schema_from_source operation")
    if structural:
        rebuilt: list[str] = []
        reason = str(structural[0].get("reason", "Restore source schema while retaining approved translated fields."))
        for line_no, (source_line, target_line) in enumerate(zip(source_lines, target_lines), 1):
            source_fields = source_line.split(pair.delimiter)
            target_fields = target_line.split(pair.delimiter)
            new_fields = source_fields[:]
            for field in pair.translatable_fields:
                if field >= len(target_fields):
                    raise ValueError(f"{pair.key}:{line_no}: baseline lacks translated field {field}")
                new_fields[field] = target_fields[field]
            new_line = pair.delimiter.join(new_fields)
            rebuilt.append(new_line)
            if new_line != target_line:
                row_id = source_fields[pair.id_field] if pair.id_field < len(source_fields) else ""
                changes.append(
                    {
                        "file": pair.output,
                        "line": line_no,
                        "id": row_id,
                        "field": "structure",
                        "source": source_line,
                        "old_target": target_line,
                        "new_target": new_line,
                        "category": "technical_structure",
                        "reason": reason,
                    }
                )
        target_lines = rebuilt

    seen: set[tuple[int, int]] = set()
    for record in records:
        if record.get("operation"):
            continue
        line_no = int(record["line"])
        field = int(record["field"])
        key = (line_no, field)
        if key in seen:
            raise ValueError(f"{pair.key}:{line_no}:{field}: duplicate correction")
        seen.add(key)
        if field not in pair.translatable_fields:
            raise ValueError(f"{pair.key}:{line_no}:{field}: field is not translatable")
        if not 1 <= line_no <= len(target_lines):
            raise ValueError(f"{pair.key}:{line_no}: line is outside the file")
        source_fields = source_lines[line_no - 1].split(pair.delimiter)
        target_fields = target_lines[line_no - 1].split(pair.delimiter)
        if field >= len(source_fields) or field >= len(target_fields):
            raise ValueError(f"{pair.key}:{line_no}:{field}: field is outside the row")
        row_id = source_fields[pair.id_field] if pair.id_field < len(source_fields) else ""
        expected_id = record.get("id")
        if expected_id is not None and str(expected_id) != row_id:
            raise ValueError(f"{pair.key}:{line_no}: expected ID {expected_id!r}, found {row_id!r}")
        old = target_fields[field]
        if "replacements" in record:
            new = old
            replacements = record["replacements"]
            if not isinstance(replacements, list) or not replacements:
                raise ValueError(f"{pair.key}:{line_no}:{field}: invalid replacements list")
            for replacement in replacements:
                needle = str(replacement["old"])
                substitute = str(replacement["new"])
                expected_count = int(replacement.get("count", 1))
                actual_count = new.count(needle)
                if actual_count != expected_count:
                    raise ValueError(
                        f"{pair.key}:{line_no}:{field}: {needle!r} occurs {actual_count} times, expected {expected_count}"
                    )
                new = new.replace(needle, substitute)
        else:
            if str(record.get("old")) != old:
                raise ValueError(f"{pair.key}:{line_no}:{field}: old text does not match the approved baseline")
            new = str(record["new"])
        if new == old:
            raise ValueError(f"{pair.key}:{line_no}:{field}: no-op correction")
        target_fields[field] = new
        target_lines[line_no - 1] = pair.delimiter.join(target_fields)
        changes.append(
            {
                "file": pair.output,
                "line": line_no,
                "id": row_id,
                "field": _label(pair, field),
                "source": source_fields[field],
                "old_target": old,
                "new_target": new,
                "category": str(record["category"]),
                "reason": str(record["reason"]),
            }
        )

    write_like(config.release_root / pair.output, target_lines, baseline)
    return sorted(changes, key=lambda row: (int(row["line"]), str(row["field"])))


def apply_corrections(
    config: ProjectConfig, corrections_path: str | Path, keys: tuple[str, ...] = ()
) -> tuple[int, tuple[PairConfig, ...]]:
    records = load_jsonl(corrections_path)
    selected = tuple(pair for pair in config.pairs if not keys or pair.key in keys)
    unknown = sorted(set(keys) - {pair.key for pair in config.pairs})
    if unknown:
        raise ValueError(f"Unknown pair keys: {', '.join(unknown)}")
    known_pairs = {pair.key for pair in config.pairs}
    record_pairs = {str(record.get("pair")) for record in records}
    unknown_records = sorted(record_pairs - known_pairs)
    if unknown_records:
        raise ValueError(f"Corrections reference unknown pairs: {', '.join(unknown_records)}")

    changes_path = config.reports_root / "CHANGES.tsv"
    selected_outputs = {pair.output for pair in selected}
    retained = [row for row in _existing_changes(changes_path) if row.get("file") not in selected_outputs]
    new_changes: list[dict[str, object]] = []
    for pair in selected:
        pair_records = [record for record in records if record.get("pair") == pair.key]
        new_changes.extend(_apply_pair(config, pair, pair_records))
    _write_changes(changes_path, retained + new_changes)
    return len(new_changes), selected
