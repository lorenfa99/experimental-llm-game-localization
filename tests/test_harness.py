from __future__ import annotations

import json
import shutil
import struct
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from locpipe import build, packets, qa, report, references, context
from locpipe.cli import approve, owner_set
from locpipe.config import Config, HarnessError, ROOT, digest, file_hash, read_json, write_json
from locpipe.db import Database, identity
from locpipe.extract import import_snapshot
from locpipe.locres import Entry, Locres, MAGIC
from locpipe.unreal import safe_entry
from scripts.checkpoint import checkpoint


class CodecTests(unittest.TestCase):
    def entries(self):
        return [Entry("", "alpha", 0xFFFFFFFF, "Press {Key}", 0, 123), Entry("Scene", "beta", 17, "Unicode € 😀", 456, 789), Entry("Scene", "gamma", 23, "Press {Key}", 456, 234), Entry("Scene", "empty", 99, "", 456, 345)]

    def test_all_versions_roundtrip_unicode_and_dedup(self):
        for version in range(4):
            with self.subTest(version=version):
                original = Locres(version, self.entries())
                parsed = Locres.parse(original.encode())
                if version >= 2:
                    self.assertEqual(original.entries, parsed.entries)
                self.assertEqual([e.text for e in original.entries], [e.text for e in parsed.entries])
                self.assertEqual(parsed.entries, Locres.parse(parsed.encode(rebuild=True)).entries)
                self.assertEqual(parsed.original, parsed.encode())

    def test_one_replacement_preserves_identity_crcs_and_key_hashes(self):
        source = Locres.parse(Locres(3, self.entries()).encode())
        target = Locres.parse(source.encode({("Scene", "beta"): "Replacement 😀 €"}))
        for before, after in zip(source.entries, target.entries):
            self.assertEqual((before.identity, before.source_hash, before.key_hash, before.namespace_hash), (after.identity, after.source_hash, after.key_hash, after.namespace_hash))
        self.assertEqual(target.entries[1].text, "Replacement 😀 €")
        self.assertEqual(target.entries[0].text, source.entries[0].text)

    def test_malformed_inputs_are_rejected(self):
        good = Locres(3, self.entries()).encode()
        bad = [good[:-1], MAGIC + b"\x09", good[:17] + struct.pack("<q", 99999999) + good[25:], good[:25] + struct.pack("<i", 999) + good[29:]]
        for data in bad:
            with self.assertRaises(HarnessError):
                Locres.parse(data)
        with self.assertRaises(HarnessError):
            Locres.parse(Locres(3, [self.entries()[0], self.entries()[0]]).encode())
        with self.assertRaises(HarnessError):
            Locres(3, self.entries()).encode({("wrong", "key"): "replacement"})
        with self.assertRaises(HarnessError):
            Locres(3, self.entries()).encode({("", "alpha"): "bad\x00text"})

    def test_unsafe_pak_names(self):
        for name in ("../escape", "/absolute", "C:/absolute", "safe/../../escape", "..\\escape"):
            with self.assertRaises(HarnessError):
                safe_entry(name)
        self.assertEqual(str(safe_entry("SampleGame/Content/Localization/Game/source/Game.locres")), "SampleGame/Content/Localization/Game/source/Game.locres")


