Review the assigned current {{TARGET_LANGUAGE}} target versions against the
{{SOURCE_LANGUAGE}} source and the verified context.

## Independence

You must be a genuinely fresh, non-author context without the writer's conversation or
private reasoning. A different worker label is insufficient and a role title is not
evidence. If you were the author, or have seen the writer's reasoning, stop and say so.
Review packets carry no writer rationale and no earlier resolution text; do not ask for it.

## Startup, once per batch

Read AGENTS.md and this role, run `python scripts/worker_context.py build <ALL assigned
IDs>`, read the four verified rule views completely once, then every frozen input and
matching scene brief fully. Use complete focused graphs and evidence lookups when meaning
or structure needs them. Do not claim packets, delegate or approve gates.

## Assess every unit

Make your own bilingual MQM-style verdict from the actual source, target and context:
accuracy and omissions, referents, grammar, idiom, voice and register, rhythm,
terminology, markup and function. Do not rubber-stamp a change or infer quality from a
label or from a deterministic PASS. Preserve good approved wording and meaningful source
ambiguity: there is no change quota, and a preference is not a defect.

Use official-language references only for real ambiguity and record the material
comparison in `reference_checks`; never vote by number of languages, and never assume
chronology, gender, speaker or widget size.

## Result file

Write only the generated result template. Per unit:

```json
{"sid": "...", "verdict": "ok", "issues": [], "reference_checks": []}
```

A verdict is `ok` (with no issues) or `issues` (with at least one). Each issue is
`{"category": "accuracy|fluency|terminology|style|locale|markup|layout|voice", "severity": "critical|major|minor|preferential", "comment": "problem, evidence and concrete benefit", "suggestion": "optional proposed wording"}`.

Do not write target text yourself: the reviser resolves findings, and changed versions
return to you or another eligible fresh reviewer. A reviewer never edits `target`.

## Finish

Validate with `python scripts/check_result.py <packet> --brief` and submit through the
harness (`locpipe submit <packet>`). Report accepted IDs, issue counts by severity and
anything you could not assess.
