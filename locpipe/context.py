from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .config import HarnessError, read_json, write_json
from .locres import Reader

TOKEN = re.compile(rb"(?<![A-Za-z0-9_])([A-Za-z0-9_]{2,128})\x00")


def base_ftext_candidate(data, match):
    """Conservative byte-level coverage audit, not a general cooked asset parser."""
    key = match.group(1)
    offset = match.start(1)
    if not re.fullmatch(rb"[0-9A-F]{32}", key) or offset < 12 or data[offset-4:offset] != b"!\x00\x00\x00":
        return None
    ns_end = offset - 4
    for size in range(1, 130):
        start = ns_end - size - 4
        if start < 5 or data[start:start+4] != size.to_bytes(4, "little"):
            continue
        raw = data[start+4:ns_end]
        if not raw.endswith(b"\0") or b"\0" in raw[:-1] or data[start-1] != 0:
            continue
        flags = int.from_bytes(data[start-5:start-1], "little")
        if flags > 15:
            continue
        try:
            namespace = raw[:-1].decode("utf-8")
            r = Reader(data)
            r.stream.seek(match.end())
            text = r.string()
        except (UnicodeDecodeError, HarnessError):
            continue
        if 1 <= len(text) <= 32768 and any(c.isalpha() for c in text) and not any(ord(c) < 32 and c not in "\r\n\t" for c in text):
            return {"namespace": namespace, "key": key.decode("ascii"), "source": text, "flags": flags, "offset": start-5, "confidence": "serialized_base_ftext_candidate", "note": "Byte-level candidate; confirm with an asset parser/runtime before adding to scope. Flags may make text transient or culture-invariant."}
    return None


def index_context(cfg, db):
    label, manifest = db.active_snapshot()
    output = cfg.path(manifest["extracted_root"])
    root = output / cfg["game"]["project_dir"] / "Content"
    if not root.is_dir():
        raise HarnessError("Extracted assets missing; restore work/extracted or capture a new snapshot")
    units = db.rows("SELECT sid,key,namespace,kind FROM units WHERE active=1")
    by_key = defaultdict(list)
    for u in units:
        by_key[u["key"].encode("ascii", errors="backslashreplace")].append(u["sid"])
    matches = []
    locations = defaultdict(list)
    total_files = 0
    engine_versions = set()
    known = {(u["namespace"], u["key"]) for u in units}
    ungathered = []
    for p in sorted(root.rglob("*")):
        if p.suffix not in (".uasset", ".uexp", ".umap"):
            continue
        total_files += 1
        data = p.read_bytes()
        engine_versions.update(s.decode("ascii") for s in re.findall(rb"\+\+UE[45]\+Release-[0-9.]+", data))
        hits = []
        for m in TOKEN.finditer(data):
            key = m.group(1)
            candidate = base_ftext_candidate(data, m)
            if candidate and (candidate["namespace"], candidate["key"]) not in known:
                ungathered.append({**candidate, "asset": p.relative_to(output).as_posix()})
            if key not in by_key:
                continue
            offset = m.start(1)
            # A serialized FString length immediately before the token establishes a
            # real string occurrence, rather than a substring of a texture or identifier.
            if offset < 4 or int.from_bytes(data[offset-4:offset], "little", signed=True) != len(key) + 1:
                continue
            for sid in by_key[key]:
                hits.append((sid, offset))
        storage = len({sid for sid, _ in hits}) >= 250
        asset = p.relative_to(output).as_posix()
        evidence = "key_in_string_table_storage" if storage else "serialized_key_occurrence"
        for sid, offset in hits:
            matches.append((label, sid, asset, offset, evidence))
            if not storage:
                locations[sid].append((asset, offset))
    with db.tx():
        db.c.execute("DELETE FROM contexts WHERE snapshot=?", (label,))
        db.c.executemany("INSERT OR IGNORE INTO contexts VALUES(?,?,?,?,?)", matches)
        for u in units:
            fallback = "key-family:" + u["key"].split("_", 1)[0] if u["namespace"] == "ImportedStringTable" else "namespace:" + (u["namespace"] or "<empty>")
            db.c.execute("UPDATE units SET grp=?,ord=0 WHERE sid=?", (fallback, u["sid"]))
            candidates = locations.get(u["sid"], [])
            dialogue = [a for a in candidates if "dialogue" in a[0].lower() and a[0].endswith(".uexp")]
            candidates = dialogue or [a for a in candidates if a[0].endswith(".uexp")] or candidates
            # Context group is an asset, with SERIALIZATION order only. A branch graph
            # or speaker identity cannot be reconstructed from byte offsets alone.
            if candidates:
                path, offset = sorted(candidates, key=lambda a: (a[0].count("/"), a[0], a[1]))[0]
                group = str(Path(path).with_suffix("")).replace("\\", "/")
                db.c.execute("UPDATE units SET grp=?,ord=? WHERE sid=?", (group, offset, u["sid"]))
        db.set_meta("context_index", {"snapshot": label, "files_scanned": total_files, "occurrences": len(matches), "units_with_context": len(locations), "ungathered_ftext_candidates": len(ungathered), "engine_versions": sorted(engine_versions), "ordering": "serialized asset order, not verified dialogue chronology"})
        db.event("context_index", db.meta("context_index"))
    apply_overrides(cfg, db)
    write_json(cfg.root / "data/context/ungathered-ftext.json", {"snapshot": label, "candidates": ungathered, "limitation": "Covers recognizable Base FText GUID identities only. FStrings, textures, movies, generated/invariant text and other FText histories require runtime or a full asset parser. Candidates are not imported as translatable units."})
    make_pilot(cfg, db)
    build_dossiers(cfg, db)
    return db.meta("context_index")


