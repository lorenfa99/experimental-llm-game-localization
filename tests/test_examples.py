"""The published examples must stay loadable and must not carry project data."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from locpipe.config import Config, ROOT, read_json
from locpipe.db import identity

EXAMPLE = ROOT / "examples/queens-domain"
SYNTHETIC_SIDS = {"QFB445556C0E5", "Q47BE2D577677"}
SID = re.compile(r"\bQ[0-9A-F]{12}\b")


class QueensDomainExampleTests(unittest.TestCase):
    def test_configuration_example_loads_as_a_project_config(self):
        with tempfile.TemporaryDirectory(prefix="locpipe-example-") as temp:
            root = Path(temp)
            shutil.copyfile(EXAMPLE / "config.example.toml", root / "config.toml")
            cfg = Config(root)
            self.assertEqual((cfg["project"]["source_culture"], cfg["project"]["target_culture"]), ("en", "it"))
            self.assertEqual(cfg["adapter"]["type"], "unreal")
            self.assertEqual(cfg["packets"]["batch_packets"], 3)
            self.assertEqual(cfg["game"]["root"], "")

    def test_receipts_example_has_the_documented_shape(self):
        rows = [json.loads(line) for line in (EXAMPLE / "receipts.example.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["event"] for r in rows], ["accepted", "dispatched_fresh_context", "accepted"])
        dispatch = rows[1]
        self.assertEqual(dispatch["fork_turns"], "none")
        self.assertIn("attestation", dispatch["dispatch_attestation"])
        for row in rows:
            self.assertTrue(row["agent"].startswith("synthetic-"))

    def test_examples_contain_only_synthetic_identities(self):
        found = set()
        for path in (ROOT / "examples").rglob("*"):
            if path.is_file():
                found |= set(SID.findall(path.read_text(encoding="utf-8")))
        self.assertLessEqual(found, SYNTHETIC_SIDS)

    def test_synthetic_identities_belong_to_the_synthetic_source(self):
        document = read_json(ROOT / "examples/synthetic/source.json")
        sids = {identity(document["localization_target"], u["namespace"], u["key"])[0] for u in document["units"]}
        self.assertTrue(SYNTHETIC_SIDS <= sids, sids)


if __name__ == "__main__":
    unittest.main()
