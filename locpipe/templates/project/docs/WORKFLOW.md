# Workflow and commands

Use `python -m locpipe` from the checkout, or installed `locpipe`. Add
`--project <directory>` before the command for a separate initialized project.

## Preparation

Run `doctor`, then `import-source <source.json> --label <new-label>` for JSON,
or `extract --label <new-label> --game-root <folder>` for Unreal. Intake never
imports a target translation. `update` captures a new Unreal revision; JSON uses
`import-source` with a fresh label. Source changes preserve history and stale targets.

Review `inventory`, `status --brief`, `references <sid>` and source/context evidence.
The proposed pilot is source-only; verify branch coverage. Establish style, glossary
and characters. Resolve actual `[DECIDE]` bullets. Keep official references compatible.

After authorization, set `project.preparation_only=false` before freezing the
linguistic contract and recording gates. Settings changes invalidate approvals.
Record each actual decision using `gate approve <gate> --by <actual-actor> --note
<evidence>`. Required pretranslation gates: source, style, glossary, characters.
The owner can explicitly delegate evidence-based choices; never invent that authority.

## Packet loop

```text
locpipe pending
locpipe next translate --who <actual-writer-context>
locpipe prepare <packet-id>
python scripts/worker_context.py --project <directory> build <packet-id>
# Read the returned complete rules, frozen packet and relevant context.
# Edit only the generated result, preserving all IDs and version bindings.
python scripts/check_result.py <packet-id> --project <directory> --brief
locpipe submit <packet-id>
```

With a separate project, include `--project <directory>` on each locpipe command.
`prepare` preserves saved results and inputs. `submit` validates and commits the
whole packet atomically. Failed results remain drafts. Recover them before new work.
Use `release` or `abandon` only after confirming the owner stopped and recording why.

For many packets, the orchestrator can claim related packets as one bounded batch,
record dispatch and acceptance receipts and audit stage closure with the scripts in
[the orchestration guide](ORCHESTRATION.md). Invoke the shared skills `loc-run`,
`loc-lqa` and `loc-update` (`.agents/skills/`, with `/loc-*` entry points for Claude
Code) to run the pipeline, the owner-requested runtime pass and a later source update.

Claim `review` in a genuinely fresh non-author context, then `revise`. The reviewer
reports issues; the reviser resolves all issues explicitly. A changed version returns
to review and final revision. Worker labels do not establish actual independence.

Complete and assess the pilot report before its gate. Then process configured waves.
After bilingual closure, run `consistency`, then separate `fluency`. Edits from either
pass keep their completed pass marker while requiring current bilingual closure.

## Focused maintenance and external review

For an outside model's second opinion, build a private kit, carry it to the chats by
hand and parse the replies with `scripts/external_review_kit.py` (see
[the external review guide](EXTERNAL-REVIEW.md)). Read external outputs and notes,
verify their exact source/target bindings, then triage them with evidence. Record accept/adapt/reject/unresolved decisions.
Use `issue-import <findings.jsonl> --origin <offline-origin> --by <actual-actor>
--note <provenance>` for validated offline findings. Required fields are documented
in [the technical contract](TECHNICAL.md). It reopens resolution and records actual
provenance; it does not change text or pretend a runtime observation occurred.

Resolve with `revise`, rereview changed versions and complete invalidated consistency
and fluency on affected units. Keep valid work elsewhere. Runtime observations use
`lqa-import` and the `lqa` stage instead. Do not relabel one origin as the other.

## Offline candidate and runtime handoff

Run `qa --source`, `qa --release`, `roundtrip`, applicable `fonts`, a fresh
`build --mode source-copy --label <label>`, then `build --mode candidate --label
<different-label>` and `verify-build <candidate-label>` after stage closure.
Builds refuse missing/stale targets, open issues, unfinished packets or stale gates.
JSON readback verifies an intermediate; Unreal readback verifies the native overlay.

Close the offline scope with `python scripts/candidate_audit.py <candidate-label>
<new-label>`: read-only evidence that stages, gates, QA and the built artifact agree.
Write concise coverage/quality evidence and a targeted runtime test plan. Preserve a
private checkpoint with `python scripts/checkpoint.py <path-inside-project>` from
the project directory. Installation and restoration are explicit owner actions; the runtime procedure is in
[the runtime LQA guide](RUNTIME-LQA.md).
`build --mode release` additionally needs actual runtime/release approvals.
A package check is not a game test.
