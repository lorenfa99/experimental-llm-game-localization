"""Audit glossary/glossary.json against the in-scope corpus; the database is opened read-only.

Checks, in order:
  1. entry shape: unique ids, types of every field the QA and worker views read, an approved
     entry has a target or do_not_translate, valid source_match, well-formed examples;
  2. form hygiene: no notes, parentheses, slashes or arrows inside forms, no duplicates;
  3. match counts of every approved entry over the active, included units, using the exact rule
     of `qa.term_matches`; zero-match and very-high-match entries are flagged for a human;
  4. synthetic QA: every example "source → target" whose source contains a form of its own entry
     must pass `qa.check` for that entry. The same examples run against the whole glossary give
     informational cross-entry findings. `require_examples` makes a missing example blocking;
  5. when characters carry `name_forms`, each form should appear in some glossary example.

Blocking problems (1, 2 and 4) make the command exit 1. A match count is evidence for the
terminologist, not a verdict: an everyday word legitimately matches many units.
The report keeps hand-written text outside its <!-- audit:begin/end --> markers.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from . import qa
from .config import HarnessError, read_json
from .orchestration import run_cli

BEGIN, END = "<!-- audit:begin -->", "<!-- audit:end -->"
ARROW = " → "
LIST_FIELDS = ("forms_source", "forms_target", "alternatives", "evidence", "examples")
BOOL_FIELDS = ("case_sensitive", "do_not_translate")


def split_example(example):
    if not isinstance(example, str) or example.count(ARROW) != 1:
        return None
    source, target = example.split(ARROW)
    return source.strip(), target.strip()


def severity(entry):
    if entry.get("status") != "approved":
        return "inactive"
    return "warning" if entry.get("qa") == "warning" else "error"


def entry_regex(entry):
    flags = 0 if entry.get("case_sensitive") else re.I
    forms = [re.escape(f) for f in (entry.get("forms_source") or [entry["source"]]) if f]
    body = "|".join(forms)
    return re.compile(f"^(?:{body})$" if entry.get("source_match", "word") == "exact" else r"(?<!\w)(?:" + body + r")(?!\w)", flags)


def snippet(text, rx, width=56):
    flat = re.sub(r"\s+", " ", text)
    match = rx.search(flat)
    if not match:
        return flat[:width]
    pad = max(0, (width - (match.end() - match.start())) // 2)
    a, b = max(0, match.start() - pad), min(len(flat), match.end() + pad)
    return ("…" if a else "") + flat[a:b].strip() + ("…" if b < len(flat) else "")


def md(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def shape_problems(document):
    entries = document.get("entries")
    if not isinstance(entries, list):
        return ["top level: 'entries' must be an array"]
    problems = []
    ids = Counter(e.get("id") for e in entries if isinstance(e, dict))
    problems += [f"duplicate id {i!r}" for i, n in ids.items() if n > 1]
    for e in entries:
        if not isinstance(e, dict):
            problems.append(f"entry is not an object: {e!r}")
            continue
        name = e.get("id")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"entry without a text id: {e.get('source')!r}")
            continue
        if not isinstance(e.get("source"), str) or not e["source"].strip():
            problems.append(f"{name}: needs a non-empty source")
        if not isinstance(e.get("status"), str):
            problems.append(f"{name}: needs a status")
        for field in LIST_FIELDS:
            value = e.get(field, [])
            if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
                problems.append(f"{name}: {field} must be an array of non-empty text")
        for field in BOOL_FIELDS:
            if field in e and not isinstance(e[field], bool):
                problems.append(f"{name}: {field} must be true or false")
        if e.get("source_match", "word") not in ("word", "exact"):
            problems.append(f"{name}: source_match must be 'word' or 'exact'")
        if e.get("qa") not in (None, "warning", "error"):
            problems.append(f"{name}: qa must be absent, 'warning' or 'error'")
        problems += [f"{name}: example without exactly one '{ARROW.strip()}': {x!r}" for x in e.get("examples", []) if split_example(x) is None]
        if e.get("status") == "approved":
            if not (isinstance(e.get("target"), str) and e["target"].strip()) and not e.get("do_not_translate"):
                problems.append(f"{name}: approved without a target (gate rule)")
            if e.get("do_not_translate") and e.get("forms_target") and e.get("forms_source") and e["forms_target"] != e["forms_source"]:
                problems.append(f"{name}: do_not_translate but forms_target differ from forms_source (QA uses forms_source)")
    return problems


def hygiene_problems(entries):
    bad = re.compile(r"[()]|/|→|^\s|\s$")
    problems = []
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str):
            continue
        for field in ("forms_target", "forms_source"):
            forms = [f for f in e.get(field, []) if isinstance(f, str)]
            problems += [f"{e['id']}: {field} {f!r}" for f in forms if bad.search(f)]
            if len(set(forms)) != len(forms):
                problems.append(f"{e['id']}: duplicate {field}")
    return problems


def audit(cfg, db, glossary=None, report=None, high=40, require_examples=False, write_report=True):
    path = Path(glossary) if glossary else cfg.root / "glossary/glossary.json"
    document = read_json(path)
    if not isinstance(document, dict):
        raise HarnessError(f"Cannot read a glossary object from {path}")
    entries = document.get("entries") if isinstance(document.get("entries"), list) else []
    blocking = defaultdict(list)
    blocking["shape"] = shape_problems(document)
    if blocking["shape"]:
        entries = [e for e in entries if isinstance(e, dict) and isinstance(e.get("id"), str) and isinstance(e.get("source"), str)
                   and not any(p.startswith(e["id"] + ":") for p in blocking["shape"])]
    blocking["hygiene"] = hygiene_problems(entries)
    approved = [e for e in entries if e.get("status") == "approved"]
    units = db.rows("SELECT sid,key,kind,source FROM units WHERE active=1 AND include=1 ORDER BY sid")
    hits = {e["id"]: [u for u in units if qa.term_matches(e, u["source"])] for e in approved}

    own_failures, without_example, cross = [], [], []
    for e in approved:
        tested = 0
        for example in e.get("examples", []):
            source, target = split_example(example) or (None, None)
            if source is None:
                continue
            if qa.term_matches(e, source):
                tested += 1
                found = [f for f in qa.check(source, target, glossary=[e]) if f["code"] == "glossary"]
                if found:
                    own_failures.append(f"{e['id']}: {example!r} → {found[0]['message']}")
            cross += [(e["id"], example, f["severity"], f["message"]) for f in qa.check(source, target, glossary=approved)
                      if f["code"] == "glossary" and not f["message"].startswith(f"Missing approved form for {e['id']}:")]
        if not tested:
            without_example.append(e["id"])
    blocking["own examples"] = own_failures
    if require_examples:
        blocking["no matching example"] = [f"{i}: no example contains one of its source forms" for i in without_example]

    name_forms_missing, name_forms_checked = [], 0
    targets = [pair[1] for e in approved for x in e.get("examples", []) for pair in [split_example(x)] if pair]
    characters = read_json(cfg.root / "style/characters.json", {"characters": []}).get("characters", [])
    for c in characters:
        for field, value in ((c.get("name_forms") or {}).items() if isinstance(c.get("name_forms"), dict) else ()):
            if field == "note" or not isinstance(value, str):
                continue
            form = value.split(";")[0].strip()
            name_forms_checked += 1
            if form and not any(form in t for t in targets):
                name_forms_missing.append(f"{c.get('id')}.{field}: {form!r}")

    level = {e["id"]: severity(e) for e in entries}
    zero = [e for e in approved if not hits[e["id"]]]
    heavy = [e for e in approved if level[e["id"]] == "error" and len(hits[e["id"]]) >= high]
    blocking_count = sum(len(v) for v in blocking.values())
    result = {"glossary": str(path), "entries": len(entries), "approved": len(approved), "in_scope_units": len(units),
              "blocking_problems": blocking_count, "blocking": {k: v[:20] for k, v in blocking.items() if v},
              "zero_match_entries": [e["id"] for e in zero], "very_high_match_entries": [e["id"] for e in heavy],
              "entries_without_matching_example": len(without_example), "cross_entry_findings": len(cross),
              "name_forms_checked": name_forms_checked, "name_forms_not_in_examples": len(name_forms_missing)}
    if write_report:
        target = Path(report) if report else cfg.root / "reports/glossary-audit.md"
        block = _report(path, document, units, entries, approved, level, blocking, hits, zero, heavy, high, cross, without_example,
                        require_examples, name_forms_checked, name_forms_missing)
        previous = target.read_text(encoding="utf-8") if target.exists() else None
        if previous and BEGIN in previous and END in previous:
            text = previous[: previous.index(BEGIN)] + block + previous[previous.index(END) + len(END):]
        else:
            text = (previous.rstrip() + "\n\n" if previous else "# Glossary audit\n\n") + block + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        result["report"] = str(target)
    return result


def _report(path, document, units, entries, approved, level, blocking, hits, zero, heavy, high, cross, without_example,
            require_examples, checked, missing):
    totals = Counter(level.values())
    out = [BEGIN, "## Automated audit", "",
           f"Generated by `python scripts/glossary_audit.py` from `{path.name}` (top-level status `{document.get('status')}`) "
           f"against {len(units)} in-scope units, read-only. A match count is evidence for a human, not a verdict.", "",
           f"Entries: {len(entries)} ({len(approved)} approved, {len(entries) - len(approved)} inactive). "
           f"Blocking problems: **{sum(len(v) for v in blocking.values())}**. "
           f"QA-active by severity: {totals['error']} error, {totals['warning']} warning.", "", "### Blocking checks", ""]
    labels = {"shape": "Entry shape", "hygiene": "Form hygiene", "own examples": "Own-example QA",
              "no matching example": "Approved entries without a matching example"}
    for key, label in labels.items():
        if key == "no matching example" and not require_examples:
            continue
        items = blocking.get(key, [])
        out.append(f"- {label}: {'OK' if not items else f'**{len(items)} problem(s)**'}")
        out += [f"  - {md(x)}" for x in items[:40]]
    if not require_examples:
        out.append(f"- Approved entries without a matching example: {len(without_example)} (informational; use --require-examples to block)")
    out += ["", "### Zero-match entries", "",
            "Approved entries whose forms do not occur in the current in-scope source. Keep them only with a recorded reason "
            "(decision-mandated form, source variant, future-proofing).", ""]
    if zero:
        out += ["| id | qa | forms_source | notes |", "|---|---|---|---|"]
        out += [f"| {e['id']} | {level[e['id']]} | {md(', '.join(e.get('forms_source') or [e['source']]))} | {md(e.get('notes', ''))} |" for e in zero]
    else:
        out.append("None.")
    out += ["", f"### Very-high-match error entries (≥ {high} units)", ""]
    if heavy:
        out += ["| id | units | forms_source | samples |", "|---|---:|---|---|"]
        for e in heavy:
            rx = entry_regex(e)
            out.append(f"| {e['id']} | {len(hits[e['id']])} | {md(', '.join(e.get('forms_source') or [e['source']]))} | "
                       + "; ".join(f"{u['sid']} {md(snippet(u['source'], rx, 44))}" for u in hits[e['id']][:3]) + " |")
    else:
        out.append("None.")
    out += ["", "### Cross-entry findings on the examples (informational)", "",
            "Each example run through `qa.check` with the whole approved glossary; findings from *other* entries. "
            "Examples are phrase fragments, so a finding means the fragment is incomplete or two entries overlap.", ""]
    if cross:
        out += ["| example of | example | severity | finding |", "|---|---|---|---|"]
        out += [f"| {i} | {md(x)} | {s} | {md(m)} |" for i, x, s, m in cross]
    else:
        out.append("None.")
    out += ["", "### Character name forms", ""]
    if not checked:
        out.append("No character carries `name_forms`; nothing to compare.")
    elif missing:
        out += [f"{checked} name forms checked; not found in any glossary example:"] + [f"- {md(x)}" for x in missing]
    else:
        out.append(f"All {checked} `name_forms` values appear verbatim in glossary examples.")
    out += ["", "### Match counts", "", "| id | qa | case | units |", "|---|---|---|---:|"]
    out += [f"| {e['id']} | {level[e['id']]} | {'sensitive' if e.get('case_sensitive') else 'insensitive'} | {len(hits[e['id']])} |" for e in approved]
    out += ["", END]
    return "\n".join(out)


# ------------------------------------------------------------------------ CLI
def _args(p):
    p.add_argument("--glossary", type=Path, help="Default: glossary/glossary.json")
    p.add_argument("--report", type=Path, help="Default: reports/glossary-audit.md")
    p.add_argument("--no-report", action="store_true", help="Print only")
    p.add_argument("--high", type=int, default=40, help="Flag error entries matching at least this many units")
    p.add_argument("--require-examples", action="store_true", help="Every approved entry needs a matching example that passes QA")


def _run(cfg, db, a):
    result = audit(cfg, db, a.glossary, a.report, a.high, a.require_examples, not a.no_report)
    return result, 1 if result["blocking_problems"] else 0


COMMANDS = {"audit": (__doc__, _args, True, _run)}


def main(argv=None):
    return run_cli(COMMANDS, "audit", argv)
