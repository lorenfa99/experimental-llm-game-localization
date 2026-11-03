"""Import source/version-bound offline linguistic findings, never runtime reports."""
from __future__ import annotations

import json
import re

from .config import HarnessError, digest
from . import packets


def import_findings(cfg, db, path, origin, actor, note):
    cfg.require_translation()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", origin or ""):
        raise HarnessError("Offline origin needs a short lowercase identifier")
    if not actor.strip() or not note.strip():
        raise HarnessError("Offline import requires its actual actor and provenance note")
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise HarnessError("Offline findings must be a nonempty JSONL object list")
    seen, imported = set(), []
    with db.tx():
        for row in rows:
            u = db.unit(row["sid"])
            if row["sid"] != u["sid"] or not u["active"] or not u["include"] or u["stale"]:
                raise HarnessError("Offline findings require exact current in-scope SIDs")
            bindings = {k: u[k] for k in ("namespace", "key", "source_sha", "source_hash", "version")}
            bindings["current_target"] = u["target"]
            if any(k not in row or row[k] != value for k, value in bindings.items()):
                raise HarnessError(f"{u['sid']} source/target changed or bindings missing; import rolled back")
            if u["target"] is None or "review" not in u["stages"]:
                raise HarnessError("Offline maintenance requires an existing reviewed translation")
            if any(u["sid"] in json.loads(p["payload"])["sids"] for p in db.rows(
                    "SELECT payload FROM packets WHERE status IN ('claimed','ready')")):
                raise HarnessError(f"{u['sid']} belongs to unfinished work; recover target first")
            if row.get("category") not in packets.CATEGORIES or row.get("severity") not in packets.SEVERITIES:
                raise HarnessError("Offline findings need a valid category and severity")
            if not isinstance(row.get("comment"), str) or not row["comment"].strip():
                raise HarnessError("Offline findings need a concrete comment")
            if row.get("suggestion") is not None and not isinstance(row["suggestion"], str):
                raise HarnessError("Offline suggestion must be text or null")
            signature = (u["sid"], row["category"], row["comment"])
            provenance = "offline:" + origin
            if signature in seen or db.one(
                    "SELECT id FROM issues WHERE sid=? AND version=? AND packet=? AND category=? AND comment=?",
                    (u["sid"], u["version"], provenance, row["category"], row["comment"])):
                raise HarnessError("Duplicate offline finding; preserve and inspect the existing resolution")
            seen.add(signature)
            cursor = db.c.execute(
                "INSERT INTO issues(sid,packet,version,category,severity,comment,suggestion) VALUES(?,?,?,?,?,?,?)",
                (u["sid"], provenance, u["version"], row["category"], row["severity"], row["comment"], row.get("suggestion")))
            # The previous bilingual review is valid for this unchanged version.
            # Reopen only its resolution stage; actual edits use the ordinary
            # revise path, invalidating review and affected corpus passes.
            stages = sorted(set(u["stages"]) - {"revise"})
            db.c.execute("UPDATE units SET stages=? WHERE sid=?", (json.dumps(stages), u["sid"]))
            imported.append({"sid": u["sid"], "issue": cursor.lastrowid, "finding_id": row.get("finding_id")})
        db.event("offline_issue_import", {"origin": origin, "actor": actor, "note": note,
                 "file": str(path), "sha256": digest(raw), "findings": rows, "imported": imported})
    return {"imported": len(imported), "origin": provenance, "resolution_stage": "revise", "issues": imported}