class QATests(unittest.TestCase):
    def test_case_counts_and_decorators_are_binding(self):
        src = 'Count {Name} {Name} <img id="0"></> %s'
        good = 'Target {Name} {Name} <img id="0"></> %s'
        self.assertFalse(any(f["severity"] == "error" for f in qa.check(src, good)))
        bad = 'Target {name} <img id="1"></img> %d'
        codes = {f["code"] for f in qa.check(src, bad)}
        self.assertTrue({"placeholders", "markup", "printf"}.issubset(codes))

    def test_glossary_word_boundaries_and_approval(self):
        terms = [{"id": "term", "source": "Orb", "target": "Approved", "status": "approved"}]
        self.assertIn("glossary", {f["code"] for f in qa.check("Use Orb", "Target", glossary=terms)})
        self.assertNotIn("glossary", {f["code"] for f in qa.check("Orbit", "Target", glossary=terms)})
        self.assertNotIn("glossary", {f["code"] for f in qa.check("Use Orb", "Use Approved", glossary=terms)})

    def test_everyday_word_terms_downgrade_glossary_miss_to_warning(self):
        terms = [{"id": "heavy", "source": "Heavy", "target": "Pesantezza", "status": "approved", "case_sensitive": True, "qa": "warning"},
                 {"id": "orb", "source": "Orb", "target": "Sfera", "status": "approved"}]
        found = {f["message"].split(":")[0]: f["severity"] for f in qa.check("Heavy Orb", "Spada pesante", glossary=terms)}
        self.assertEqual(found, {"Missing approved form for heavy": "warning", "Missing approved form for orb": "error"})

    def test_exact_command_term_does_not_override_duration_noun(self):
        term = {"id": "play", "source": "Play", "target": "Gioca", "status": "approved",
                "forms_source": ["Play", "Start"], "forms_target": ["Gioca"],
                "source_match": "exact", "case_sensitive": True, "qa": "error"}
        def glossary_errors(source, target):
            return [f for f in qa.check(source, target, glossary=[term]) if f["code"] == "glossary"]
        self.assertFalse(glossary_errors("Play Time", "Tempo di gioco"))
        self.assertFalse(glossary_errors("Play", "Gioca"))
        self.assertEqual([f["severity"] for f in glossary_errors("Play", "Tempo di gioco")], ["error"])
        self.assertTrue(glossary_errors("Start", "Testo"))
        term["case_sensitive"] = False
        self.assertTrue(glossary_errors("play", "Testo"))
        self.assertFalse(glossary_errors("PLAY", "gioca"))

    def test_question_infinitives_retain_binding_verb_forms(self):
        for source, imperative, infinitive in (("Confirm", "Conferma", "Confermare"),
                                               ("Apply", "Applica", "Applicare")):
            with self.subTest(source=source):
                term = {"id": source, "source": source, "target": imperative, "status": "approved",
                        "forms_target": [imperative, infinitive], "qa": "error"}
                question = source + " Video Changes?"
                self.assertFalse(any(f["severity"] == "error" for f in qa.check(
                    question, infinitive + " le modifiche video?", glossary=[term])))
                self.assertFalse(any(f["severity"] == "error" for f in qa.check(source, imperative, glossary=[term])))
                self.assertTrue(any(f["code"] == "glossary" and f["severity"] == "error"
                                    for f in qa.check(question, "Testo", glossary=[term])))

    def test_unknown_glossary_source_match_is_blocking(self):
        term = {"id": "play", "source": "Play", "target": "Gioca", "status": "approved", "source_match": "typo"}
        self.assertTrue(any(f["code"] == "glossary_configuration" and f["severity"] == "error"
                            for f in qa.check("Play", "Gioca", glossary=[term])))

    def test_sentinels_unicode_and_empty_targets(self):
        self.assertIn("sentinel", {f["code"] for f in qa.check("<Empty String>", "Changed")})
        for bad in (None, "", "bad\x00text", "bad\ufffd", "bad\ud800"):
            self.assertTrue(any(f["severity"] == "error" for f in qa.check("Source", bad)))


class HarnessFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="locpipe-test-")
        self.root = Path(self.temp.name)
        shutil.copyfile(ROOT / "config.toml", self.root / "config.toml")
        # The real project's owner-chosen pilot families do not exist in synthetic corpora.
        (self.root / "config.local.toml").write_text("[project]\npreparation_only=false\nsource_culture='source'\ntarget_culture='target'\n[adapter]\ntype='unreal'\n[pipeline]\npilot_groups=[]\n[references]\npreferred_cultures=['fr','es-419','pt-BR','de']\n", encoding="utf-8")
        (self.root / "style").mkdir()
        (self.root / "style/style-guide.md").write_text("Synthetic test contract. No real game translation.", encoding="utf-8")
        write_json(self.root / "style/characters.json", {"characters": []})
        write_json(self.root / "glossary/glossary.json", {"entries": []})
        self.cfg = Config(self.root)
        self.db = Database(self.cfg)
        self.native = Locres(3, [Entry("ImportedStringTable", "option_alpha", 11, "Press {Key}", 123, 456), Entry("ImportedStringTable", "option_beta", 22, "Choose {Key}", 123, 789)])
        self.seed("demo", self.native)
        self.db.c.execute("UPDATE units SET pilot=1")
        for gate in ("source", "style", "glossary", "characters"):
            approve(self.cfg, self.db, gate, "Synthetic fixture owner decision", "test-owner")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def seed(self, label, native, refs=None):
        manifest = {"label": label, "content_hash": digest(label + json.dumps([(e.key,e.text,e.source_hash) for e in native.entries])), "localization_files": [], "entry_count": 1, "extracted_root": "work/extracted/"+label, "paks": []}
        return import_snapshot(self.cfg, self.db, label, native, refs or {}, manifest)

    def answer(self, pid, text="Target {Key}"):
        p = packets.get(self.db, pid)
        a = read_json(self.root / "work/results" / (pid + ".json"))
        for row in a["units"]:
            if p["stage"] == "review":
                row.update(verdict="ok", issues=[])
            else:
                row.update(target=text, note="Synthetic fixture", acknowledged_warnings=[])
        return a

    def save_submit(self, pid, answer):
        write_json(self.root / "work/results" / (pid + ".json"), answer)
        return packets.submit(self.cfg, self.db, pid)

    def translate(self):
        pid = packets.claim(self.cfg, self.db, "translate", "translator")["claimed"]
        self.assertTrue(self.save_submit(pid, self.answer(pid))["accepted"])
        return pid


