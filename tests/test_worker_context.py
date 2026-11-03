from __future__ import annotations

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from locpipe import qa, packets, worker_context as wc
from locpipe.cli import approve
from locpipe.config import HarnessError, file_hash, write_json
from locpipe.db import Database
from scripts.checkpoint import checkpoint
from test_harness import HarnessFixture


class WorkerContextTests(HarnessFixture):
    def setUp(self):
        super().setUp()
        (self.root / "docs").mkdir(exist_ok=True)
        (self.root / "docs/MULTILINGUAL-REFERENCES.md").write_text("Synthetic reference policy.", encoding="utf-8")
        self.approve_rules()

    def approve_rules(self):
        for gate in ("source", "style", "glossary", "characters"):
            approve(self.cfg, self.db, gate, "Synthetic fixture decision", "test-owner")

    def rich_glossary(self):
        return {"status": "draft", "source_snapshot": "demo", "binding": "Synthetic approval metadata.", "entries": [
            {"id": "orb", "source": "Orb", "target": "Sfera", "status": "approved", "kind": "item",
             "forms_source": ["Orb", "Orbs"], "forms_target": ["Sfera", "Sfere"], "gender": "f",
             "notes": "Use the capital only as an item label.", "rationale": "A round item, not an orbit.",
             "examples": ["Use Orb -> Usa Sfera"], "evidence": ["QTEST source evidence"],
             "future_constraint": {"never": ["Orbita"]}},
            {"id": "heavy", "source": "Heavy", "target": "Pesantezza", "status": "approved", "kind": "mechanic",
             "case_sensitive": True, "qa": "warning", "evidence": ["Another source"]},
            {"id": "nerava", "source": "Nerava", "target": "Nerava", "status": "approved", "kind": "name",
             "do_not_translate": True, "gender": None, "evidence": [], "notes": "Keep the unknown gender unknown."},
            {"id": "old", "source": "Orb", "target": "Orbita", "status": "rejected", "kind": "item",
             "notes": "A rejected alternative must never become approved through compaction."},
        ]}

    def test_compact_files_preserve_quoted_json_like_prose_and_unicode(self):
        value = {"entries": [{"notes": 'Keep ", {braces}, \\\\ and è…\nexactly.' * 20,
                              "forms": ['<img id="1"></>', "{Key}", "Sfera"]}]}
        self.assertEqual(json.loads(wc.readable_compact_json(value)), value)

    def test_windows_extended_prefix_does_not_break_containment_comparison(self):
        if os.name != "nt":
            self.skipTest("Windows namespace path regression")
        from pathlib import Path
        from unittest.mock import Mock
        for resolved, normal in [(r"\\?\C:\project\work\cache", r"C:\project\work\cache"),
                                 (r"\\?\UNC\server\share\cache", r"\\server\share\cache")]:
            path = Mock()
            path.resolve.return_value = Path(resolved)
            self.assertEqual(wc.resolved_for_containment(path), Path(normal))

    def test_every_rule_and_unknown_field_survives_including_rejected_records(self):
        source = self.rich_glossary()
        working = wc.compact(source, "entries")
        restored = wc.expand(working, "entries")
        self.assertEqual(restored, wc.working_rules(source))
        self.assertEqual([r["id"] for r in restored["entries"]], ["orb", "heavy", "nerava", "old"])
        self.assertEqual(restored["entries"][0]["future_constraint"], {"never": ["Orbita"]})
        self.assertEqual(restored["entries"][0]["examples"], source["entries"][0]["examples"])
        self.assertEqual(restored["entries"][-1]["status"], "rejected")
        # A new object-shaped evidence field is not silently classified as provenance.
        source["entries"][0]["evidence"] = {"constraint": "Read this unknown future field"}
        self.assertEqual(wc.expand(wc.compact(source, "entries"), "entries"), wc.working_rules(source))
        self.assertIn("evidence", wc.expand(wc.compact(source, "entries"), "entries")["entries"][0])

    def test_working_glossary_has_identical_actual_qa_behavior(self):
        original = self.rich_glossary()
        restored = wc.expand(wc.compact(original, "entries"), "entries")
        for source, target in (("Use Orb", "Usa Sfera"), ("Use Orbs", "Usa Sfere"),
                       ("Heavy Orb", "Sfera pesante"), ("heavy Orbit", "Orbita pesante"),
                       ("Use Nerava", "Usa altro"), ("Use Orb", "Usa Orbita")):
            with self.subTest(source=source, target=target):
                self.assertEqual(qa.check(source, target, glossary=original["entries"]),
                                 qa.check(source, target, glossary=restored["entries"]))

    def test_bundle_is_reused_and_complete_original_evidence_is_available(self):
        glossary = self.rich_glossary()
        characters = {"characters": [{"id": "person", "status": "approved", "gender": None,
                       "voice": "Quiet", "address": {"to_player": {"form": "tu", "evidence": ["QVOICE"]}},
                       "notes": "An address shift is a rule, not provenance."}]}
        write_json(self.root / "glossary/glossary.json", glossary)
        write_json(self.root / "style/characters.json", characters)
        before = file_hash(self.root / "glossary/glossary.json")
        path, manifest = wc.ensure_bundle(self.cfg)
        stamp = (path / "glossary.rules.json").stat().st_mtime_ns
        same, second = wc.ensure_bundle(self.cfg)
        self.assertEqual(path, same)
        self.assertEqual(stamp, (same / "glossary.rules.json").stat().st_mtime_ns)
        self.assertEqual(before, file_hash(self.root / "glossary/glossary.json"))
        self.assertEqual(wc.lookup(self.cfg, "glossary", ["orb"])["records"][0], glossary["entries"][0])
        self.assertEqual(wc.lookup(self.cfg, "characters", ["person"])["records"], characters["characters"])
        self.assertEqual((path / "style-guide.md").read_bytes(), (self.root / "style/style-guide.md").read_bytes())
        self.assertEqual(manifest["statistics"]["glossary_records"], 4)
        self.assertEqual(manifest, second)

    def test_focused_dialogue_preserves_full_branches_incoming_links_and_cycles(self):
        graphs = {"/Game/A": {"steps": [{"sid": "QA", "source": "Same source-language"}],
                              "branches": [{"conditions": ["condition"], "next": "/Game/B.B"}],
                              "future_links": {"/Game/ÑPC.ÑPC": None}},
                  "/Game/B": {"steps": [{"sid": "QB"}], "next": "/Game/C.C", "unknown_extra": {"keep": True}},
                  "/Game/C": {"steps": [{"sid": "QC"}], "next": "/Game/A.A"},
                  "/Game/Incoming": {"next": "/Game/B.B"},
                  "/Game/ÑPC": {"steps": [{"sid": "QUNI"}]},
                  "/Game/Unrelated": {"steps": [{"sid": "QX", "source": "Same source-language"}]}}
        result = wc.focused_dialogue({"snapshot": "demo", "dialogues": graphs}, ["QB"])
        expected = {k: v for k, v in graphs.items() if k != "/Game/Unrelated"}
        self.assertEqual(result["dialogues"], expected)
        with self.assertRaises(HarnessError):
            wc.focused_dialogue({"dialogues": graphs}, ["Same source-language"])
        with self.assertRaises(HarnessError):
            wc.focused_dialogue({"dialogues": graphs}, ["QMISSING"])

    def test_stale_contract_and_modified_cache_are_rejected_without_overwriting(self):
        path, manifest = wc.ensure_bundle(self.cfg)
        old = manifest["contract_hash"]
        with (self.root / "style/style-guide.md").open("a", encoding="utf-8") as f:
            f.write("\nNew synthetic policy.")
        with self.assertRaises(HarnessError):
            wc.ensure_bundle(self.cfg, old)
        self.assertFalse(wc.lookup(self.cfg, "glossary", [], old)["is_current_contract"])
        changed = path / "glossary.rules.json"
        changed.write_text("{}", encoding="utf-8")
        with self.assertRaises(HarnessError):
            wc.load_bundle(self.cfg, old)
        self.assertEqual(changed.read_text(encoding="utf-8"), "{}")

    def test_dialogue_lookup_is_snapshot_bound_and_concurrently_reusable(self):
        source = self.root / "work/research/dialogue/graphs.json"
        source.parent.mkdir(parents=True)
        sid = self.db.unit("option_alpha")["sid"]
        document = {"snapshot": "demo", "dialogues": {"/Game/Synthetic": {
            "steps": [{"sid": sid, "source": "Press {Key}"}], "branches": ["keep all"]}}}
        write_json(source, document)
        original = file_hash(source)
        with ThreadPoolExecutor(max_workers=3) as pool:
            outputs = list(pool.map(lambda _: wc.dialogue_lookup(self.cfg, ["option_alpha"]), range(3)))
        self.assertEqual(len({row["read_complete_file"] for row in outputs}), 1)
        self.assertEqual(file_hash(source), original)
        saved = json.loads((self.root / outputs[0]["read_complete_file"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["dialogues"], document["dialogues"])
        document["snapshot"] = "different"
        write_json(source, document)
        with self.assertRaises(HarnessError):
            wc.dialogue_lookup(self.cfg, [sid])

    def test_concurrent_builders_publish_one_complete_bundle(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: wc.ensure_bundle(self.cfg), range(3)))
        self.assertEqual(len({str(path) for path, _ in results}), 1)
        wc.load_bundle(self.cfg, results[0][1]["contract_hash"])

    def test_batch_validation_is_read_only_and_checks_worker_limits(self):
        self.cfg.values["packets"]["max_units"] = 1
        self.approve_rules()
        ids = [packets.claim(self.cfg, self.db, "translate", "worker")["claimed"] for _ in range(2)]
        before = self.db.rows("SELECT * FROM packets ORDER BY id")
        files = {p: file_hash(self.root / "work/packets" / (p + ".json")) for p in ids}
        batch = wc.validate_batch(self.cfg, ids)
        self.assertEqual(batch["worker"], "worker")
        self.assertEqual(len(batch["packets"]), 2)
        self.assertEqual(before, self.db.rows("SELECT * FROM packets ORDER BY id"))
        self.assertEqual(files, {p: file_hash(self.root / "work/packets" / (p + ".json")) for p in ids})
        with self.assertRaises(HarnessError):
            wc.validate_batch(self.cfg, [ids[0], ids[0]])
        with closing(Database(self.cfg, readonly=True)) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.set_meta("forbidden", True)

    def test_oversized_single_is_kept_but_oversized_multi_packet_batch_is_rejected(self):
        self.cfg.values["packets"].update(max_units=1, batch_max_input_bytes=1)
        self.approve_rules()
        ids = [packets.claim(self.cfg, self.db, "translate", "worker")["claimed"] for _ in range(2)]
        self.assertTrue(wc.validate_batch(self.cfg, ids[:1])["oversized_single_read_fully"])
        with self.assertRaises(HarnessError):
            wc.validate_batch(self.cfg, ids)

    def test_mixed_worker_batch_and_stale_packet_are_not_accepted(self):
        self.cfg.values["packets"]["max_units"] = 1
        self.approve_rules()
        first = packets.claim(self.cfg, self.db, "translate", "one")["claimed"]
        second = packets.claim(self.cfg, self.db, "translate", "two")["claimed"]
        with self.assertRaises(HarnessError):
            wc.validate_batch(self.cfg, [first, second])
        with (self.root / "style/style-guide.md").open("a", encoding="utf-8") as f:
            f.write("\nChanged policy.")
        with self.assertRaises(HarnessError):
            wc.validate_batch(self.cfg, [first])

    def test_checkpoints_preserve_worker_prompts_and_frozen_context(self):
        import zipfile
        path, _ = wc.ensure_bundle(self.cfg)
        prompt = self.root / "work/prompts/translator.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("Synthetic worker prompt.", encoding="utf-8")
        dispatch = self.root / "work/orchestration/dispatch.jsonl"
        dispatch.parent.mkdir(parents=True)
        receipt = '{"worker":"reviewer-fixture","fork_turns":"none","packets":["review-fixture"]}\n'
        dispatch.write_text(receipt, encoding="utf-8")
        project_config = self.root / ".codex/config.toml"
        project_config.parent.mkdir(parents=True)
        project_config.write_text("[agents]\nmax_concurrent_threads_per_session = 6\n", encoding="utf-8")
        output = self.root / "saved.zip"
        checkpoint(self.root, output)
        with zipfile.ZipFile(output) as z:
            self.assertIn("work/prompts/translator.md", z.namelist())
            self.assertIn((path / "manifest.json").relative_to(self.root).as_posix(), z.namelist())
            self.assertEqual(z.read("work/orchestration/dispatch.jsonl"), dispatch.read_bytes())
            self.assertEqual(z.read(".codex/config.toml"), project_config.read_bytes())
