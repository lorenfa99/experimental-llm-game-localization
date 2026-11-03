"""Dry-run a packet result through the harness's own submit checks without submitting.

Read-only: target never writes the database, the attempt counter or the errors file, so
workers can fix QA errors before spending one of their three submit attempts.

    python scripts/check_result.py <packet-id> [--file <result.json>]

Prints the blocking errors and, per unit, the QA warnings that need an acknowledgment.
Exit status 0 means `python -m locpipe submit <packet-id>` should accept the result.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locpipe import packets  # noqa: E402
from locpipe.config import Config, HarnessError, read_json  # noqa: E402
from locpipe.db import Database  # noqa: E402
from locpipe.qa import check  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("packet")
    ap.add_argument("--file")
    ap.add_argument("--brief", action="store_true",
                    help="Run every check; print all errors and warning counts instead of repeated warning text")
    ap.add_argument("--project", type=Path, default=Path.cwd())
    args = ap.parse_args(argv)
    cfg = Config(args.project)
    with closing(Database(cfg, readonly=True)) as db:
        p = packets.get(db, args.packet)
        result = read_json(Path(args.file) if args.file else cfg.root / "work/results" / (p["id"] + ".json"))
        out = {"packet": p["id"], "stage": p["stage"], "errors": [], "warnings": {}}
        try:
            packets._preflight(cfg, db, p, result)
            out["errors"] = packets._validate(cfg, db, p, result)
        except HarnessError as e:
            out["errors"] = [str(e)]
        if p["stage"] != "review" and isinstance(result, dict):
            terms = read_json(cfg.root / "glossary/glossary.json", {"entries": []})["entries"]
            for a in result.get("units", []):
                if not isinstance(a, dict) or not isinstance(a.get("target"), str):
                    continue
                u = db.unit(a["sid"])
                warnings = [f for f in check(u["source"], a["target"], kind=u["kind"], glossary=terms, ratio=cfg["qa"]["length_ratio_warning"], target_culture=cfg["project"]["target_culture"]) if f["severity"] == "warning"]
                if warnings:
                    out["warnings"][a["sid"]] = [f"{f['code']}: {f['message']}" for f in warnings]
        if args.brief:
            counts = {}
            for warnings in out["warnings"].values():
                for message in warnings:
                    code = message.split(":", 1)[0]
                    counts[code] = counts.get(code, 0) + 1
            out = {"packet": out["packet"], "stage": out["stage"], "errors": out["errors"],
                   "warning_units": len(out["warnings"]), "warning_counts": counts,
                   "all_submit_checks_executed": True}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1 if out["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