class StateTests(HarnessFixture):
    def test_context_refresh_drops_deleted_asset_association(self):
        root = self.root / "work/extracted/demo/SampleGame/Content"
        root.mkdir(parents=True)
        self.db.c.execute("UPDATE units SET grp='old-deleted-asset',ord=9876")
        context.index_context(self.cfg,self.db)
        unit = self.db.unit("option_alpha")
        self.assertEqual((unit["grp"],unit["ord"]),("key-family:option",0))

    def test_owner_pilot_groups_add_whole_groups_and_reject_unknown(self):
        (self.root / "work/extracted/demo/SampleGame/Content").mkdir(parents=True)
        self.cfg.values["pipeline"]["pilot_units_per_kind"] = 0
        self.cfg.values["pipeline"]["pilot_groups"] = ["key-family:option"]
        context.index_context(self.cfg,self.db)
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM units WHERE pilot=1")["n"],2)
        self.cfg.values["pipeline"]["pilot_groups"] = ["missing-group"]
        with self.assertRaises(HarnessError):
            context.index_context(self.cfg,self.db)

    def test_full_game_reclassifies_filled_demo_sentinels(self):
        demo = Locres(3,[Entry("ImportedStringTable","item_new_desc",100,"<Empty String>")])
        self.seed("sentinel-demo",demo)
        self.assertEqual(self.db.unit("item_new_desc")["include"],0)
        full = Locres(3,[Entry("ImportedStringTable","item_new_desc",101,"Restores health when used.")])
        self.seed("sentinel-full",full)
        unit = self.db.unit("item_new_desc")
        self.assertEqual((unit["kind"],unit["include"]),("mechanics",1))
        self.assertIsNone(unit["target"])

    def test_style_gate_requires_decisions_not_instructional_marker_mentions(self):
        path = self.root / "style/style-guide.md"
        path.write_text("Instructions mention [DECIDE].\n- [DECIDE] An unresolved choice.\n",encoding="utf-8")
        with self.assertRaises(HarnessError):
            approve(self.cfg,self.db,"style","Synthetic decision","test-owner")
        path.write_text("Instructions mention [DECIDE]. All actual decisions resolved.\n",encoding="utf-8")
        self.assertEqual(approve(self.cfg,self.db,"style","Synthetic decision","test-owner")["status"],"approved")

    def test_preparation_guard_has_no_corpus_side_effect(self):
        self.cfg.values["project"]["preparation_only"] = True
        sid = self.db.rows("SELECT sid FROM units")[0]["sid"]
        for call in (lambda: packets.claim(self.cfg,self.db,"translate","worker"), lambda: owner_set(self.cfg,self.db,sid,"Target {Key}","test"), lambda: approve(self.cfg,self.db,"source","test","owner"), lambda: build.build(self.cfg,self.db,"candidate","candidate")):
            with self.assertRaises(HarnessError):
                call()
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM units WHERE target IS NOT NULL")["n"], 0)
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM packets")["n"], 0)

    def test_update_retains_targets_history_locks_and_marks_stale(self):
        sid = self.db.unit("option_alpha")["sid"]
        owner_set(self.cfg,self.db,sid,"Target {Key}","Synthetic fixture",lock=True)
        updated = Locres(3, [Entry("ImportedStringTable","option_alpha",33,"Changed {Key}",123,456), Entry("ImportedStringTable","option_new",44,"New {Key}",123,777)])
        result = self.seed("full", updated)
        self.assertEqual((result["new"],result["changed"],result["removed"]), (1,1,1))
        u = self.db.unit(sid)
        self.assertTrue(u["stale"] and u["locked"])
        self.assertEqual(u["target"], "Target {Key}")
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM history")["n"], 1)
        self.assertFalse(self.db.unit("option_beta")["active"])
        self.assertEqual(report.diff(self.db,"demo","full")["changed"][0]["sid"],sid)
        self.assertFalse(self.db.gate_ok("source"))

    def test_crc_only_change_and_duplicate_english_do_not_merge(self):
        sid = self.db.unit("option_alpha")["sid"]
        owner_set(self.cfg,self.db,sid,"Target {Key}","Synthetic fixture")
        native = Locres(3,[Entry("ImportedStringTable","option_alpha",99,"Press {Key}"),Entry("ImportedStringTable","option_beta",22,"Press {Key}")])
        self.seed("crc-change",native)
        self.assertTrue(self.db.unit(sid)["stale"])
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM units WHERE active=1")["n"],2)
        self.assertNotEqual(identity("Game","A","key")[0],identity("Game","B","key")[0])

    def test_incompatible_reference_is_stored_but_not_a_target(self):
        native = Locres(3,[Entry("ImportedStringTable","option_alpha",11,"Press {Key}")])
        self.seed("refs",native,{"fr":Locres(3,[Entry("ImportedStringTable","option_alpha",999,"Reference only")])})
        r = self.db.one("SELECT * FROM refs WHERE snapshot='refs'")
        self.assertFalse(r["compatible"])
        self.assertIsNone(self.db.unit("option_alpha")["target"])

    def test_snapshot_labels_are_immutable_and_cannot_reactivate(self):
        with self.assertRaises(HarnessError):
            self.seed("demo",Locres(3,[Entry("", "wrong",0,"Wrong")]))
        self.seed("full",self.native)
        with self.assertRaises(HarnessError):
            self.seed("demo",self.native)

    def test_checkpoint_contains_consistent_db_and_excludes_live_paths(self):
        path = self.root / "work/checkpoints/state.zip"
        result = checkpoint(self.root,path)
        self.assertTrue(result["private"])
        import zipfile
        import sqlite3
        with zipfile.ZipFile(path) as z:
            self.assertNotIn("config.local.toml",z.namelist())
            data = z.read("data/localization.sqlite")
            manifest = json.loads(z.read("CHECKPOINT.json"))
            self.assertEqual(digest(data),manifest["files"]["data/localization.sqlite"])
        copied = self.root / "backup.sqlite"
        copied.write_bytes(data)
        with closing(sqlite3.connect(copied)) as c:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0],"ok")


