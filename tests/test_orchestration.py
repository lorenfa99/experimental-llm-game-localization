"""Synthetic engineering tests for orchestrator tooling; simulated roles are not real reviewers."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from locpipe import orchestration as orch, packets
from locpipe.adapters import json as adapter
from locpipe.cli import approve
from locpipe.config import Config, HarnessError, ROOT, read_json, write_json
from locpipe.db import Database
from locpipe.locres import Entry, Locres

TARGETS = {"confirm": "確定 {Key}", "back": "戻る", "cancel": "取消 {Key}"}


class OrchestrationFixture(unittest.TestCase):
    packet_settings = "max_units=40"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="locpipe-orch-test-")
        self.root = Path(self.temp.name)
        shutil.copyfile(ROOT / "config.toml", self.root / "config.toml")
        (self.root / "config.local.toml").write_text(
            f'[project]\npreparation_only=false\ntarget_culture="ja"\n[packets]\n{self.packet_settings}\n', encoding="utf-8")
        (self.root / "style").mkdir()
        (self.root / "style/style-guide.md").write_text("Synthetic fixture contract.", encoding="utf-8")
        (self.root / "docs").mkdir()
        (self.root / "docs/MULTILINGUAL-REFERENCES.md").write_text("Synthetic reference policy.", encoding="utf-8")
        write_json(self.root / "style/characters.json", {"characters": []})
        write_json(self.root / "glossary/glossary.json", {"entries": []})
        self.cfg = Config(self.root)
        self.db = Database(self.cfg)
        document = {"schema": "locpipe.source.v1", "localization_target": "Game", "source_culture": "en", "units": [
            {"namespace": "UI", "key": "confirm", "source": "Confirm {Key}", "kind": "ui", "wave": "ui", "group": "menu/a"},
            {"namespace": "UI", "key": "back", "source": "Back", "kind": "ui", "wave": "ui", "group": "menu/b"},
            {"namespace": "UI", "key": "cancel", "source": "Cancel {Key}", "kind": "ui", "wave": "ui", "group": "menu/c"},
            {"namespace": "UI", "key": "blank", "source": "", "include": False}]}
        write_json(self.root / "input.json", document)
        adapter.capture(self.cfg, self.db, "initial", self.root / "input.json")
        adapter.index_context(self.cfg, self.db)
        for gate in ("source", "style", "glossary", "characters"):
            approve(self.cfg, self.db, gate, "Synthetic test authorization only", "synthetic-owner")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def stage(self, stage, worker, receipts=False):
        """Complete one stage. Review packets get a fresh-context dispatch receipt when asked."""
        done = []
        while True:
            pid = packets.claim(self.cfg, self.db, stage, worker)["claimed"]
            if not pid:
                return done
            if receipts and stage == "review":
                orch.record_receipt(self.cfg, self.db, "dispatch", "fresh-agent-" + pid[-4:], [pid], capacity=2)
            result = read_json(self.root / "work/results" / (pid + ".json"))
            for row in result["units"]:
                if stage == "review":
                    row.update(verdict="ok", issues=[])
                elif stage in ("translate", "consistency", "fluency"):
                    row.update(target=TARGETS[self.db.unit(row["sid"])["key"]], note="Synthetic role simulation.")
            write_json(self.root / "work/results" / (pid + ".json"), result)
            self.assertTrue(packets.submit(self.cfg, self.db, pid)["accepted"])
            orch.record_receipt(self.cfg, self.db, "accepted", worker, [pid])
            done.append(pid)

    def finish_offline(self, receipts=True):
        self.stage("translate", "writer")
        self.stage("review", "reviewer", receipts)
        self.stage("revise", "reviser")
        approve(self.cfg, self.db, "pilot", "Synthetic pilot fixture only", "synthetic-owner")
        self.stage("consistency", "consistency")
        self.stage("fluency", "fluency")


class BatchClaimTests(OrchestrationFixture):
    packet_settings = "max_units=1"

    def test_related_groups_are_claimed_together_within_limits(self):
        result = orch.claim_batch(self.cfg, self.db, "translate", "writer-1", 3, "menu/")
        self.assertEqual(len(result["claims"]), 3)
        self.assertEqual(result["frozen_input_bytes"], sum(c["actual_bytes"] for c in result["claims"]))
        self.assertEqual(result["contract_hash"], self.cfg.contract_hash())
        self.assertGreater(result["working_rules_bytes"], 0)
        self.assertNotIn("warning", result)
        self.assertEqual(len(packets.pending(self.cfg, self.db)), 3)

    def test_unrelated_groups_stay_in_separate_assignments(self):
        result = orch.claim_batch(self.cfg, self.db, "translate", "writer-1", 3)
        self.assertEqual(len(result["claims"]), 1)

    def test_batch_limit_and_stage_are_validated_before_any_claim(self):
        for stage, count in (("translate", 4), ("translate", 0), ("lqa", 1)):
            with self.assertRaises(HarnessError):
                orch.claim_batch(self.cfg, self.db, stage, "writer-1", count)
        self.assertFalse(packets.pending(self.cfg, self.db))

    def test_no_eligible_work_claims_nothing(self):
        result = orch.claim_batch(self.cfg, self.db, "review", "reviewer-1", 2)
        self.assertEqual((result["claims"], result["contract_hash"]), ([], None))


class ByteBudgetTests(OrchestrationFixture):
    packet_settings = "max_units=1\nbatch_max_input_bytes=4097"

    def test_byte_budget_stops_the_batch_after_the_first_packet(self):
        result = orch.claim_batch(self.cfg, self.db, "translate", "writer-1", 3, "menu/")
        self.assertEqual(len(result["claims"]), 1)
        self.assertEqual(len(packets.pending(self.cfg, self.db)), 1)


class ReceiptTests(OrchestrationFixture):
    def claimed(self, count=1):
        return [c["claimed"] for c in orch.claim_batch(self.cfg, self.db, "translate", "writer-1", count, "menu/")["claims"]]

    def test_dispatch_is_idempotent_and_requires_live_claims(self):
        ids = self.claimed()
        first = orch.record_receipt(self.cfg, self.db, "dispatch", "agent-1", ids, capacity=4)
        self.assertEqual((first["event"], first["fork_turns"], first["runtime_worker_capacity"]), ("dispatched_fresh_context", "none", 4))
        self.assertRegex(first["date"], r"^\d{4}-\d\d-\d\d$")
        self.assertTrue(orch.record_receipt(self.cfg, self.db, "dispatch", "agent-1", ids)["already_recorded"])
        self.assertEqual(len(orch.read_log(self.cfg)), 1)
        for event, note in (("dispatch", None), ("accepted", None), ("reconcile-dispatch", "  ")):
            with self.subTest(event=event), self.assertRaises(HarnessError):
                orch.record_receipt(self.cfg, self.db, event, "agent-1", ids, note) if event != "dispatch" else \
                    orch.record_receipt(self.cfg, self.db, event, "agent-1", ["translate-unknown"])

    def test_receipts_reject_mixed_or_duplicate_packets_and_blank_agents(self):
        a = self.claimed()[0]
        b = orch.claim_batch(self.cfg, self.db, "translate", "writer-2", 1)["claims"][0]["claimed"]
        for ids, agent in (([a, b], "agent"), ([a, a], "agent"), ([a], " "), ([], "agent")):
            with self.assertRaises(HarnessError):
                orch.record_receipt(self.cfg, self.db, "dispatch", agent, ids)

    def test_reconcile_requires_actual_evidence_and_records_it(self):
        ids = self.claimed()
        record = orch.record_receipt(self.cfg, self.db, "reconcile-dispatch", "agent-9", ids, note="Fork 7, turns none, created before claim.")
        self.assertEqual(record["actual_fork_attestation"], "Fork 7, turns none, created before claim.")
        self.assertEqual(record["packet_statuses_when_recorded"], {ids[0]: "claimed"})

    def test_acceptance_records_changes_and_flags_pilot_edits(self):
        pid = orch.claim_batch(self.cfg, self.db, "translate", "writer-1", 1)["claims"][0]["claimed"]
        with self.assertRaises(HarnessError):
            orch.record_receipt(self.cfg, self.db, "accepted", "writer-1", [pid])
        result = read_json(self.root / "work/results" / (pid + ".json"))
        for row in result["units"]:
            row.update(target=TARGETS[self.db.unit(row["sid"])["key"]], note="Synthetic.")
        write_json(self.root / "work/results" / (pid + ".json"), result)
        self.assertTrue(packets.submit(self.cfg, self.db, pid)["accepted"])
        record = orch.record_receipt(self.cfg, self.db, "accepted", "writer-1", [pid])
        self.assertEqual(len(record["target_changes"]), 1)
        self.assertEqual(record["changed_pilot_sids"], [record["target_changes"][0]["sid"]])
        self.assertEqual((record["target_changes"][0]["before_version"], record["target_changes"][0]["current_version"]), (0, 1))
        self.assertEqual(record["attempts"], {pid: 1})


class AuditTests(OrchestrationFixture):
    def test_stage_audit_passes_only_with_matching_records_and_receipts(self):
        self.finish_offline()
        result = orch.stage_audit(self.cfg, self.db, "audit-ok", full_offline=True)
        self.assertTrue(result["summary"]["all_metadata_checks_passed"], result)
        self.assertEqual(result["summary"]["units"], 3)
        self.assertEqual(set(result["summary"]["counts"].values()), {3})
        saved = read_json(Path(result["path"]))
        self.assertFalse(saved["runtime_verified"])
        self.assertTrue(all(row["review_agent_receipts"] for row in saved["evidence"]))

    def test_stage_audit_reports_a_missing_fresh_context_receipt(self):
        self.finish_offline(receipts=False)
        result = orch.stage_audit(self.cfg, self.db, "audit-no-receipts")
        self.assertFalse(result["summary"]["all_metadata_checks_passed"])
        self.assertEqual(result["summary"]["counts"]["fresh_context_dispatch_receipt"], 0)
        failed = read_json(Path(result["path"]))["findings"]
        self.assertTrue(all("fresh_context_dispatch_receipt" in f["checks"] for f in failed))

    def test_stage_audit_rejects_unsafe_reused_or_empty_scope(self):
        self.finish_offline()
        orch.stage_audit(self.cfg, self.db, "taken")
        for label, wave in (("taken", "all"), ("../escape", "all"), ("fresh", "no-such-wave"), ("empty", "story")):
            with self.subTest(label=label, wave=wave), self.assertRaises(HarnessError):
                orch.stage_audit(self.cfg, self.db, label, wave)

    def test_evidence_snapshot_is_private_complete_and_escapes_table_cells(self):
        self.finish_offline()
        self.db.c.execute("UPDATE units SET reason='a|b' WHERE key='back'")
        result = orch.evidence_snapshot(self.cfg, self.db, "snap")
        folder = Path(result["directory"])
        evidence = read_json(folder / "evidence.json")
        self.assertTrue(evidence["private_game_derived"])
        self.assertEqual(evidence["coverage"]["units"], 3)
        self.assertEqual(len(evidence["accepted_results"]), len(self.db.rows("SELECT id FROM packets WHERE status='accepted'")))
        self.assertTrue(evidence["dispatch_records"])
        table = (folder / "pilot-table.md").read_text(encoding="utf-8")
        self.assertIn("Source (en)", table)
        self.assertIn("確定 {Key}", table)
        with self.assertRaises(HarnessError):
            orch.evidence_snapshot(self.cfg, self.db, "snap")

    def test_save_progress_replaces_one_section_and_keeps_the_rest(self):
        handoff = self.root / "HANDOFF.md"
        handoff.write_text("# Handoff\n\nIntro line.\n\n## Older\n\nKeep this.\n", encoding="utf-8")
        orch.claim_batch(self.cfg, self.db, "translate", "writer-1", 1)
        first = orch.save_progress(self.cfg, self.db, goal="Finish the pilot.", notes=["Extra note."])
        second = orch.save_progress(self.cfg, self.db, goal="Finish the pilot.")
        text = handoff.read_text(encoding="utf-8")
        self.assertEqual((first["pending_packets"], second["handoff"]), (1, "updated"))
        self.assertEqual(text.count(orch.PROGRESS_HEADER), 1)
        self.assertIn("Intro line.", text)
        self.assertIn("## Older\n\nKeep this.", text)
        self.assertNotIn("Extra note.", text)
        latest = read_json(self.root / "work/orchestration/pending-latest.json")
        self.assertEqual(latest["pending"][0]["worker"], "writer-1")
        self.assertEqual(len((self.root / "work/orchestration/progress-history.jsonl").read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(orch.save_progress(self.cfg, self.db, handoff=False)["handoff"], "not updated")

    def test_save_progress_replaces_a_final_section_too(self):
        (self.root / "HANDOFF.md").write_text("# Handoff\n\nIntro.\n", encoding="utf-8")
        orch.save_progress(self.cfg, self.db)
        orch.save_progress(self.cfg, self.db)
        self.assertEqual((self.root / "HANDOFF.md").read_text(encoding="utf-8").count(orch.PROGRESS_HEADER), 1)


class CandidateAuditTests(OrchestrationFixture):
    def built(self):
        self.finish_offline()
        adapter.build(self.cfg, self.db, "candidate", "candidate")

    def test_json_candidate_audit_collects_closure_formats_and_scalars(self):
        self.built()
        result = orch.candidate_audit(self.cfg, self.db, "candidate", "final", expect_units=3, expect_words=5)
        self.assertEqual((result["in_scope"], result["exclusions"], result["format_probes"]), (3, 1, 2))
        self.assertTrue(result["artifact_content"]["artifact_matches_corpus"])
        self.assertIsNone(result["font_coverage_ok"])
        self.assertFalse(result["runtime_verified"])
        saved = read_json(Path(result["report"]))
        self.assertEqual({p["key"] for p in saved["format_probes"]}, {"confirm", "cancel"})
        self.assertIn("確", {p["character"] for p in saved["printable_scalars"]})
        self.assertEqual(saved["stage_completion"], {s: 3 for s in orch.REQUIRED_STAGES})

    def test_candidate_audit_refuses_open_work_scope_drift_and_tampering(self):
        self.finish_offline()
        adapter.build(self.cfg, self.db, "candidate", "candidate")
        with self.assertRaises(HarnessError):
            orch.candidate_audit(self.cfg, self.db, "candidate", "wrong-scope", expect_units=4)
        self.assertFalse((self.root / "reports/offline-evidence/wrong-scope").exists())
        self.db.c.execute("INSERT INTO issues(sid,packet,version,category,severity,comment) SELECT sid,'p',version,'style','minor','open' FROM units LIMIT 1")
        with self.assertRaises(HarnessError):
            orch.candidate_audit(self.cfg, self.db, "candidate", "open-issue")
        self.db.c.execute("DELETE FROM issues")
        path = self.root / "build/candidate/localization.json"
        path.write_text(path.read_text(encoding="utf-8").replace("戻る", "戻らない"), encoding="utf-8")
        with self.assertRaises(HarnessError):
            orch.candidate_audit(self.cfg, self.db, "candidate", "tampered")

    def test_candidate_audit_requires_a_candidate_not_a_source_copy(self):
        self.finish_offline()
        adapter.build(self.cfg, self.db, "source-copy", "copy")
        with self.assertRaises(HarnessError):
            orch.candidate_audit(self.cfg, self.db, "copy", "wrong-mode")

    def test_incomplete_stages_block_the_audit(self):
        self.stage("translate", "writer")
        with self.assertRaises(HarnessError):
            orch.candidate_audit(self.cfg, self.db, "candidate", "premature")

    def test_unreal_artifact_comparison_checks_hashes_text_and_exclusions(self):
        crc = zlib.crc32(b"Hello")
        native = Locres(3, [Entry("UI", "hello", crc, "Hello", 11, 22), Entry("UI", "skip", 7, "Skip", 11, 33)])
        path = self.root / "data/sources/demo/localization/en/Game.locres"
        path.parent.mkdir(parents=True)
        path.write_bytes(native.encode())
        units = [{"sid": "A", "namespace": "UI", "key": "hello", "source_hash": crc, "source": "Hello", "target": "Ciao", "include": 1},
                 {"sid": "B", "namespace": "UI", "key": "skip", "source_hash": 7, "source": "Skip", "target": None, "include": 0}]
        build = {"source_content_hash": "h", "source_paks": [], "pak": "build/c/c.pak", "entry": "Sample/x.locres"}
        manifest = {"content_hash": "h", "paks": []}
        good = native.encode({("UI", "hello"): "Ciao"})
        with patch("locpipe.orchestration.unreal.repak", return_value=good):
            result = orch._unreal_artifact(self.cfg, self.db, build, units, "demo", manifest)
        self.assertEqual((result["native_identities"], result["candidate_semantic_roundtrip"]), (2, True))
        for name, data, mutate in (("wrong text", native.encode({("UI", "hello"): "Salve"}), None),
                                   ("excluded unit translated", native.encode({("UI", "hello"): "Ciao", ("UI", "skip"): "Salta"}), None),
                                   ("source drift", good, lambda: units[0].update(source_hash=crc + 1)),
                                   ("container drift", good, lambda: build.update(source_content_hash="other"))):
            with self.subTest(name), patch("locpipe.orchestration.unreal.repak", return_value=data):
                if mutate:
                    mutate()
                with self.assertRaises(HarnessError):
                    orch._unreal_artifact(self.cfg, self.db, build, units, "demo", manifest)


class CommandLineTests(OrchestrationFixture):
    def run_command(self, command, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = orch.main(command, ["--project", str(self.root), *args])
        return code, json.loads(out.getvalue())

    def test_cli_wrappers_report_results_and_errors_as_json(self):
        code, payload = self.run_command("claim-batch", "translate", "writer-1", "--max-packets", "2", "--related-prefix", "menu/")
        self.assertEqual((code, len(payload["claims"])), (0, 2))
        ids = [c["claimed"] for c in payload["claims"]]
        code, payload = self.run_command("record-batch", "dispatch", "agent-1", *ids, "--capacity", "3")
        self.assertEqual((code, payload["runtime_worker_capacity"]), (0, 3))
        code, payload = self.run_command("save-progress", "--goal", "Go.", "--no-handoff")
        self.assertEqual((code, payload["pending_packets"]), (0, 2))
        code, payload = self.run_command("stage-audit", "../bad")
        self.assertEqual(code, 1)
        self.assertIn("error", payload)

    def test_every_script_is_a_thin_wrapper_over_a_registered_command(self):
        scripts = {"claim_batch": "claim-batch", "record_batch": "record-batch", "stage_audit": "stage-audit",
                   "report_snapshot": "snapshot", "save_progress": "save-progress", "candidate_audit": "candidate-audit"}
        self.assertEqual(set(scripts.values()), set(orch.COMMANDS))
        for name, command in scripts.items():
            text = (ROOT / "scripts" / (name + ".py")).read_text(encoding="utf-8")
            self.assertIn(f'main("{command}")', text)
            self.assertEqual(text, (ROOT / "locpipe/templates/project/scripts" / (name + ".py")).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
