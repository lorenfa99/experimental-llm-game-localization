---
name: loc-run
description: Resume a locpipe localization project through its pilot and the full offline scope, with independent review, preserved gates and receipts for every dispatch.
---

# Run the offline localization

Use this project only. Read AGENTS.md, HANDOFF.md, config.toml, docs/DECISION-AUTHORITY.md
and the relevant parts of docs/WORKFLOW.md, docs/FILE-ORDER.md and docs/ORCHESTRATION.md.
Run doctor, `status --brief`, `pending`, `gate list` and `plan` once, then recover any
pending packet and its draft before claiming new work.

Translation must be authorized (`project.preparation_only=false`) and the four preparation
gates approved by their actual owner or a documented delegate. Never approve a gate just
to unblock work. Never infer translation authorization from receiving game files.

Start or recover the pilot before bulk work. Assigned workers follow AGENTS.md's role
startup and docs/EFFICIENCY.md: they read the verified rule views once per batch, every
assigned frozen input and the matching scene briefs fully, and use focused complete
graphs when meaning or structure needs them. Models and effort follow the current
environment; do not import settings from the case study.

Batch with `scripts/claim_batch.py` (related packets, within the configured packet and byte
limits), dispatch each batch to its own worker, and record what actually happened with
`scripts/record_batch.py dispatch` and `accepted`. One live worker owns each packet.
Writers and bilingual reviewers use separate genuinely fresh contexts (`fork_turns=none`
where the host supports it); a new worker label is not independence. If independence is
unavailable, preserve the drafts and report the limitation.

Preserve every quality stage: translate, review, revise, then corpus consistency and a
separate target-language fluency pass. Every changed version returns to fresh review and a
final revision. Recover drafts with `pending`/`prepare`; never automatically steal,
release or overwrite. Submit through the harness and investigate exact rejection errors.

Use `scripts/stage_audit.py` for a traceability audit, `scripts/report_snapshot.py` for the
pilot evidence table, `scripts/save_progress.py` before a pause, and
`scripts/candidate_audit.py` to close the offline scope. These check records against each
other; none of them judges language or proves isolation.

Binding changes (config, style, glossary, characters) invalidate claims and approvals and
need a deliberate rebase and evidence-backed renewal between affected batches. Finish the
offline scope with QA, a candidate build and a runtime handoff inside this project.
Runtime and release acceptance, installation and any launch of the game need the owner's
further instruction. Do not publish game-derived material or call paid APIs.