class ReferenceTests(HarnessFixture):
    def seed_references(self, values=None):
        if values is None:
            values = {culture:(11,f"Synthetic {culture} reference {{Key}}") for culture in ("fr","es-419","pt-BR","de","ja","ru","zh-Hans")}
        resources = {culture:Locres(3,[Entry("ImportedStringTable","option_alpha",crc,text)]) for culture,(crc,text) in values.items()}
        self.seed("reference-build",self.native,resources)

    def test_lookup_excludes_stale_blank_sentinel_and_pseudo_references(self):
        self.seed_references({"fr":(999,"Old reference"),"es-419":(11,""),"pt-BR":(11,"<Empty String>"),"de":(11,"Press {Key}"),"ru":(11,"Synthetic independent wording"),"en-US-POSIX":(11,"Source plus filler")})
        result = references.lookup(self.cfg,self.db,"option_alpha")
        self.assertEqual({r["culture"] for r in result["references"]},{"de","ru"})
        copied = next(r for r in result["references"] if r["culture"]=="de")
        self.assertTrue(copied["same_as_source"])
        self.assertFalse(copied["adds_independent_wording"])
        audited = references.lookup(self.cfg,self.db,"option_alpha",include_unusable=True)
        rejected = {r["culture"]:r["excluded_reasons"] for r in audited["references"] if not r["usable"]}
        self.assertIn("source_revision_mismatch",rejected["fr"])
        self.assertIn("blank_or_sentinel",rejected["es-419"])
        self.assertIn("excluded_pseudo_or_test_locale",rejected["en-US-POSIX"])

    def test_historical_lookup_uses_that_snapshot_source_revision(self):
        self.seed_references({"fr":(11,"Original matched wording")})
        newer = Locres(3,[Entry("ImportedStringTable","option_alpha",999,"Changed source {Key}")])
        self.seed("newer-build",newer)
        result = references.lookup(self.cfg,self.db,"option_alpha",snapshot="reference-build")
        self.assertEqual(result["english"],"Press {Key}")
        self.assertTrue(result["references"][0]["usable"])
        self.assertEqual(result["source_hash"],11)

    def test_focused_lookup_is_read_only_in_preparation_mode(self):
        self.seed_references()
        self.cfg.values["project"]["preparation_only"] = True
        result = references.lookup(self.cfg,self.db,"option_alpha",cultures=["ja","missing"])
        self.assertEqual([r["culture"] for r in result["references"]],["ja"])
        self.assertEqual(result["requested_cultures_unavailable"],["missing"])
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM units WHERE target IS NOT NULL")["n"],0)
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM packets")["n"],0)

    def test_packet_shows_primary_references_and_on_demand_cultures(self):
        self.seed_references()
        for gate in ("source","style","glossary","characters"):
            approve(self.cfg,self.db,gate,"Synthetic reference-build decision","test-owner")
        pid = packets.claim(self.cfg,self.db,"translate","translator")["claimed"]
        frozen = read_json(self.root/"work/packets"/(pid+".json"))
        unit = next(u for u in frozen["units"] if u["key"]=="option_alpha")
        self.assertEqual([r["culture"] for r in unit["official_references"]],["fr","es-419","pt-BR","de"])
        self.assertEqual(set(unit["additional_reference_cultures"]),{"ja","ru","zh-Hans"})
        self.assertIn("--snapshot reference-build",unit["reference_lookup"])
        self.assertIn("docs/MULTILINGUAL-REFERENCES.md",frozen["required_rules"])
        self.assertTrue(frozen["reference_instructions"])
        self.assertEqual(read_json(self.root/"work/results"/(pid+".json"))["units"][0]["reference_checks"],[])

    def test_material_check_cannot_cite_unavailable_or_unresolved_evidence(self):
        self.seed_references({"fr":(11,"Matched synthetic wording")})
        for gate in ("source","style","glossary","characters"):
            approve(self.cfg,self.db,gate,"Synthetic reference-build decision","test-owner")
        pid = packets.claim(self.cfg,self.db,"translate","translator")["claimed"]
        a = self.answer(pid)
        row = next(r for r in a["units"] if r["sid"]==self.db.unit("option_alpha")["sid"])
        check = {"question":"Which control is referenced?","cultures":["missing"],"finding":"Synthetic evidence record","status":"supported"}
        row["reference_checks"] = [check]
        self.assertFalse(self.save_submit(pid,a)["accepted"])
        check.update(cultures=["fr"],status="unresolved")
        self.assertFalse(self.save_submit(pid,a)["accepted"])
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM units WHERE target IS NOT NULL")["n"],0)
        check["status"] = "supported"
        self.assertTrue(self.save_submit(pid,a)["accepted"])
        accepted = read_json(self.root/"work/results/accepted"/(pid+".json"))
        self.assertEqual(next(r for r in accepted["units"] if r["sid"]==row["sid"])["reference_checks"],[check])

    def test_reviewer_can_record_conflicting_evidence_as_an_issue(self):
        self.seed_references({"fr":(11,"Matched synthetic wording")})
        check = {"question":"Which referent?","cultures":["fr"],"finding":"Synthetic conflict requiring research","status":"conflict"}
        sid = self.db.unit("option_alpha")["sid"]
        self.assertEqual(references.validate_checks(self.cfg,self.db,sid,"reference-build",[check],stage="review",verdict="issues"),[])
        self.assertTrue(references.validate_checks(self.cfg,self.db,sid,"reference-build",[check],stage="review",verdict="ok"))

    def test_reference_policy_change_invalidates_frozen_claim(self):
        pid = packets.claim(self.cfg,self.db,"translate","translator")["claimed"]
        (self.root/"docs").mkdir()
        (self.root/"docs/MULTILINGUAL-REFERENCES.md").write_text("Changed reference interpretation rule",encoding="utf-8")
        with self.assertRaises(HarnessError):
            self.save_submit(pid,self.answer(pid))


