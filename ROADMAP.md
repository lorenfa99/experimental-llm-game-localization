# Scope and next steps

Implemented: versioned source/target state, immutable snapshots, frozen packet
ownership, stage and gate checks, complete rule views, source-bound offline findings,
JSON/Unreal adapters, project initialization and synthetic regression coverage.

Future work can add dedicated Unity/gettext/table adapters, format-specific syntax
rules, improved parser coverage and host integrations with actual context receipts.
Model dispatch currently belongs to the agent environment. The CLI cannot prove
that two labels correspond to independent model contexts or that runtime was tested.

Known limitation: QA matches glossary target forms on word boundaries. For scripts
written without spaces (Chinese, Japanese), a target form adjacent to other characters
is not detected; a script-aware matcher is future work.

Keep future adapters source-first, resumable, lossless and independently verifiable.
Do not extend format support by treating unfamiliar binary assets as plain strings.
