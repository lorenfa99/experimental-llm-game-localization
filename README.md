# Experimental LLM Game Localization

A source-first, human-reviewed, structure-safe workflow for experimenting with
LLM-assisted video-game localization.

This project automates the engineering around localization: corpus inventory,
schema declaration, immutable baselines, explicit correction lists,
deterministic validation, consistency indexes, checksums, and release evidence.
It does **not** claim that unattended LLM output is release-ready.

## Why this exists

Large game localizations fail in two different ways:

1. the language can be inaccurate, literal, flat, or inconsistent;
2. the file can be structurally invalid even when the prose sounds good.

The workflow treats these as separate problems. An LLM or human editor makes
linguistic decisions. Deterministic tools preserve and verify the data.

The approach was distilled from a complete Italian localization project that
combined two phases:

- a Web workflow with independent candidates, adjudication, and two revisions;
- a Codex workflow with per-file source-first review, explicit corrections,
  corpus-wide audits, packaging, and verification of the shipped game asset.

## Three supported workflows

### Greenfield localization

Use independent translations, adjudication, an expansive editorial revision,
and an isolated final revision. Freeze the resulting file as the approved
baseline, then run the release-QA workflow.

### Existing translation

Skip candidate generation. Treat the existing translation as an approved
baseline and perform a minimal-diff final QA: source-first semantic review,
target-language quality review, explicit corrections, structural validation,
and corpus-wide consistency checks.

### Hybrid

Generate or improve selected high-risk material with the editorial pipeline,
then switch to the conservative release-QA workflow once a baseline is
approved. Do not mix expansive rewriting and final minimal-diff QA silently.

## Quick start

Requirements: Python 3.11 or newer. The core CLI uses only the standard
library.

```powershell
python -m pip install -e .
locpipe init my-localization
locpipe inventory my-localization/project.toml
locpipe validate my-localization/project.toml --mode baseline
locpipe apply my-localization/project.toml my-localization/work/CORRECTIONS.jsonl
locpipe validate my-localization/project.toml --mode release
locpipe index my-localization/project.toml
locpipe checksums my-localization/project.toml
```

A synthetic, copyright-safe example is available under
[`examples/synthetic`](examples/synthetic).

## Repository map

- `src/locpipe/`: deterministic CLI and reusable Python library.
- `prompts/`: provider-neutral prompt templates for the editorial stages.
- `docs/`: methodology, porting guide, validation contract, and lessons learned.
- `case-studies/dread-delusion/`: methodology and historical prompts only; no
  extracted game text or proprietary game assets.
- `examples/synthetic/`: small synthetic delimited-text project.
- `tests/`: standard-library unit tests.

## Core invariants

- Source files and approved baselines are immutable.
- Each file pair declares its own schema and editable fields.
- Non-translatable fields remain unchanged.
- Line count, row order, IDs, delimiters, markers, placeholders, numbers,
  encoding, BOM, newline style, and final-newline state are validated.
- Linguistic corrections are authored explicitly; scripts never invent prose.
- Baseline failures are recorded before editorial changes begin.
- A release is not complete until the packaged artifact is independently read
  back and checked by a game-specific adapter.

## Important limits

The included CLI currently targets delimited text tables. Extraction from and
injection into Unity, Unreal, proprietary archives, databases, or binary asset
formats requires a game-specific adapter. Those adapters must be developed and
distributed only when legally permitted.

Do not commit copyrighted game text, extracted assets, encryption keys,
credentials, or commercial binaries to a public repository. This toolkit does
not grant permission to translate or redistribute any game.

## AI transparency

The methodology supports manual use of ChatGPT, Codex, or another language
model, but ships no provider integration and sends no data to an external API.
Automation ends at orchestration and validation unless a user deliberately
adds a provider adapter.

## Status

Experimental. The design is intentionally conservative: a validator PASS
proves structural compliance, not linguistic quality.

## License

Code and original documentation are released under the MIT License. Game
content, third-party tools, and external model services are not covered.
