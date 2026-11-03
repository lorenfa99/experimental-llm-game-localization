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


def coverage(cfg, db, characters):
    """Character-map coverage of the exact characters used by final targets, per captured game font.

    Read-only evidence. A font that lacks a character is a finding; a font that has it
    still proves nothing about routing, fallback or rendering."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError as e:
        raise HarnessError("Font coverage needs FontTools. Install the optional fonts extra for this toolkit") from e
    label, manifest = db.active_snapshot()
    output = cfg.path(manifest["extracted_root"])
    root = output / cfg["game"]["project_dir"] / "Content"
    fonts = []
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in (".ufont", ".ttf", ".otf"):
            continue
        row = {"path": p.relative_to(output).as_posix(), "sha256": file_hash(p)}
        try:
            with TTFont(p, lazy=True) as font:
                cmap = font.getBestCmap() or {}
                row.update(status="cmap_only", missing=[f"U+{ord(c):04X}" for c in sorted(set(characters)) if ord(c) not in cmap])
        except Exception as e:
            row.update(status="unparsed", error=str(e))
        fonts.append(row)
    return {"snapshot": label, "fonts": fonts,
            "all_cover": bool(fonts) and all(f["status"] == "cmap_only" and not f["missing"] for f in fonts),
            "limitation": "Character-map coverage does not verify font routing, fallback, atlas generation, clipping or rendering in game."}
