# Changes

## 0.3.0

- Add the orchestration layer from the Queen's Domain run: bounded batch claims,
  dispatch/reconciliation/acceptance receipts, current-version stage audit, evidence
  snapshot with a bilingual pilot table, live HANDOFF progress and a read-only final
  candidate audit with an optional `audit_candidate` adapter hook.
- Add the offline external-review kit: word-balanced chats, rules and context bundles,
  hash manifest, strict parsing bound to exact unit versions, triage skeleton and an
  `issue-import` export that returns aggregates only.
- Add `glossary_audit.py` and `plan_groups.py` for large corpora; QA glossary matching is
  shared through `qa.term_matches`.
- Add shared agent skills (`loc-run`, `loc-lqa`, `loc-update`), Claude Code commands and
  the offline-worker and runtime-fix prompts; rewrite the translate, review and
  revision prompts around the verified rule views.
- Document orchestration, external review and runtime LQA; scaffold all of it with
  `locpipe init`; add `examples/queens-domain`.
- Known limitation: glossary target forms are matched on word boundaries, so scripts
  written without spaces are not matched when adjacent to other characters.

## 0.2.0

- Replace the original delimited-table toolkit and legacy ensemble prompts with
  the actual versioned Queen's Domain harness, generalized for reuse.
- Add source/target-neutral fields, configurable cultures, engine-neutral JSON,
  project initialization and an explicit custom-adapter interface.
- Preserve immutable intake, SQLite history, transactional claims, frozen packets,
  five offline stages, bound approvals, issue resolutions and draft recovery.
- Include version-matched offline issue provenance and private-input isolation.
- Generalize Unreal paths, discovery, process checks and local report metadata.
- Document fully agent-orchestrated work and focused maintenance with fresh review.
- Keep real project data private; include synthetic regression and end-to-end demos.

The previous toolkit remains in Git history; old project.toml/correction files and
private Queen's Domain databases are not silently migrated into this schema.
