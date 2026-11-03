# Offline batch worker brief

The orchestrator's message assigns your worker label, role and exact packet IDs. All work
and writes stay inside {{PROJECT_ROOT}}. Use that project's Python environment with
`PYTHONIOENCODING=utf-8`. No model or reasoning overrides, external model/API processes,
game, launcher or save actions, publication or upload, remote creation/push, claims or
delegation by packet workers.

Read AGENTS.md and your role instructions:

- translate: prompts/TRANSLATE.md
- review: prompts/BILINGUAL_REVIEW.md
- revise: prompts/RESOLVED_REVISION.md
- consistency: prompts/CORPUS_CONSISTENCY.md
- fluency: prompts/TARGET_FLUENCY.md

Run `python scripts/worker_context.py build <ALL assigned IDs>` before submitting any of
them. Read all FOUR complete returned rule views once per batch, every frozen input fully,
matching COMPLETE scene briefs, and complete relevant focused graphs or native evidence
when meaning or structure needs them. Read in bounded chunks without tool truncation.
Inherit all `record_defaults`; unknown binding fields stay authoritative. Do not repeat
orchestrator startup or history, or routinely reread equivalent canonical masters.

One role, one fresh context, at most the configured number of related packets and frozen
bytes (`packets.batch_packets`, `packets.batch_max_input_bytes`). A single oversized
packet runs alone and is read fully. Process packets in order. Exactly one live owner per
packet. Write only the printed result paths and your own evidence folder. Never overwrite
a frozen input, source, accepted archive, another worker's draft or a binding rule.

Actually assess EVERY unit, including short labels and pilot units. Reuse the existing
result template for unchanged text and avoid preferential churn. Preserve native
identities, source stamps, exact placeholders and markup, and every issue resolution.
The same source text does not merge identities or automatically require identical
wording; keep justified functional and contextual differences. Consult related current
units beyond the frozen neighbours where consistency or meaning requires it, and record
the versions you relied on. Accepted results and indexes are evidence, not presumed
approval.

Real ambiguity requires actual inspection of the matching official-language references
under docs/MULTILINGUAL-REFERENCES.md and concrete material comparisons, never language
counts or unsupported lore, gender, speaker, chronology, reachability or width claims.
Focused complete evidence is sufficient: do not regenerate whole-corpus audits or redo
research the approved contract already settled unless you find a real defect.

Keep one concise batch assessment. Detailed notes are for actual changes, material
comparisons, mandatory QA-warning reasons and issue resolutions; a clean unit needs no
boilerplate. Warning reasons may be reused only after checking they still apply to this
exact source and target.

Validate with `python scripts/check_result.py <ID> --brief` (detailed mode for
unexplained warnings) and submit only through the harness. After three rejected submits,
stop and report the exact errors. Deterministic validation is not linguistic assessment.
Once accepted and the necessary evidence is saved, finish promptly: accepted IDs and
counts, changed SIDs and the pilot flag, review issues and resolutions, and unresolved
findings only. Do not append a second general audit or a runtime certification.
