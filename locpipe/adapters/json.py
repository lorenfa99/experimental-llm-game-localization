"""Engine-neutral source capture and verified JSON intermediates, without game writes."""
from dataclasses import dataclass, field
import json
import time
from types import SimpleNamespace
import zlib

from ..config import HarnessError, digest, file_hash, read_json, write_json
from ..db import identity
from ..unreal import safe_name

INPUT_MODE = "source-file"

@dataclass
class SourceEntry:
    namespace: str
    key: str
    source_hash: int
    text: str
    metadata: dict = field(default_factory=dict)

    @property
    def identity(self):
        return self.namespace, self.key


def decode(cfg, raw):
    document = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(document, dict) or document.get("schema") != "locpipe.source.v1":
        raise HarnessError("Expected a locpipe.source.v1 JSON object")
    if document.get("localization_target") != cfg["game"]["localization_target"]:
        raise HarnessError("Source localization_target differs from the configured identity domain")
    if document.get("source_culture") != cfg["project"]["source_culture"]:
        raise HarnessError("Source culture differs from project.source_culture")
    rows = document.get("units")
    if not isinstance(rows, list) or not rows:
        raise HarnessError("Source units must be a nonempty array")
    entries, refs, seen = [], {}, set()
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("namespace", "key", "source")):
            raise HarnessError("Each unit needs string namespace, key and source")
        if not row["key"] or "target" in row:
            raise HarnessError("Keys cannot be empty; import existing translations separately with version bindings")
        pair = row["namespace"], row["key"]
        if pair in seen:
            raise HarnessError(f"Duplicate native identity {pair!r}")
        seen.add(pair)
        revision = row.get("source_hash", zlib.crc32(row["source"].encode("utf-8")))
        if type(revision) is not int or not 0 <= revision <= 0xFFFFFFFF:
            raise HarnessError("source_hash must be an unsigned 32-bit revision; omitted values use UTF-8 CRC32")
        metadata = {k: row[k] for k in ("kind", "wave", "group", "context") if k in row}
        if any(not isinstance(v, str) for v in metadata.values()):
            raise HarnessError("Optional kind, wave, group and context must be strings")
        if "wave" in row and row["wave"] not in cfg["pipeline"]["waves"]:
            raise HarnessError("Unknown source wave")
        if "include" in row:
            if type(row["include"]) is not bool:
                raise HarnessError("include must be a boolean")
            metadata["include"] = int(row["include"])
        entries.append(SourceEntry(*pair, revision, row["source"], metadata))
        references = row.get("references", {})
        if not isinstance(references, dict):
            raise HarnessError("references must map culture codes to version-bound records")
        for culture, ref in references.items():
            if not isinstance(culture, str) or not culture or culture == document["source_culture"]:
                raise HarnessError("Reference cultures must be nonempty and different from the source")
            if not isinstance(ref, dict) or not isinstance(ref.get("text"), str):
                raise HarnessError("Each reference needs text and its actual source_hash")
            if type(ref.get("source_hash")) is not int or not 0 <= ref["source_hash"] <= 0xFFFFFFFF:
                raise HarnessError("References need their own unsigned 32-bit source_hash; no guessed compatibility")
            refs.setdefault(culture, []).append(SourceEntry(*pair, ref["source_hash"], ref["text"]))
    return document, SimpleNamespace(entries=entries), {k: SimpleNamespace(entries=v) for k, v in refs.items()}


