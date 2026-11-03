from __future__ import annotations

import re
import unicodedata
from collections import Counter

PLACEHOLDER = re.compile(r"(?<!`)\{([^{}]+)\}")
TAG = re.compile(r"<[^<>\r\n]+>")
PRINTF = re.compile(r"%(?:\d+\$)?[-+#0 ]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[diuoxXfFeEgGaAcsp]")


def placeholders(text):
    # Escaped double braces and Unreal backtick escapes are literal text.
    text = text.replace("{{", "").replace("}}", "")
    return Counter(m.group(1) for m in PLACEHOLDER.finditer(text))


def plain(text):
    return TAG.sub("", text)


def check(source, target, *, kind="unclassified", glossary=(), max_length=None, ratio=1.6, target_culture=None):
    out = []

    def add(code, severity, message):
        out.append({"code": code, "severity": severity, "message": message})

    if not isinstance(target, str) or not target.strip():
        return [{"code": "empty", "severity": "error", "message": "Target must be a non-empty string"}]
    if placeholders(source) != placeholders(target):
        add("placeholders", "error", f"Named/positional arguments differ: {dict(placeholders(source))} vs {dict(placeholders(target))}")
    if TAG.findall(source) != TAG.findall(target):
        add("markup", "error", "RichText/decorator tags or their order/attributes changed")
    if Counter(PRINTF.findall(source)) != Counter(PRINTF.findall(target)):
        add("printf", "error", "Printf placeholders differ")
    if source == "<Empty String>" and target != source:
        add("sentinel", "error", "Shipped empty sentinel must be preserved")
    if any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in target):
        add("control", "error", "Forbidden control character (including NUL)")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in target):
        add("unicode", "error", "Unpaired UTF-16 surrogate")
    if "\ufffd" in target:
        add("unicode", "error", "Unicode replacement character")
    for term in glossary:
        if term.get("status") != "approved":
            continue
        source_forms = term.get("forms_source") or [term["source"]]
        flags = 0 if term.get("case_sensitive") else re.I
        source_match = term.get("source_match", "word")
        if source_match not in ("word", "exact"):
            add("glossary_configuration", "error", f"Invalid source_match for {term.get('id', term['source'])}: {source_match!r}")
            continue
        matches_source = any(
            re.fullmatch(re.escape(form), source, flags) if source_match == "exact"
            else re.search(r"(?<!\w)" + re.escape(form) + r"(?!\w)", source, flags)
            for form in source_forms
        )
        if matches_source:
            forms = term.get("forms_target") or [term.get("target", "")]
            if term.get("do_not_translate"):
                forms = source_forms
            if not any(form and re.search(r"(?<!\w)" + re.escape(form) + r"(?!\w)", target, flags) for form in forms):
                # Everyday-word terms ("Heavy", "Burn") may occur outside the glossary sense:
                # the entry downgrades a miss to a warning that needs a justified acknowledgment.
                severity = "warning" if term.get("qa") == "warning" else "error"
                add("glossary", severity, f"Missing approved form for {term.get('id', term['source'])}: {forms}")
    p_en, p_it = plain(source), plain(target)
    if Counter(re.findall(r"\d+(?:[.,]\d+)?", PLACEHOLDER.sub("", p_en))) != Counter(re.findall(r"\d+(?:[.,]\d+)?", PLACEHOLDER.sub("", p_it))):
        add("numbers", "warning", "Visible numbers changed; verify meaning and locale formatting")
    if max_length and len(p_it) > max_length:
        add("length", "warning", f"{len(p_it)} characters exceeds measured limit {max_length}")
    elif len(p_en) >= 12 and len(p_it) > len(p_en) * ratio:
        add("length", "warning", f"Length is {len(p_it)/len(p_en):.2f} times source-language; inspect the actual widget")
    if source.count("\n") != target.count("\n"):
        add("line_breaks", "warning", "Line/paragraph break count differs")
    if re.search(r"[^\n\r] {2,}[^\n\r]", target):
        add("spaces", "warning", "Repeated spaces")
    if target_culture and target_culture.split("-")[0] == "it" and re.search(r"\b(?:pò|qual'è|qual’é|qual’è)\b", target, re.I):
        add("spelling", "error", "Check Italian po' / qual è spelling")
    if target == source and re.search(r"[A-Za-z]{3}", source):
        add("unchanged", "warning", "Target equals source-language; supply a reason when this is intentional")
    return out


def run(cfg, db, *, source=False):
    import json
    from .config import read_json, write_json

    terms = read_json(cfg.root / "glossary/glossary.json", {"entries": []})["entries"]
    findings = []
    rows = db.rows("SELECT * FROM units WHERE active=1 AND include=1")
    for u in rows:
        if not source and u["target"] is None:
            continue
        data = json.loads(u["data"])
        for f in check(u["source"], u["source"] if source else u["target"], kind=u["kind"], glossary=() if source else terms, max_length=data.get("max_length"), ratio=cfg["qa"]["length_ratio_warning"], target_culture=cfg["project"]["source_culture"] if source else cfg["project"]["target_culture"]):
            if source and f["code"] == "unchanged":
                continue
            findings.append({"sid": u["sid"], **f})
    result = {"mode": "source-self-check" if source else "target", "in_scope": len(rows), "translated": sum(u["target"] is not None for u in rows), "missing": sum(u["target"] is None for u in rows), "stale": sum(u["stale"] for u in rows), "errors": sum(f["severity"] == "error" for f in findings), "warnings": sum(f["severity"] == "warning" for f in findings), "findings": findings}
    write_json(cfg.root / "reports" / ("qa-source.json" if source else "qa.json"), result)
    return result
