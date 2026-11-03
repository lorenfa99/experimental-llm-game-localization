"""Synthetic engineering tests for the external-review kit; no reviewer or model is involved."""
from __future__ import annotations

import io
import json
import random
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from locpipe import offline_issues, review_kit as kit
from locpipe.config import HarnessError, ROOT, read_json, write_json
from test_orchestration import OrchestrationFixture


def unit(sid, group, key, source="One two", namespace="UI"):
    return {"sid": sid, "grp": group, "namespace": namespace, "key": key, "source": source}


def brute_force(weights, parts):
    best = None
    def go(start, left, worst):
        nonlocal best
        if left == 1:
            worst = max(worst, sum(weights[start:]))
            best = worst if best is None else min(best, worst)
            return
        for end in range(start + 1, len(weights) - left + 2):
            go(end, left - 1, max(worst, sum(weights[start:end])))
    go(0, parts, 0)
    return best


class PartitionTests(unittest.TestCase):
    def test_partition_is_exact_contiguous_and_optimal(self):
        rng = random.Random(7)
        for _ in range(150):
            weights = [rng.randint(1, 20) for _ in range(rng.randint(1, 9))]
            parts = rng.randint(1, 11)
            starts = kit.partition(weights, parts)
            self.assertEqual(len(starts), min(parts, len(weights)))
            self.assertEqual(starts[0], 0)
            self.assertEqual(starts, sorted(set(starts)))
            ends = starts[1:] + [len(weights)]
            heaviest = max(sum(weights[a:b]) for a, b in zip(starts, ends))
            self.assertEqual(heaviest, brute_force(weights, min(parts, len(weights))), (weights, parts))

    def test_name_and_description_units_share_a_chat(self):
        rows = [unit("A", "items", "sword_name", "Iron sword"), unit("B", "items", "sword_desc", "Heavy iron blade " * 6),
                unit("C", "items", "shield_name"), unit("D", "items", "shield_desc"), unit("E", "items", "ring")]
        chats = kit.balanced_chats(rows, 3)
        placed = {u["sid"]: i for i, chat in enumerate(chats) for u in chat}
        self.assertEqual(placed["A"], placed["B"])
        self.assertEqual(placed["C"], placed["D"])
        self.assertEqual(sorted(placed), list("ABCDE"))
        self.assertEqual(kit.key_stem("sword_description"), "sword")
        self.assertEqual(kit.key_stem("sword_other"), "sword_other")

    def test_fence_cannot_be_closed_by_unit_text(self):
        text = "line\n~~~~\n~~~~~~ more"
        fenced = kit.fence(text)
        self.assertTrue(fenced.startswith("~" * 7))
        self.assertEqual(fenced.count("~" * 7), 2)
        self.assertEqual(kit.fence("plain").splitlines()[0], "~~~~text")


