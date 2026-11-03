from __future__ import annotations

from .config import HarnessError, file_hash, write_json


def audit(cfg, db):
    try:
        from fontTools.ttLib import TTFont
    except ImportError as e:
        raise HarnessError("Font audit needs FontTools. Install the optional fonts extra for this toolkit") from e
    label, manifest = db.active_snapshot()
    output = cfg.path(manifest["extracted_root"])
    root = output / cfg["game"]["project_dir"] / "Content"
    probe = cfg["qa"]["font_characters"]
    fonts = []
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in (".ufont", ".ttf", ".otf"):
            continue
        try:
            with TTFont(p, lazy=True) as font:
                cmap = font.getBestCmap() or {}
                fonts.append({"path": p.relative_to(output).as_posix(), "sha256": file_hash(p), "glyphs": len(cmap), "missing_probe": "".join(c for c in probe if ord(c) not in cmap), "status": "cmap_only"})
        except Exception as e:
            fonts.append({"path": p.relative_to(output).as_posix(), "status": "unparsed", "error": str(e)})
    result = {"snapshot": label, "probe": probe, "fonts": fonts, "limitation": "Character-map coverage does not verify font routing, fallback, atlas generation, clipping or rendering in game. Require runtime LQA."}
    write_json(cfg.root / "reports/fonts.json", result)
    return result
