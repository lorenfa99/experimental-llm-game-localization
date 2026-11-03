import json
import unittest

from locpipe import packets
from locpipe.cli import approve, dispatch, parser
from locpipe.config import HarnessError, read_json
from locpipe.offline_issues import import_findings
from test_harness import HarnessFixture


class OfflineIssueTests(HarnessFixture):
    def ready(self):
        self.translate()
        self.db.c.execute("UPDATE units SET stages=?", (json.dumps(
            ["translate", "review", "revise", "consistency", "fluency"]),))
        approve(self.cfg, self.db, "pilot", "Synthetic completed pilot", "test-owner")
        return [self.db.unit(r["sid"]) for r in self.db.rows("SELECT sid FROM units ORDER BY sid")]

    def finding(self, u):
        return {**{k: u[k] for k in ("sid", "namespace", "key", "source_sha", "source_hash", "version")},
                "current_target": u["target"], "category": "accuracy", "severity": "minor",
                "comment": "Synthetic offline linguistic finding", "suggestion": "Improved {Key}",
                "finding_id": "G01", "external_file_sha256": "synthetic-provenance"}

    def load(self, rows):
        path = self.root / "offline.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return import_findings(self.cfg, self.db, path, "gemini-linguistic", "actual-agent", "Synthetic offline research")

    def test_offline_provenance_resolution_and_real_edit_invalidation(self):
        units = self.ready()
        before = {u["sid"]: u for u in units}
        result = self.load([self.finding(units[0])])
        sid, other = units[0]["sid"], units[1]["sid"]
        self.assertEqual(result["resolution_stage"], "revise")
        issue = self.db.one("SELECT * FROM issues")
        self.assertEqual((issue["packet"], issue["category"]), ("offline:gemini-linguistic", "accuracy"))
        self.assertEqual(self.db.unit(other), before[other])
        self.assertEqual(self.db.unit(sid)["version"], before[sid]["version"])
        self.assertNotIn("revise", self.db.unit(sid)["stages"])
        self.assertIn("review", self.db.unit(sid)["stages"])
        event = json.loads(self.db.one("SELECT data FROM events WHERE type='offline_issue_import'")["data"])
        self.assertEqual(event["actor"], "actual-agent")
        self.assertEqual(event["findings"][0]["external_file_sha256"], "synthetic-provenance")
        claim = packets.claim(self.cfg, self.db, "revise", "corrector")["claimed"]
        corrective_input = read_json(self.root / "work/packets" / (claim + ".json"))
        self.assertEqual(corrective_input["units"][0]["issues"][0]["id"], issue["id"])
        answer = self.answer(claim, "Improved {Key}")
        answer["units"][0]["resolutions"] = [{"issue": issue["id"], "decision": "accepted", "reason": "Actual correction"}]
        self.assertTrue(self.save_submit(claim, answer)["accepted"])
        current = self.db.unit(sid)
        self.assertEqual(current["version"], before[sid]["version"] + 1)
        self.assertEqual(set(current["stages"]), {"translate"})
        self.assertEqual(self.db.one("SELECT status FROM issues")["status"], "accepted")
        self.assertFalse(self.db.gate_ok("pilot"))
        self.assertFalse(self.db.gate_ok("runtime"))
        self.assertFalse(self.db.gate_ok("release"))
        self.assertEqual([u["sid"] for u in packets.eligible(self.cfg, self.db, "review", "fresh-reviewer")], [sid])
        review = packets.claim(self.cfg, self.db, "review", "fresh-reviewer")["claimed"]
        review_input = read_json(self.root / "work/packets" / (review + ".json"))
        self.assertEqual(review_input["units"][0]["issues"], [])
        self.assertNotIn("Actual correction", json.dumps(review_input))
        self.assertEqual(self.db.one("SELECT resolution FROM issues")["resolution"], "Actual correction")

    def test_every_binding_is_required_and_second_failure_rolls_back_first(self):
        units = self.ready()
        original = [self.db.unit(u["sid"]) for u in units]
        for field in ("sid", "namespace", "key", "source_sha", "source_hash", "version", "current_target"):
            with self.subTest(field=field):
                good, bad = self.finding(units[0]), self.finding(units[1])
                bad.pop(field)
                with self.assertRaises((HarnessError, KeyError)):
                    self.load([good, bad])
                self.assertEqual(self.db.rows("SELECT * FROM issues"), [])
                self.assertEqual([self.db.unit(u["sid"]) for u in units], original)
        for field, value in (("sid", units[1]["key"]), ("namespace", "wrong"), ("key", "wrong"),
                             ("source_sha", "wrong"), ("source_hash", -1), ("version", -1), ("current_target", "stale")):
            with self.subTest(stale=field):
                good, bad = self.finding(units[0]), self.finding(units[1])
                bad[field] = value
                with self.assertRaises(HarnessError):
                    self.load([good, bad])
                self.assertEqual(self.db.rows("SELECT * FROM issues"), [])
                self.assertEqual([self.db.unit(u["sid"]) for u in units], original)

    def test_reimport_cannot_duplicate_or_discard_a_resolution(self):
        units = self.ready()
        row = self.finding(units[0])
        with self.assertRaises(HarnessError):
            self.load([row, row])
        self.assertEqual(self.db.rows("SELECT * FROM issues"), [])
        self.load([row])
        self.db.c.execute("UPDATE issues SET status='rejected',resolution='Preserved reason'")
        with self.assertRaises(HarnessError):
            self.load([row])
        self.assertEqual(self.db.one("SELECT resolution FROM issues")["resolution"], "Preserved reason")
        self.assertEqual(len(self.db.rows("SELECT * FROM issues")), 1)

    def test_active_claim_and_preparation_guards_have_no_import_side_effect(self):
        units = self.ready()
        row = self.finding(units[0])
        self.cfg.values["project"]["preparation_only"] = True
        with self.assertRaises(HarnessError):
            self.load([row])
        self.cfg.values["project"]["preparation_only"] = False
        self.db.c.execute("UPDATE units SET stages='[\"translate\"]' WHERE sid=?", (row["sid"],))
        packets.claim(self.cfg, self.db, "review", "fresh-reviewer")
        self.db.c.execute("UPDATE units SET stages='[\"translate\",\"review\",\"revise\"]' WHERE sid=?", (row["sid"],))
        with self.assertRaisesRegex(HarnessError, "unfinished work"):
            self.load([row])
        self.assertEqual(self.db.rows("SELECT * FROM issues"), [])
        self.assertFalse(self.db.one("SELECT id FROM events WHERE type='offline_issue_import'"))

    def test_cli_route_is_explicit_and_existing_runtime_import_is_unchanged(self):
        units = self.ready()
        path = self.root / "offline.jsonl"
        path.write_text(json.dumps(self.finding(units[0])), encoding="utf-8")
        args = parser().parse_args(["issue-import", str(path), "--origin", "gemini-linguistic", "--by", "actual-agent", "--note", "Offline evidence"])
        result, code = dispatch(args, self.cfg, self.db)
        self.assertEqual((code, result["imported"]), (0, 1))
        path.write_text(json.dumps({"sid": units[1]["sid"], "severity": "minor", "comment": "Synthetic actual runtime observation"}), encoding="utf-8")
        result, code = dispatch(parser().parse_args(["lqa-import", str(path)]), self.cfg, self.db)
        self.assertEqual((code, result["imported"]), (0, 1))
        runtime = self.db.one("SELECT * FROM issues WHERE packet='owner-lqa'")
        self.assertEqual((runtime["sid"], runtime["category"]), (units[1]["sid"], "layout"))


if __name__ == "__main__":
    unittest.main()