class KitFixture(OrchestrationFixture):
    def setUp(self):
        super().setUp()
        self.db.c.execute("UPDATE units SET data=json_set(data,'$.context','Shown on the pause menu.') WHERE key='back'")

    def sid(self, key):
        return self.db.one("SELECT sid FROM units WHERE key=?", (key,))["sid"]

    def built(self, label="kit", chats=2, **options):
        self.finish_offline()
        return kit.build(self.cfg, self.db, label, chats, **options)

    def answer(self, folder, name, lines, prose="Coverage: all units read.\n"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(prose + "```jsonl\n" + "\n".join(
            line if isinstance(line, str) else json.dumps(line, ensure_ascii=False) for line in lines) + "\n```\n", encoding="utf-8")

    def finding(self, key, **changes):
        u = self.db.one("SELECT * FROM units WHERE key=?", (key,))
        row = {"sid": u["sid"], "version": u["version"], "current_target": u["target"], "category": "style", "severity": "minor",
               "comment": "Concrete problem and benefit.", "suggestion": "改善案", "evidence": "rule", "confidence": "high"}
        row.update(changes)
        return row


class BuildTests(KitFixture):
    def test_kit_is_complete_private_and_verified(self):
        result = self.built()
        folder = Path(result["folder"])
        self.assertEqual((result["chats"], result["units"], result["source_words"], result["uploaded"]), (2, 3, 5, False))
        self.assertTrue(result["coverage_verified_exact_once"])
        manifest = read_json(folder / "MANIFEST.json")
        self.assertTrue(manifest["private_game_derived"])
        self.assertEqual(manifest["contract_hash"], self.cfg.contract_hash())
        self.assertEqual(sorted(s for c in manifest["chats"] for s in c["sids"]), sorted(
            r["sid"] for r in self.db.rows("SELECT sid FROM units WHERE include=1")))
        for name in ("RULES.md", "PROMPT.md", "README.md", "INDEX.md", "CHATS/CHAT-01/COMPARE.md", "CHATS/CHAT-01/START.md",
                     "CHATS/CHAT-02/CONTEXT.md", "CHATS/CHAT-01/REFERENCES.jsonl"):
            self.assertTrue((folder / name).is_file(), name)
        self.assertIn("Synthetic fixture contract.", (folder / "RULES.md").read_text(encoding="utf-8"))
        prompt = (folder / "PROMPT.md").read_text(encoding="utf-8")
        self.assertIn("bilingual en to ja reviewer", prompt)
        self.assertIn('"current_target"', prompt)
        with zipfile.ZipFile(result["zip"]) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertIn("MANIFEST.json", bundle.namelist())
        data = [json.loads(line) for line in (folder / "CHATS/CHAT-01/DATA.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all({"sid", "version", "source", "target", "source_hash"} <= set(row) for row in data))
        compare = (folder / "CHATS/CHAT-01/COMPARE.md").read_text(encoding="utf-8")
        self.assertIn("確定 {Key}", compare)
        self.assertIn("### Source (en)", compare)

    def test_unit_notes_briefs_and_graphs_reach_the_right_chat(self):
        self.finish_offline()
        briefs = self.root / "briefs"
        briefs.mkdir()
        (briefs / "index.md").write_text("Index of briefs.", encoding="utf-8")
        (briefs / "scene.md").write_text(f"Scene cites {self.sid('confirm')} only.", encoding="utf-8")
        (briefs / "unrelated.md").write_text("Nothing cited here.", encoding="utf-8")
        graph = {"snapshot": self.db.meta("active_snapshot"), "dialogues": {"/Game/D1": {"lines": [{"sid": self.sid("back"), "text": "Back"}]}}}
        write_json(self.root / "graphs.json", graph)
        result = kit.build(self.cfg, self.db, "ctx", 3, context_dir=briefs, graphs=self.root / "graphs.json")
        manifest = read_json(Path(result["folder"]) / "MANIFEST.json")
        by_sid = {sid: c for c in manifest["chats"] for sid in c["sids"]}
        confirm, back = by_sid[self.sid("confirm")], by_sid[self.sid("back")]
        self.assertEqual(confirm["scene_briefs"], ["index.md", "scene.md"])
        self.assertEqual(back["graph_components"], 1)
        context = (Path(result["folder"]) / "CHATS" / f"CHAT-{back['chat']:02d}" / "CONTEXT.md").read_text(encoding="utf-8")
        self.assertIn("Shown on the pause menu.", context)
        self.assertIn("Complete relevant dialogue graphs", context)
        self.assertNotIn("Nothing cited here.", context)

    def test_text_attachments_and_stale_graph_research(self):
        self.finish_offline()
        write_json(self.root / "graphs.json", {"snapshot": "other", "dialogues": {}})
        with self.assertRaises(HarnessError):
            kit.build(self.cfg, self.db, "stale-graph", 2, graphs=self.root / "graphs.json")
        self.assertFalse((self.root / "work/external-review/stale-graph").exists())
        self.assertFalse((self.root / "work/external-review/stale-graph.partial").exists())
        result = kit.build(self.cfg, self.db, "txt", 2, suffix=".txt")
        self.assertTrue((Path(result["folder"]) / "CHATS/CHAT-01/COMPARE.txt").is_file())
        self.assertIn("RULES.txt", (Path(result["folder"]) / "README.md").read_text(encoding="utf-8"))

    def test_unfinished_or_unsettled_work_blocks_the_kit(self):
        with self.assertRaises(HarnessError):
            kit.build(self.cfg, self.db, "too-early", 2)
        self.finish_offline()
        self.db.c.execute("INSERT INTO issues(sid,packet,version,category,severity,comment) SELECT sid,'p',version,'style','minor','open' FROM units LIMIT 1")
        with self.assertRaises(HarnessError):
            kit.build(self.cfg, self.db, "open-issue", 2)
        self.db.c.execute("DELETE FROM issues")
        for kwargs in ({"label": "../up"}, {"chats": 0}, {"chats": 100}, {"expect_units": 4}, {"expect_words": 6}, {"suffix": ".pdf"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(HarnessError):
                kit.build(self.cfg, self.db, **{"label": "bad", "chats": 2, **kwargs})
        kit.build(self.cfg, self.db, "once", 2, expect_units=3, expect_words=5)
        with self.assertRaises(HarnessError):
            kit.build(self.cfg, self.db, "once", 2)


class AnswerTests(KitFixture):
    def test_answers_are_bound_filtered_and_rejections_are_kept(self):
        result = self.built()
        manifest = read_json(Path(result["folder"]) / "MANIFEST.json")
        chat = next(c for c in manifest["chats"] if self.sid("back") in c["sids"])
        other = next(c for c in manifest["chats"] if c["chat"] != chat["chat"])
        mine = [k for k in ("confirm", "back", "cancel") if self.sid(k) in chat["sids"]]
        foreign = next(k for k in ("confirm", "back", "cancel") if self.sid(k) in other["sids"])
        good = self.finding(mine[0])
        answers = self.root / "answers"
        self.answer(answers, f"CHAT-{chat['chat']:02d}-result.txt", [
            good,
            good,                                                            # duplicate
            self.finding(mine[0], comment="Different concern.", severity="major"),
            self.finding(mine[0], comment="Wrong version.", version=9),
            self.finding(mine[0], comment="Wrong text.", current_target="別の文章"),
            self.finding(mine[0], comment="Bad category.", category="vibes"),
            self.finding(mine[0], comment="No-op.", suggestion=self.db.one("SELECT target FROM units WHERE key=?", (mine[0],))["target"]),
            self.finding(foreign, comment="Belongs elsewhere."),
            {**good, "sid": "QNOSUCHUNIT00", "comment": "Unknown."},
            '{"sid": "broken", ',
        ])
        parsed = kit.parse(self.cfg, self.db, "kit", answers, "r1")
        folder = Path(parsed["directory"])
        self.assertEqual((parsed["candidates"], parsed["rejected_inputs"], parsed["unparseable_json_lines"]), (2, 7, 1))
        self.assertEqual(parsed["chats_without_answers"], [other["chat"]])
        self.assertEqual(set(parsed["rejected_by_reason"]), {
            "duplicate finding", "version or current_target does not echo the kit exactly", "invalid category or severity",
            "suggestion equals the current target", f"sid belongs to chat {other['chat']:02d}, not this answer", "sid is not in the kit"})
        candidates = [json.loads(l) for l in (folder / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([c["finding_id"] for c in candidates], [f"C{chat['chat']:02d}-001", f"C{chat['chat']:02d}-002"])
        triage = read_json(folder / "triage.json")
        self.assertEqual(len(triage["rows"]), 2)
        self.assertTrue(all(r["decision"] is None and r["binding"]["version"] == 1 for r in triage["rows"]))
        with self.assertRaises(HarnessError):
            kit.parse(self.cfg, self.db, "kit", answers, "r1")

    def test_answer_files_must_name_their_chat_and_something_must_be_there(self):
        self.built()
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(HarnessError):
            kit.parse(self.cfg, self.db, "kit", empty, "none")
        self.answer(self.root / "unnamed", "result.txt", [self.finding("back")])
        with self.assertRaises(HarnessError):
            kit.parse(self.cfg, self.db, "kit", self.root / "unnamed", "unnamed")
        self.answer(self.root / "toomany", "CHAT-07-result.txt", [self.finding("back")])
        with self.assertRaises(HarnessError):
            kit.parse(self.cfg, self.db, "kit", self.root / "toomany", "toomany")

    def test_a_changed_kit_or_unit_is_not_trusted(self):
        result = self.built()
        chat = next(c for c in read_json(Path(result["folder"]) / "MANIFEST.json")["chats"] if self.sid("back") in c["sids"])
        answers = self.root / "answers"
        self.answer(answers, f"CHAT-{chat['chat']:02d}.txt", [self.finding("back")])
        self.db.c.execute("UPDATE units SET target='差し替え', version=version+1 WHERE key='back'")
        parsed = kit.parse(self.cfg, self.db, "kit", answers, "moved")
        self.assertEqual((parsed["candidates"], parsed["rejected_by_reason"]), (0, {"the unit changed after the kit was built": 1}))
        data = Path(result["folder"]) / f"CHATS/CHAT-{chat['chat']:02d}/DATA.jsonl"
        data.write_text(data.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(HarnessError):
            kit.parse(self.cfg, self.db, "kit", answers, "tampered")

    def test_triage_to_accepted_export_roundtrips_into_issue_import(self):
        result = self.built()
        manifest = read_json(Path(result["folder"]) / "MANIFEST.json")
        answers = self.root / "answers"
        for c in manifest["chats"]:
            keys = [k for k in ("confirm", "back", "cancel") if self.sid(k) in c["sids"]]
            self.answer(answers, f"CHAT-{c['chat']:02d}-result.txt", [self.finding(k, comment=f"Concern about {k}.") for k in keys])
        parsed = kit.parse(self.cfg, self.db, "kit", answers, "r2")
        triage_path = Path(parsed["directory"]) / "triage.json"
        triage = read_json(triage_path)
        self.assertEqual(len(triage["rows"]), 3)

        with self.assertRaises(HarnessError):                      # undecided
            kit.accepted(self.cfg, self.db, triage_path)
        keys = {r["sid"]: k for k in ("confirm", "back", "cancel") for r in triage["rows"] if r["sid"] == self.sid(k)}
        decisions = {"confirm": "accepted", "back": "adapted", "cancel": "rejected"}
        for row in triage["rows"]:
            row.update(decision=decisions[keys[row["sid"]]], reason="Checked against source and rules.")
            if row["decision"] == "adapted":
                row["adapted_suggestion"] = "戻る（調整）"
        write_json(triage_path, triage)

        incomplete = json.loads(json.dumps(triage))
        incomplete["rows"][0]["reason"] = " "
        write_json(self.root / "bad-triage.json", incomplete)
        with self.assertRaises(HarnessError):
            kit.accepted(self.cfg, self.db, self.root / "bad-triage.json")
        unadapted = json.loads(json.dumps(triage))
        next(r for r in unadapted["rows"] if r["decision"] == "adapted")["adapted_suggestion"] = None
        write_json(self.root / "unadapted.json", unadapted)
        with self.assertRaises(HarnessError):
            kit.accepted(self.cfg, self.db, self.root / "unadapted.json")

        self.db.c.execute("UPDATE units SET version=version+1 WHERE key='confirm'")   # moved after triage
        exported = kit.accepted(self.cfg, self.db, triage_path)
        self.assertEqual((exported["exported"], exported["by_decision"]), (1, {"accepted": 1, "adapted": 1, "rejected": 1}))
        self.assertEqual(len(exported["stale_since_triage"]), 1)
        self.assertEqual(exported["exported_by_category"], {"style": 1})
        rows = [json.loads(l) for l in Path(exported["file"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual((rows[0]["sid"], rows[0]["suggestion"]), (self.sid("back"), "戻る（調整）"))
        self.assertNotIn("evidence", rows[0])
        with self.assertRaises(HarnessError):
            kit.accepted(self.cfg, self.db, triage_path)

        imported = offline_issues.import_findings(self.cfg, self.db, Path(exported["file"]), "gemini-test", "synthetic importer", "Synthetic roundtrip.")
        self.assertEqual(imported["imported"], 1)
        issue = self.db.one("SELECT * FROM issues")
        self.assertEqual((issue["sid"], issue["packet"], issue["status"]), (self.sid("back"), "offline:gemini-test", "open"))


class CommandLineTests(KitFixture):
    def run_command(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = kit.main([*args, "--project", str(self.root)])
        return code, json.loads(out.getvalue())

    def test_cli_builds_and_reports_errors_as_json(self):
        self.finish_offline()
        code, payload = self.run_command("build", "cli", "--chats", "3", "--expect-units", "3")
        self.assertEqual((code, payload["chats"]), (0, 3))
        code, payload = self.run_command("build", "cli")
        self.assertEqual(code, 1)
        self.assertIn("error", payload)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(kit.main(["nonsense"]), 2)
            self.assertEqual(kit.main([]), 2)

    def test_script_and_template_copy_are_identical(self):
        text = (ROOT / "scripts/external_review_kit.py").read_text(encoding="utf-8")
        self.assertIn("raise SystemExit(main())", text)
        self.assertEqual(text, (ROOT / "locpipe/templates/project/scripts/external_review_kit.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
