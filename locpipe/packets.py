"""Transactional, resumable linguistic packets. Disabled in preparation-only mode."""
from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict

from .config import HarnessError, read_json, write_json
from .qa import check
from . import references

STAGES = ("translate", "review", "revise", "consistency", "fluency", "lqa")
CATEGORIES = {"accuracy", "fluency", "terminology", "style", "locale", "markup", "layout", "voice"}
SEVERITIES = {"critical", "major", "minor", "preferential"}


def pending(cfg, db):
    rows = db.rows("SELECT id,stage,status,worker,attempts,created FROM packets WHERE status IN ('claimed','ready') ORDER BY created")
    return [{**p, "result_exists": (cfg.root / "work/results" / (p["id"] + ".json")).exists()} for p in rows]


def blockers(cfg, db):
    if cfg["project"]["preparation_only"]:
        return ["Preparation only: wait for the owner's instruction to start translation"]
    return ["Owner gate " + g for g in cfg["pipeline"]["required_gates"] if not db.gate_ok(g)]


def eligible(cfg, db, stage, worker=""):
    if stage not in STAGES:
        raise HarnessError(f"Unknown stage {stage}")
    units = db.rows("SELECT * FROM units WHERE active=1 AND include=1 ORDER BY grp,ord,sid")
    if not db.gate_ok("pilot"):
        units = [u for u in units if u["pilot"]]
        if stage in ("consistency", "fluency", "lqa"):
            return []
    elif stage in ("translate", "review", "revise"):
        # An earlier wave must complete bilingual review and revision before later waves.
        for wave in cfg["pipeline"]["waves"]:
            candidates = [u for u in units if u["wave"] == wave]
            if any("revise" not in json.loads(u["stages"]) or u["stale"] for u in candidates):
                units = candidates
                break
    if stage in ("consistency", "fluency", "lqa"):
        prerequisite = {"consistency": "revise", "fluency": "consistency", "lqa": "fluency"}[stage]
        for u in units:
            done = set(json.loads(u["stages"]))
            if u["stale"]:
                return []
            # A pass starts only after the preceding corpus-wide stages finish.
            # Its own completed marker may then coexist with pending bilingual
            # review of an edit made by that pass. Other ready units can continue;
            # the edited unit is not offered again and build/LQA still wait.
            if stage == "consistency":
                ready = "revise" in done or "consistency" in done
            elif stage == "fluency":
                ready = "consistency" in done and ("revise" in done or "fluency" in done)
            else:
                ready = prerequisite in done and "revise" in done
            if not ready:
                return []
    reserved = set()
    for p in db.rows("SELECT payload FROM packets WHERE status IN ('claimed','ready')"):
        reserved.update(json.loads(p["payload"])["sids"])
    result = []
    for u in units:
        done = set(json.loads(u["stages"]))
        if u["sid"] in reserved or (u["locked"] and stage == "translate"):
            continue
        ready = False
        if stage == "translate":
            ready = u["target"] is None or bool(u["stale"])
        elif stage == "review":
            authored = db.one("SELECT id FROM history WHERE sid=? AND actor=? LIMIT 1", (u["sid"], worker))
            ready = u["target"] is not None and not u["stale"] and "review" not in done and worker != u["last_writer"] and not authored
        elif stage == "revise":
            ready = "review" in done and "revise" not in done
        elif stage == "lqa":
            ready = bool(db.one("SELECT id FROM issues WHERE sid=? AND status='open' LIMIT 1", (u["sid"],))) and not u["stale"]
        else:
            ready = stage not in done and "revise" in done and not u["stale"]
        if ready:
            result.append(u)
    return result


def select(cfg, units):
    """One packet's units: the first eligible group, bounded by the configured size limits.

    The only selection rule; claims and batch previews both use it."""
    group = units[0]["grp"]
    selected, words = [], 0
    for u in units:
        n = len(u["source"].split())
        if u["grp"] != group:
            continue
        if selected and (len(selected) >= cfg["packets"]["max_units"] or words + n > cfg["packets"]["max_words"]):
            break
        selected.append(u)
        words += n
    return group, selected, words


def claim_payload(cfg, db, group, selected, words):
    """Version-bound claim stamp. Later submits are rejected if any of it changed."""
    return {"sids": [u["sid"] for u in selected], "group": group, "snapshot": db.meta("active_snapshot"), "corpus_hash": db.corpus_hash(), "contract_hash": cfg.contract_hash(), "versions": {u["sid"]: [u["source_sha"], u["source_hash"], u["version"]] for u in selected}, "source_words": words}


