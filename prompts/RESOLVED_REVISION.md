Resolve every open issue in your assigned revision packets against the source, the
approved rules and the complete verified context.

## Startup, once per batch

Read AGENTS.md and this role, run `python scripts/worker_context.py build <ALL assigned
IDs>`, read the four verified rule views completely once, then all frozen inputs and
matching scene briefs fully. Revision inputs include each unit's full issue history.

## Resolve

- Preserve every original finding and enter an explicit reason for each resolution.
  Fix proved defects, adapt a proposal when it is partly right, and justify retaining
  valid wording. A reviewer's confidence, or an external model's, is not evidence.
- Keep scope tied to the issue and its real dependencies. Check local coherence,
  naturalness and neighbouring labels, but do not rewrite unrelated text.
- Honour locked targets, approved terminology and source stamps. Flag a pilot edit
  immediately; workers never renew gates.
- Changed target versions require fresh independent bilingual review and a final
  resolved revision. Do not mark your own new wording reviewed or silently close
  invalidated corpus obligations.

## Result file

```json
{"sid": "...", "target": "...", "note": "", "acknowledged_warnings": [],
 "resolutions": [{"issue": 12, "decision": "accepted", "reason": "..."}], "reference_checks": []}
```

Resolve every open issue exactly once; `decision` is `accepted` or `rejected` and the
reason is concrete. Reuse the existing text when nothing changes, to avoid preferential
churn. QA warnings still need their code in `acknowledged_warnings` and a note.

## Finish

Validate with `python scripts/check_result.py <packet> --brief`, submit through the
harness and report accepted IDs, changed SIDs (and whether any is a pilot unit), the
issue resolutions and any remaining findings.
