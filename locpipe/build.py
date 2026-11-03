from __future__ import annotations

import json
import csv
import os
import shutil
import subprocess
import time
from pathlib import Path

from .config import HarnessError, file_hash, read_json, write_json
from .locres import Locres
from .qa import run as qa_run
from .unreal import repak, safe_entry, safe_name


def preflight(cfg, db, mode):
    if mode not in ("source-copy", "candidate", "release"):
        raise HarnessError("Build mode must be source-copy, candidate or release")
    label, manifest = db.active_snapshot()
    if mode != "source-copy":
        cfg.require_translation()
        gates = cfg["pipeline"]["required_gates"] + ["pilot"]
        if mode == "release":
            gates += ["runtime", "release"]
        missing = [g for g in gates if not db.gate_ok(g)]
        if missing:
            raise HarnessError("Build blocked by owner gates: " + ", ".join(missing))
        qa = qa_run(cfg, db)
        if qa["missing"] or qa["stale"] or qa["errors"]:
            raise HarnessError("Build blocked: missing/stale targets or blocking QA findings")
        incomplete = [u["sid"] for u in db.rows("SELECT sid,stages FROM units WHERE active=1 AND include=1") if not {"translate", "review", "revise", "consistency", "fluency"}.issubset(json.loads(u["stages"]))]
        if incomplete or db.one("SELECT id FROM issues WHERE status='open' LIMIT 1"):
            raise HarnessError(f"Build blocked: {len(incomplete)} units need linguistic stages, or open review issues remain")
        if db.one("SELECT id FROM packets WHERE status IN ('claimed','ready') LIMIT 1"):
            raise HarnessError("Build blocked by unfinished packets; recover drafts first")
    return label, manifest


