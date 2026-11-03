"""Exercise the real harness with synthetic roles; not a language or runtime test."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from locpipe.adapters import json as adapter
from locpipe import packets, qa, report
from locpipe.cli import approve
from locpipe.config import Config, read_json, write_json
from locpipe.db import Database
from locpipe.project import initialize


def run(directory):
    root = initialize(directory)
    (root / "config.local.toml").write_text("[project]\npreparation_only=false\n", encoding="utf-8")
    (root / "style/style-guide.md").write_text("Synthetic simulation; preserve placeholders and source meaning.\n", encoding="utf-8")
    cfg = Config(root)
    db = Database(cfg)
    try:
        adapter.capture(cfg, db, "synthetic", ROOT / "examples/synthetic/source.json")
        adapter.index_context(cfg, db)
        for gate in ("source", "style", "glossary", "characters"):
            approve(cfg, db, gate, "Synthetic engineering fixture; not a real owner approval", "synthetic-demo")
        translations = {"confirm": "Conferma {Key}", "return": "Torna"}

        def complete_stage(stage):
            while True:
                packet = packets.claim(cfg, db, stage, "synthetic-" + stage)["claimed"]
                if not packet:
                    break
                result = read_json(root / "work/results" / (packet + ".json"))
                for row in result["units"]:
                    if stage == "review":
                        row.update(verdict="ok", issues=[])
                    else:
                        row.update(target=translations[db.unit(row["sid"])["key"]],
                                   note="Scripted fixture, no real linguistic assessment.")
                write_json(root / "work/results" / (packet + ".json"), result)
                if not packets.submit(cfg, db, packet)["accepted"]:
                    raise RuntimeError("Synthetic stage failed submit validation")

        for stage in ("translate", "review", "revise"):
            complete_stage(stage)
        approve(cfg, db, "pilot", "Synthetic engineering fixture; no real pilot assessment", "synthetic-demo")
        for stage in ("consistency", "fluency"):
            complete_stage(stage)
        source_copy = adapter.build(cfg, db, "source-copy", "source-copy")
        candidate = adapter.build(cfg, db, "candidate", "candidate")
        adapter.verify(cfg, "source-copy")
        adapter.verify(cfg, "candidate")
        source_qa, target_qa = qa.run(cfg, db, source=True), qa.run(cfg, db)
        if source_qa["errors"] or target_qa["errors"]:
            raise RuntimeError("Synthetic QA failed")
        adapter.roundtrip(cfg, db)
        report.render(cfg, db)
        summary = {"engineering_simulation": "PASS", "project": str(root),
                   "simulated_roles_not_real_independent_review": True,
                   "linguistic_quality_verified": False, "runtime_verified": False,
                   "stage_completion": report.status(cfg, db)["stage_completion"],
                   "pending_gates": [g["name"] for g in db.gate_status() if g["status"] == "pending"],
                   "source_copy": source_copy["artifact_sha256"], "candidate": candidate["artifact_sha256"]}
        write_json(root / "reports/SIMULATION.json", summary)
        return summary
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path,
                        default=ROOT / "work" / ("synthetic-demo-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")))
    print(json.dumps(run(parser.parse_args().directory), ensure_ascii=False, indent=2))
