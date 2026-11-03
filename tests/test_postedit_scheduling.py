"""Safety boundaries for batched post-edit repair and compact validation output."""
from __future__ import annotations

import contextlib
import io
import json
import os
from unittest.mock import patch

from test_harness import HarnessFixture
from locpipe import build, packets
from locpipe.cli import approve
from locpipe.config import HarnessError, file_hash, read_json, write_json
from locpipe.worker_context import readable_compact_json
from scripts import check_result


class PosteditSchedulingTests(HarnessFixture):
    def setUp(self):
        super().setUp()
        self.translate()
        for stage, worker in (("review", "initial-reviewer"), ("revise", "initial-reviser")):
            pid = packets.claim(self.cfg, self.db, stage, worker)["claimed"]
            self.assertTrue(self.save_submit(pid, self.answer(pid))["accepted"])
        # Keep alpha as an approved pilot and beta as ordinary bulk text.
        self.db.c.execute("UPDATE units SET pilot=0 WHERE key='option_beta'")
        for gate in ("source", "style", "glossary", "characters", "pilot"):
            approve(self.cfg, self.db, gate, "Synthetic completed bilingual fixture", "test-owner")
        self.alpha = self.db.unit("option_alpha")["sid"]
        self.beta = self.db.unit("option_beta")["sid"]

    def assess(self, sid, stage, text=None):
        unit = self.db.unit(sid)
        packets.write_target(self.db, unit, unit["target"] if text is None else text,
                             stage, stage + "-editor", "Synthetic actual assessment")

    def repair_beta(self):
        pid = packets.claim(self.cfg, self.db, "review", "fresh-postedit-reviewer")["claimed"]
        self.assertIsNotNone(pid)
        self.assertTrue(self.save_submit(pid, self.answer(pid))["accepted"])
        pid = packets.claim(self.cfg, self.db, "revise", "postedit-reviser")["claimed"]
        self.assertIsNotNone(pid)
        answer = read_json(self.root / "work/results" / (pid + ".json"))
        for row in answer["units"]:
            row["note"] = "Assessed fresh OK review; retain corrected text"
        self.assertTrue(self.save_submit(pid, answer)["accepted"])

    def test_unassessed_unreviewed_unit_still_blocks_initial_consistency(self):
        self.assess(self.beta, "translate", "Corretto {Key}")
        self.assertEqual(packets.eligible(self.cfg, self.db, "consistency"), [])

    def test_consistency_continues_other_units_while_its_own_edits_await_review(self):
        self.assess(self.beta, "consistency", "Corretto {Key}")
        self.assertEqual([u["sid"] for u in packets.eligible(self.cfg, self.db, "consistency")],
                         [self.alpha])
        self.assertNotIn("review", self.db.unit(self.beta)["stages"])
        self.assertNotIn("revise", self.db.unit(self.beta)["stages"])
        self.assertEqual(packets.eligible(self.cfg, self.db, "fluency"), [])
        self.assess(self.alpha, "consistency")
        self.assertEqual(packets.eligible(self.cfg, self.db, "fluency"), [])
        with self.assertRaisesRegex(HarnessError, "linguistic stages"):
            build.build(self.cfg, self.db, "candidate", "must-refuse-unreviewed-edit")
        self.repair_beta()
        self.assertEqual({u["sid"] for u in packets.eligible(self.cfg, self.db, "fluency")},
                         {self.alpha, self.beta})

    def test_fluency_continues_but_runtime_and_build_wait_for_final_repair(self):
        for sid in (self.alpha, self.beta):
            self.assess(sid, "consistency")
        self.assess(self.beta, "fluency", "Corretto {Key}")
        self.assertEqual([u["sid"] for u in packets.eligible(self.cfg, self.db, "fluency")],
                         [self.alpha])
        self.assess(self.alpha, "fluency")
        self.db.c.execute(
            "INSERT INTO issues(sid,packet,version,category,severity,comment) VALUES(?,?,?,?,?,?)",
            (self.alpha, "synthetic-runtime-evidence", self.db.unit(self.alpha)["version"],
             "layout", "minor", "Synthetic runtime observation"))
        self.assertEqual(packets.eligible(self.cfg, self.db, "lqa"), [])
        with self.assertRaisesRegex(HarnessError, "linguistic stages"):
            build.build(self.cfg, self.db, "candidate", "must-refuse-unreviewed-fluency")
        self.repair_beta()
        self.assertEqual([u["sid"] for u in packets.eligible(self.cfg, self.db, "lqa")],
                         [self.alpha])

    def test_previous_phase_must_finish_before_fluency_even_during_repairs(self):
        self.assess(self.beta, "consistency")
        self.assertEqual(packets.eligible(self.cfg, self.db, "fluency"), [])

    def test_pilot_text_change_still_stops_bulk_until_substantive_gate_renewal(self):
        self.assess(self.alpha, "consistency", "Corretto {Key}")
        self.assertFalse(self.db.gate_ok("pilot"))
        self.assertEqual(packets.eligible(self.cfg, self.db, "consistency"), [])
        with self.assertRaisesRegex(HarnessError, "owner gates"):
            build.build(self.cfg, self.db, "candidate", "must-refuse-stale-pilot")

    def test_existing_claim_ownership_remains_exclusive_during_repairs(self):
        self.assess(self.beta, "consistency", "Corretto {Key}")
        claim = packets.claim(self.cfg, self.db, "consistency", "exclusive-editor")
        self.assertIsNotNone(claim["claimed"])
        self.assertEqual(packets.get(self.db, claim["claimed"])["payload"]["sids"], [self.alpha])
        self.assertEqual(packets.eligible(self.cfg, self.db, "consistency", "other-editor"), [])
        self.assertEqual(packets.get(self.db, claim["claimed"])["worker"], "exclusive-editor")

    def test_unchanged_assessments_preserve_version_and_bilingual_completion(self):
        before = self.db.unit(self.beta)
        for stage in ("consistency", "fluency"):
            self.assess(self.beta, stage)
        after = self.db.unit(self.beta)
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["target"], before["target"])
        self.assertTrue({"review", "revise", "consistency", "fluency"}.issubset(after["stages"]))