def claim(cfg, db, stage, worker):
    cfg.require_translation()
    if not worker.strip():
        raise HarnessError("A named worker/context is required")
    with db.tx():
        blocked = blockers(cfg, db)
        if blocked:
            raise HarnessError("Blocked: " + "; ".join(blocked))
        recover = [p for p in pending(cfg, db) if p["stage"] == stage and p["status"] == "ready" and p["result_exists"]]
        if recover:
            raise HarnessError("Recover saved released packets before new claims: " + ", ".join(p["id"] for p in recover))
        units = eligible(cfg, db, stage, worker)
        if not units:
            return {"claimed": None, "reason": "No eligible work; inspect plan, pending packets, locks and owner gates"}
        group, selected, words = select(cfg, units)
        pid = stage + "-" + uuid.uuid4().hex[:12]
        payload = claim_payload(cfg, db, group, selected, words)
        db.c.execute("INSERT INTO packets(id,stage,status,worker,payload,created) VALUES(?,?,'claimed',?,?,?)", (pid, stage, worker, json.dumps(payload), time.time()))
    prepare(cfg, db, pid)
    return {"claimed": pid, "stage": stage, "units": len(selected), "group": group, "source_words": words}


def get(db, pid):
    p = db.one("SELECT * FROM packets WHERE id=?", (pid,))
    if not p:
        raise HarnessError(f"Unknown packet {pid}")
    p["payload"] = json.loads(p["payload"])
    return p


UNIT_FIELDS = ("sid", "namespace", "key", "kind", "wave", "source", "target", "version", "stale", "locked", "pilot", "reason", "data")


def render(cfg, db, p):
    """Frozen packet input. Each serialized neighbor window is listed once per group
    (`group_windows`); a unit points into target with `window` [start, end). References keep
    culture and text; version hashes live in the payload. Nothing else is dropped."""
    snapshot = p["payload"]["snapshot"]
    before, after = cfg["packets"]["context_before"], cfg["packets"]["context_after"]
    units, spans = [], defaultdict(set)
    for sid in p["payload"]["sids"]:
        u = db.unit(sid)
        neighbors = db.rows("SELECT sid,source,target,ord FROM units WHERE active=1 AND grp=? ORDER BY ord,sid", (u["grp"],))
        idx = next(i for i, r in enumerate(neighbors) if r["sid"] == sid)
        spans[u["grp"]].update(range(max(0, idx - before), min(len(neighbors), idx + after + 1)))
        ref = references.packet_context(cfg, db, sid, snapshot)
        ref["official_references"] = [{"culture": r["culture"], "text": r["text"], **({"same_as_source": True} if r["same_as_source"] else {})} for r in ref["official_references"]]
        evidence = db.rows("SELECT asset,offset,evidence FROM contexts WHERE snapshot=? AND sid=? ORDER BY asset,offset", (snapshot, sid))
        memory = db.rows("SELECT sid,target,grp FROM units WHERE active=1 AND source_sha=? AND target IS NOT NULL AND stale=0 AND sid<>?", (u["source_sha"], sid))
        units.append(({k: u[k] for k in UNIT_FIELDS if k != "data" or u[k]}, u["grp"], idx, ref, evidence, memory))
    windows, out, claimed = {}, [], set(p["payload"]["sids"])
    for group, indexes in spans.items():
        neighbors = db.rows("SELECT sid,source,target,ord FROM units WHERE active=1 AND grp=? ORDER BY ord,sid", (group,))
        windows[group] = [{"index": i, **neighbors[i], "in_packet": neighbors[i]["sid"] in claimed} for i in sorted(indexes)]
    for fields, group, idx, ref, evidence, memory in units:
        out.append({**fields, "group": group, "window": [max(0, idx - before), idx + after + 1], **ref,
                    "asset_evidence": [f"{e['asset']}@{e['offset']}" for e in evidence if e["evidence"] != "key_in_string_table_storage"],
                    "in_string_table_storage": any(e["evidence"] == "key_in_string_table_storage" for e in evidence),
                    # A fresh reviewer judges the current text without the
                    # corrector's previous resolution rationale/suggestions.
                    # Full issue history stays available to resolution stages.
                    "translation_memory": memory, "issues": [] if p["stage"] == "review" else db.rows("SELECT * FROM issues WHERE sid=? ORDER BY id", (fields["sid"],))})
    return {"id": p["id"], "stage": p["stage"], "worker": p["worker"], "payload": p["payload"],
            "context_note": "Serialization order is not verified story chronology. A unit's `window` gives [start, end) group indexes in `group_windows`; read verified scene briefs and research speaker/branch when needed.",
            "reference_instructions": references.INSTRUCTIONS, "group_windows": windows, "units": out,
            "required_rules": ["style/style-guide.md", "style/characters.json", "glossary/glossary.json", "docs/MULTILINGUAL-REFERENCES.md"]}


