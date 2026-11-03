# Example: Queen's Domain, English to Italian

This harness grew out of an English-to-Italian localization of the Unreal Engine game
*Queen's Domain*. This page shows how that run maps onto the repository: which settings,
roles and scripts it used, and what its public record looks like. It is a process
example only. **It contains no game text**: no source strings, translations, official
reference languages, native keys or CRCs, character or glossary content, scene briefs,
private research, checkpoints or worker conversations. Those stay in the owner's private
project.

The [case study](../../docs/CASE_STUDY_QUEENS_DOMAIN.md) records the same run in prose.

## At a glance

| | |
|---|---|
| Game / engine | Queen's Domain / Unreal, one unencrypted vanilla `.pak` with `.locres` resources |
| Direction | English (`en`) to Italian (`it`), with French, Spanish, Portuguese and German as working references |
| Adapter | `unreal` (native key/namespace hashes and source CRCs retained; readback of the built overlay) |
| Scope | 2,272 in-scope units; a 134-unit pilot assessed before bulk work |
| Preparation | Claude Opus 5.5 in Claude Code: source and context research, style guide, glossary, character profiles |
| Translation and quality stages | GPT-6.1 Sol in Codex, managed by an orchestrator: translate, independent bilingual review, resolved revision, consistency, Italian fluency |
| Outside opinion | Twelve manually carried chats with the model the owner recorded as Gemini 4 Argon |
| Owner role | Authorization, binding decisions, delegation limits and gate approvals |

Model names are the owner's record, not a quality claim. Different labels were never
treated as proof of independent contexts.

## How the run maps onto the repository

| What the project did | Where it lives here |
|---|---|
| Captured an immutable source snapshot and indexed context | `locpipe extract` / `import-source`, [adapters](../../docs/ADAPTERS.md) |
| Wrote and froze style, glossary and characters, then recorded owner approvals | `style/`, `glossary/`, `locpipe gate approve`, [decision authority](../../docs/DECISION-AUTHORITY.md) |
| Audited the glossary against the whole corpus before translating | `scripts/glossary_audit.py` |
| Grouped assets into larger scene and item families for packeting | `scripts/plan_groups.py`, `data/overrides.json` |
| Ran a small representative pilot and assessed a bilingual pilot report | `scripts/report_snapshot.py`, `pilot` gate |
| Handed related packets to one worker at a time within byte and count limits | `scripts/claim_batch.py`, `batch_packets`, `batch_max_input_bytes` |
| Recorded who received which packets in a fresh context | `scripts/record_batch.py`, [`receipts.example.jsonl`](receipts.example.jsonl) |
| Kept every changed version going back to independent review | `locpipe next review`, stale-input rejection, [workflow](../../docs/WORKFLOW.md) |
| Checked that every current version has a matching review and revision | `scripts/stage_audit.py` |
| Kept the HANDOFF current across paused sessions | `scripts/save_progress.py` |
| Asked an outside model for a second opinion, offline | `scripts/external_review_kit.py`, [external review](../../docs/EXTERNAL-REVIEW.md) |
| Triaged that opinion in a fresh context and imported only accepted findings | `triage.json`, `accepted`, `locpipe issue-import` |
| Closed the offline scope with source-copy, roundtrip, pak readback, font and markup checks | `scripts/candidate_audit.py`, `locpipe build`, `locpipe verify-build` |
| Prepared (but did not perform) in-game testing | [runtime LQA](../../docs/RUNTIME-LQA.md), `lqa` stage |
| Ran the whole thing as a repeatable agent routine | `.agents/skills/loc-run`, `loc-lqa`, `loc-update` and the `/loc-*` commands |

## Settings

[`config.example.toml`](config.example.toml) is the project's configuration with paths,
process names and game-specific scene families replaced by placeholders. The numbers
that mattered in practice: packets of at most 40 units / 1,100 source words with eight
units of context before and four after; at most three packets per batch; and a 180 KB
cap on the frozen input handed to one worker so that rules, packets and scene briefs are
always read in full rather than clipped.

## What the receipts look like

[`receipts.example.jsonl`](receipts.example.jsonl) was produced by running the real
`record_receipt` code on the invented project in [`../synthetic`](../synthetic): a
translate acceptance, a fresh-context review dispatch and a review acceptance. The
identities in it are the synthetic units' own and the text is not stored. The real run's
receipts are private because they list real identities. Their shape is identical.

Each dispatch line is an attestation by the orchestrator that it gave a named context
exactly these packets, created with `fork_turns=none`. The harness cannot verify that.
`stage_audit` only checks that the receipts and the corpus records agree.

## The external-review pass, in aggregate

After the pipeline had closed, the owner carried a private bilingual kit through twelve
chats and pasted the replies back as text. An orchestrator parsed them against the exact
unit versions, and a separate fresh context triaged each row against current source,
rules and context.

| | |
|---|---|
| Structured proposals | 28 |
| Deduplicated free-text notes | 21 |
| Accepted | 3 targeted corrections |
| Rejected, with evidence | 25 proposals |
| Re-review | the 3 changed versions went through independent bilingual rereview, resolved revision and local consistency/fluency |
| Retained | all unaffected work, with its receipts |

A majority of models, or a model's confidence, was never treated as evidence.

## Evidence boundaries

The candidate completed offline QA, native identity and CRC checks, source-copy and
roundtrip checks, actual pak readback and applicable font and markup checks. Runtime
and release approvals remained pending at offline closure: a built and verified overlay
does not show that the game mounts it, and font character-map coverage does not show how
the text renders. The public beta of the Italian patch is a separate decision from those
harness gates. The
[public mod repository](https://github.com/lorenfa99/queens-domain-traduzione-italiana)
credits the tools and methodology.

## Using this as a starting point

1. Create a project with `locpipe init`, set the cultures, identity domain and adapter,
   and import your own source.
2. Write style, glossary and characters first, audit them, and have the owner approve
   them. Nothing is translated before that.
3. Run a pilot and assess it. Only then open the full scope, with
   `project.preparation_only = false`.
4. Let an orchestrator run [`loc-run`](../../.agents/skills/loc-run/SKILL.md). Insist on
   genuinely fresh review contexts; if your host cannot provide them, say so.
5. If you want an outside opinion, treat it as untrusted text and triage it independently.
6. Keep installation, game launch and publication as explicit owner decisions.

If you adapt this for a language written without spaces, read the glossary-boundary
limitation in the [roadmap](../../ROADMAP.md) first.