class CompactCheckTests(HarnessFixture):
    def validate(self, pid, brief):
        output = io.StringIO()
        with patch.object(check_result, "Config", return_value=self.cfg), contextlib.redirect_stdout(output):
            code = check_result.main([pid, *( ["--brief"] if brief else [] )])
        return code, json.loads(output.getvalue())

    def test_brief_runs_same_checks_and_summarizes_warnings_without_attempts(self):
        pid = packets.claim(self.cfg, self.db, "translate", "synthetic-writer")["claimed"]
        answer = self.answer(pid)
        for row in answer["units"]:
            row.update(target=self.db.unit(row["sid"])["source"], note="Intentional synthetic equality",
                       acknowledged_warnings=["unchanged"])
        write_json(self.root / "work/results" / (pid + ".json"), answer)
        frozen = self.root / "work/packets" / (pid + ".json")
        frozen_hash = file_hash(frozen)
        detailed_code, detailed = self.validate(pid, False)
        brief_code, brief = self.validate(pid, True)
        self.assertEqual((detailed_code, brief_code), (0, 0))
        self.assertEqual(detailed["errors"], brief["errors"])
        self.assertEqual(brief["warning_counts"], {"unchanged": 2})
        self.assertEqual(brief["warning_units"], 2)
        self.assertTrue(brief["all_submit_checks_executed"])
        self.assertEqual(packets.get(self.db, pid)["attempts"], 0)
        self.assertEqual(file_hash(frozen), frozen_hash)

    def test_brief_preserves_every_blocking_error(self):
        pid = packets.claim(self.cfg, self.db, "translate", "synthetic-writer")["claimed"]
        answer = self.answer(pid, text="Bad {Wrong}")
        write_json(self.root / "work/results" / (pid + ".json"), answer)
        detailed_code, detailed = self.validate(pid, False)
        brief_code, brief = self.validate(pid, True)
        self.assertEqual((detailed_code, brief_code), (1, 1))
        self.assertTrue(detailed["errors"])
        self.assertEqual(detailed["errors"], brief["errors"])
        self.assertEqual(packets.get(self.db, pid)["attempts"], 0)


class FrozenPacketCompactionTests(HarnessFixture):
    def test_new_compact_packet_preserves_entire_render_and_exact_strings(self):
        data = {"future": {"quoted": 'Text {Key}, "[literal]" \\n € À',
                           "nested": [None, True, 17, {"comma": ","}]}}
        self.db.c.execute("UPDATE units SET data=?", (json.dumps(data, ensure_ascii=False),))
        pid = packets.claim(self.cfg, self.db, "translate", "synthetic-writer")["claimed"]
        packet = packets.get(self.db, pid)
        path = self.root / "work/packets" / (pid + ".json")
        rendered = packets.render(self.cfg, self.db, packet)
        self.assertEqual(read_json(path), rendered)
        expected = readable_compact_json(rendered).replace("\n", os.linesep).encode("utf-8")
        self.assertEqual(path.read_bytes(), expected)
        old_pretty = (json.dumps(rendered, ensure_ascii=False, indent=1) + "\n").replace("\n", os.linesep).encode("utf-8")
        self.assertLess(len(expected), len(old_pretty))
        self.assertEqual(read_json(path)["units"][0]["data"], data)
        self.assertEqual(read_json(path)["payload"], packet["payload"])
        preview = {**rendered, "id": "translate-" + "0" * 12}
        self.assertEqual(len(readable_compact_json(preview).replace("\n", os.linesep).encode("utf-8")),
                         path.stat().st_size)

    def test_preexisting_pretty_frozen_packet_and_draft_are_never_reformatted(self):
        pid = packets.claim(self.cfg, self.db, "translate", "synthetic-writer")["claimed"]
        frozen = self.root / "work/packets" / (pid + ".json")
        # Synthetic historical input: older serialization with exactly the same values.
        write_json(frozen, read_json(frozen), indent=2)
        draft = self.root / "work/results" / (pid + ".json")
        before = (frozen.read_bytes(), draft.read_bytes())
        packets.prepare(self.cfg, self.db, pid)
        self.assertEqual((frozen.read_bytes(), draft.read_bytes()), before)
