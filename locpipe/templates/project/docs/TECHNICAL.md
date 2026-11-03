# Technical contract

## Identity and state

`data/localization.sqlite` is authoritative. Unit identity is the JSON tuple
(localization target, namespace, key), with a unique full tuple and short hashed SID.
Source text, source SHA-256 and source revision/CRC never merge identities. A null
`target` is untranslated. Public fields use `source`/`target` and `source_sha`;
locales are configured, not inferred from field names.

Every snapshot is immutable under data/sources. Source text or revision changes
retain targets/history but invalidate their linguistic stages and mark them stale.
Missing identities become inactive. Never reactivate an old snapshot or transfer
same-text translations to different identities automatically.

## Claims, review and gates

SQLite IMMEDIATE transactions reserve units across stages and commit complete
results atomically. Frozen packets bind snapshot, corpus/contract hash, source SHA,
source revision and target version. Incomplete/duplicate/stale results are rejected.
Saved drafts and immutable accepted-result archives remain available after interruption.

Reviewer eligibility rejects past authors of that unit. Review inputs omit private
writer notes and resolution reasoning. Actual fresh-context creation is supplied and
verified by the agent host; another label cannot establish independence.

Approval records bind source/scope and the policy contract; pilot/runtime/release also
bind current target versions. Configuration, rules, glossary and profile changes
invalidate previous bindings. Preparation mode blocks editing and linguistic claims.
A CLI approval cannot establish that an owner's real decision or a substantive pilot
assessment exists: the orchestrator must retain that evidence.

## Offline issue import

Each JSONL row contains `sid`, `namespace`, `key`, `source_sha`, `source_hash`,
`version`, `current_target`, `category`, `severity`, `comment`, and optional
`suggestion`/`finding_id`. Every binding must match the reviewed live version.
Origin, actual actor, input hash and findings are stored in an event. Duplicate,
stale or concurrently claimed findings fail atomically. Import reopens revision;
new target text invalidates review and affected corpus passes.

## QA and scope

QA checks placeholder multiplicity/case, printf arguments, exact RichText tags,
Unicode, approved glossary forms and nonempty targets. Numbers, lengths, line
breaks, repeated spaces and intentional source copies need appropriate review.
Italian spelling checks run only for configured Italian targets. Add language-
specific rules deliberately; source/target culture and runtime syntax remain explicit.

Classification is a source-derived proposal. JSON can declare kind/wave/group/include;
Unreal key heuristics remain provisional. Reviewed data/overrides.json entries must
match `source_sha`. Serialization order is not dialogue chronology or reachability.

Complete rule views reconstruct all non-provenance glossary/profile fields, including
unknown fields and inherited defaults. Full original provenance remains available
through lookup. Relevant dialogue lookup returns entire linked graph components;
obtaining a reliable game-specific graph is an adapter/research responsibility.

## Candidate and runtime evidence

Candidates require all five offline stages, current gates, complete current targets,
no open issue or unfinished packet and passing QA. Engine-specific builders validate
native identities, source revisions and real artifact readback. JSON candidates are
verified intermediates only. Font character maps do not prove routing or rendering.
Private checkpoints use SQLite backup/integrity checks and retain drafts/history.

Runtime mounting, visible layout, fonts, branches and gameplay still need actual
in-game LQA. Runtime/release approvals are separate; no packaging check supplies them.
