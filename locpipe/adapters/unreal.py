"""Unreal locres/.pak adapter from the production harness; game paths are configured."""
from .. import build as packaging, context, extract, fonts as font_audit
from ..config import HarnessError, file_hash, write_json
from ..locres import Locres
from .. import unreal as pak

INPUT_MODE = "game-root"
capture = extract.extract
index_context = context.index_context
build = packaging.build
verify = packaging.verify
install = packaging.install
restore = packaging.restore
fonts = font_audit.audit
discover = pak.discover


def doctor(cfg, db):
    checks = []
    try:
        checks.append({"check": "repak", "ok": True, "value": pak.repak(cfg, "--version")})
    except HarnessError as exc:
        checks.append({"check": "repak", "ok": False, "error": str(exc)})
    if db.meta("active_snapshot"):
        label, manifest = db.active_snapshot()
        for resource in manifest["localization_files"]:
            suffix = resource["path"].split("/Localization/", 1)[1].split("/", 1)[1]
            path = cfg.root / "data/sources" / label / "localization" / suffix
            checks.append({"check": "immutable:" + suffix,
                           "ok": path.is_file() and file_hash(path) == resource["sha256"]})
    return checks


def roundtrip(cfg, db):
    label, _ = db.active_snapshot()
    results = []
    for path in sorted((cfg.root / "data/sources" / label / "localization").glob("*/*.locres")):
        native = Locres.load(path)
        if Locres.parse(native.encode(rebuild=True)).entries != native.entries:
            raise HarnessError(f"Semantic roundtrip failed for {path}")
        results.append({"culture": path.parent.name, "version": native.version,
                        "entries": len(native.entries), "semantic_roundtrip": True,
                        "source_copy_byte_identical": native.encode() == path.read_bytes()})
    if not results:
        raise HarnessError("No captured locres resources to roundtrip")
    result = {"adapter": "unreal", "resources": results}
    write_json(cfg.root / "reports/roundtrip.json", result)
    return result
