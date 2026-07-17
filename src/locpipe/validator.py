from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from .fileio import file_sha256, read_document
from .models import Issue, PairConfig, ProjectConfig
from .tokens import marker_sequence, number_sequence, placeholder_sequence


def _fingerprint_issues(config: ProjectConfig) -> list[Issue]:
    manifest = config.work_root / "INPUT_SHA256.tsv"
    if not manifest.exists():
        return [Issue("corpus", str(manifest), "", "", "FINGERPRINT_MANIFEST_MISSING", "Run locpipe inventory first.")]
    issues: list[Issue] = []
    with manifest.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            stored = Path(row["path"])
            path = stored if stored.is_absolute() else config.base_dir / stored
            if not path.exists():
                issues.append(Issue("corpus", row["path"], "", "", "FROZEN_FILE_MISSING", row["role"]))
            elif file_sha256(path) != row["sha256"]:
                issues.append(Issue("corpus", row["path"], "", "", "FROZEN_FILE_CHANGED", row["role"]))
    return issues


def _target_path(config: ProjectConfig, pair: PairConfig, mode: str) -> Path:
    return config.baseline_root / pair.baseline if mode == "baseline" else config.release_root / pair.output


def validate_pair(config: ProjectConfig, pair: PairConfig, mode: str) -> list[Issue]:
    issues: list[Issue] = []
    source_path = config.source_root / pair.source
    baseline_path = config.baseline_root / pair.baseline
    target_path = _target_path(config, pair, mode)
    if not target_path.exists():
        return [Issue(pair.key, pair.output, "", "", "TARGET_MISSING", str(target_path))]

    source = read_document(source_path)
    baseline = read_document(baseline_path)
    target = read_document(target_path)
    if mode == "release":
        for code, actual, expected in (
            ("ENCODING_CHANGED", target.encoding, baseline.encoding),
            ("BOM_CHANGED", target.bom, baseline.bom),
            ("NEWLINE_STYLE_CHANGED", target.newline, baseline.newline),
            ("FINAL_NEWLINE_CHANGED", target.final_newline, baseline.final_newline),
        ):
            if actual != expected:
                issues.append(Issue(pair.key, pair.output, "", "", code, f"expected {expected!r}, got {actual!r}"))

    if len(source.lines) != len(target.lines):
        issues.append(Issue(pair.key, pair.output, "", "", "LINE_COUNT", f"source={len(source.lines)} target={len(target.lines)}"))

    for line_no, (source_line, target_line) in enumerate(zip(source.lines, target.lines), 1):
        source_fields = source_line.split(pair.delimiter)
        target_fields = target_line.split(pair.delimiter)
        if len(source_fields) != len(target_fields):
            issues.append(
                Issue(pair.key, pair.output, line_no, "", "DELIMITER_OR_FIELD_COUNT", f"source={len(source_fields)} target={len(target_fields)}")
            )
            continue
        baseline_fields = baseline.lines[line_no - 1].split(pair.delimiter) if line_no <= len(baseline.lines) else []
        required = max((*pair.translatable_fields, pair.id_field))
        if required >= len(source_fields):
            issues.append(Issue(pair.key, pair.output, line_no, required, "DECLARED_FIELD_MISSING", "Configured field is outside the source row."))
            continue
        for field, (source_value, target_value) in enumerate(zip(source_fields, target_fields)):
            if field not in pair.translatable_fields:
                if pair.opaque_reference == "baseline" and field < len(baseline_fields):
                    expected = baseline_fields[field]
                else:
                    expected = source_value
                if target_value != expected:
                    issues.append(Issue(pair.key, pair.output, line_no, field, "OPAQUE_FIELD_CHANGED", "Non-translatable field differs."))
                continue

            if source_value in config.locked_values:
                expected = baseline_fields[field] if mode == "release" and field < len(baseline_fields) else source_value
                if target_value != expected:
                    issues.append(Issue(pair.key, pair.output, line_no, field, "LOCKED_VALUE_CHANGED", repr(source_value)))
                continue
            source_markers = marker_sequence(source_value, config.markers)
            target_markers = marker_sequence(target_value, config.markers)
            if source_markers != target_markers:
                issues.append(Issue(pair.key, pair.output, line_no, field, "MARKER_SEQUENCE", f"source={source_markers!r} target={target_markers!r}"))
            source_numbers = number_sequence(source_value)
            target_numbers = number_sequence(target_value)
            if source_numbers != target_numbers:
                issues.append(Issue(pair.key, pair.output, line_no, field, "NUMBER_SEQUENCE", f"source={source_numbers!r} target={target_numbers!r}"))
            source_placeholders = placeholder_sequence(source_value)
            target_placeholders = placeholder_sequence(target_value)
            if source_placeholders != target_placeholders:
                issues.append(
                    Issue(pair.key, pair.output, line_no, field, "PLACEHOLDER_SEQUENCE", f"source={source_placeholders!r} target={target_placeholders!r}")
                )
    return issues


def validate_project(config: ProjectConfig, mode: str, keys: tuple[str, ...] = ()) -> tuple[list[Issue], tuple[PairConfig, ...]]:
    if mode not in {"baseline", "release"}:
        raise ValueError("mode must be baseline or release")
    selected = tuple(pair for pair in config.pairs if not keys or pair.key in keys)
    unknown = sorted(set(keys) - {pair.key for pair in config.pairs})
    if unknown:
        raise ValueError(f"Unknown pair keys: {', '.join(unknown)}")
    issues: list[Issue] = []
    for pair in selected:
        issues.extend(validate_pair(config, pair, mode))
    issues.extend(_fingerprint_issues(config))
    return issues, selected


def render_report(config: ProjectConfig, mode: str, issues: list[Issue], selected: tuple[PairConfig, ...]) -> str:
    counts = Counter(issue.code for issue in issues)
    per_pair: dict[str, int] = defaultdict(int)
    for issue in issues:
        per_pair[issue.pair] += 1
    lines = [
        f"# {mode.capitalize()} localization validation",
        "",
        f"- Project: `{config.name}`",
        f"- Result: **{'PASS' if not issues else 'FAIL'}**",
        f"- Pairs checked: {len(selected)}",
        f"- Issues: {len(issues)}",
        "- Scope: structure, opaque fields, locked values, marker/number/placeholder sequences, release encoding/newlines, and frozen input fingerprints.",
        "- Note: marker-adjacent punctuation is intentionally not mirrored unless a project-specific validator requires it.",
        "",
        "## Issue summary",
        "",
    ]
    if counts:
        lines.extend(("| Code | Count |", "|---|---:|"))
        lines.extend(f"| `{code}` | {count} |" for code, count in sorted(counts.items()))
    else:
        lines.append("No deterministic violations found.")
    lines.extend(("", "## Per-pair results", "", "| Pair | Issues | Result |", "|---|---:|---|"))
    for pair in selected:
        count = per_pair.get(pair.key, 0)
        lines.append(f"| `{pair.key}` | {count} | {'PASS' if count == 0 else 'FAIL'} |")
    corpus_count = per_pair.get("corpus", 0)
    if corpus_count:
        lines.append(f"| `corpus` | {corpus_count} | FAIL |")
    if issues:
        lines.extend(("", "## Exact issues", "", "| Pair | File | Line | Field | Code | Detail |", "|---|---|---:|---:|---|---|"))
        for issue in issues:
            detail = issue.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{issue.pair}` | `{issue.file}` | {issue.line} | {issue.field} | `{issue.code}` | {detail} |")
    return "\n".join(lines) + "\n"


def write_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8", newline="\n")
