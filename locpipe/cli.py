from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from . import __version__, build, context, extract, fonts, packets, qa, report, unreal, references
from .config import Config, HarnessError, digest, file_hash, read_json, write_json
from .db import Database, GATES
from .locres import Locres


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def doctor(cfg, db):
    from .adapters import get_adapter
    checks = [{"check": "python", "ok": sys.version_info >= (3, 11), "value": sys.version.split()[0]},
              {"check": "preparation_only", "ok": True, "value": cfg["project"]["preparation_only"]}]
    for name in ("style/style-guide.md", "style/characters.json", "glossary/glossary.json",
                 "docs/WORKFLOW.md", "AGENTS.md"):
        checks.append({"check": name, "ok": (cfg.root / name).is_file()})
    checks.extend(get_adapter(cfg).doctor(cfg, db))
    return {"version": __version__, "ok": all(c["ok"] for c in checks), "checks": checks}


def approve(cfg, db, name, note, actor):
    cfg.require_translation()
    if not note.strip() or not actor.strip():
        raise HarnessError("Gate approval requires an owner identity and decision note")
    if name == "pilot":
        units = db.rows("SELECT stages,target,stale FROM units WHERE active=1 AND include=1 AND pilot=1")
        if not units or any(u["target"] is None or u["stale"] or "revise" not in json.loads(u["stages"]) for u in units):
            raise HarnessError("Pilot cannot be approved until its translation, independent review and revision are complete")
    if name == "style":
        text = (cfg.root / "style/style-guide.md").read_text(encoding="utf-8")
        if re.search(r"(?m)^\s*[-*]\s+\[DECIDE\]", text):
            raise HarnessError("Resolve the [DECIDE] items in style/style-guide.md before approval")
    if name == "glossary":
        glossary = read_json(cfg.root / "glossary/glossary.json", {"entries": []})
        bad = [t.get("id") for t in glossary["entries"] if t.get("status") == "approved" and not (t.get("target") or t.get("do_not_translate"))]
        if bad:
            raise HarnessError("Approved glossary entries need target-language or do_not_translate: " + str(bad))
    with db.tx():
        db.c.execute("UPDATE gates SET status='approved',evidence_hash=?,note=?,actor=?,updated=? WHERE name=?", (db.gate_hash(name), note, actor, time.time(), name))
        db.event("owner_gate", {"name": name, "note": note, "actor": actor, "status": "approved"})
    return {"gate": name, "status": "approved", "evidence_hash": db.gate_hash(name)}


def owner_set(cfg, db, sid, text, note, lock=False):
    cfg.require_translation()
    if not note.strip():
        raise HarnessError("An owner edit requires a note")
    terms = read_json(cfg.root / "glossary/glossary.json", {"entries": []})["entries"]
    with db.tx():
        u = db.unit(sid)
        if not u["active"] or not u["include"]:
            raise HarnessError("Owner edits require an active in-scope unit")
        findings = qa.check(u["source"], text, glossary=terms, target_culture=cfg["project"]["target_culture"])
        errors = [f for f in findings if f["severity"] == "error"]
        if errors:
            raise HarnessError(json.dumps(errors, ensure_ascii=False))
        packets.write_target(db, u, text, "translate", "owner", note)
        if lock:
            db.c.execute("UPDATE units SET locked=1 WHERE sid=?", (u["sid"],))
        db.event("owner_set", {"sid": u["sid"], "note": note, "lock": lock})
    return {"sid": u["sid"], "updated": True, "findings": findings}


def import_targets(cfg, db, path):
    cfg.require_translation()
    if path.suffix == ".tsv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            answers = list(csv.DictReader(f, delimiter="\t"))
    else:
        answers = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    answers = [a for a in answers if a.get("target") not in (None, "")]
    if len({a["sid"] for a in answers}) != len(answers):
        raise HarnessError("Duplicate IDs in import")
    terms = read_json(cfg.root / "glossary/glossary.json", {"entries": []})["entries"]
    changed = []
    with db.tx():
        for a in answers:
            u = db.unit(a["sid"])
            if not u["active"] or not u["include"] or u["locked"]:
                raise HarnessError(f"{u['sid']} is absent, excluded or locked")
            if (a["sid"] != u["sid"] or a.get("namespace") != u["namespace"] or a.get("key") != u["key"]
                    or a.get("source_sha") != u["source_sha"]
                    or int(a.get("source_hash", -1)) != u["source_hash"]
                    or int(a.get("version", -1)) != u["version"]):
                raise HarnessError(f"{u['sid']} source/target changed since export; entire import rolled back")
            findings = qa.check(u["source"], a["target"], glossary=terms, target_culture=cfg["project"]["target_culture"])
            if any(f["severity"] == "error" for f in findings):
                raise HarnessError(f"{u['sid']} blocking QA: {findings}")
            if a["target"] != u["target"]:
                if not a.get("note", "").strip():
                    raise HarnessError(f"{u['sid']} needs an owner import note")
                packets.write_target(db, u, a["target"], "translate", "owner-import", a["note"])
                changed.append(u["sid"])
        db.event("owner_import", {"file": str(path), "sids": changed})
    return {"updated": len(changed), "sids": changed}


