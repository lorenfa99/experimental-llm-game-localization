# Agent roles

Replace template variables (`{{SOURCE_LANGUAGE}}`, `{{TARGET_LANGUAGE}}`,
`{{PROJECT_ROOT}}`) for the project. Start with ORCHESTRATOR.md. Assigned workers read
AGENTS.md, their role, complete rule views, frozen packets and matching scenes. Global
startup is not repeated per packet. The host creates real isolated contexts; a role title
or simulated demo actor is not evidence of independence.

| Prompt | Used by | Purpose |
|---|---|---|
| ORCHESTRATOR.md | the root agent | run the authorized offline scope end to end |
| OFFLINE_WORKER.md | every packet worker | common batch brief; points to the role prompt |
| TRANSLATE.md | writer | first translation of frozen packets |
| BILINGUAL_REVIEW.md | fresh reviewer | independent verdicts and issues; never edits text |
| RESOLVED_REVISION.md | reviser | resolve every open issue with reasons |
| CORPUS_CONSISTENCY.md | editor | cross-group names, senses, address, references |
| TARGET_FLUENCY.md | editor | separate target-language fluency pass |
| OFFLINE_CANDIDATE.md | orchestrator | close the offline scope with a verified candidate |
| RUNTIME_LQA.md | orchestrator | owner-requested runtime test and tracking |
| RUNTIME_FIX.md | reviser | focused correction of a reported wording |
| MAINTENANCE.md | orchestrator | focused corrections reusing completed work |
| EXTERNAL_REVIEW.md | outside reviewer | optional additional findings, as proposals only |

Initial order: translate, review, revise, consistency, fluency, offline candidate, then an
owner-requested runtime LQA. Every changed version returns to review. The orchestrator's
batching and receipts are described in docs/ORCHESTRATION.md and the offline
external-review kit in docs/EXTERNAL-REVIEW.md. The three workflow skills live in
`.agents/skills/`, with Claude Code entry points in `.claude/commands/`.
