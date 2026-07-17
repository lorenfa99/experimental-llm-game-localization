# Codex-style release QA

## Mission

Perform final release-quality review of every declared source/baseline pair for
`{{PROJECT_NAME}}`.

This is a minimal-diff QA pass, not a fresh translation. Preserve good approved
writing and change only demonstrable semantic, grammatical, consistency,
naturalness, voice, or technical defects.

Work autonomously. Create manifests, plans, checkpoints, correction lists,
validators, reports, and intermediate artifacts required for a resumable audit.

## Before editing

1. inventory and explicitly pair every file;
2. record encoding, BOM, newline style, line count, schema, editable fields,
   opaque fields, pairing confidence, and SHA-256;
3. inspect representative rows of every schema;
4. write a file-by-file plan;
5. implement deterministic validators;
6. run baseline validation and record pre-existing issues.

## Per-file review

For every editable field:

1. compare the source and approved target source-first;
2. review target-language grammar, idiom, collocation, address, agreement,
   voice, rhythm, and internal consistency;
3. review coordinated context such as sequences, title/body pairs, task stages,
   item families, and runtime fragments;
4. retain the baseline when alternatives are equally defensible;
5. write an explicit correction record before mutation;
6. rebuild the output deterministically from the baseline;
7. validate the completed file;
8. update changes, validation, unresolved, and progress reports.

Do not ask for confirmation after each file. Ask only when an ambiguity blocks
a substantial part of the work; otherwise record it and continue.

## Corpus-wide audit

After individual files, review binding terminology and capitalization,
characters/titles, factions, locations, classes, address and player agreement,
repeated source text, recurring UI and item mechanics, calques, subtitle
sequences, books, task chains, and document voice. Automatic searches may
surface evidence but may not decide translations.

## Release gate

- rerun every validator across the complete release;
- verify all frozen inputs and references;
- generate checksums;
- verify the game-specific package independently when applicable;
- report files/rows reviewed, changes by file and category, unresolved items,
  validator results, packaging results, and AI/tool use.

Do not declare completion while an applicable deterministic check fails.
