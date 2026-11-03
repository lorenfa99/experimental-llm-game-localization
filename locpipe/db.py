from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager

from .config import Config, HarnessError, digest

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots (
 label TEXT PRIMARY KEY, manifest TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS units (
 sid TEXT PRIMARY KEY, uid TEXT UNIQUE NOT NULL, namespace TEXT NOT NULL, key TEXT NOT NULL,
 source TEXT NOT NULL, source_sha TEXT NOT NULL, source_hash INTEGER NOT NULL,
 kind TEXT NOT NULL, wave TEXT NOT NULL, grp TEXT NOT NULL, ord INTEGER NOT NULL,
 include INTEGER NOT NULL DEFAULT 1, reason TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1, stale INTEGER NOT NULL DEFAULT 0,
 pilot INTEGER NOT NULL DEFAULT 0, target TEXT, version INTEGER NOT NULL DEFAULT 0,
 locked INTEGER NOT NULL DEFAULT 0, stages TEXT NOT NULL DEFAULT '[]',
 last_writer TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS units_group ON units(grp, ord);
CREATE TABLE IF NOT EXISTS snapshot_units (
 snapshot TEXT NOT NULL REFERENCES snapshots(label), sid TEXT NOT NULL REFERENCES units(sid),
 source TEXT NOT NULL, source_sha TEXT NOT NULL, source_hash INTEGER NOT NULL,
 PRIMARY KEY(snapshot,sid)
);
CREATE TABLE IF NOT EXISTS refs (
 snapshot TEXT NOT NULL, sid TEXT NOT NULL, culture TEXT NOT NULL,
 text TEXT NOT NULL, source_hash INTEGER NOT NULL, compatible INTEGER NOT NULL,
 PRIMARY KEY(snapshot,sid,culture)
);
CREATE TABLE IF NOT EXISTS contexts (
 snapshot TEXT NOT NULL, sid TEXT NOT NULL, asset TEXT NOT NULL,
 offset INTEGER NOT NULL, evidence TEXT NOT NULL,
 PRIMARY KEY(snapshot,sid,asset,offset)
);
CREATE INDEX IF NOT EXISTS contexts_sid ON contexts(snapshot,sid);
CREATE TABLE IF NOT EXISTS history (
 id INTEGER PRIMARY KEY, sid TEXT NOT NULL, version INTEGER NOT NULL,
 target TEXT, stage TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL,
 packet TEXT, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS packets (
 id TEXT PRIMARY KEY, stage TEXT NOT NULL, status TEXT NOT NULL,
 worker TEXT NOT NULL, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 created REAL NOT NULL, finished REAL
);
CREATE TABLE IF NOT EXISTS issues (
 id INTEGER PRIMARY KEY, sid TEXT NOT NULL, packet TEXT NOT NULL,
 version INTEGER NOT NULL, category TEXT NOT NULL, severity TEXT NOT NULL,
 comment TEXT NOT NULL, suggestion TEXT, status TEXT NOT NULL DEFAULT 'open', resolution TEXT
);
CREATE TABLE IF NOT EXISTS gates (
 name TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending',
 evidence_hash TEXT, note TEXT, actor TEXT, updated REAL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, type TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL
);
"""
GATES = ("source", "style", "glossary", "characters", "pilot", "runtime", "release")


def identity(target, namespace, key):
    uid = json.dumps([target, namespace, key], ensure_ascii=False, separators=(",", ":"))
    return "Q" + digest(uid)[:12].upper(), uid


class Database:
    def __init__(self, cfg: Config, *, readonly=False):
        self.cfg = cfg
        path = cfg.root / "data/localization.sqlite"
        if not readonly:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(path.as_uri() + "?mode=ro" if readonly else path,
                                 uri=readonly, timeout=60, isolation_level=None)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA foreign_keys=ON")
        if readonly:
            return
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)
        self.c.executemany("INSERT OR IGNORE INTO gates(name) VALUES(?)", [(g,) for g in GATES])

    def close(self):
        self.c.close()

    @contextmanager
    def tx(self):
        self.c.execute("BEGIN IMMEDIATE")
        try:
            yield self.c
            self.c.commit()
        except BaseException:
            self.c.rollback()
            raise

    def rows(self, sql, args=()):
        return [dict(r) for r in self.c.execute(sql, args)]

    def one(self, sql, args=()):
        r = self.c.execute(sql, args).fetchone()
        return dict(r) if r else None

    def meta(self, key, default=None):
        r = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def set_meta(self, key, value):
        self.c.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def event(self, kind, value):
        self.c.execute("INSERT INTO events(type,data,created) VALUES(?,?,?)", (kind, json.dumps(value, ensure_ascii=False), time.time()))

    def active_snapshot(self):
        label = self.meta("active_snapshot")
        r = self.one("SELECT * FROM snapshots WHERE label=?", (label,))
        if not r:
            raise HarnessError("No imported snapshot. Run `locpipe extract --label demo --game-root <folder>`.")
        return label, json.loads(r["manifest"])

    def unit(self, sid):
        r = self.one("SELECT * FROM units WHERE sid=?", (sid,))
        if not r:
            matches = self.rows("SELECT * FROM units WHERE key=?", (sid,))
            if len(matches) > 1:
                raise HarnessError(f"Ambiguous key {sid!r}; use its stable SID")
            r = matches[0] if matches else None
        if not r:
            raise HarnessError(f"Unknown unit {sid!r}")
        r["data"] = json.loads(r["data"])
        r["stages"] = json.loads(r["stages"])
        return r

    def corpus_hash(self):
        label, manifest = self.active_snapshot()
        return digest(json.dumps([label, manifest["content_hash"], self.rows("SELECT sid,source_sha,source_hash,include,kind,wave,grp,pilot FROM units WHERE active=1 ORDER BY sid")], sort_keys=True))

    def gate_hash(self, name):
        # A new source, rules, glossary, character decision, scope or pilot invalidates approvals.
        suffix = ""
        if name in ("pilot", "runtime", "release"):
            where = " AND pilot=1" if name == "pilot" else ""
            suffix = json.dumps(self.rows("SELECT sid,version,stale FROM units WHERE active=1 AND include=1" + where + " ORDER BY sid"))
        return digest(self.corpus_hash() + self.cfg.contract_hash() + suffix)

    def gate_ok(self, name):
        row = self.one("SELECT * FROM gates WHERE name=?", (name,))
        return bool(row and row["status"] == "approved" and row["evidence_hash"] == self.gate_hash(name))

    def gate_status(self):
        return [{**r, "effective_status": "approved" if self.gate_ok(r["name"]) else "stale" if r["status"] == "approved" else r["status"]} for r in self.rows("SELECT * FROM gates ORDER BY rowid")]