def apply_overrides(cfg, db):
    entries = read_json(cfg.root / "data/overrides.json", {})
    with db.tx():
        for sid, changes in entries.items():
            unit = db.unit(sid)
            if changes.get("source_sha") != unit["source_sha"]:
                raise HarnessError(f"Context override for {sid} is stale; review against the new source-language")
            allowed = {k: v for k, v in changes.items() if k in ("kind", "wave", "grp", "ord", "include", "reason")}
            if allowed:
                db.c.execute("UPDATE units SET " + ",".join(k + "=?" for k in allowed) + " WHERE sid=?", (*allowed.values(), sid))


def make_pilot(cfg, db):
    # Selection is source-only and reproducible. Freeze while any linguistic work exists.
    if db.one("SELECT sid FROM units WHERE target IS NOT NULL LIMIT 1"):
        return
    selected = set()
    groups = defaultdict(list)
    for u in db.rows("SELECT * FROM units WHERE active=1 AND include=1 ORDER BY grp,ord,sid"):
        groups[u["kind"]].append(u)
    n = cfg["pipeline"]["pilot_units_per_kind"]
    for kind, units in groups.items():
        # Spread samples through each kind instead of choosing the first lexical block.
        for i in range(min(n, len(units))):
            selected.add(units[i * len(units) // min(n, len(units))]["sid"])
    scenes = db.rows("SELECT grp,COUNT(*) n FROM units WHERE active=1 AND include=1 AND kind='dialogue' GROUP BY grp HAVING n BETWEEN 8 AND 60 ORDER BY n DESC,grp")
    if scenes:
        selected.update(u["sid"] for u in db.rows("SELECT sid FROM units WHERE grp=? AND active=1 AND include=1", (scenes[0]["grp"],)))
    # Owner-chosen whole groups (complete scenes/lists) added to the automatic sample.
    for group in cfg["pipeline"].get("pilot_groups", []):
        members = db.rows("SELECT sid FROM units WHERE grp=? AND active=1 AND include=1", (group,))
        if not members:
            raise HarnessError(f"pipeline.pilot_groups names an empty or unknown group: {group}")
        selected.update(u["sid"] for u in members)
    with db.tx():
        db.c.execute("UPDATE units SET pilot=0 WHERE active=1")
        db.c.executemany("UPDATE units SET pilot=1 WHERE sid=?", [(s,) for s in sorted(selected)])
    write_json(cfg.root / "data/context/pilot.json", {"status": "proposed", "selection": "Spread sample per kind plus one complete serialized dialogue asset group. Verify branch completeness before pilot approval.", "sids": sorted(selected)})


def build_dossiers(cfg, db):
    label, _ = db.active_snapshot()
    groups = defaultdict(list)
    for u in db.rows("SELECT sid,key,source,kind,grp,ord,reason FROM units WHERE active=1 AND include=1 ORDER BY grp,ord,sid"):
        groups[u["grp"]].append(u)
    dossiers = []
    for group, units in groups.items():
        dossiers.append({"group": group, "evidence": "Asset association from serialized keys when available; key family otherwise.", "ordering": "Serialized order only; branching and actual chronology unverified.", "speaker": None, "addressee": None, "brief_status": "needs_verified_context_research", "units": units})
    write_json(cfg.root / "data/context/scenes.json", dossiers)
    # Candidates are source-language only; a terminologist later supplies research and target-language.
    terms = db.rows("SELECT sid,key,source,kind,grp FROM units WHERE active=1 AND include=1 AND (kind='name' OR key LIKE 'status_%' OR key LIKE 'dmgtype_%' OR key LIKE 'playerattribs_%') ORDER BY wave,key")
    write_json(cfg.root / "data/context/term-candidates.json", [{**u, "target": None, "status": "source_candidate"} for u in terms])
    actors = sorted({p.split("/NPCs/", 1)[1].split("/", 1)[0] for r in db.rows("SELECT DISTINCT asset FROM contexts WHERE snapshot=? AND asset LIKE '%/NPCs/%'", (label,)) for p in [r["asset"]]})
    write_json(cfg.root / "data/context/character-candidates.json", [{"asset_folder": a, "display_name": None, "gender": "unknown", "voice": None, "address": None, "status": "asset_folder_candidate", "note": "Folder label is evidence of an asset family, not proof of a speaker or identity."} for a in actors])
    return {"groups": len(dossiers), "terms": len(terms), "actor_folders": len(actors)}
