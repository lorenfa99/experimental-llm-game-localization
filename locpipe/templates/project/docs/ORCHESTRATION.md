# Orchestrating a run

The orchestrator is the root agent. It schedules work and keeps the record; it does not
translate or review the batches it dispatches. These scripts support that job. Every one
reads the project database through the harness, prints JSON, exits 1 on a refusal with
`{"error": ...}`, and takes `--project <directory>` for a separate project. None of them
calls a model, judges language, approves a gate or proves that a context was isolated.

| Script | Purpose |
|---|---|
| `claim_batch.py` | claim related packets for one worker within the configured limits |
| `record_batch.py` | append dispatch / reconciliation / acceptance receipts |
| `stage_audit.py` | check that every current version has its review, revision and receipts |
| `report_snapshot.py` | private evidence snapshot plus a bilingual pilot table |
| `save_progress.py` | refresh the live-state section of HANDOFF.md before a pause |
| `candidate_audit.py` | final read-only evidence for one built candidate |
| `glossary_audit.py` | audit the glossary against the corpus with the QA matching rule |
| `plan_groups.py` | propose larger packet families as a reviewable overrides file |
| `external_review_kit.py` | build and triage an outside-review kit ([EXTERNAL-REVIEW.md](EXTERNAL-REVIEW.md)) |

## The dispatch loop

```text
python scripts/claim_batch.py translate writer-1 --max-packets 3 --related-prefix "family:UI/"
# hand the printed packets to ONE fresh worker (prompts/OFFLINE_WORKER.md + role prompt)
python scripts/record_batch.py dispatch <agent-id> <packet-id>... --capacity 4
# the worker validates and submits through the harness
python scripts/record_batch.py accepted <agent-id> <packet-id>...
```

`claim_batch` claims through the ordinary `next` logic, so the stage rules, gates and
one-live-owner guarantee are unchanged. It adds three things: it groups packets whose
group names share `--related-prefix`; it renders each frozen input before claiming more
and stops when the batch would exceed `packets.batch_max_input_bytes` (a single oversized
packet runs alone and the result says so); and it builds the verified rule views once
for the whole batch. The result reports the frozen byte total, the contract hash and the
rule-view size.

Receipts go to `work/orchestration/dispatch.jsonl`. They are attestations by the
orchestrator, not proof:

- `dispatch` records that a review (or other) batch went to a fresh context created with
  `fork_turns=none`, the agent id, the packets and the verified concurrent worker capacity.
  It requires live claims and is idempotent.
- `reconcile-dispatch` repairs a missing receipt after the fact. It requires `--note`
  quoting the actual fork or assignment evidence; a label alone is refused.
- `accepted` records the harness outcome per packet: review verdicts and severities,
  issue resolutions, target changes with before/after versions, and which pilot units
  changed (a pilot edit invalidates the pilot gate, so it is surfaced immediately).

If a host cannot create a context with no inherited history, do not dispatch a review:
preserve the drafts and report the limitation.

## Audits

`stage_audit.py <new-label> [--wave W] [--full-offline]` writes
`reports/offline-evidence/<label>/current-version-audit.json`. For each in-scope unit
it checks that the current version has all required stage tags, an accepted bilingual
review of exactly this version whose source stamp matches, a final revision after that
review, a reviewer who never authored the text, a fresh-context dispatch receipt for the
review, and no stale flag. `--full-offline` adds consistency and fluency. Failures list
the unit and which check failed. It is a traceability check: it shows that the records
agree, not that the language is good.

`report_snapshot.py <new-label>` writes `evidence.json` (coverage, pilot, accepted
results, issues, dispatch records) and `pilot-table.md`, a bilingual table of the pilot
units with versions, stages and issues for the pilot assessment. It never grades quality.

`save_progress.py [--goal TEXT] [--note TEXT] [--no-handoff]` writes
`work/orchestration/pending-latest.json`, appends `progress-history.jsonl` and replaces
only the "Current orchestrator progress" section of HANDOFF.md (inserting it ahead of the
first section on the first run). It reads state; claims, submissions and approvals are
untouched. Run it before any planned pause and after recovering an interrupted run.

## Closing the offline scope

`candidate_audit.py <candidate-label> <new-label> [--expect-units N] [--expect-words N]`
requires complete stages, no live packet, no open issue, valid offline gates, clean
source and target QA and a candidate that matches the current contract and corpus. It then
compares the built artifact with the corpus (the JSON adapter and the Unreal adapter are
built in; a custom adapter can provide `audit_candidate(cfg, db, build)`), lists every
format-bearing string with its QA result, inventories the printable characters the
targets use, and checks them against the captured game fonts when the adapter has them.
A font that lacks a used character stops the audit. The report states that none of this is
runtime evidence. `--expect-units`/`--expect-words` pin the scope you believe you have.

## Before bulk work

- `plan_groups.py --rules rules.json` proposes families (for example one packet group
  per item class instead of one per asset). Review it, then `--merge scope.json` writes
  `data/overrides.json`, which `index_context` applies; overrides bind to `source_sha`, so
  a changed source makes a stale decision fail loudly. Rules are data: see the module
  documentation in `locpipe/grouping.py`.
- `glossary_audit.py` reports shape and hygiene problems, entries that never match, entries
  that match an everyday word in many units, and whether each entry's own examples pass
  `qa.check`. Blocking problems exit 1. A match count is evidence for the terminologist.
  Note that target forms are matched on word boundaries; for scripts written without
  spaces (Chinese, Japanese) keep a glossary form delimited by spaces or punctuation in
  its examples, or the QA check will not see it.
