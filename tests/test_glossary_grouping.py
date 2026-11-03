"""Synthetic engineering tests for the glossary audit and the packet-group proposal."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from locpipe import context, glossary_audit as audit, grouping
from locpipe.config import HarnessError, ROOT, read_json, write_json
from test_orchestration import OrchestrationFixture


def term(identifier, source, target, **fields):
    return {"id": identifier, "source": source, "target": target, "status": "approved", "forms_target": [target], **fields}


class GlossaryAuditTests(OrchestrationFixture):
    def run_audit(self, entries, **options):
        path = self.root / "audit-glossary.json"
        write_json(path, {"status": "draft", "entries": entries})
        return audit.audit(self.cfg, self.db, path, self.root / "reports/audit.md", **options)

    def clean(self):
        return [term("t-confirm", "Confirm", "確定", examples=["Confirm {Key} → 確定 {Key}"]),
                term("t-back", "Back", "戻る", examples=["Back → 戻る"]),
                term("t-unused", "Nothing", "なし", examples=["Nothing → なし"])]

    def test_clean_glossary_reports_matches_and_zero_match_entries(self):
        result = self.run_audit(self.clean())
        self.assertEqual((result["blocking_problems"], result["approved"], result["in_scope_units"]), (0, 3, 3))
        self.assertEqual(result["zero_match_entries"], ["t-unused"])
        text = (self.root / "reports/audit.md").read_text(encoding="utf-8")
        self.assertIn("| t-confirm | error | insensitive | 1 |", text)
        self.assertIn("Blocking problems: **0**", text)

    def test_report_keeps_hand_written_text_outside_the_markers(self):
        self.run_audit(self.clean())
        path = self.root / "reports/audit.md"
        path.write_text("# Notes\n\nKept above.\n\n" + path.read_text(encoding="utf-8").split("# Glossary audit\n\n", 1)[1] + "\nKept below.\n", encoding="utf-8")
        self.run_audit(self.clean()[:2])
        text = path.read_text(encoding="utf-8")
        self.assertIn("Kept above.", text)
        self.assertIn("Kept below.", text)
        self.assertEqual(text.count(audit.BEGIN), 1)
        self.assertNotIn("t-unused", text)

    def test_shape_problems_block_and_unsafe_entries_are_not_matched(self):
        entries = [term("dup", "A", "B"), term("dup", "C", "D"),
                   {"id": "no-target", "source": "Back", "status": "approved"},
                   term("bad-match", "Back", "戻る", source_match="fuzzy"),
                   term("bad-example", "Back", "戻る", examples=["Back without an arrow"]),
                   term("bad-flag", "Back", "戻る", case_sensitive="yes"),
                   {"source": "orphan", "status": "approved", "target": "x"},
                   "not an object"]
        result = self.run_audit(entries)
        shape = " ".join(result["blocking"]["shape"])
        for expected in ("duplicate id 'dup'", "no-target: approved without a target", "bad-match: source_match", "bad-example: example without",
                         "bad-flag: case_sensitive", "entry without a text id", "entry is not an object"):
            self.assertIn(expected, shape)
        self.assertGreater(result["blocking_problems"], 5)

    def test_form_hygiene_blocks_notes_alternatives_and_duplicates(self):
        result = self.run_audit([term("notes", "Back", "戻る", forms_target=["戻る (note)", "戻る/帰る", "戻る", "戻る"]),
                                 term("space", "Cancel", "取消", forms_target=[" 取消"])])
        hygiene = result["blocking"]["hygiene"]
        self.assertEqual(len(hygiene), 4)
        self.assertTrue(any("duplicate forms_target" in h for h in hygiene))

    def test_own_examples_must_pass_qa_and_missing_examples_can_block(self):
        failing = term("t-back", "Back", "戻る", examples=["Back → 違う訳"])
        self.assertTrue(any("t-back" in x for x in self.run_audit([failing])["blocking"]["own examples"]))
        quiet = term("t-cancel", "Cancel", "取消")
        informational = self.run_audit([quiet])
        self.assertEqual((informational["blocking_problems"], informational["entries_without_matching_example"]), (0, 1))
        blocking = self.run_audit([quiet], require_examples=True)
        self.assertEqual(blocking["blocking_problems"], 1)
        self.assertIn("no matching example", blocking["blocking"])

    def test_exact_and_case_rules_are_shared_with_qa(self):
        entries = [term("exact", "Back", "戻る", source_match="exact", examples=["Back → 戻る"]),
                   term("cased", "back", "戻る", case_sensitive=True, examples=["back → 戻る"])]
        result = self.run_audit(entries)
        self.assertEqual(result["blocking_problems"], 0)
        text = (self.root / "reports/audit.md").read_text(encoding="utf-8")
        self.assertIn("| exact | error | insensitive | 1 |", text)
        self.assertIn("| cased | error | sensitive | 0 |", text)
        self.assertEqual(result["zero_match_entries"], ["cased"])

    def test_heavy_error_entries_are_flagged_for_a_human(self):
        result = self.run_audit([term("everyday", "Confirm", "確定", examples=["Confirm → 確定"])], high=1)
        self.assertEqual(result["very_high_match_entries"], ["everyday"])
        self.assertEqual(self.run_audit([term("warn", "Confirm", "確定", qa="warning", examples=["Confirm → 確定"])], high=1)["very_high_match_entries"], [])

    def test_character_name_forms_are_checked_against_examples(self):
        write_json(self.root / "style/characters.json", {"characters": [{"id": "c1", "name_forms": {"label": "アルマ", "note": "ignored"}}]})
        entries = [term("t-back", "Back", "戻る", examples=["Back → 戻る"])]
        self.assertEqual(self.run_audit(entries)["name_forms_not_in_examples"], 1)
        entries[0]["examples"].append("Alma → アルマ")
        entries.append(term("alma", "Alma", "アルマ", examples=["Alma → アルマ"]))
        result = self.run_audit(entries)
        self.assertEqual((result["name_forms_checked"], result["name_forms_not_in_examples"]), (1, 0))

    def test_command_exit_code_follows_blocking_problems(self):
        path = self.root / "cli-glossary.json"
        out = io.StringIO()
        for entries, code in ((self.clean(), 0), ([term("t-back", "Back", "戻る", examples=["Back → 違う訳"])], 1)):
            write_json(path, {"entries": entries})
            with redirect_stdout(out):
                self.assertEqual(audit.main(["--project", str(self.root), "--glossary", str(path), "--no-report"]), code)
        self.assertFalse((self.root / "reports/glossary-audit.md").exists())
        with redirect_stdout(out):
            self.assertEqual(audit.main(["--project", str(self.root), "--glossary", str(self.root / "missing.json")]), 1)

    def test_scripts_are_thin_wrappers_with_template_copies(self):
        for name, module in (("glossary_audit", "glossary_audit"), ("plan_groups", "grouping")):
            text = (ROOT / "scripts" / (name + ".py")).read_text(encoding="utf-8")
            self.assertIn(f"from locpipe.{module} import main", text)
            self.assertEqual(text, (ROOT / "locpipe/templates/project/scripts" / (name + ".py")).read_text(encoding="utf-8"))


class FamilyTests(unittest.TestCase):
    def test_rules_depth_and_fallback_groups(self):
        rules = {"strip_prefix": "Game/Content/", "depth": 2,
                 "rules": [{"pattern": "^UI/Menus/([^/]+)", "family": r"UI/Menus/\1"}, {"pattern": "^NPCs/", "family": "NPCs"}]}
        cases = {"Game/Content/UI/Menus/Options/screen": "UI/Menus/Options", "Game/Content/NPCs/Cook/talk": "NPCs",
                 "Game/Content/Items/Weapons/sword": "Items/Weapons", "Other/Deep/Path/x": "Other/Deep",
                 "key-family:status": "key-and-namespace", "namespace:UI": "key-and-namespace", "single": "single"}
        for group, expected in cases.items():
            self.assertEqual(grouping.family(group, rules), expected, group)
        self.assertEqual(grouping.family("A/B/C"), "A/B")
        for depth in (0, "2", None):
            with self.assertRaises(HarnessError):
                grouping.family("A/B", {"depth": depth})

    def test_rule_files_are_validated(self):
        self.assertEqual(grouping.read_rules(None), {})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rules.json"
            for bad in ([], {"rules": [{"pattern": "x"}]}, {"rules": [{"pattern": "(", "family": "x"}]}):
                write_json(path, bad)
                with self.subTest(bad=bad), self.assertRaises(HarnessError):
                    grouping.read_rules(path)
            write_json(path, {"rules": [{"pattern": "^a", "family": "A"}]})
            self.assertEqual(grouping.read_rules(path)["rules"][0]["family"], "A")


class GroupingTests(OrchestrationFixture):
    def sids(self):
        return {r["key"]: r["sid"] for r in self.db.rows("SELECT sid,key FROM units")}

    def test_proposal_merges_groups_into_ordered_families(self):
        proposal = grouping.propose(self.cfg, self.db, {"depth": 1})
        ids = self.sids()
        # The excluded blank unit has no stored group of its own and joins the key/namespace fallback family.
        self.assertEqual({p["grp"] for p in proposal.values()}, {"family:menu", "family:key-and-namespace"})
        self.assertEqual(proposal[ids["blank"]]["grp"], "family:key-and-namespace")
        self.assertEqual([proposal[ids[k]]["ord"] for k in ("confirm", "back", "cancel")], [0, 10, 20])
        self.assertEqual(proposal[ids["back"]]["from_group"], "menu/b")
        self.assertEqual(proposal[ids["back"]]["source_sha"], self.db.unit(ids["back"])["source_sha"])
        self.assertEqual(grouping.propose(self.cfg, self.db, {"depth": 1, "prefix": "scene:"})[ids["back"]]["grp"], "scene:menu")

    def test_structural_order_overrides_stored_order_inside_one_group(self):
        self.db.c.execute("UPDATE units SET grp='menu/a'")
        ids = self.sids()
        proposal = grouping.propose(self.cfg, self.db, {"depth": 1}, {ids["cancel"]: 1, ids["back"]: 2})
        ranked = sorted(proposal, key=lambda sid: proposal[sid]["ord"])
        self.assertEqual(ranked[:2], [ids["cancel"], ids["back"]])

    def test_merge_refuses_overwrite_unknown_and_stale_decisions_then_applies(self):
        proposal = grouping.propose(self.cfg, self.db, {"depth": 1})
        ids = self.sids()
        sha = self.db.unit(ids["back"])["source_sha"]
        with self.assertRaises(HarnessError):
            grouping.merge(self.cfg, proposal, {"QUNKNOWN": {"source_sha": "x"}})
        with self.assertRaises(HarnessError):
            grouping.merge(self.cfg, proposal, {ids["back"]: {"source_sha": "stale"}})
        self.assertFalse((self.root / "data/overrides.json").exists())
        path = grouping.merge(self.cfg, proposal, {ids["back"]: {"source_sha": sha, "kind": "ui", "wave": "mechanics", "reason": "Reviewed.", "grp": "ignored"}})
        merged = read_json(self.root / "data/overrides.json")
        self.assertEqual(merged[ids["back"]], {"source_sha": sha, "grp": "family:menu", "ord": 10, "kind": "ui", "wave": "mechanics", "reason": "Reviewed."})
        with self.assertRaises(HarnessError):
            grouping.merge(self.cfg, proposal, {})
        grouping.merge(self.cfg, proposal, {}, replace=True)
        context.apply_overrides(self.cfg, self.db)
        self.assertEqual({r["grp"] for r in self.db.rows("SELECT grp FROM units WHERE active=1 AND include=1")}, {"family:menu"})
        self.assertTrue(path.endswith("overrides.json"))

    def test_command_writes_a_proposal_and_optionally_merges(self):
        write_json(self.root / "rules.json", {"depth": 1})
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(grouping.main(["--project", str(self.root), "--rules", str(self.root / "rules.json")]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual((result["units"], result["families"]), (4, {"family:key-and-namespace": 1, "family:menu": 3}))
        self.assertEqual(len(read_json(self.root / "work/research/grouping/grouping-proposal.json")), 4)
        self.assertNotIn("overrides", result)
        write_json(self.root / "scope.json", {})
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(grouping.main(["--project", str(self.root), "--rules", str(self.root / "rules.json"), "--merge", "scope.json"]), 0)
        self.assertTrue((self.root / "data/overrides.json").is_file())


if __name__ == "__main__":
    unittest.main()