def prepare(cfg, db, pid):
    p = get(db, pid)
    path = cfg.root / "work/results" / (pid + ".json")
    if not path.exists():
        units = []
        for sid in p["payload"]["sids"]:
            u = db.unit(sid)
            if p["stage"] == "review":
                units.append({"sid": sid, "verdict": None, "issues": [], "reference_checks": []})
            else:
                units.append({"sid": sid, "target": u["target"], "note": "", "acknowledged_warnings": [], "resolutions": [], "reference_checks": []})
        write_json(path, {"packet": pid, "worker": p["worker"], "units": units})
    # Persist a frozen packet input. Do not render new source into an old claim.
    packet_file = cfg.root / "work/packets" / (pid + ".json")
    if not packet_file.exists():
        # Keep all fields and exact strings; remove only serialization whitespace.
        # Wrap at structural commas so complete files remain practical to read.
        # Existing frozen inputs are never rewritten.
        from .worker_context import readable_compact_json
        packet_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = packet_file.with_suffix(packet_file.suffix + ".tmp")
        temporary.write_text(readable_compact_json(render(cfg, db, p)), encoding="utf-8")
        temporary.replace(packet_file)
    return {"packet": str(packet_file), "result": str(path), "status": p["status"], "current_contract_hash": cfg.contract_hash(), "claimed_contract_hash": p["payload"]["contract_hash"]}


def _preflight(cfg, db, p, result):
    payload = p["payload"]
    if p["status"] not in ("claimed", "ready"):
        raise HarnessError(f"Packet is {p['status']}; target cannot be submitted")
    if payload["snapshot"] != db.meta("active_snapshot") or payload["corpus_hash"] != db.corpus_hash():
        raise HarnessError("Source/scope changed since claim; preserve the draft and rebase deliberately")
    if payload["contract_hash"] != cfg.contract_hash():
        raise HarnessError("Style/glossary/characters/config changed since claim; preserve the draft and refresh the assignment")
    if blockers(cfg, db):
        raise HarnessError("Owner approval gates changed since claim")
    if result.get("packet") != p["id"] or result.get("worker") != p["worker"]:
        raise HarnessError("Result packet/worker differs from the claim")
    answers = result.get("units", [])
    if not isinstance(answers, list) or not all(isinstance(a, dict) for a in answers):
        raise HarnessError("Result units must be an array of objects")
    sids = [a.get("sid") for a in answers]
    if len(sids) != len(set(sids)) or set(sids) != set(payload["sids"]):
        raise HarnessError("Result must contain every claimed unit exactly once, and no extras")
    for sid in sids:
        u = db.unit(sid)
        if [u["source_sha"], u["source_hash"], u["version"]] != payload["versions"][sid] or not u["active"]:
            raise HarnessError(f"Unit {sid} changed since claim")
        if p["stage"] == "review" and (u["last_writer"] == p["worker"] or db.one("SELECT id FROM history WHERE sid=? AND actor=? LIMIT 1", (sid, p["worker"]))):
            raise HarnessError("Independent reviewer must use a different worker/context from the latest writer")


def _validate(cfg, db, p, result):
    terms = read_json(cfg.root / "glossary/glossary.json", {"entries": []})["entries"]
    errors = []
    for a in result["units"]:
        u = db.unit(a["sid"])
        errors.extend(u["sid"] + ": " + e for e in references.validate_checks(cfg, db, u["sid"], p["payload"]["snapshot"], a.get("reference_checks", []), stage=p["stage"], verdict=a.get("verdict")))
        if p["stage"] == "review":
            issues = a.get("issues")
            if a.get("verdict") not in ("ok", "issues") or not isinstance(issues, list) or (a["verdict"] == "ok" and issues) or (a["verdict"] == "issues" and not issues):
                errors.append(u["sid"] + ": invalid review verdict/issues")
                continue
            for issue in issues:
                if not isinstance(issue, dict) or issue.get("category") not in CATEGORIES or issue.get("severity") not in SEVERITIES or not isinstance(issue.get("comment"), str) or not issue["comment"].strip():
                    errors.append(u["sid"] + ": every review issue needs a valid category/severity/comment")
        else:
            if u["locked"] and a.get("target") != u["target"]:
                errors.append(u["sid"] + ": target is locked; preserve wording or request an owner unlock")
            findings = check(u["source"], a.get("target"), kind=u["kind"], glossary=terms, ratio=cfg["qa"]["length_ratio_warning"], target_culture=cfg["project"]["target_culture"])
            errors.extend(u["sid"] + ": " + f["message"] for f in findings if f["severity"] == "error")
            acknowledgments = a.get("acknowledged_warnings", [])
            if any(f["severity"] == "warning" and f["code"] not in acknowledgments for f in findings):
                errors.append(u["sid"] + ": acknowledge every QA warning code with a note")
            if any(f["severity"] == "warning" for f in findings) and not a.get("note", "").strip():
                errors.append(u["sid"] + ": QA warning acknowledgment requires a note")
            if p["stage"] in ("revise", "lqa"):
                issues = db.rows("SELECT id FROM issues WHERE sid=? AND status='open'", (u["sid"],))
                resolutions = a.get("resolutions", [])
                ids = [r.get("issue") for r in resolutions if isinstance(r, dict)]
                if len(ids) != len(set(ids)) or set(ids) != {r["id"] for r in issues}:
                    errors.append(u["sid"] + ": resolve every open issue exactly once")
                for r in resolutions:
                    if not isinstance(r, dict) or r.get("decision") not in ("accepted", "rejected") or not r.get("reason", "").strip():
                        errors.append(u["sid"] + ": each resolution needs accepted/rejected and a reason")
    return errors