def parser():
    p = argparse.ArgumentParser(description="Versioned agent localization harness", epilog="Preparation mode blocks target edits and linguistic claims. See docs/WORKFLOW.md.")
    p.add_argument("--project", type=Path, default=Path.cwd(), help="Project directory containing config.toml")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="Create a new preparation-only project; never overwrite a nonempty directory")
    init.add_argument("directory", type=Path)
    source = sub.add_parser("import-source", help="Capture an engine-neutral locpipe.source.v1 file")
    source.add_argument("file", type=Path)
    source.add_argument("--label", required=True)
    source.add_argument("--no-context", action="store_true")
    for name in ("doctor", "discover", "inventory", "roundtrip", "fonts", "report"):
        sub.add_parser(name)
    for name in ("status", "plan", "pending"):
        q = sub.add_parser(name)
        q.add_argument("--json", action="store_true", help="JSON is also the default output")
        q.add_argument("--brief", action="store_true")
    for name in ("extract", "update"):
        q = sub.add_parser(name)
        q.add_argument("--label", required=True, help="Immutable snapshot label; use a new label after updates")
        q.add_argument("--game-root")
        q.add_argument("--no-context", action="store_true")
    q = sub.add_parser("context")
    q.add_argument("action", choices=["index"])
    q = sub.add_parser("unit")
    q.add_argument("sid")
    q = sub.add_parser("references", help="Compare matching official languages for one source identity")
    q.add_argument("sid")
    q.add_argument("--snapshot")
    q.add_argument("--cultures", nargs="+")
    q.add_argument("--include-unusable", action="store_true", help="Audit excluded/stale entries with explicit reasons")
    q = sub.add_parser("script")
    q.add_argument("group")
    q = sub.add_parser("search")
    q.add_argument("pattern")
    q.add_argument("--field", choices=["source", "target", "key"], default="source")
    q.add_argument("--limit", type=int, default=20)
    q = sub.add_parser("export")
    q.add_argument("output")
    q.add_argument("--format", choices=["jsonl", "tsv"], default="jsonl")
    q = sub.add_parser("import")
    q.add_argument("file")
    q = sub.add_parser("set")
    q.add_argument("sid")
    q.add_argument("text")
    q.add_argument("--note", required=True)
    q.add_argument("--lock", action="store_true")
    q = sub.add_parser("unlock")
    q.add_argument("sid")
    q.add_argument("--note", required=True)
    q = sub.add_parser("gate")
    q.add_argument("action", choices=["list", "approve", "revoke"])
    q.add_argument("name", nargs="?", choices=GATES)
    q.add_argument("--note")
    q.add_argument("--by", default="owner")
    q = sub.add_parser("next")
    q.add_argument("stage", choices=packets.STAGES)
    q.add_argument("--who", required=True)
    q = sub.add_parser("prepare")
    q.add_argument("packet")
    q = sub.add_parser("submit")
    q.add_argument("packet")
    q.add_argument("--file")
    q = sub.add_parser("release")
    q.add_argument("packet")
    q.add_argument("--reason", required=True)
    q = sub.add_parser("abandon")
    q.add_argument("packet")
    q.add_argument("--reason", required=True, help="Preserve files and unreserve deliberately obsolete work")
    q = sub.add_parser("qa")
    q.add_argument("--source", action="store_true")
    q.add_argument("--release", action="store_true", help="Fail on missing or stale targets too")
    q = sub.add_parser("diff")
    q.add_argument("old")
    q.add_argument("new")
    q = sub.add_parser("build")
    q.add_argument("--mode", choices=["source-copy", "candidate", "release"], required=True)
    q.add_argument("--label", required=True)
    for name in ("verify-build", "install", "restore"):
        q = sub.add_parser(name)
        q.add_argument("label")
    q = sub.add_parser("lqa-import")
    q.add_argument("file", help="JSONL observations: sid, severity, comment, optional screenshot/save")
    q = sub.add_parser("issue-import", help="Import source/version-bound offline linguistic findings")
    q.add_argument("file", help="JSONL: sid, namespace, key, source_sha, source_hash, version, current_target, category, severity, comment")
    q.add_argument("--origin", required=True, help="External offline provenance, e.g. gemini-linguistic")
    q.add_argument("--by", required=True, help="Actual importing actor; never inferred as the owner")
    q.add_argument("--note", required=True, help="Provenance and evidence record")
    return p


