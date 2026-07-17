from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checksums import write_checksums
from .config import load_config
from .corrections import apply_corrections
from .indexes import build_indexes
from .initialize import initialize_project
from .inventory import build_inventory
from .validator import render_report, validate_project, write_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="locpipe", description="Deterministic QA for human-reviewed game localization")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a safe project skeleton")
    init.add_argument("directory", type=Path)

    inventory = sub.add_parser("inventory", help="Build manifest and freeze input fingerprints")
    inventory.add_argument("config", type=Path)

    validate = sub.add_parser("validate", help="Validate approved baseline or release outputs")
    validate.add_argument("config", type=Path)
    validate.add_argument("--mode", choices=("baseline", "release"), required=True)
    validate.add_argument("--pair", action="append", default=[])
    validate.add_argument("--report", type=Path)

    apply = sub.add_parser("apply", help="Apply an explicit JSONL correction list from immutable baselines")
    apply.add_argument("config", type=Path)
    apply.add_argument("corrections", type=Path)
    apply.add_argument("--pair", action="append", default=[])

    index = sub.add_parser("index", help="Surface repeated source text and numbered sequences for human review")
    index.add_argument("config", type=Path)
    index.add_argument("--min-length", type=int, default=12)

    checksums = sub.add_parser("checksums", help="Create SHA256SUMS.txt for declared release files")
    checksums.add_argument("config", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            root = initialize_project(args.directory)
            print(f"Initialized localization project: {root}")
            return 0

        config = load_config(args.config)
        if args.command == "inventory":
            manifest, fingerprints = build_inventory(config)
            print(f"Manifest: {manifest}")
            print(f"Frozen inputs: {fingerprints}")
            return 0
        if args.command == "validate":
            issues, selected = validate_project(config, args.mode, tuple(args.pair))
            report = render_report(config, args.mode, issues, selected)
            report_path = args.report or config.reports_root / f"VALIDATION_{args.mode.upper()}.md"
            if not report_path.is_absolute():
                report_path = config.base_dir / report_path
            write_report(report_path, report)
            print(f"{args.mode}: {'PASS' if not issues else 'FAIL'}; pairs={len(selected)}; issues={len(issues)}; report={report_path}")
            return 0 if not issues else 1
        if args.command == "apply":
            correction_path = args.corrections if args.corrections.is_absolute() else config.base_dir / args.corrections
            count, selected = apply_corrections(config, correction_path, tuple(args.pair))
            print(f"Applied {count} documented changes across {len(selected)} pair(s).")
            return 0
        if args.command == "index":
            repeated, sequences = build_indexes(config, args.min_length)
            print(f"Repeated source index: {repeated}")
            print(f"Sequence index: {sequences}")
            return 0
        if args.command == "checksums":
            output = write_checksums(config)
            print(f"Checksums: {output}")
            return 0
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
