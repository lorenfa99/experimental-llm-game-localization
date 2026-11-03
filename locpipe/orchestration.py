"""Orchestrator tooling: bounded batch claims, dispatch/acceptance receipts, traceability
audits, evidence snapshots, candidate audits and live-state handoffs.

Nothing here judges language, approves a gate or proves that a context was really
isolated. Receipts record what the orchestrator attests; the audits check that the
records agree with the database and with each other.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import packets, qa, report, unreal
from .config import Config, HarnessError, digest, file_hash, read_json, write_json
from .db import Database
from .worker_context import ensure_bundle, readable_compact_json, validate_batch

DISPATCH_LOG = "work/orchestration/dispatch.jsonl"
CLAIM_STAGES = ("translate", "review", "revise", "consistency", "fluency")
REQUIRED_STAGES = ("translate", "review", "revise", "consistency", "fluency")
EVENTS = {"dispatch": "dispatched_fresh_context",
          "reconcile-dispatch": "dispatch_receipt_reconciled",
          "accepted": "accepted"}
PROGRESS_HEADER = "## Current orchestrator progress"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def evidence_dir(cfg, label):
    if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", label):
        raise HarnessError("Use a new label of letters, digits, hyphens and underscores")
    out = cfg.root / "reports/offline-evidence" / label
    if out.exists():
        raise HarnessError("Existing evidence is preserved; choose a different label")
    return out


@contextmanager
def consistent_read(db):
    """One read transaction, so counts and per-unit rows describe the same moment."""
    db.c.execute("BEGIN")
    try:
        yield
    finally:
        db.c.execute("ROLLBACK")


def read_log(cfg):
    path = cfg.root / DISPATCH_LOG
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


# --------------------------------------------------------------------- claims
def claim_batch(cfg, db, stage, worker, max_packets=1, related_prefix=""):
    """Claim up to `max_packets` related packets for one worker, within the configured
    batch limits, and prepare the verified rule views that worker reads once."""
    if stage not in CLAIM_STAGES:
        raise HarnessError("Batch claims cover " + ", ".join(CLAIM_STAGES))
    limit = cfg["packets"]["batch_packets"]
    if not 1 <= max_packets <= limit:
        raise HarnessError(f"Requested packet count exceeds the configured batch limit ({limit})")
    byte_limit = cfg["packets"]["batch_max_input_bytes"]
    ids, claims, total, initial, warning = [], [], 0, None, None
    for _ in range(max_packets):
        units = packets.eligible(cfg, db, stage, worker)
        if not units:
            break
        group, selected, words = packets.select(cfg, units)
        if initial is not None and group != initial and not (
                related_prefix and group.startswith(related_prefix) and initial.startswith(related_prefix)):
            break
        # Preview the exact frozen input before claiming, so a batch never exceeds its byte budget.
        preview = packets.render(cfg, db, {"id": stage + "-" + "0" * 12, "stage": stage, "worker": worker,
                                           "payload": packets.claim_payload(cfg, db, group, selected, words)})
        size = len(readable_compact_json(preview).replace("\n", os.linesep).encode("utf-8"))
        if ids and total + size > byte_limit - 4096:
            break
        claim = packets.claim(cfg, db, stage, worker)
        if not claim["claimed"]:
            break
        actual = (cfg.root / "work/packets" / (claim["claimed"] + ".json")).stat().st_size
        ids.append(claim["claimed"])
        total += actual
        initial = group
        claims.append({**claim, "actual_bytes": actual})
        if claim["group"] != group or (len(ids) > 1 and total > byte_limit):
            warning = ("Actual grouping or size differed from the preview. Every claim is preserved; "
                       "give the worker only the claims that fit and assign the rest to a fresh worker.")
            break
    result = {"worker": worker, "stage": stage, "claims": claims, "frozen_input_bytes": total,
              "contract_hash": None, "working_rules_bytes": None}
    if warning:
        result["warning"] = warning
    if ids:
        batch = validate_batch(cfg, ids)
        _, manifest = ensure_bundle(cfg, batch["contract_hash"])
        result.update(contract_hash=batch["contract_hash"],
                      working_rules_bytes=manifest["statistics"]["working_input_bytes"])
    return result


# -------------------------------------------------------------------- receipts
def record_receipt(cfg, db, event, agent, packet_ids, note=None, capacity=None, fork_turns="none"):
    """Append a dispatch or acceptance receipt without changing harness state."""
    if event not in EVENTS:
        raise HarnessError("Receipt event must be " + ", ".join(EVENTS))
    if not agent or not agent.strip():
        raise HarnessError("A receipt names the actual agent/context")
    ids = list(packet_ids)
    if not ids or len(set(ids)) != len(ids):
        raise HarnessError("Give distinct packet IDs")
    rows = [packets.get(db, pid) for pid in ids]
    if len({p["worker"] for p in rows}) != 1 or len({p["stage"] for p in rows}) != 1:
        raise HarnessError("One worker and role per recorded batch")
    name = EVENTS[event]
    if any(r.get("event") == name and r.get("packets") == ids for r in read_log(cfg)):
        return {"already_recorded": True, "packets": ids}
    payloads = [p["payload"] for p in rows]
    now = utc_now()
    record = {
        "event": name, "utc": now, "date": now[:10], "agent": agent,
        "worker": rows[0]["worker"], "stage": rows[0]["stage"],
        "contract_hash": payloads[0]["contract_hash"], "packets": ids,
        "units": sum(len(p["sids"]) for p in payloads),
        "groups": list(dict.fromkeys(p["group"] for p in payloads)),
        "frozen_input_bytes": sum((cfg.root / "work/packets" / (pid + ".json")).stat().st_size for pid in ids),
    }
    if capacity is not None:
        record["runtime_worker_capacity"] = capacity
    if event in ("dispatch", "reconcile-dispatch"):
        if len(rows) > cfg["packets"]["batch_packets"]:
            raise HarnessError("Packet count exceeds the batch cap")
        if len(rows) > 1 and record["frozen_input_bytes"] > cfg["packets"]["batch_max_input_bytes"]:
            raise HarnessError("Batch byte cap exceeded")
        if event == "dispatch":
            if any(p["status"] != "claimed" for p in rows):
                raise HarnessError("Dispatch requires live claims")
        else:
            if not note or not note.strip():
                raise HarnessError("Reconciliation needs the actual fork/assignment evidence, not a worker label")
            if any(p["status"] not in ("claimed", "accepted") for p in rows):
                raise HarnessError("Reconcile only known live or accepted assignments")
            if any(p["status"] == "accepted" and not (cfg.root / "work/results/accepted" / (p["id"] + ".json")).is_file() for p in rows):
                raise HarnessError("Accepted archive missing")
            record.update(actual_fork_attestation=note, receipt_recorded_after_actual_dispatch=True,
                          packet_statuses_when_recorded={p["id"]: p["status"] for p in rows})
        record["fork_turns"] = fork_turns
        record["dispatch_attestation"] = ("The orchestrator attests it gave the named context exactly these exclusive "
                                          f"packet IDs, created with fork_turns={fork_turns}. This is an attestation, not proof.")
    else:
        if any(p["status"] != "accepted" for p in rows):
            raise HarnessError("Cannot record unaccepted work as accepted")
        results = [read_json(cfg.root / "work/results/accepted" / (pid + ".json")) for pid in ids]
        if any(r is None for r in results):
            raise HarnessError("Accepted result archive missing")
        answers = [a for result in results for a in result["units"]]
        record["attempts"] = {p["id"]: p["attempts"] for p in rows}
        record["reference_checks"] = sum(len(a.get("reference_checks", [])) for a in answers)
        record["acknowledged_warning_occurrences"] = sum(len(a.get("acknowledged_warnings", [])) for a in answers)
        record["review_verdicts"] = dict(Counter(a["verdict"] for a in answers if "verdict" in a))
        record["review_issue_severities"] = dict(Counter(i["severity"] for a in answers for i in a.get("issues", [])))
        record["issue_resolutions"] = dict(Counter(r["decision"] for a in answers for r in a.get("resolutions", [])))
        changes, resolution_sids = [], []
        for packet, result in zip(rows, results):
            frozen = read_json(cfg.root / "work/packets" / (packet["id"] + ".json"))
            originals = {u["sid"]: u for u in frozen["units"]}
            for answer in result["units"]:
                sid = answer["sid"]
                if answer.get("resolutions"):
                    resolution_sids.append(sid)
                if "target" in answer and answer["target"] != originals[sid]["target"]:
                    changes.append({"sid": sid, "pilot": bool(originals[sid]["pilot"]), "packet": packet["id"],
                                    "before_version": packet["payload"]["versions"][sid][2],
                                    "current_version": db.unit(sid)["version"]})
        record["target_changes"] = changes
        record["changed_pilot_sids"] = [c["sid"] for c in changes if c["pilot"]]
        record["issue_resolution_sids"] = resolution_sids
    path = cfg.root / DISPATCH_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


# ---------------------------------------------------------------------- audits
def stage_audit(cfg, db, label, wave="all", full_offline=False):
    """Check that every unit's CURRENT version has a matching accepted review and final
    revision, a fresh-context dispatch receipt and no open issue. Traceability only."""
    if wave != "all" and wave not in cfg["pipeline"]["waves"]:
        raise HarnessError("Unknown wave " + wave)
    output = evidence_dir(cfg, label)
    receipts = {}
    for record in read_log(cfg):
        if record.get("stage") == "review" and record.get("fork_turns") == "none":
            for pid in record.get("packets", []):
                receipts.setdefault(pid, []).append(record)
    required = set(REQUIRED_STAGES[:3]) | (set(REQUIRED_STAGES[3:]) if full_offline else set())
    with consistent_read(db):
        units = db.rows("SELECT * FROM units WHERE active=1 AND include=1 ORDER BY sid")
        if wave != "all":
            units = [u for u in units if u["wave"] == wave]
        if not units:
            raise HarnessError("No in-scope units for this audit")
        reviews, revisions = {}, {}
        for packet in db.rows("SELECT id,stage,worker,payload FROM packets WHERE status='accepted' AND stage IN ('review','revise') ORDER BY finished,id"):
            payload = json.loads(packet["payload"])
            result = read_json(cfg.root / "work/results/accepted" / (packet["id"] + ".json"))
            if result is None:
                raise HarnessError("Accepted result archive missing: " + packet["id"])
            for answer in result["units"]:
                stamp = payload["versions"][answer["sid"]]
                entry = {"packet": packet["id"], "worker": packet["worker"], "answer": answer, "source_stamp": stamp}
                (reviews if packet["stage"] == "review" else revisions)[(answer["sid"], stamp[2])] = entry
        evidence, findings = [], []
        for unit in units:
            key = (unit["sid"], unit["version"])
            review, revision = reviews.get(key), revisions.get(key)
            stamp = [unit["source_sha"], unit["source_hash"], unit["version"]]
            context_receipts = receipts.get(review["packet"], []) if review else []
            authored = bool(review and db.one("SELECT id FROM history WHERE sid=? AND actor=? LIMIT 1", (unit["sid"], review["worker"])))
            checks = {
                "required_stage_tags": required.issubset(json.loads(unit["stages"])),
                "current_version_review_ok": bool(review and review["answer"].get("verdict") == "ok"),
                "review_source_stamp_matches": bool(review and review["source_stamp"] == stamp),
                "current_version_final_revision": bool(revision and revision["answer"].get("target") == unit["target"]
                                                       and not revision["answer"].get("resolutions") and revision["source_stamp"] == stamp),
                "reviewer_never_authored": bool(review and not authored),
                "fresh_context_dispatch_receipt": bool(context_receipts),
                "translated_not_stale": unit["target"] is not None and not unit["stale"],
            }
            failed = [name for name, passed in checks.items() if not passed]
            if failed:
                findings.append({"sid": unit["sid"], "checks": failed})
            evidence.append({"sid": unit["sid"], "namespace": unit["namespace"], "key": unit["key"],
                             "source_sha": unit["source_sha"], "source_hash": unit["source_hash"], "version": unit["version"],
                             "stages": json.loads(unit["stages"]),
                             "latest_review_packet": review["packet"] if review else None,
                             "latest_revision_packet": revision["packet"] if revision else None,
                             "review_agent_receipts": [r.get("agent") for r in context_receipts], "checks": checks})
        sids = {u["sid"] for u in units}
        open_issues = [r for r in db.rows("SELECT id,sid,severity,category FROM issues WHERE status='open'") if r["sid"] in sids]
        run = qa.run(cfg, db)
        qa_errors = [r for r in run["findings"] if r["severity"] == "error" and r["sid"] in sids]
        counts = {name: sum(row["checks"][name] for row in evidence) for name in evidence[0]["checks"]}
        summary = {"units": len(units), "counts": counts, "open_issue_count": len(open_issues),
                   "blocking_qa_error_count": len(qa_errors),
                   "all_metadata_checks_passed": not findings and not open_issues and not qa_errors}
        data = {"created_utc": utc_now(), "private_game_derived": True, "scope": wave, "required_stages": sorted(required),
                "snapshot": db.meta("active_snapshot"), "contract_hash": cfg.contract_hash(), "corpus_hash": db.corpus_hash(),
                "summary": summary, "findings": findings, "open_issues": open_issues, "qa_errors": qa_errors, "evidence": evidence,
                "quality_assessment": "Traceability metadata only; actual independent linguistic judgments remain in accepted review/revision records",
                "runtime_verified": False}
    write_json(output / "current-version-audit.json", data)
    return {"path": str(output / "current-version-audit.json"), "summary": summary}


def _completion(rows, stages):
    return {"units": len(rows), "source_words": sum(len(u["source"].split()) for u in rows),
            "translated": sum(u["target"] is not None for u in rows),
            "missing": sum(u["target"] is None for u in rows), "stale": sum(bool(u["stale"]) for u in rows),
            "stage_completion": {s: sum(s in u["stages"] for u in rows) for s in stages}}


def _cell(value):
    if value is None:
        return "[untranslated]"
    return html.escape(str(value)).replace("|", "&#124;").replace("\r", "").replace("\n", "<br>")


def evidence_snapshot(cfg, db, label):
    """Private, complete evidence snapshot plus a bilingual pilot table. Never assesses quality."""
    out = evidence_dir(cfg, label)
    with consistent_read(db):
        units = db.rows("SELECT * FROM units WHERE active=1 ORDER BY grp,ord,sid")
        for u in units:
            u["stages"], u["data"] = json.loads(u["stages"]), json.loads(u["data"])
        scope = [u for u in units if u["include"]]
        pilot = [u for u in scope if u["pilot"]]
        stages = cfg["pipeline"]["stages"]
        issues = db.rows("SELECT * FROM issues ORDER BY id")
        rows = db.rows("SELECT * FROM packets ORDER BY created")
        accepted, missing = [], []
        for p in rows:
            p["payload"] = json.loads(p["payload"])
            if p["status"] != "accepted":
                continue
            archive = cfg.root / "work/results/accepted" / (p["id"] + ".json")
            if archive.is_file():
                accepted.append({"path": archive.relative_to(cfg.root).as_posix(), "sha256": file_hash(archive), "result": read_json(archive)})
            else:
                missing.append(p["id"])
        pilot_sids = {u["sid"] for u in pilot}
        pilot_issues = [i for i in issues if i["sid"] in pilot_sids]
        run = qa.run(cfg, db)
        evidence = {
            "created_utc": utc_now(), "private_game_derived": True, "snapshot": db.meta("active_snapshot"),
            "contract_hash": cfg.contract_hash(), "corpus_hash": db.corpus_hash(),
            "quality_assessment": "Not performed by this reporting script; inspect independent linguistic records and the orchestrator's assessment",
            "runtime_verified": False, "status": report.status(cfg, db),
            "coverage": _completion(scope, stages),
            "waves": {w: _completion([u for u in scope if u["wave"] == w], stages) for w in cfg["pipeline"]["waves"]},
            "pilot": {**_completion(pilot, stages),
                      "groups": {g: _completion([u for u in pilot if u["grp"] == g], stages) for g in sorted({u["grp"] for u in pilot})},
                      "issues_by_status": dict(Counter(i["status"] for i in pilot_issues)),
                      "issues_by_severity": dict(Counter(i["severity"] for i in pilot_issues)),
                      "qa_findings": [f for f in run["findings"] if f["sid"] in pilot_sids]},
            "qa": run, "issues": issues, "packets": rows, "accepted_results": accepted,
            "accepted_result_archives_missing": missing, "units": units,
            "history": db.rows("SELECT * FROM history ORDER BY id"),
            "gate_events": db.rows("SELECT * FROM events WHERE type IN ('owner_gate','owner_gate_revoke') ORDER BY id"),
        }
    log = cfg.root / DISPATCH_LOG
    if log.is_file():
        evidence["dispatch_log_sha256"] = file_hash(log)
        evidence["dispatch_records"] = read_log(cfg)
    out.mkdir(parents=True)
    write_json(out / "evidence.json", evidence)
    source, target = cfg["project"]["source_culture"], cfg["project"]["target_culture"]
    table = ["# Pilot bilingual evidence table", "",
             "Private game-derived snapshot. This table includes incomplete units and is not a quality acceptance.",
             "Source identities and exact line-break style are retained in evidence.json. Runtime remains untested.", "",
             f"| SID / namespace / key | Group / kind | Source ({source}) | Current target ({target}) | Version / stages | Issues |",
             "|---|---|---|---|---|---|"]
    for u in pilot:
        related = [i for i in pilot_issues if i["sid"] == u["sid"]]
        issue_text = "; ".join(f"#{i['id']} {i['severity']}/{i['category']}: {i['status']} — {i.get('resolution') or i['comment']}" for i in related) or "none recorded"
        table.append("| " + " | ".join([f"{u['sid']}<br>{_cell(u['namespace'])}<br>{_cell(u['key'])}",
                                         f"{_cell(u['grp'])}<br>{_cell(u['kind'])}", _cell(u["source"]), _cell(u["target"]),
                                         f"v{u['version']}<br>{', '.join(u['stages']) or 'none'}", _cell(issue_text)]) + " |")
    (out / "pilot-table.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    return {"directory": str(out), "coverage": evidence["coverage"],
            "pilot": {k: v for k, v in evidence["pilot"].items() if k != "groups"},
            "sha256": file_hash(out / "evidence.json")}


def save_progress(cfg, db, goal="", notes=(), handoff=True):
    """Write a private live-state handoff. Claims, submits and approvals are untouched."""
    with consistent_read(db):
        units = db.rows("SELECT sid,stages,target,stale FROM units WHERE active=1 AND include=1")
        counts = Counter(stage for u in units for stage in json.loads(u["stages"]))
        pending = db.rows("SELECT id,stage,worker,payload,attempts FROM packets WHERE status IN ('claimed','ready') ORDER BY created")
        for packet in pending:
            payload = json.loads(packet.pop("payload"))
            packet["units"], packet["group"] = len(payload["sids"]), payload["group"]
        data = {"utc": utc_now(), "goal": goal, "notes": list(notes), "snapshot": db.meta("active_snapshot"),
                "contract_hash": cfg.contract_hash(), "corpus_hash": db.corpus_hash(), "stage_counts": dict(counts),
                "scope": len(units), "missing": sum(u["target"] is None for u in units), "stale": sum(bool(u["stale"]) for u in units),
                "open_issues": db.one("SELECT COUNT(*) n FROM issues WHERE status='open'")["n"],
                "gates": {g["name"]: g["effective_status"] for g in db.gate_status()}, "pending": pending}
    write_json(cfg.root / "work/orchestration/pending-latest.json", data)
    with (cfg.root / "work/orchestration/progress-history.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(data, ensure_ascii=False) + "\n")
    state = "not updated"
    path = cfg.root / "HANDOFF.md"
    if handoff and path.is_file():
        lines = [PROGRESS_HEADER + " — " + data["utc"], ""]
        if goal:
            lines += [goal, ""]
        lines += [f"Stage completion: {json.dumps(dict(counts))}.",
                  f"Scope {len(units)}; missing {data['missing']}, stale {data['stale']}, open issues {data['open_issues']}.",
                  f"Gates: {json.dumps(data['gates'])}.", "", "Pending claims (verify live before recovery):"]
        lines += [f"- {p['worker']}: {p['id']} ({p['stage']}, {p['units']} units, {p['group']}, attempts {p['attempts']})." for p in pending] or ["- none."]
        lines += ["", "Each claim has one live owner; preserve drafts and never release on timeout. Actual agent status is separate from claim state.",
                  *notes, f"Contract {data['contract_hash']}; corpus {data['corpus_hash']}.",
                  "Receipts: work/orchestration/dispatch.jsonl. Machine-readable progress: work/orchestration/pending-latest.json.",
                  "Historical sections below do not override this live state.", "", ""]
        text = path.read_text(encoding="utf-8")
        if PROGRESS_HEADER in text:
            start = text.index(PROGRESS_HEADER)
            end = text.find("\n## ", start + len(PROGRESS_HEADER))
            before, after = text[:start], (text[end + 1:] if end >= 0 else "")
        else:
            # First run: the section goes ahead of the first existing section, after any introduction.
            first = text.find("\n## ")
            before, after = (text[:first].rstrip("\n") + "\n\n", text[first + 1:]) if first >= 0 else (text.rstrip("\n") + "\n\n", "")
        text = before + "\n".join(lines) + after
        path.write_text(text if after else text.rstrip("\n") + "\n", encoding="utf-8", newline="\n")
        state = "updated"
    return {"stages": dict(counts), "pending_packets": len(pending), "open_issues": data["open_issues"], "handoff": state}


# ------------------------------------------------------------ candidate audit
def _json_artifact(cfg, build, units):
    document = read_json(cfg.path(build["artifact"]))
    rows = {(u["namespace"], u["key"]): u for u in units}
    if len(document["units"]) != len(units):
        raise HarnessError("Candidate unit count differs from the active corpus")
    for entry in document["units"]:
        u = rows.get((entry.get("namespace"), entry.get("key")))
        if u is None or entry.get("source") != u["source"] or entry.get("target") != (u["target"] if u["include"] else u["source"]):
            raise HarnessError("Candidate text or identity differs from the corpus: " + (u["sid"] if u else str(entry.get("key"))))
    return {"adapter": "json", "units_compared": len(units), "artifact_matches_corpus": True}


def _unreal_artifact(cfg, db, build, units, snapshot, manifest):
    from .locres import Locres
    if (build["source_content_hash"] != manifest["content_hash"] or build["source_paks"] != manifest["paks"]):
        raise HarnessError("Candidate source-container record differs from the captured baseline")
    target = cfg["game"]["localization_target"]
    source = Locres.load(cfg.root / "data/sources" / snapshot / "localization" / cfg["project"]["source_culture"] / f"{target}.locres")
    candidate = Locres.parse(unreal.repak(cfg, "get", cfg.path(build["pak"]), build["entry"], binary=True))
    if candidate.version != source.version:
        raise HarnessError("Candidate changed the native locres format version")

    def semantic(resource):
        return {e.identity: (e.source_hash, e.namespace_hash, e.key_hash, e.text) for e in resource.entries}

    expected = semantic(source)
    identities = {(u["namespace"], u["key"]): u for u in units}
    if len(identities) != len(units) or set(identities) != set(expected):
        raise HarnessError("Active corpus and native identities differ")
    for ident, unit in identities.items():
        crc, ns_hash, key_hash, original = expected[ident]
        if unit["source_hash"] != crc or unit["source"] != original:
            raise HarnessError("Source identity/CRC/text mismatch: " + unit["sid"])
        expected[ident] = (crc, ns_hash, key_hash, unit["target"] if unit["include"] else original)
    if semantic(candidate) != expected or len(candidate.entries) != len(source.entries):
        raise HarnessError("Candidate text, exclusions, identities or native hashes differ")
    rebuilt = Locres.parse(candidate.encode(rebuild=True))
    if rebuilt.version != candidate.version or semantic(rebuilt) != semantic(candidate):
        raise HarnessError("Candidate semantic roundtrip failed")
    return {"adapter": "unreal", "native_identities": len(source.entries), "all_native_hashes_and_texts_match": True,
            "candidate_semantic_roundtrip": True, "candidate_rebuild_sha256": digest(rebuilt.original)}


def candidate_audit(cfg, db, candidate, label, expect_units=None, expect_words=None):
    """Read-only final evidence for one built candidate: closure, gates, QA, artifact content
    against the corpus, format-bearing strings, character inventory and font coverage."""
    from .adapters import get_adapter
    unreal.safe_name(candidate)
    output = evidence_dir(cfg, label)
    adapter = get_adapter(cfg)
    with consistent_read(db):
        units = db.rows("SELECT * FROM units WHERE active=1 ORDER BY sid")
        scope = [u for u in units if u["include"]]
        if not scope:
            raise HarnessError("No in-scope units to audit")
        words = sum(len(u["source"].split()) for u in scope)
        if (expect_units is not None and len(scope) != expect_units) or (expect_words is not None and words != expect_words):
            raise HarnessError(f"Scope is {len(scope)} units / {words} words and differs from the stated expectation")
        if any(not set(REQUIRED_STAGES) <= set(json.loads(u["stages"])) for u in scope):
            raise HarnessError("Final audit requires complete current offline linguistic stages")
        if db.one("SELECT id FROM packets WHERE status IN ('claimed','ready') LIMIT 1"):
            raise HarnessError("Finish live/recoverable packets before the final candidate audit")
        if db.one("SELECT id FROM issues WHERE status='open' LIMIT 1"):
            raise HarnessError("Resolve all open issues before the final candidate audit")
        gates = db.gate_status()
        if any(not db.gate_ok(g) for g in [*cfg["pipeline"]["required_gates"], "pilot"]):
            raise HarnessError("Offline gates must be valid before the final candidate audit")
        target_qa, source_qa = qa.run(cfg, db), qa.run(cfg, db, source=True)
        if target_qa["errors"] or target_qa["missing"] or target_qa["stale"] or source_qa["errors"]:
            raise HarnessError("Final source/target QA has blocking findings")
        snapshot, manifest = db.active_snapshot()
        build = adapter.verify(cfg, candidate)
        if (build.get("mode") != "candidate" or build.get("snapshot") != snapshot
                or build.get("contract_hash") != cfg.contract_hash() or build.get("corpus_hash") != db.corpus_hash()):
            raise HarnessError("Candidate does not match the current finalized corpus/contract")
        if build.get("adapter") == "json":
            content = _json_artifact(cfg, build, units)
        elif "pak" in build and "entry" in build:
            content = _unreal_artifact(cfg, db, build, units, snapshot, manifest)
        elif callable(getattr(adapter, "audit_candidate", None)):
            content = adapter.audit_candidate(cfg, db, build)
        else:
            content = {"artifact_matches_corpus": None,
                       "note": "This adapter exposes no audit_candidate hook; artifact content was not independently compared"}
        probes = []
        for u in units:
            tags, printf, holders = qa.TAG.findall(u["source"]), qa.PRINTF.findall(u["source"]), sorted(qa.placeholders(u["source"]))
            if tags or printf or holders:
                shown = u["target"] if u["include"] else u["source"]
                probes.append({"sid": u["sid"], "namespace": u["namespace"], "key": u["key"], "include": bool(u["include"]),
                               "placeholders": holders, "tags": tags, "printf": printf, "version": u["version"],
                               "stages": json.loads(u["stages"]), "qa": qa.check(u["source"], shown, kind=u["kind"])})
        chars = Counter(c for u in scope for c in u["target"] if c.isprintable())
        configured = cfg["qa"]["font_characters"]
        fonts, covered = {"supported": False}, None
        if manifest.get("extracted_root"):
            from . import fonts as font_audit
            try:
                fonts = font_audit.coverage(cfg, db, "".join(chars))
                covered = fonts["all_cover"]
            except HarnessError as exc:
                fonts = {"supported": False, "error": str(exc)}
        result = {
            "utc": utc_now(), "private_game_derived": True, "snapshot": snapshot, "contract_hash": cfg.contract_hash(),
            "corpus_hash": db.corpus_hash(), "candidate": build, "in_scope": len(scope), "in_scope_source_words": words,
            "source_copy_exclusions": len(units) - len(scope), "artifact_content": content,
            "target_version_text_fingerprint": digest(json.dumps([(u["sid"], u["version"], u["target"]) for u in scope], ensure_ascii=False)),
            "stage_completion": {s: sum(s in json.loads(u["stages"]) for u in scope) for s in REQUIRED_STAGES},
            "format_probe_count": len(probes), "format_probes": probes, "qa_target": target_qa, "qa_source": source_qa,
            "printable_scalars": [{"character": c, "codepoint": f"U+{ord(c):04X}", "occurrences": n} for c, n in sorted(chars.items())],
            "scalars_outside_configured_probe": sorted(c for c in chars if ord(c) > 127 and c not in configured),
            "fonts": fonts, "font_coverage_ok": covered, "gates": gates, "runtime_verified": False,
            "limitations": "Artifact comparison, readback and roundtrip are not runtime testing. Font character-map coverage is not rendering, "
                           "routing, fallback or layout proof. Reachability and strings the source index cannot see remain LQA questions.",
        }
    write_json(output / "candidate-audit.json", result)
    summary = {"report": str(output / "candidate-audit.json"), "in_scope": len(scope), "exclusions": len(units) - len(scope),
               "format_probes": len(probes), "font_coverage_ok": covered, "artifact_content": content, "runtime_verified": False}
    if covered is False:
        raise HarnessError("Inspect missing/unparsed font evidence before declaring offline completion: " + json.dumps(summary, ensure_ascii=False))
    return summary


# ------------------------------------------------------------------------ CLI
def _claim_args(p):
    p.add_argument("stage", choices=CLAIM_STAGES)
    p.add_argument("worker")
    p.add_argument("--max-packets", type=int, default=1)
    p.add_argument("--related-prefix", default="", help="Groups sharing this prefix may be claimed together")


def _receipt_args(p):
    p.add_argument("event", choices=tuple(EVENTS))
    p.add_argument("agent")
    p.add_argument("packets", nargs="+")
    p.add_argument("--note", help="For reconciliation: cite the actual fresh fork/assignment; labels alone are not evidence")
    p.add_argument("--capacity", type=int, help="Verified concurrent worker capacity at dispatch time")
    p.add_argument("--fork-turns", default="none", help="How the context was created; independent review needs 'none'")


def _audit_args(p):
    p.add_argument("label", help="New evidence directory name")
    p.add_argument("--wave", default="all")
    p.add_argument("--full-offline", action="store_true", help="Also require consistency and fluency")


def _snapshot_args(p):
    p.add_argument("label", help="New evidence directory name")


def _progress_args(p):
    p.add_argument("--goal", default="")
    p.add_argument("--note", action="append", default=[])
    p.add_argument("--no-handoff", action="store_true")


def _candidate_args(p):
    p.add_argument("candidate", help="Candidate build label")
    p.add_argument("label", help="New evidence directory name")
    p.add_argument("--expect-units", type=int)
    p.add_argument("--expect-words", type=int)


COMMANDS = {
    "claim-batch": (claim_batch.__doc__, _claim_args, False,
                    lambda cfg, db, a: claim_batch(cfg, db, a.stage, a.worker, a.max_packets, a.related_prefix)),
    "record-batch": (record_receipt.__doc__, _receipt_args, True,
                     lambda cfg, db, a: record_receipt(cfg, db, a.event, a.agent, a.packets, a.note, a.capacity, a.fork_turns)),
    "stage-audit": (stage_audit.__doc__, _audit_args, True,
                    lambda cfg, db, a: stage_audit(cfg, db, a.label, a.wave, a.full_offline)),
    "snapshot": (evidence_snapshot.__doc__, _snapshot_args, True,
                 lambda cfg, db, a: evidence_snapshot(cfg, db, a.label)),
    "save-progress": (save_progress.__doc__, _progress_args, True,
                      lambda cfg, db, a: save_progress(cfg, db, a.goal, a.note, not a.no_handoff)),
    "candidate-audit": (candidate_audit.__doc__, _candidate_args, True,
                        lambda cfg, db, a: candidate_audit(cfg, db, a.candidate, a.label, a.expect_units, a.expect_words)),
}


def main(command, argv=None):
    """Entry point shared by the thin scripts in scripts/."""
    return run_cli(COMMANDS, command, argv)


def run_cli(commands, command, argv=None):
    """Run one `commands` entry: (doc, add_arguments, readonly_db, run). Prints JSON; errors exit 1.
    `run` may return (result, exit_code) when a successful run should still fail the shell step."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    doc, add, readonly, run = commands[command]
    parser = argparse.ArgumentParser(prog=command, description=(doc or "").split("\n")[0])
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project directory containing config.toml")
    add(parser)
    args = parser.parse_args(argv)
    db = None
    try:
        cfg = Config(args.project)
        db = Database(cfg, readonly=readonly)
        result = run(cfg, db, args)
        result, code = result if isinstance(result, tuple) else (result, 0)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (HarnessError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        if db:
            db.close()