class CorpusStageTests(HarnessFixture):
    def ready_corpus(self, *, consistency=False):
        self.translate()
        self.cfg.values["packets"]["max_units"] = 1
        self.db.c.execute("UPDATE units SET pilot=0 WHERE key='option_alpha'")
        stages = ["translate", "review", "revise"] + (["consistency"] if consistency else [])
        self.db.c.execute("UPDATE units SET stages=?", (json.dumps(stages),))
        for gate in ("source", "style", "glossary", "characters", "pilot"):
            approve(self.cfg, self.db, gate, "Synthetic reviewed baseline", "test-owner")

    def test_consistency_continues_other_units_but_edit_needs_fresh_review(self):
        self.ready_corpus()
        alpha, beta = (self.db.unit(key)["sid"] for key in ("option_alpha", "option_beta"))
        first = packets.claim(self.cfg, self.db, "consistency", "corpus-editor")["claimed"]
        self.assertTrue(self.save_submit(first, self.answer(first, "Edited {Key}"))["accepted"])
        self.assertNotIn("revise", self.db.unit(alpha)["stages"])
        self.assertEqual([u["sid"] for u in packets.eligible(self.cfg, self.db, "consistency")], [beta])
        self.assertEqual(packets.eligible(self.cfg, self.db, "review", "corpus-editor"), [])
        second = packets.claim(self.cfg, self.db, "consistency", "other-editor")["claimed"]
        self.assertTrue(self.save_submit(second, self.answer(second))["accepted"])
        self.assertEqual(packets.eligible(self.cfg, self.db, "fluency"), [])
        with self.assertRaisesRegex(HarnessError, "linguistic stages"):
            build.build(self.cfg, self.db, "candidate", "pending-review")
        review = packets.claim(self.cfg, self.db, "review", "fresh-reviewer")["claimed"]
        self.assertTrue(self.save_submit(review, self.answer(review))["accepted"])
        revise = packets.claim(self.cfg, self.db, "revise", "final-reviser")["claimed"]
        self.assertTrue(self.save_submit(revise, self.answer(revise, "Edited {Key}"))["accepted"])
        self.assertEqual({u["sid"] for u in packets.eligible(self.cfg, self.db, "fluency")}, {alpha, beta})

    def test_fluency_continues_other_units_but_build_and_lqa_wait(self):
        self.ready_corpus(consistency=True)
        beta = self.db.unit("option_beta")["sid"]
        first = packets.claim(self.cfg, self.db, "fluency", "fluency-editor")["claimed"]
        self.assertTrue(self.save_submit(first, self.answer(first, "Edited {Key}"))["accepted"])
        self.assertEqual([u["sid"] for u in packets.eligible(self.cfg, self.db, "fluency")], [beta])
        second = packets.claim(self.cfg, self.db, "fluency", "other-fluency-editor")["claimed"]
        self.assertTrue(self.save_submit(second, self.answer(second))["accepted"])
        self.assertEqual(packets.eligible(self.cfg, self.db, "lqa"), [])
        with self.assertRaisesRegex(HarnessError, "linguistic stages"):
            build.build(self.cfg, self.db, "candidate", "pending-fluency-review")

    def test_corpus_pass_entry_prior_stage_and_stale_guards_remain(self):
        self.ready_corpus()
        alpha = self.db.unit("option_alpha")["sid"]
        self.db.c.execute("UPDATE units SET stages='[\"translate\",\"review\"]' WHERE sid=?", (alpha,))
        self.assertEqual(packets.eligible(self.cfg, self.db, "consistency"), [])
        self.db.c.execute("UPDATE units SET stages='[\"translate\",\"review\",\"revise\"]' WHERE sid=?", (alpha,))
        self.assertEqual(len(packets.eligible(self.cfg, self.db, "consistency")), 2)
        self.db.c.execute("UPDATE units SET stale=1 WHERE sid=?", (alpha,))
        self.assertEqual(packets.eligible(self.cfg, self.db, "consistency"), [])
        self.db.c.execute("UPDATE units SET stale=0,stages='[\"translate\",\"review\",\"revise\",\"consistency\"]' WHERE sid=?", (alpha,))
        self.assertEqual(packets.eligible(self.cfg, self.db, "fluency"), [])
        self.db.c.execute("UPDATE units SET stages='[\"translate\",\"fluency\"]' WHERE sid=?", (alpha,))
        self.assertEqual(packets.eligible(self.cfg, self.db, "fluency"), [])

    def test_pilot_edit_still_requires_pilot_reassessment_before_corpus_claims(self):
        self.ready_corpus()
        first = packets.claim(self.cfg, self.db, "consistency", "corpus-editor")["claimed"]
        self.assertTrue(self.save_submit(first, self.answer(first))["accepted"])
        pilot = packets.claim(self.cfg, self.db, "consistency", "pilot-editor")["claimed"]
        self.assertTrue(self.save_submit(pilot, self.answer(pilot, "Edited {Key}"))["accepted"])
        self.assertFalse(self.db.gate_ok("pilot"))
        for stage in ("consistency", "fluency", "lqa"):
            self.assertEqual(packets.eligible(self.cfg, self.db, stage), [])
        with self.assertRaisesRegex(HarnessError, "pilot"):
            build.build(self.cfg, self.db, "candidate", "pending-pilot")


