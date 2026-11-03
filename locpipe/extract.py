from __future__ import annotations

import json
import re
import shutil
import time
from collections import Counter
from pathlib import Path

from . import db as database
from .config import Config, HarnessError, digest, file_hash, write_json
from .locres import Locres
from .unreal import extract_pak, list_paks, safe_name


def classify(entry):
    key, text = entry.key.lower(), entry.text
    if text in ("", "<Empty String>"):
        return "sentinel", "unclassified", 0, "Empty source or literal shipped sentinel; preserve verbatim"
    if re.fullmatch(r"[\W\d_]+", text) or (key.startswith("binding_") and len(text) == 1):
        return "symbol", "unclassified", 0, "Symbol/number/key legend; source copy pending scope review"
    if re.search(r"\[dev name\]|only shows in editor|texttexttext|pls pls|^Test$|^frog$|^AllCorrect$|Compiling \{num\}|shader compile", text, re.I) or key == "characterteststring":
        return "diagnostic", "unclassified", 0, "Diagnostic/development candidate; runtime reachability not established"
    if key.endswith("_name") or key.endswith("_areaname") or "_save_" in key:
        return "name", "names", 1, "Key suffix heuristic; verify in context"
    if entry.namespace == "Dialogue" or key.startswith("d_"):
        return "dialogue", "story", 1, "Dialogue namespace/key prefix; branch/speaker must be checked"
    if re.match(r"(?:book\d|note\d|document\d)", key) and key.endswith("_desc"):
        return "readable", "story", 1, "Readable key family; verify in context"
    if key.endswith("_desc") or key.startswith(("guide_", "status_", "playerattribs_", "wepstats_", "dmgtype_")):
        return "mechanics", "mechanics", 1, "Description/mechanics key heuristic; may include lore"
    if key.startswith(("option", "buttonhint", "pausemenu", "titlescreen", "hud_", "journal_", "binding_", "menu", "modal_", "shop_", "save", "demo", "systemmessage", "credits_", "numformat_")):
        return "ui", "ui", 1, "UI key family; size limits unmeasured"
    return "unclassified", "unclassified", 1, "Unclassified: requires context/scope review before bulk translation"


