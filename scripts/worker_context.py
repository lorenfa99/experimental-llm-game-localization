"""Build reusable complete working rules, or look up original research evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locpipe.config import Config, HarnessError  # noqa: E402
from locpipe.worker_context import ensure_bundle, lookup, validate_batch, dialogue_lookup  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build", help="No packet IDs: preview rules only, without claims or approvals")
    build.add_argument("packets", nargs="*")
    find = sub.add_parser("lookup", help="Return complete original records including supporting evidence")
    find.add_argument("kind", choices=("glossary", "characters"))
    find.add_argument("ids", nargs="+")
    find.add_argument("--contract")
    dialogue = sub.add_parser("dialogue", help="Complete relevant linked graphs by stable SID, key or /Game/package")
    dialogue.add_argument("identifiers", nargs="+")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    cfg = Config(args.project)
    try:
        if args.action == "dialogue":
            result = dialogue_lookup(cfg, args.identifiers)
        elif args.action == "lookup":
            result = lookup(cfg, args.kind, args.ids, args.contract)
        else:
            batch = validate_batch(cfg, args.packets)
            path, manifest = ensure_bundle(cfg, batch["contract_hash"])
            result = {**batch, "manifest": str(path / "manifest.json"),
                      "read_once_per_batch": [str(path / name) for name in manifest["required_reads_once_per_batch"]],
                      "statistics": manifest["statistics"], "lookup": manifest["lookup"],
                      "character_lookup": manifest["character_lookup"],
                      "note": "Read the complete working rules once in this worker context, and every assigned packet/scene. Fresh independent reviewers read their own rules. No gate or linguistic stage is bypassed."}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except HarnessError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