class PacketTests(HarnessFixture):
    def test_compact_frozen_input_preserves_all_values_and_existing_legacy_file(self):
        source = 'Press {Key}: "è, [x]" \\ path\r\nNext line\n'
        native = Locres(3, [Entry("ImportedStringTable", "option_alpha", 0xFFFFFFFF, source),
                           Entry("ImportedStringTable", "option_beta", 22, "Choose {Key}")])
        reference = 'Synthetic "é, {Key}" reference\r\nwith \\ path'
        self.seed("compact-input", native, {"fr": Locres(3, [
            Entry("ImportedStringTable", "option_alpha", 0xFFFFFFFF, reference)])})
        extra = {"future_field": {"quoted": '", {value}', "nullable": None,
                                   "sequence": [False, 4294967295, "😀\r\n"]}}
        self.db.c.execute("UPDATE units SET data=? WHERE key='option_alpha'", (json.dumps(extra),))
        for gate in ("source", "style", "glossary", "characters"):
            approve(self.cfg, self.db, gate, "Synthetic compact-input fixture", "test-owner")
        pid = packets.claim(self.cfg, self.db, "translate", "translator")["claimed"]
        path = self.root / "work/packets" / (pid + ".json")
        expected = packets.render(self.cfg, self.db, packets.get(self.db, pid))
        self.assertEqual(read_json(path), expected)
        unit = next(u for u in read_json(path)["units"] if u["key"] == "option_alpha")
        self.assertEqual((unit["source"], unit["data"], unit["official_references"][0]["text"]),
                         (source, extra, reference))
        pretty = json.dumps(expected, ensure_ascii=False, indent=1) + "\n"
        self.assertLess(len(path.read_text(encoding="utf-8")), len(pretty))
        # Represent an input frozen by the older serializer, then recover target.
        path.write_text(pretty, encoding="utf-8")
        legacy = path.read_bytes()
        packets.prepare(self.cfg, self.db, pid)
        self.assertEqual(path.read_bytes(), legacy)
        self.assertEqual(read_json(path), expected)

    def test_locked_text_can_be_reviewed_but_not_changed_by_worker(self):
        self.translate()
        self.db.c.execute("UPDATE units SET locked=1")
        review = packets.claim(self.cfg,self.db,"review","reviewer")["claimed"]
        self.assertTrue(self.save_submit(review,self.answer(review))["accepted"])
        revise = packets.claim(self.cfg,self.db,"revise","reviser")["claimed"]
        self.assertFalse(self.save_submit(revise,self.answer(revise,"Changed {Key}"))["accepted"])
        self.assertTrue(self.save_submit(revise,self.answer(revise))["accepted"])

    def test_lqa_issue_resolution_is_recorded_and_re_reviewed(self):
        self.translate()
        self.db.c.execute("UPDATE units SET stages='[\"translate\",\"review\",\"revise\",\"consistency\",\"fluency\"]'")
        approve(self.cfg,self.db,"pilot","Synthetic pilot","test-owner")
        sid = self.db.unit("option_alpha")["sid"]
        self.db.c.execute("INSERT INTO issues(sid,packet,version,category,severity,comment) VALUES(?,'owner-lqa',1,'layout','minor','Synthetic width issue')",(sid,))
        pid = packets.claim(self.cfg,self.db,"lqa","lqa-worker")["claimed"]
        a = self.answer(pid)
        issue = self.db.one("SELECT id FROM issues WHERE sid=?",(sid,))["id"]
        a["units"][0]["resolutions"] = [{"issue":issue,"decision":"accepted","reason":"Synthetic shorter wording"}]
        a["units"][0]["target"] = "Short {Key}"
        self.assertTrue(self.save_submit(pid,a)["accepted"])
        self.assertEqual(self.db.one("SELECT status FROM issues WHERE id=?",(issue,))["status"],"accepted")
        self.assertNotIn("review",self.db.unit(sid)["stages"])

    def test_prepare_preserves_draft_and_frozen_input(self):
        pid = packets.claim(self.cfg,self.db,"translate","translator")["claimed"]
        path = self.root / "work/results" / (pid+".json")
        packet_path = self.root / "work/packets" / (pid+".json")
        path.write_text('{"partial":"keep me"}',encoding="utf-8")
        frozen = packet_path.read_bytes()
        packets.prepare(self.cfg,self.db,pid)
        self.assertEqual(path.read_text(),'{"partial":"keep me"}')
        self.assertEqual(packet_path.read_bytes(),frozen)

    def test_frozen_packet_lists_each_neighbor_once_with_unit_windows(self):
        pid = packets.claim(self.cfg,self.db,"translate","translator")["claimed"]
        frozen = read_json(self.root/"work/packets"/(pid+".json"))
        group = frozen["payload"]["group"]
        window = frozen["group_windows"][group]
        self.assertEqual(len({r["sid"] for r in window}), len(window))
        self.assertTrue(all(r["in_packet"] == (r["sid"] in frozen["payload"]["sids"]) for r in window))
        for unit in frozen["units"]:
            start, end = unit["window"]
            self.assertIn(unit["sid"], [r["sid"] for r in window if start <= r["index"] < end])
            self.assertEqual(unit["source"], self.db.unit(unit["sid"])["source"])
            self.assertNotIn("uid", unit)

    def test_submit_is_atomic_and_requires_complete_unique_units(self):
        pid = packets.claim(self.cfg,self.db,"translate","translator")["claimed"]
        answer = self.answer(pid)
        answer["units"][1]["target"] = "Missing argument"
        self.assertFalse(self.save_submit(pid,answer)["accepted"])
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM units WHERE target IS NOT NULL")["n"],0)
        answer = self.answer(pid)
        answer["units"] = answer["units"][:1]
        with self.assertRaises(HarnessError):
            self.save_submit(pid,answer)
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM history")["n"],0)

    def test_source_or_contract_changes_reject_stale_work(self):
        pid = packets.claim(self.cfg,self.db,"translate","translator")["claimed"]
        answer = self.answer(pid)
        (self.root / "style/style-guide.md").write_text("Changed rule",encoding="utf-8")
        with self.assertRaises(HarnessError):
            self.save_submit(pid,answer)
        self.assertIsNone(self.db.unit("option_alpha")["target"])

    def test_target_version_conflict_rejects_whole_packet(self):
        pid = packets.claim(self.cfg,self.db,"translate","translator")["claimed"]
        answer = self.answer(pid)
        sid = self.db.unit("option_alpha")["sid"]
        owner_set(self.cfg,self.db,sid,"Owner {Key}","Synthetic fixture")
        with self.assertRaises(HarnessError):
            self.save_submit(pid,answer)
        self.assertIsNone(self.db.unit("option_beta")["target"])

    def test_independent_review_revision_and_double_submit(self):
        pid = self.translate()
        with self.assertRaises(HarnessError):
            packets.submit(self.cfg,self.db,pid)
        self.assertIsNone(packets.claim(self.cfg,self.db,"review","translator")["claimed"])
        review = packets.claim(self.cfg,self.db,"review","reviewer")["claimed"]
        self.assertTrue(self.save_submit(review,self.answer(review))["accepted"])
        revise = packets.claim(self.cfg,self.db,"revise","reviser")["claimed"]
        self.assertTrue(self.save_submit(revise,self.answer(revise))["accepted"])
        self.assertTrue(all("revise" in self.db.unit(r["sid"])["stages"] for r in self.db.rows("SELECT sid FROM units")))
        approve(self.cfg,self.db,"pilot","Synthetic pilot accepted","test-owner")
        self.db.c.execute("UPDATE units SET stages='[\"translate\",\"review\",\"revise\",\"consistency\"]'")
        self.assertTrue(self.db.gate_ok("pilot"),"Stage bookkeeping alone must not invalidate pilot approval")

    def test_issue_resolution_returns_changed_text_to_review(self):
        self.translate()
        review = packets.claim(self.cfg,self.db,"review","reviewer")["claimed"]
        a = self.answer(review)
        first = a["units"][0]["sid"]
        a["units"][0].update(verdict="issues",issues=[{"category":"accuracy","severity":"major","comment":"Synthetic accuracy issue","suggestion":"Revised {Key}"}])
        self.assertTrue(self.save_submit(review,a)["accepted"])
        revise = packets.claim(self.cfg,self.db,"revise","reviser")["claimed"]
        a = self.answer(revise)
        issue = self.db.one("SELECT id FROM issues WHERE sid=?",(first,))["id"]
        for row in a["units"]:
            if row["sid"] == first:
                row.update(target="Revised {Key}",resolutions=[{"issue":issue,"decision":"accepted","reason":"Synthetic corrected wording"}])
        self.assertTrue(self.save_submit(revise,a)["accepted"])
        self.assertNotIn("review",self.db.unit(first)["stages"])
        self.assertEqual(self.db.one("SELECT status FROM issues WHERE id=?",(issue,))["status"],"accepted")
        self.assertIsNone(packets.claim(self.cfg,self.db,"review","translator")["claimed"],"Any earlier author is barred from self-review")
        self.assertIsNotNone(packets.claim(self.cfg,self.db,"review","reviewer")["claimed"])

    def test_concurrent_claims_never_overlap(self):
        def claim(worker):
            db = Database(self.cfg)
            try:
                return packets.claim(self.cfg,db,"translate",worker)
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim,["one","two"]))
        self.assertEqual(sum(bool(r["claimed"]) for r in results),1)