def capture(cfg, db, label, path):
    from ..extract import import_snapshot
    safe_name(label)
    raw = path.read_bytes()
    _, native, refs = decode(cfg, raw)  # Validate completely before any DB mutation.
    content_hash = digest(raw)
    previous = db.one("SELECT manifest FROM snapshots WHERE label=?", (label,))
    if previous:
        if json.loads(previous["manifest"])["content_hash"] != content_hash or db.meta("active_snapshot") != label:
            raise HarnessError("Snapshot label is immutable; capture this revision under a new label")
        return {"label": label, "unchanged_snapshot": True}
    directory = cfg.root / "data/sources" / label
    if directory.exists():
        raise HarnessError("Partial snapshot exists; preserve and inspect it before retrying")
    directory.mkdir(parents=True)
    (directory / "source.json").write_bytes(raw)
    manifest = {"label": label, "adapter": "json", "content_hash": content_hash,
                "source_sha256": content_hash, "source_culture": cfg["project"]["source_culture"],
                "native_entries": len(native.entries), "entry_count": len(native.entries),
                "localization_files": [], "paks": [], "extracted_root": "",
                "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    write_json(directory / "manifest.json", manifest)
    stats = import_snapshot(cfg, db, label, native, refs, manifest)
    return {"label": label, **stats}


def frozen(cfg, db):
    label, manifest = db.active_snapshot()
    path = cfg.root / "data/sources" / label / "source.json"
    if manifest.get("adapter") != "json" or not path.is_file() or file_hash(path) != manifest["source_sha256"]:
        raise HarnessError("Immutable JSON snapshot is missing, modified or belongs to another adapter")
    return manifest, path.read_bytes()


def doctor(cfg, db):
    checks = [{"check": "adapter:json", "ok": True, "external_tools_required": False}]
    if db.meta("active_snapshot"):
        try:
            frozen(cfg, db)
            checks.append({"check": "immutable:source.json", "ok": True})
        except HarnessError as exc:
            checks.append({"check": "immutable:source.json", "ok": False, "error": str(exc)})
    return checks


def index_context(cfg, db):
    from ..context import apply_overrides, make_pilot, build_dossiers
    _, raw = frozen(cfg, db)
    _, native, _ = decode(cfg, raw)
    with db.tx():
        for order, row in enumerate(native.entries):
            sid, _ = identity(cfg["game"]["localization_target"], row.namespace, row.key)
            group = row.metadata.get("group", "namespace:" + (row.namespace or "<empty>"))
            data = {"context": row.metadata["context"]} if "context" in row.metadata else {}
            db.c.execute("UPDATE units SET grp=?,ord=?,data=? WHERE sid=?", (group, order, json.dumps(data), sid))
        db.set_meta("context_index", {"snapshot": db.meta("active_snapshot"), "adapter": "json",
                    "units_with_context": sum(bool(r.metadata.get("context")) for r in native.entries),
                    "ordering": "Input serialization order; chronology and reachability unverified"})
        db.event("context_index", db.meta("context_index"))
    apply_overrides(cfg, db)
    make_pilot(cfg, db)
    build_dossiers(cfg, db)
    return db.meta("context_index")


def roundtrip(cfg, db):
    _, raw = frozen(cfg, db)
    original = json.loads(raw.decode("utf-8-sig"))
    rebuilt = json.loads(json.dumps(original, ensure_ascii=False))
    if original != rebuilt:
        raise HarnessError("JSON semantic roundtrip failed")
    result = {"adapter": "json", "semantic_roundtrip": True, "source_sha256": digest(raw)}
    write_json(cfg.root / "reports/roundtrip.json", result)
    return result


def build(cfg, db, mode, name):
    from ..build import preflight
    safe_name(name)
    label, _ = preflight(cfg, db, mode)
    _, raw = frozen(cfg, db)
    document = json.loads(raw.decode("utf-8-sig"))
    if mode != "source-copy":
        rows = {(u["namespace"], u["key"]): u for u in db.rows("SELECT * FROM units WHERE active=1")}
        for unit in document["units"]:
            u = rows[unit["namespace"], unit["key"]]
            unit["target"] = u["target"] if u["include"] else unit["source"]
        document["target_culture"] = cfg["project"]["target_culture"]
        data = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    else:
        data = raw
    root = cfg.root / "build" / name
    if root.exists():
        raise HarnessError("Build exists; use a new label")
    root.mkdir(parents=True)
    artifact = root / "localization.json"
    artifact.write_bytes(data)
    if artifact.read_bytes() != data or json.loads(artifact.read_text(encoding="utf-8-sig")) != document:
        raise HarnessError("JSON artifact readback failed")
    record = {"id": name, "mode": mode, "adapter": "json", "snapshot": label,
              "artifact": artifact.relative_to(cfg.root).as_posix(), "artifact_sha256": digest(data),
              "source_sha256": digest(raw), "contract_hash": cfg.contract_hash(), "corpus_hash": db.corpus_hash(),
              "unit_count": len(document["units"]), "readback_verified": True,
              "runtime_verified": False, "installable": False,
              "limitation": "Verified intermediate JSON; game injection/packaging requires an engine adapter"}
    write_json(root / "manifest.json", record)
    db.event("build", record)
    return record


def verify(cfg, name):
    safe_name(name)
    record = read_json(cfg.root / "build" / name / "manifest.json")
    if not record or record.get("adapter") != "json":
        raise HarnessError("JSON build manifest not found")
    path = cfg.path(record["artifact"]).resolve()
    if not path.is_relative_to((cfg.root / "build" / name).resolve()) or not path.is_file() or file_hash(path) != record["artifact_sha256"]:
        raise HarnessError("Build artifact is missing, modified or outside its build directory")
    json.loads(path.read_text(encoding="utf-8-sig"))
    return {"verified": True, **record}


def fonts(cfg, db):
    return {"supported": False, "fonts": [], "runtime_verified": False,
            "limitation": "Engine-neutral JSON carries no fonts; a game adapter must audit actual fonts and rendering"}


def discover(cfg):
    return []


def install(cfg, db, name):
    raise HarnessError("JSON builds are intermediate files; no generic game installation is implemented")


restore = install