def dispatch(args, cfg, db):
    from .adapters import get_adapter
    adapter = get_adapter(cfg)
    cmd = args.cmd
    if cmd == "import-source":
        if adapter.INPUT_MODE != "source-file":
            raise HarnessError("import-source requires a source-file adapter")
        result = adapter.capture(cfg, db, args.label, args.file.resolve())
        if not args.no_context:
            result["context"] = adapter.index_context(cfg, db)
        return result, 0
    if cmd == "doctor":
        result = doctor(cfg, db)
        return result, 0 if result["ok"] else 2
    if cmd == "discover":
        return {"game_roots": adapter.discover(cfg)}, 0
    if cmd in ("extract", "update"):
        if adapter.INPUT_MODE != "game-root":
            raise HarnessError("Use import-source for source-file adapters")
        result = adapter.capture(cfg, db, args.label, args.game_root)
        if not args.no_context:
            result["context"] = adapter.index_context(cfg, db)
        return result, 0
    if cmd == "context":
        return adapter.index_context(cfg, db), 0
    if cmd == "status":
        result = report.status(cfg, db)
        if args.brief:
            result = {k: result[k] for k in ("mode", "snapshot", "native_entries", "provisional_in_scope", "targets_nonnull_all_units", "stale", "pending_packets", "open_issues")}
        return result, 0
    if cmd == "inventory":
        return db.active_snapshot()[1], 0
    if cmd == "plan":
        blocked = packets.blockers(cfg, db)
        return {"blockers": blocked, "eligible_by_stage": {s: len(packets.eligible(cfg, db, s, "planning-reviewer")) for s in packets.STAGES}, "next": "PREPARATION: review current source/context and multilingual references; wait for the owner's instruction to translate" if cfg["project"]["preparation_only"] else "; ".join(blocked) if blocked else "Recover pending packets, then claim the earliest eligible stage; pilot approval precedes bulk waves"}, 0
    if cmd == "pending":
        return packets.pending(cfg, db), 0
    if cmd == "unit":
        u = db.unit(args.sid)
        label, _ = db.active_snapshot()
        return {**u, "references": db.rows("SELECT * FROM refs WHERE snapshot=? AND sid=?", (label, u["sid"])), "contexts": db.rows("SELECT * FROM contexts WHERE snapshot=? AND sid=? ORDER BY asset,offset", (label, u["sid"])), "history": db.rows("SELECT * FROM history WHERE sid=? ORDER BY id", (u["sid"],)), "issues": db.rows("SELECT * FROM issues WHERE sid=? ORDER BY id", (u["sid"],))}, 0
    if cmd == "references":
        return references.lookup(cfg, db, args.sid, snapshot=args.snapshot, cultures=args.cultures, include_unusable=args.include_unusable), 0
    if cmd == "search":
        rx = re.compile(args.pattern, re.I)
        rows = db.rows("SELECT sid,key,source,target,grp FROM units WHERE active=1 ORDER BY grp,ord,sid")
        return [u for u in rows if rx.search(u[args.field] or "")][:max(1,min(args.limit,500))], 0
    if cmd == "script":
        return {"ordering": "Serialized asset order; branch chronology unverified", "units": db.rows("SELECT sid,key,source,target,ord FROM units WHERE active=1 AND grp=? ORDER BY ord,sid", (args.group,))}, 0
    if cmd == "export":
        return report.export(cfg, db, cfg.path(args.output), args.format), 0
    if cmd == "import":
        return import_targets(cfg, db, cfg.path(args.file)), 0
    if cmd == "set":
        return owner_set(cfg, db, args.sid, args.text, args.note, args.lock), 0
    if cmd == "unlock":
        cfg.require_translation()
        with db.tx():
            u = db.unit(args.sid)
            db.c.execute("UPDATE units SET locked=0 WHERE sid=?", (u["sid"],))
            db.event("owner_unlock", {"sid": u["sid"], "note": args.note})
        return {"unlocked": u["sid"]}, 0
    if cmd == "gate":
        if args.action == "list":
            return db.gate_status(), 0
        if not args.name or not args.note:
            raise HarnessError("Gate changes require a gate name and --note recording the owner's decision")
        if args.action == "approve":
            return approve(cfg, db, args.name, args.note, args.by), 0
        db.c.execute("UPDATE gates SET status='pending',note=?,actor=?,updated=? WHERE name=?", (args.note, args.by, time.time(), args.name))
        db.event("owner_gate_revoke", {"name": args.name, "note": args.note})
        return {"gate": args.name, "status": "pending"}, 0
    if cmd == "next":
        return packets.claim(cfg, db, args.stage, args.who), 0
    if cmd == "prepare":
        return packets.prepare(cfg, db, args.packet), 0
    if cmd == "submit":
        result = packets.submit(cfg, db, args.packet, cfg.path(args.file) if args.file else None)
        return result, 0 if result["accepted"] else 2
    if cmd == "release":
        p = packets.get(db, args.packet)
        if p["status"] != "claimed":
            raise HarnessError("Only a claimed packet can be released")
        db.c.execute("UPDATE packets SET status='ready' WHERE id=?", (args.packet,))
        db.event("release", {"packet": args.packet, "reason": args.reason})
        return {"released": args.packet, "draft_preserved": True}, 0
    if cmd == "abandon":
        with db.tx():
            p = packets.get(db, args.packet)
            if p["status"] not in ("claimed", "ready"):
                raise HarnessError("Only unfinished work can be abandoned")
            db.c.execute("UPDATE packets SET status='obsolete',finished=? WHERE id=?", (time.time(), args.packet))
            db.event("packet_abandoned", {"packet": args.packet, "reason": args.reason})
        return {"abandoned": args.packet, "draft_and_frozen_input_preserved": True}, 0
    if cmd == "qa":
        result = qa.run(cfg, db, source=args.source)
        code = 2 if result["errors"] or (args.release and (result["missing"] or result["stale"])) else 0
        return result, code
    if cmd == "fonts":
        return adapter.fonts(cfg, db), 0
    if cmd == "roundtrip":
        return adapter.roundtrip(cfg, db), 0
    if cmd == "report":
        return report.render(cfg, db), 0
    if cmd == "diff":
        result = report.diff(db, args.old, args.new)
        write_json(cfg.root / "reports" / f"diff-{unreal.safe_name(args.old)}-{unreal.safe_name(args.new)}.json", result)
        return result, 0
    if cmd == "build":
        return adapter.build(cfg, db, args.mode, args.label), 0
    if cmd == "verify-build":
        return adapter.verify(cfg, args.label), 0
    if cmd == "install":
        return adapter.install(cfg, db, args.label), 0
    if cmd == "restore":
        return adapter.restore(cfg, db, args.label), 0
    if cmd == "issue-import":
        from .offline_issues import import_findings
        return import_findings(cfg, db, cfg.path(args.file), args.origin, args.by, args.note), 0
    if cmd == "lqa-import":
        observations = [json.loads(line) for line in cfg.path(args.file).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        with db.tx():
            for row in observations:
                u = db.unit(row["sid"])
                if row.get("severity") not in packets.SEVERITIES or not row.get("comment", "").strip():
                    raise HarnessError("LQA observations need valid severity and comment")
                db.c.execute("INSERT INTO issues(sid,packet,version,category,severity,comment) VALUES(?,'owner-lqa',?,'layout',?,?)", (u["sid"], u["version"], row["severity"], row["comment"]))
            db.event("lqa_import", observations)
        return {"imported": len(observations)}, 0
    raise HarnessError(f"Unimplemented command {cmd}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parser().parse_args(argv)
    db = None
    try:
        if args.cmd == "init":
            from .project import initialize
            emit({"initialized": str(initialize(args.directory)), "preparation_only": True})
            return 0
        cfg = Config(args.project)
        db = Database(cfg)
        result, code = dispatch(args, cfg, db)
        emit(result)
        return code
    except (HarnessError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    finally:
        if db:
            db.close()
