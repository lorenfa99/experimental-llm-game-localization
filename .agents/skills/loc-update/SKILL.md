---
name: loc-update
description: Capture a new game build or source file and compare it with the existing localization snapshot without starting translation.
---

# Capture and compare a new source revision

Read AGENTS.md, docs/ADAPTERS.md and docs/WORKFLOW.md. Run `status --brief` and `pending`.
Stop or finish conflicting active work before changing sources, and use a fresh immutable
label with the actual new game root or source file (`update` for Unreal, `import-source`
for the JSON adapter).

Inspect adapter failures rather than forcing assumptions from the previous build:
container formats, encryption, additional archives, localization targets or cultures may
change. Preserve the previous baseline and every old draft. Compare identity,
source-language text and CRC additions, removals and changes; a remap candidate is a
proposal that needs evidence, never an automatic carry-over.

Refresh the context index, reference compatibility, scope, font audit, source QA, binary
roundtrip, pilot proposal and report (`scripts/plan_groups.py` proposes packet families).
Keep preparation-only mode when it is active. Do not translate or approve gates merely
because new material has arrived. Update HANDOFF.md with verified findings and unresolved
work. Do not install or publish anything as part of source intake.