def write_target(db, u, text, stage, actor, note, packet=None):
    stages = set(u["stages"])
    changed = text != u["target"] or bool(u["stale"])
    if changed:
        stages.discard("review")
        stages.discard("revise")
        stages.discard("lqa")
        if stage not in ("fluency", "lqa"):
            stages.discard("fluency")
        if stage not in ("consistency", "fluency", "lqa"):
            stages.discard("consistency")
        stages.add("translate")
        version = u["version"] + 1
        db.c.execute("UPDATE units SET target=?,version=?,stale=0,last_writer=? WHERE sid=?", (text, version, actor, u["sid"]))
        db.c.execute("INSERT INTO history(sid,version,target,stage,actor,note,packet,created) VALUES(?,?,?,?,?,?,?,?)", (u["sid"], version, text, stage, actor, note, packet, time.time()))
    stages.add(stage)
    if changed and stage in ("revise", "consistency", "fluency", "lqa"):
        # Every changed sentence returns to bilingual review. Retain a completed
        # corpus-edit pass so review can finish without repeating that pass forever.
        stages.discard("review")
        stages.discard("revise")
    db.c.execute("UPDATE units SET stages=? WHERE sid=?", (json.dumps(sorted(stages)), u["sid"]))


def submit(cfg, db, pid, path=None):
    cfg.require_translation()
    p = get(db, pid)
    result = read_json(path or cfg.root / "work/results" / (pid + ".json"))
    if not isinstance(result, dict):
        raise HarnessError("Result JSON missing or not an object")
    errors = []
    with db.tx():
        p = get(db, pid)  # Re-read under the write lock: duplicate submits cannot race.
        _preflight(cfg, db, p, result)
        errors = _validate(cfg, db, p, result)
        db.c.execute("UPDATE packets SET attempts=attempts+1 WHERE id=?", (pid,))
        if not errors:
            for a in result["units"]:
                u = db.unit(a["sid"])
                if p["stage"] == "review":
                    for issue in a["issues"]:
                        db.c.execute("INSERT INTO issues(sid,packet,version,category,severity,comment,suggestion) VALUES(?,?,?,?,?,?,?)", (u["sid"], pid, u["version"], issue["category"], issue["severity"], issue["comment"], issue.get("suggestion")))
                    db.c.execute("UPDATE units SET stages=? WHERE sid=?", (json.dumps(sorted(set(u["stages"]) | {"review"})), u["sid"]))
                else:
                    resolutions = a.get("resolutions", []) if p["stage"] in ("revise", "lqa") else []
                    for r in resolutions:
                        db.c.execute("UPDATE issues SET status=?,resolution=? WHERE id=?", (r["decision"], r["reason"], r["issue"]))
                    write_target(db, u, a["target"], p["stage"], p["worker"], a.get("note", ""), pid)
                    if resolutions:
                        stages = set(db.unit(u["sid"])["stages"]) - {"review", "revise"}
                        db.c.execute("UPDATE units SET stages=? WHERE sid=?", (json.dumps(sorted(stages)), u["sid"]))
            db.c.execute("UPDATE packets SET status='accepted',finished=? WHERE id=?", (time.time(), pid))
            db.event("packet_accepted", result)
    if errors:
        write_json(cfg.root / "work/results" / (pid + ".errors.json"), {"errors": errors})
        return {"accepted": False, "errors": errors}
    write_json(cfg.root / "work/results/accepted" / (pid + ".json"), result)
    return {"accepted": True, "packet": pid, "units": len(result["units"])}
