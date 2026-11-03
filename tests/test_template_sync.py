"""The scaffold copied by `locpipe init` must match the files this repository itself ships."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "locpipe/templates/project"
# The scaffold's .gitignore is written for a user's project, not for this toolkit repository.
INTENTIONALLY_DIFFERENT = {".gitignore"}


class TemplateSyncTests(unittest.TestCase):
    def test_template_files_match_their_repository_counterparts(self):
        files = sorted(p.relative_to(TEMPLATE).as_posix() for p in TEMPLATE.rglob("*") if p.is_file())
        self.assertTrue(files)
        missing, different = [], []
        for name in files:
            if name in INTENTIONALLY_DIFFERENT:
                continue
            counterpart = ROOT / name
            if not counterpart.is_file():
                missing.append(name)
            elif counterpart.read_bytes() != (TEMPLATE / name).read_bytes():
                different.append(name)
        self.assertEqual((missing, different), ([], []), "Update both copies together")

    def test_scaffolded_workflow_entry_points_are_shipped(self):
        for name in ("scripts/claim_batch.py", "scripts/candidate_audit.py", "AGENTS.md", "docs/WORKFLOW.md"):
            self.assertTrue((TEMPLATE / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