def build(cfg, db, mode, name):
    safe_name(name)
    label, manifest = preflight(cfg, db, mode)
    root = cfg.root / "build" / name
    if root.exists():
        raise HarnessError(f"Build {name!r} already exists; use a new label")
    project, target = cfg["game"]["project_dir"], cfg["game"]["localization_target"]
    culture = cfg["project"]["source_culture"]
    native_path = cfg.root / "data/sources" / label / "localization" / culture / f"{target}.locres"
    expected_file = next((f for f in manifest["localization_files"] if f["path"].endswith(f"/{culture}/{target}.locres")), None)
    if not expected_file or file_hash(native_path) != expected_file["sha256"]:
        raise HarnessError("Immutable native source is missing or changed; build refused")
    native = Locres.load(native_path)
    replacements = {}
    if mode != "source-copy":
        replacements = {(u["namespace"], u["key"]): u["target"] for u in db.rows("SELECT * FROM units WHERE active=1 AND include=1")}
    data = native.encode(replacements)
    rebuilt = Locres.parse(data)
    expected = {e.identity: (e.source_hash, replacements.get(e.identity, e.text), e.namespace_hash, e.key_hash) for e in native.entries}
    actual = {e.identity: (e.source_hash, e.text, e.namespace_hash, e.key_hash) for e in rebuilt.entries}
    if expected != actual:
        raise HarnessError("Locres round-trip changed identities, text or hash metadata")
    slot = cfg["build"]["slot"]
    if slot != culture:
        raise HarnessError("Only a native-culture overlay is supported; other culture/menu strategies require runtime implementation")
    entry = f"{project}/Content/Localization/{target}/{slot}/{target}.locres"
    safe_entry(entry)
    staged = root / "staging" / entry
    staged.parent.mkdir(parents=True)
    staged.write_bytes(data)
    pak = root / cfg["build"]["filename"]
    repak(cfg, "pack", root / "staging", pak, "--version", cfg["build"]["pak_version"], "--mount-point", cfg["build"]["mount_point"])
    pak_entries = repak(cfg, "list", pak).splitlines()
    if pak_entries != [entry]:
        raise HarnessError(f"Unexpected overlay payload: {pak_entries}")
    unpacked = repak(cfg, "get", pak, entry, binary=True)
    if unpacked != data:
        raise HarnessError("Built pak failed binary readback verification")
    record = {"id": name, "mode": mode, "snapshot": label, "source_content_hash": manifest["content_hash"], "contract_hash": cfg.contract_hash(), "corpus_hash": db.corpus_hash(), "source_paks": manifest["paks"], "pak": pak.relative_to(cfg.root).as_posix(), "pak_sha256": file_hash(pak), "entry": entry, "locres_sha256": file_hash(staged), "unit_count": len(native.entries), "translated_count": len(replacements), "binary_readback_verified": True, "runtime_verified": False, "installable": mode != "source-copy", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    write_json(root / "manifest.json", record)
    db.event("build", record)
    return record


def verify(cfg, name):
    safe_name(name)
    record = read_json(cfg.root / "build" / name / "manifest.json")
    if not record:
        raise HarnessError("Build manifest not found")
    pak = cfg.path(record["pak"])
    if not pak.resolve().is_relative_to((cfg.root / "build").resolve()) or file_hash(pak) != record["pak_sha256"]:
        raise HarnessError("Build pak is missing, outside build/, or has changed")
    if repak(cfg, "list", pak).splitlines() != [record["entry"]]:
        raise HarnessError("Build entry list changed")
    from .config import digest
    if digest(repak(cfg, "get", pak, record["entry"], binary=True)) != record["locres_sha256"]:
        raise HarnessError("Build locres readback hash changed")
    return {"verified": True, **record}


def _game_closed(cfg):
    if os.name != "nt":
        raise HarnessError("Install/restore currently supports Windows process checks only")
    names = cfg["game"].get("process_names", [])
    if not isinstance(names, list) or not names or any(
            not isinstance(name, str) or not name or any(c in name for c in "\\/\r\n\x00")
            for name in names):
        raise HarnessError("Configure the actual game.process_names before install/restore")
    r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    if r.returncode:
        raise HarnessError("Cannot verify the game process is closed")
    running = {row[0].casefold() for row in csv.reader(r.stdout.splitlines()) if row}
    if running.intersection(name.casefold() for name in names):
        raise HarnessError("Close the configured game processes before install/restore")


def install(cfg, db, name):
    # Exposed for a future owner-authorized playtest; never called by setup/extract/build.
    cfg.require_translation()
    record = verify(cfg, name)
    if not record["installable"]:
        raise HarnessError("Source-copy builds are diagnostic artifacts and cannot be installed by this harness")
    if record["corpus_hash"] != db.corpus_hash() or record["contract_hash"] != cfg.contract_hash():
        raise HarnessError("Build is stale; rebuild before installing")
    game = cfg.game_root()
    pakdir = game / cfg["game"]["pak_relative"]
    _game_closed(cfg)
    for p in record["source_paks"]:
        if file_hash(pakdir / p["name"]) != p["sha256"]:
            raise HarnessError("Installed vanilla pak differs from the build baseline")
    dest = pakdir / cfg["build"]["filename"]
    if dest.exists():
        raise HarnessError("Overlay already exists. Restore the owned overlay first; existing files are never overwritten")
    receipt = {"build": name, "game_root": str(game), "destination": str(dest), "pak_sha256": record["pak_sha256"], "installed_at": time.time(), "restored": False}
    receipt_path = cfg.root / "backups" / f"install-{name}.json"
    if receipt_path.exists():
        raise HarnessError("An install receipt with that build name already exists; make a fresh build")
    write_json(receipt_path, {**receipt, "state": "planned"})
    # Exclusive destination creation closes the check/create race and preserves existing mods.
    with cfg.path(record["pak"]).open("rb") as src, dest.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    if file_hash(dest) != record["pak_sha256"]:
        raise HarnessError("Installed overlay verification failed; use the planned receipt for recovery")
    write_json(receipt_path, {**receipt, "state": "installed"})
    db.event("install", receipt)
    return receipt


def restore(cfg, db, name):
    safe_name(name)
    path = cfg.root / "backups" / f"install-{name}.json"
    receipt = read_json(path)
    if not receipt or receipt.get("restored"):
        raise HarnessError("No active owned install receipt for this build")
    # Restoration remains available even if preparation-only mode was re-enabled.
    game = Path(receipt["game_root"]).resolve()
    dest = Path(receipt["destination"]).resolve()
    expected = (game / cfg["game"]["pak_relative"] / cfg["build"]["filename"]).resolve()
    if dest != expected or not dest.is_relative_to(game):
        raise HarnessError("Receipt destination does not match the expected game overlay")
    _game_closed(cfg)
    if dest.exists():
        if file_hash(dest) != receipt["pak_sha256"]:
            raise HarnessError("Overlay changed outside the harness; preserve and inspect target before restoring")
        dest.unlink()  # One verified owned file. No original game asset was replaced.
    write_json(path, {**receipt, "restored": True, "state": "restored", "restored_at": time.time()})
    db.event("restore", {"build": name})
    return {"restored": name, "removed_overlay": str(dest)}
