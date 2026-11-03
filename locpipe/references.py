"""Focused, version-matched official-language lookup for source disambiguation."""
from __future__ import annotations

from .config import HarnessError

INSTRUCTIONS = [
    "Interpret source-language and verified scene evidence first. When referents, gender/number, polysemy, lore or mechanics are ambiguous, compare the matching official references.",
    "Use preferred available languages first, then fetch other available cultures with the unit's reference_lookup command when they can clarify the same question.",
    "References are evidence, not authority or independent votes. Do not copy foreign phrasing into target-language, overrule source-language by majority vote, or infer a person's gender from an object's grammatical gender.",
    "Only the same snapshot/namespace/key/source-hash revision is usable. Empty/sentinel, pseudo and stale references are excluded. Source-identical text is labelled and adds no independent wording evidence.",
    "When references affect a decision, record reference_checks with question, cultures, finding and status. Cite the actual comparison; do not claim certainty from a source-hash match alone.",
    "If meaningful ambiguity remains or languages conflict without adequate source-language/context evidence, preserve the draft and raise the specific question. A reviewer records an issue; a writer must not submit a guessed resolution.",
    "In preparation-only mode research the source and reference evidence only; keep every target-language target null.",
]


def policy(cfg):
    settings = cfg.values.get("references", {})
    return {
        "preferred_cultures": settings.get("preferred_cultures", ["fr", "es-419", "pt-BR", "de"]),
        "excluded_cultures": settings.get("excluded_cultures", ["en-US-POSIX"]),
        "packet_primary_limit": settings.get("packet_primary_limit", 4),
    }


def lookup(cfg, db, sid, *, snapshot=None, cultures=None, include_unusable=False):
    unit = db.unit(sid)
    snapshot = snapshot or db.active_snapshot()[0]
    source = db.one("SELECT * FROM snapshot_units WHERE snapshot=? AND sid=?", (snapshot, unit["sid"]))
    if not source:
        raise HarnessError(f"{unit['sid']} has no source revision in snapshot {snapshot!r}")
    p = policy(cfg)
    preferred = {culture: i for i, culture in enumerate(p["preferred_cultures"])}
    selected = set(cultures) if cultures else None
    rows = db.rows("SELECT culture,text,source_hash,compatible FROM refs WHERE snapshot=? AND sid=?", (snapshot, unit["sid"]))
    refs = []
    for row in rows:
        if selected is not None and row["culture"] not in selected:
            continue
        reasons = []
        if row["culture"] in p["excluded_cultures"]:
            reasons.append("excluded_pseudo_or_test_locale")
        if not row["compatible"] or row["source_hash"] != source["source_hash"]:
            reasons.append("source_revision_mismatch")
        if row["text"].strip() in ("", "<Empty String>"):
            reasons.append("blank_or_sentinel")
        same = row["text"] == source["source"]
        item = {"culture": row["culture"], "text": row["text"], "source_hash": row["source_hash"], "usable": not reasons, "excluded_reasons": reasons, "same_as_source": same, "adds_independent_wording": not same and not reasons}
        if item["usable"] or include_unusable:
            refs.append(item)
    refs.sort(key=lambda r: (preferred.get(r["culture"], len(preferred)), r["culture"]))
    available = {r["culture"] for r in refs}
    return {
        "sid": unit["sid"], "snapshot": snapshot, "namespace": unit["namespace"], "key": unit["key"],
        "english": source["source"], "source_hash": source["source_hash"], "source_sha": source["source_sha"],
        "references": refs, "requested_cultures_unavailable": sorted(selected - available) if selected else [],
        "caution": "Version matching establishes the source revision, not linguistic correctness. Compare source-language and scene evidence; do not decide by majority vote.",
    }


def packet_context(cfg, db, sid, snapshot):
    result = lookup(cfg, db, sid, snapshot=snapshot)
    limit = policy(cfg)["packet_primary_limit"]
    if not isinstance(limit, int) or limit < 1:
        raise HarnessError("references.packet_primary_limit must be a positive integer")
    primary, rest = result["references"][:limit], result["references"][limit:]
    return {
        "official_references": primary,
        "additional_reference_cultures": [r["culture"] for r in rest],
        "reference_lookup": f"python -m locpipe references {sid} --snapshot {snapshot}" + (" --cultures " + " ".join(r["culture"] for r in rest) if rest else ""),
    }


def validate_checks(cfg, db, sid, snapshot, checks, *, stage, verdict=None):
    if not isinstance(checks, list):
        return ["reference_checks must be an array"]
    available = {r["culture"] for r in lookup(cfg, db, sid, snapshot=snapshot)["references"]}
    errors = []
    for item in checks:
        if not isinstance(item, dict):
            errors.append("Each reference check must be an object")
            continue
        cited = item.get("cultures")
        if not isinstance(cited, list) or not cited or not all(isinstance(c, str) for c in cited):
            errors.append("Each reference check needs a non-empty array of culture codes")
        elif len(cited) != len(set(cited)) or set(cited) - available:
            errors.append("Reference check cites a duplicate, missing, excluded or stale culture")
        if not all(isinstance(item.get(k), str) and item[k].strip() for k in ("question", "finding")):
            errors.append("Each reference check needs a concrete question and finding")
        if item.get("status") not in ("supported", "conflict", "unresolved"):
            errors.append("Reference check status must be supported, conflict or unresolved")
        elif item["status"] != "supported" and not (stage == "review" and verdict == "issues"):
            errors.append("Unresolved multilingual ambiguity requires a question before writer submission, or a reviewer issue")
    return errors