def import_snapshot(cfg, db, label, native, references, manifest):
    """Atomic baseline/update import. No target language is ever copied from any locale."""
    existing = db.one("SELECT manifest FROM snapshots WHERE label=?", (label,))
    if existing:
        if json.loads(existing["manifest"])["content_hash"] != manifest["content_hash"]:
            raise HarnessError(f"Snapshot {label!r} already contains different inputs; choose a new label")
        if db.meta("active_snapshot") != label:
            raise HarnessError("Historical snapshots cannot be reactivated by extraction. Import a new label for the current game.")
        return {"unchanged_snapshot": True, "units": len(native.entries)}
    stats = Counter(new=0, changed=0, unchanged=0, removed=0, reference_mismatches=0)
    ref_maps = {culture: {e.identity: e for e in r.entries} for culture, r in references.items()}
    with db.tx():
        db.c.execute("INSERT INTO snapshots VALUES(?,?,?)", (label, json.dumps(manifest), time.time()))
        was_active = {r["sid"] for r in db.rows("SELECT sid FROM units WHERE active=1")}
        db.c.execute("UPDATE units SET active=0")
        now_active = set()
        for order, e in enumerate(native.entries):
            sid, uid = database.identity(cfg["game"]["localization_target"], e.namespace, e.key)
            now_active.add(sid)
            old = db.one("SELECT * FROM units WHERE uid=?", (uid,))
            sha = digest(e.text)
            kind, wave, include, reason = classify(e)
            group = ("key-family:" + e.key.split("_", 1)[0]) if e.namespace == "ImportedStringTable" else "namespace:" + (e.namespace or "<empty>")
            metadata = getattr(e, "metadata", {})
            kind, wave = metadata.get("kind", kind), metadata.get("wave", wave)
            include = metadata.get("include", include)
            group = metadata.get("group", group)
            if old:
                changed = old["source_sha"] != sha or old["source_hash"] != e.source_hash
                stats["changed" if changed else "unchanged"] += 1
                db.c.execute("UPDATE units SET source=?,source_sha=?,source_hash=?,active=1,stale=?,stages=? WHERE sid=?", (e.text, sha, e.source_hash, int(bool(old["stale"] or (changed and old["target"] is not None))), "[]" if changed else old["stages"], sid))
                if changed:
                    # A demo sentinel/developer placeholder can become real full-game
                    # text. Re-run the source-derived proposal; reviewed overrides
                    # remain separate and source-hash-bound in context indexing.
                    db.c.execute("UPDATE units SET kind=?,wave=?,include=?,reason=? WHERE sid=?", (kind, wave, include, reason, sid))
                explicit = {k: metadata[k] for k in ("kind", "wave", "include") if k in metadata}
                if explicit:
                    db.c.execute("UPDATE units SET " + ",".join(k + "=?" for k in explicit) + " WHERE sid=?",
                                 (*explicit.values(), sid))
            else:
                stats["new"] += 1
                db.c.execute("INSERT INTO units(sid,uid,namespace,key,source,source_sha,source_hash,kind,wave,grp,ord,include,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (sid, uid, e.namespace, e.key, e.text, sha, e.source_hash, kind, wave, group, order, include, reason))
            db.c.execute("INSERT INTO snapshot_units VALUES(?,?,?,?,?)", (label, sid, e.text, sha, e.source_hash))
            for culture, values in ref_maps.items():
                ref = values.get(e.identity)
                if ref:
                    compatible = ref.source_hash == e.source_hash
                    stats["reference_mismatches"] += not compatible
                    db.c.execute("INSERT INTO refs VALUES(?,?,?,?,?,?)", (label, sid, culture, ref.text, ref.source_hash, int(compatible)))
        stats["removed"] = len(was_active - now_active)
        db.set_meta("active_snapshot", label)
        db.set_meta("last_import", dict(stats))
        db.event("snapshot_import", {"label": label, **stats})
    return dict(stats)


def extract(cfg: Config, db, label: str, root: str | None = None):
    safe_name(label)
    game = cfg.game_root(root)
    paks, entries, info = list_paks(cfg, game)
    fingerprint = [{"name": p.name, "size": p.stat().st_size, "sha256": file_hash(p)} for p in paks]
    content_hash = digest(json.dumps(fingerprint, sort_keys=True))
    old = db.one("SELECT manifest FROM snapshots WHERE label=?", (label,))
    if old and json.loads(old["manifest"])["content_hash"] != content_hash:
        raise HarnessError("Snapshot label is immutable; use a new label for this build")
    if old:
        if db.meta("active_snapshot") != label:
            raise HarnessError("Use a new snapshot label for an updated/reinstalled build")
        return {"unchanged_snapshot": True, "label": label}
    output = cfg.root / "work/extracted" / label
    extract_pak(cfg, paks[0], output)
    project, target = cfg["game"]["project_dir"], cfg["game"]["localization_target"]
    locbase = output / project / "Content/Localization" / target
    culture = cfg["project"]["source_culture"]
    source = locbase / culture / f"{target}.locres"
    if not source.is_file():
        raise HarnessError(f"Missing native source {source}; inspect target/culture before continuing")
    resources = {}
    for p in sorted(locbase.glob(f"*/{target}.locres")):
        resources[p.parent.name] = Locres.load(p)
    native = resources.pop(culture)
    # Length-stress test pseudo locale is inventory only, never a reference language.
    references = {c: r for c, r in resources.items() if c not in cfg.values.get("references", {}).get("excluded_cultures", ["en-US-POSIX"])}
    files = [{"path": p.relative_to(output).as_posix(), "sha256": file_hash(p), "size": p.stat().st_size} for p in sorted(locbase.rglob("*")) if p.is_file()]
    manifest = {"label": label, "game_root": str(game), "extracted_root": output.relative_to(cfg.root).as_posix(), "content_hash": content_hash, "paks": fingerprint, "pak_info": info, "entry_count": len(entries), "localization_files": files, "source_culture": culture, "native_entries": len(native.entries), "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    version = game / "version.txt"
    if version.is_file():
        manifest["version_file"] = {"text": version.read_text(encoding="utf-8-sig").strip(), "sha256": file_hash(version)}
    steamapps = game.parent.parent
    for acf in sorted(steamapps.glob("appmanifest_*.acf")):
        values = dict(re.findall(r'"([^"\r\n]+)"\s+"([^"\r\n]*)"', acf.read_text(encoding="utf-8-sig")))
        if values.get("installdir") == game.name:
            manifest["steam"] = {k: values[k] for k in ("appid", "name", "buildid", "LastUpdated", "installdir") if k in values}
            break
    # Immutable raw resources support offline rebuilds and auditing without a Steam install.
    source_dir = cfg.root / "data/sources" / label
    if source_dir.exists() and any(source_dir.iterdir()):
        raise HarnessError(f"Uncommitted partial snapshot at {source_dir}; inspect/recover target before retrying")
    source_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(locbase, source_dir / "localization", dirs_exist_ok=True)
    write_json(source_dir / "manifest.json", manifest)
    stats = import_snapshot(cfg, db, label, native, references, manifest)
    write_json(cfg.root / "data/inventory" / f"{label}.json", {**manifest, "entries": entries, "import": stats})
    return {"label": label, **stats}
