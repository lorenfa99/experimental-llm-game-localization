"""Synthetic engineering tests; simulated roles do not certify linguistic independence."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from locpipe import build, packets, qa
from locpipe.adapters import get_adapter
from locpipe.adapters import json as adapter
from locpipe.cli import approve, import_targets, main
from locpipe.config import Config, HarnessError, ROOT, read_json, write_json
from locpipe.db import Database
from locpipe.project import initialize


class JsonAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="locpipe-json-test-")
        self.root = Path(self.temp.name)
        shutil.copyfile(ROOT / "config.toml", self.root / "config.toml")
        (self.root / "config.local.toml").write_text(
            '[project]\npreparation_only=false\ntarget_culture="ja"\n', encoding="utf-8")
        (self.root / "style").mkdir()
        (self.root / "style/style-guide.md").write_text("Synthetic fixture contract.", encoding="utf-8")
        write_json(self.root / "style/characters.json", {"characters": []})
        write_json(self.root / "glossary/glossary.json", {"entries": []})
        self.cfg = Config(self.root)
        self.db = Database(self.cfg)
        self.document = {"schema": "locpipe.source.v1", "localization_target": "Game", "source_culture": "en",
            "opaque": {"keep": [1, "metadata"]}, "units": [
                {"namespace": "UI", "key": "confirm", "source": "Confirm {Key}", "source_hash": 1001,
                 "kind": "ui", "wave": "ui", "group": "menu", "context": "A synthetic confirmation action.",
                 "references": {"fr": {"text": "Confirmer {Key}", "source_hash": 1001}}},
                {"namespace": "Other", "key": "confirm", "source": "Confirm {Key}",
                 "kind": "ui", "wave": "ui", "group": "menu"},
                {"namespace": "UI", "key": "blank", "source": "", "include": False},
                {"namespace": "UI", "key": "number", "source": "42", "include": False}]}
        self.input = self.root / "input.json"

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def capture(self, label="initial", document=None):
        write_json(self.input, self.document if document is None else document)
        result = adapter.capture(self.cfg, self.db, label, self.input)
        if not result.get("unchanged_snapshot"):
            adapter.index_context(self.cfg, self.db)
        return result

    def stage(self, stage, worker):
        while True:
            pid = packets.claim(self.cfg, self.db, stage, worker)["claimed"]
            if not pid:
                break
            result = read_json(self.root / "work/results" / (pid + ".json"))
            for row in result["units"]:
                if stage == "review":
                    row.update(verdict="ok", issues=[])
                else:
                    row.update(target="確定 {Key}", note="Synthetic role simulation; no actual language review claimed.")
            write_json(self.root / "work/results" / (pid + ".json"), result)
            self.assertTrue(packets.submit(self.cfg, self.db, pid)["accepted"])

    def complete(self):
        self.capture()
        for gate in ("source", "style", "glossary", "characters"):
            approve(self.cfg, self.db, gate, "Synthetic test authorization only", "synthetic-owner")
        self.stage("translate", "synthetic-writer")
        self.stage("review", "synthetic-reviewer")
        self.stage("revise", "synthetic-reviser")
        approve(self.cfg, self.db, "pilot", "Synthetic pilot fixture only", "synthetic-owner")
        self.stage("consistency", "synthetic-consistency")
        self.stage("fluency", "synthetic-fluency")

    def test_distinct_identities_and_reference_never_becomes_target(self):
        self.capture()
        units = self.db.rows("SELECT * FROM units WHERE include=1")
        self.assertEqual(len(units), 2)
        self.assertNotEqual(units[0]["sid"], units[1]["sid"])
        self.assertEqual(units[0]["source"], units[1]["source"])
        self.assertTrue(all(u["target"] is None for u in units))
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM refs")["n"], 1)

    def test_complete_pipeline_build_preserves_metadata_and_source_copies(self):
        self.complete()
        record = adapter.build(self.cfg, self.db, "candidate", "candidate")
        payload = read_json(self.cfg.path(record["artifact"]))
        self.assertEqual(payload["target_culture"], "ja")
        self.assertEqual(payload["opaque"], self.document["opaque"])
        self.assertEqual([u["source"] for u in payload["units"]], [u["source"] for u in self.document["units"]])
        self.assertEqual([u["target"] for u in payload["units"]], ["確定 {Key}", "確定 {Key}", "", "42"])
        self.assertTrue(adapter.verify(self.cfg, "candidate")["verified"])
        self.assertFalse(record["runtime_verified"] or record["installable"])
        self.assertEqual({g["name"] for g in self.db.gate_status() if g["status"] == "pending"}, {"runtime", "release"})

    def test_source_copy_is_byte_identical_in_preparation_mode(self):
        self.capture()
        self.cfg.values["project"]["preparation_only"] = True
        record = adapter.build(self.cfg, self.db, "source-copy", "source-copy")
        self.assertEqual(self.cfg.path(record["artifact"]).read_bytes(), self.input.read_bytes())
        self.assertTrue(adapter.roundtrip(self.cfg, self.db)["semantic_roundtrip"])

    def test_candidate_requires_language_stages_and_release_requires_runtime_gates(self):
        self.capture()
        with self.assertRaises(HarnessError):
            adapter.build(self.cfg, self.db, "candidate", "premature")
        self.assertFalse((self.root / "build/premature").exists())
        self.complete_after_existing_capture()
        with self.assertRaises(HarnessError):
            adapter.build(self.cfg, self.db, "release", "unaccepted-release")

    def complete_after_existing_capture(self):
        for gate in ("source", "style", "glossary", "characters"):
            approve(self.cfg, self.db, gate, "Synthetic fixture only", "synthetic-owner")
        for stage, actor in (("translate", "writer"), ("review", "reviewer"), ("revise", "reviser")):
            self.stage(stage, actor)
        approve(self.cfg, self.db, "pilot", "Synthetic fixture only", "synthetic-owner")
        self.stage("consistency", "consistency")
        self.stage("fluency", "fluency")

    def test_duplicate_identity_and_invalid_metadata_reject_before_capture(self):
        for mutate in (lambda d: d["units"].append(copy.deepcopy(d["units"][0])),
                       lambda d: d["units"][0].update(include="yes"),
                       lambda d: d["units"][0].update(source_hash=True),
                       lambda d: d["units"][0].update(wave="unknown"),
                       lambda d: d["units"][0].update(target="Unreviewed target")):
            document = copy.deepcopy(self.document)
            mutate(document)
            with self.assertRaises(HarnessError):
                self.capture(document=document)
            self.assertIsNone(self.db.meta("active_snapshot"))
            self.assertFalse((self.root / "data/sources/initial").exists())

    def test_source_culture_and_identity_domain_are_explicit(self):
        for field, value in (("source_culture", "de"), ("localization_target", "AnotherDomain")):
            document = copy.deepcopy(self.document)
            document[field] = value
            with self.assertRaises(HarnessError):
                self.capture(document=document)

    def test_official_references_require_their_own_source_revision(self):
        document = copy.deepcopy(self.document)
        del document["units"][0]["references"]["fr"]["source_hash"]
        with self.assertRaises(HarnessError):
            self.capture(document=document)

    def test_snapshot_update_preserves_history_and_invalidates_changed_unit(self):
        self.complete()
        before = self.db.rows("SELECT * FROM units WHERE namespace='UI' AND key='confirm'")[0]
        history_count = self.db.one("SELECT COUNT(*) n FROM history")["n"]
        document = copy.deepcopy(self.document)
        document["units"][0].update(source="Confirm now {Key}", source_hash=1002)
        self.capture("updated", document)
        current = self.db.unit(before["sid"])
        self.assertTrue(current["stale"])
        self.assertEqual(current["stages"], [])
        self.assertEqual(current["target"], before["target"])
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM history")["n"], history_count)
        self.assertFalse(self.db.gate_ok("source"))
        self.assertFalse(self.db.one("SELECT compatible FROM refs WHERE snapshot='updated'")["compatible"])

    def test_existing_snapshot_cannot_be_overwritten(self):
        self.capture()
        document = copy.deepcopy(self.document)
        document["opaque"]["keep"] = ["different"]
        with self.assertRaises(HarnessError):
            self.capture(document=document)
        self.assertEqual(read_json(self.root / "data/sources/initial/source.json"), self.document)

    def test_explicit_scope_update_applies_even_when_source_text_is_unchanged(self):
        self.capture()
        document = copy.deepcopy(self.document)
        document["units"][0]["include"] = False
        self.capture("scope-update", document)
        row = self.db.rows("SELECT * FROM units WHERE namespace='UI' AND key='confirm'")[0]
        self.assertEqual(row["include"], 0)

    def test_target_import_rejects_old_native_revision_even_when_text_and_version_match(self):
        self.capture()
        old = self.db.rows("SELECT * FROM units WHERE namespace='UI' AND key='confirm'")[0]
        document = copy.deepcopy(self.document)
        document["units"][0]["source_hash"] = 1002
        self.capture("revision-only", document)
        current = self.db.unit(old["sid"])
        self.assertEqual((old["source_sha"], old["version"]), (current["source_sha"], current["version"]))
        incoming = {k: old[k] for k in ("sid", "namespace", "key", "source_sha", "source_hash", "version")}
        incoming.update(target="確定 {Key}", note="Synthetic stale revision test")
        path = self.root / "work/stale-target.jsonl"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(incoming) + "\n", encoding="utf-8")
        with self.assertRaises(HarnessError):
            import_targets(self.cfg, self.db, path)
        self.assertIsNone(self.db.unit(old["sid"])["target"])

    def test_tampered_source_or_artifact_is_rejected(self):
        self.complete()
        record = adapter.build(self.cfg, self.db, "candidate", "candidate")
        self.cfg.path(record["artifact"]).write_text("{}", encoding="utf-8")
        with self.assertRaises(HarnessError):
            adapter.verify(self.cfg, "candidate")
        (self.root / "data/sources/initial/source.json").write_text("{}", encoding="utf-8")
        self.assertFalse(adapter.doctor(self.cfg, self.db)[-1]["ok"])
        with self.assertRaises(HarnessError):
            adapter.build(self.cfg, self.db, "candidate", "from-tampered-source")

    def test_json_adapter_cannot_write_to_a_game_or_claim_font_verification(self):
        with self.assertRaises(HarnessError):
            adapter.install(self.cfg, self.db, "anything")
        self.assertFalse(adapter.fonts(self.cfg, self.db)["supported"])
        self.assertIs(get_adapter(self.cfg), adapter)

    def test_italian_spelling_rule_is_not_applied_to_other_languages(self):
        self.assertNotIn("spelling", {f["code"] for f in qa.check("Word", "pò", target_culture="ja")})
        self.assertIn("spelling", {f["code"] for f in qa.check("Word", "pò", target_culture="it-IT")})


class ProjectTests(unittest.TestCase):
    def test_custom_adapter_requires_explicit_module_and_complete_interface(self):
        cfg = SimpleNamespace(values={"adapter": {"type": "custom", "module": "../unsafe"}})
        with self.assertRaises(HarnessError):
            get_adapter(cfg)
        cfg.values["adapter"]["module"] = "synthetic.adapter"
        with patch("locpipe.adapters.import_module", return_value=SimpleNamespace(INPUT_MODE="source-file")):
            with self.assertRaises(HarnessError):
                get_adapter(cfg)

    def test_initialized_project_runs_offline_and_cannot_be_reinitialized(self):
        with tempfile.TemporaryDirectory(prefix="locpipe-init-test-") as temporary:
            root = initialize(Path(temporary) / "project")
            self.assertTrue(Config(root)["project"]["preparation_only"])
            self.assertEqual(main(["--project", str(root), "doctor"]), 0)
            (root / "work/draft.txt").write_text("Keep my draft", encoding="utf-8")
            with self.assertRaises(HarnessError):
                initialize(root)
            self.assertEqual((root / "work/draft.txt").read_text(encoding="utf-8"), "Keep my draft")

    def test_unreal_process_guard_uses_configured_executable_names(self):
        cfg = {"game": {"process_names": ["OtherGame-Win64-Shipping.exe"]}}
        response = SimpleNamespace(returncode=0, stdout='"OtherGame-Win64-Shipping.exe","42"\n')
        with patch("locpipe.build.os.name", "nt"), patch("locpipe.build.subprocess.run", return_value=response):
            with self.assertRaises(HarnessError):
                build._game_closed(cfg)
            cfg["game"]["process_names"] = ["DifferentGame.exe"]
            build._game_closed(cfg)
            cfg["game"]["process_names"] = []
            with self.assertRaises(HarnessError):
                build._game_closed(cfg)
