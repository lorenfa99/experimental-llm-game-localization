# Experimental LLM Game Localization

A working, versioned localization harness derived from the **Queen's Domain**
Italian project. An orchestrator runs the linguistic workflow through real agent
contexts; Python preserves identities, freezes assignments and verifies results.

The complete linguistic pipeline can run automatically inside an existing coding
agent environment. Owners set scope, authorization and decision authority. The
harness itself makes no model calls and requires no paid API integration.

## The method

1. **Prepare:** capture immutable source/reference revisions; establish scope,
   complete scene context, style, glossary and character profiles.
2. **Pilot:** translate a representative set, independently review it, resolve
   findings and assess a pilot report before accepting its gate.
3. **Translate:** one writer owns each small frozen packet.
4. **Review and revise:** a genuinely separate bilingual reviewer reports issues;
   the reviser resolves every issue. Every changed version returns to review.
5. **Consistency, then fluency:** separate corpus passes, followed by independent
   rereview of their changes.
6. **Verify an offline candidate:** complete stage/version closure, QA, source-copy,
   roundtrip, artifact readback and applicable font/markup checks.
7. **Runtime LQA and release:** actual in-game testing and owner decisions remain
   distinct from successful offline packaging.

A different worker name is insufficient proof of independence. The host must
create a fresh context without the writer's conversation or private reasoning.

For later corrections, reuse completed work: inspect the findings and real
cross-references, change only justified text, independently rereview it, complete
invalidated stages and run one final complete deterministic verification round.
Two principal linguistic contexts usually suffice for a small maintenance batch.

## What is implemented

- SQLite corpus, source snapshots, target versions, history and approval records;
- transactional claims, one live owner per packet, frozen inputs and saved drafts;
- stage scheduling, stale-input rejection, issues and explicit resolutions;
- version-bound **offline** external-review imports with real provenance;
- lossless complete rule views, focused evidence lookups and complete linked graphs;
- placeholder, markup, Unicode, glossary and configurable-language QA;
- candidate/release prerequisites, local reports and private SQLite-safe checkpoints;
- engine-neutral JSON and Unreal `.locres` / single `.pak` adapters;
- orchestration scripts: bounded batch claims, dispatch/acceptance receipts, stage and
  candidate audits, evidence snapshots and live HANDOFF progress;
- an offline external-review kit (build, parse, independent triage, `issue-import`);
- glossary audit and packet-family planning for bulk work;
- shared agent skills (`loc-run`, `loc-lqa`, `loc-update`) with Claude Code commands.

The agent host supplies model access and actual context isolation. JSON builds are
verified intermediates; injection into a game requires a suitable engine adapter.

## Quick start

Python 3.11+; the core uses the standard library. From a checkout:

```powershell
python -m locpipe doctor
python -m locpipe import-source examples/synthetic/source.json --label synthetic
python -m locpipe status --brief
python -m locpipe pending
python -m locpipe gate list
python -m locpipe plan
```

Preparation mode starts enabled. Establish project-specific rules and actual owner
or delegated decisions before enabling translation and recording approvals.
Start the orchestrator with [the reusable prompt](prompts/ORCHESTRATOR.md).

To create an isolated project:

```powershell
python -m pip install -e .
locpipe init my-localization
locpipe --project my-localization doctor
```

The initializer supplies configuration, rules, role prompts and worker utilities.
Change source/target cultures, identity domain and adapter for your project.
`config.local.toml` holds local settings and stays private.

For a fully scripted **engineering simulation**, without models or game files:

```powershell
python scripts/run_synthetic_demo.py
python -m unittest discover -s tests -v
```

Simulated roles exercise the state machine; they do not certify linguistic quality
or real independent agent contexts.

## Adapters and commands

The JSON adapter accepts lossless, identity-based source exports from any engine.
The Unreal adapter retains native key/namespace hashes and source CRCs, verifies
pak readback and supports receipt-owned overlay installation/restoration when
explicitly authorized. It supports a single unencrypted vanilla pak, not IoStore.
A configured custom adapter can extend the same protocol.

See [workflow and commands](docs/WORKFLOW.md), [orchestration](docs/ORCHESTRATION.md),
[external review](docs/EXTERNAL-REVIEW.md), [runtime LQA](docs/RUNTIME-LQA.md),
[adapter format](docs/ADAPTERS.md), [technical contract](docs/TECHNICAL.md) and
[efficient agent use](docs/EFFICIENCY.md).

## Evidence and origins

[The Queen's Domain case study](docs/CASE_STUDY_QUEENS_DOMAIN.md) records the current
method, owner-recorded Claude/Codex/Gemini tools and aggregate outcomes, and
[`examples/queens-domain`](examples/queens-domain/README.md) shows how that project's
workflow maps onto this repository. Neither contains extracted game text. This repository distributes reusable code, empty project
rules and synthetic fixtures; real corpora, references and checkpoints stay private.

Version **0.3.0** adds the orchestration, external-review and runtime-handoff tooling
on top of the 0.2.0 harness, which replaced the earlier delimited-table toolkit. The old files remain
in Git history. Its `project.toml` and correction format are not compatible with this
versioned database: perform an explicit source intake instead of copying old state.

MIT license for this code and original documentation. Third-party tools and game
material keep their own licenses; see [tool notices](tools/THIRD-PARTY.md).
