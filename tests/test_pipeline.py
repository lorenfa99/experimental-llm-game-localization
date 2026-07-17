from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from locpipe.config import load_config  # noqa: E402
from locpipe.corrections import apply_corrections  # noqa: E402
from locpipe.inventory import build_inventory  # noqa: E402
from locpipe.validator import validate_project  # noqa: E402


CONFIG = '''[project]
name = "Test project"
source_root = "input/source"
baseline_root = "input/baseline"
release_root = "release"
work_root = "work"
reports_root = "reports"
references = ["reference/glossary.tsv"]
delimiter = "|"
markers = ["<<", ">>", "##", "#"]
locked_values = ["", "null"]

[[pairs]]
key = "dialogue"
source = "dialogue_en.txt"
baseline = "dialogue_it.txt"
output = "dialogue_it.txt"
schema = "dialogue_3"
id_field = 0
translatable_fields = [1]
field_labels = ["text"]
confidence = "explicit"
opaque_reference = "source"
'''


SOURCE = (
    "A|A gate costs 10% and needs {0} keys.|opaque\r\n"
    "B|<<You inspect it.>> Return with 3 keys.|opaque\r\n"
)
BASELINE = (
    "A|Un cancello costa il 10% e richiede {0} chiavi.|opaque\r\n"
    "B|<<Lo esamini.>> Torna con 3 chiavi.|opaque\r\n"
)


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "input/source").mkdir(parents=True)
        (self.root / "input/baseline").mkdir(parents=True)
        (self.root / "reference").mkdir()
        (self.root / "work").mkdir()
        (self.root / "reports").mkdir()
        (self.root / "project.toml").write_text(CONFIG, encoding="utf-8")
        (self.root / "input/source/dialogue_en.txt").write_bytes(SOURCE.encode("utf-8"))
        (self.root / "input/baseline/dialogue_it.txt").write_bytes(BASELINE.encode("utf-8"))
        (self.root / "reference/glossary.tsv").write_text("source\ttarget\nkey\tchiave\n", encoding="utf-8")
        self.config = load_config(self.root / "project.toml")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_inventory_and_baseline_validation(self) -> None:
        manifest, fingerprints = build_inventory(self.config)
        self.assertTrue(manifest.is_file())
        self.assertTrue(fingerprints.is_file())
        issues, selected = validate_project(self.config, "baseline")
        self.assertEqual((), tuple(issues))
        self.assertEqual("dialogue", selected[0].key)

    def test_explicit_correction_preserves_structure_and_crlf(self) -> None:
        build_inventory(self.config)
        correction = {
            "pair": "dialogue",
            "line": 2,
            "id": "B",
            "field": 1,
            "old": "<<Lo esamini.>> Torna con 3 chiavi.",
            "new": "<<Lo esamini.>> Ritorna con 3 chiavi.",
            "category": "naturalness",
            "reason": "Synthetic test correction.",
        }
        path = self.root / "work/CORRECTIONS.jsonl"
        path.write_text(json.dumps(correction, ensure_ascii=False) + "\n", encoding="utf-8")
        count, _ = apply_corrections(self.config, path)
        self.assertEqual(1, count)
        output = (self.root / "release/dialogue_it.txt").read_bytes()
        self.assertIn(b"\r\n", output)
        self.assertNotIn(b"\n", output.replace(b"\r\n", b""))
        issues, _ = validate_project(self.config, "release")
        self.assertEqual([], issues)

    def test_missing_marker_is_reported(self) -> None:
        build_inventory(self.config)
        (self.root / "release").mkdir()
        damaged = BASELINE.replace("<<Lo esamini.>>", "Lo esamini.")
        (self.root / "release/dialogue_it.txt").write_bytes(damaged.encode("utf-8"))
        issues, _ = validate_project(self.config, "release")
        self.assertIn("MARKER_SEQUENCE", {issue.code for issue in issues})

    def test_frozen_input_mutation_is_reported(self) -> None:
        build_inventory(self.config)
        glossary = self.root / "reference/glossary.tsv"
        glossary.write_text("source\ttarget\nkey\tchiavi\n", encoding="utf-8")
        issues, _ = validate_project(self.config, "baseline")
        self.assertIn("FROZEN_FILE_CHANGED", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