class InstallTests(HarnessFixture):
    def prepare_install(self):
        game = self.root / "fake-game"
        pakdir = game / self.cfg["game"]["pak_relative"]
        pakdir.mkdir(parents=True)
        native = pakdir / "native.pak"
        native.write_bytes(b"Synthetic vanilla game container")
        self.cfg.values["game"]["root"] = str(game)
        overlay = self.root / "build/candidate/overlay.pak"
        overlay.parent.mkdir(parents=True)
        overlay.write_bytes(b"Synthetic overlay container")
        record = {"id":"candidate","installable":True,"corpus_hash":self.db.corpus_hash(),"contract_hash":self.cfg.contract_hash(),"source_paks":[{"name":native.name,"sha256":file_hash(native)}],"pak":overlay.relative_to(self.root).as_posix(),"pak_sha256":file_hash(overlay)}
        return game,pakdir,native,record

    def test_additive_install_and_restore_leave_vanilla_unchanged(self):
        game,pakdir,native,record = self.prepare_install()
        before = native.read_bytes()
        with patch("locpipe.build.verify",return_value=record),patch("locpipe.build._game_closed"):
            build.install(self.cfg,self.db,"candidate")
            self.assertTrue((pakdir/self.cfg["build"]["filename"]).exists())
            self.cfg.values["project"]["preparation_only"] = True
            build.restore(self.cfg,self.db,"candidate")
        self.assertFalse((pakdir/self.cfg["build"]["filename"]).exists())
        self.assertEqual(native.read_bytes(),before)

    def test_existing_overlay_or_changed_baseline_is_preserved(self):
        game,pakdir,native,record = self.prepare_install()
        dest = pakdir/self.cfg["build"]["filename"]
        dest.write_bytes(b"Someone else's overlay")
        with patch("locpipe.build.verify",return_value=record),patch("locpipe.build._game_closed"):
            with self.assertRaises(HarnessError):
                build.install(self.cfg,self.db,"candidate")
            self.assertEqual(dest.read_bytes(),b"Someone else's overlay")
            dest.unlink()
            native.write_bytes(b"Changed vanilla")
            with self.assertRaises(HarnessError):
                build.install(self.cfg,self.db,"candidate")
        self.assertFalse(dest.exists())

    def test_modified_overlay_and_receipt_path_are_not_removed(self):
        game,pakdir,native,record = self.prepare_install()
        dest = pakdir/self.cfg["build"]["filename"]
        with patch("locpipe.build.verify",return_value=record),patch("locpipe.build._game_closed"):
            build.install(self.cfg,self.db,"candidate")
            dest.write_bytes(b"Externally modified")
            with self.assertRaises(HarnessError):
                build.restore(self.cfg,self.db,"candidate")
            self.assertTrue(dest.exists())
            path = self.root/"backups/install-candidate.json"
            receipt = read_json(path)
            receipt["destination"] = str(self.root/"outside.pak")
            write_json(path,receipt)
            with self.assertRaises(HarnessError):
                build.restore(self.cfg,self.db,"candidate")
        self.assertTrue(dest.exists())


if __name__ == "__main__":
    unittest.main()
