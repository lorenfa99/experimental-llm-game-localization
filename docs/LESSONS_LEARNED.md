# Lessons learned from a full localization

## What mattered more than prompt size

The strongest improvement came from combining editorial reasoning with a
resume-safe engineering process. Long prompts helped define the standard, but
they did not replace inventory, explicit schemas, per-file checkpoints,
correction ledgers, validators, and targeted re-audits.

## Practical lessons

### A technical PASS is not a language PASS

A file can preserve every marker and still contain wrong referents, false
friends, calques, weak rhythm, or unusable item descriptions. Structural and
linguistic review must be reported separately.

### Validate the baseline before editing

Pre-existing delimiter defects and malformed rows must be distinguished from
new regressions. Otherwise the reviewer either hides source defects or is blamed
for them later.

### Never infer one schema for a corpus

Dialogue, items, books, tasks, endings, subtitles, and UI strings can share a
file extension while using different editable columns and row identities.
Header names are not always trustworthy. Record the decision per pair.

### Rebuild from the baseline

Applying a reviewed correction list to the immutable baseline is safer than
editing the release repeatedly. It detects stale old text, duplicate decisions,
wrong row IDs, wrong fields, and accidental no-op changes.

### Search tools should surface, not decide

Regex searches are excellent for finding false friends, suspicious phrases,
address forms, capitalization drift, and repeated source text. Most hits are
contextually valid. Automatic replacement turns a useful detector into a source
of regressions.

### Exact repeats need one decision, except when context differs

The same English line may legitimately differ by speaker, gender, UI function,
or word sense. Long exact duplicate passages usually benefit from harmonization;
short formulas require contextual adjudication.

### Sequences are larger than rows

Numbered subtitles, title/body pairs, task stages, composable runtime fragments,
item variants, and multi-line jokes must be reviewed as units. A good isolated
line can break the complete sequence.

### Runtime markers have semantics, not aesthetics

If a marker changes color only, preserve its delimiter sequence and payload
relationship while allowing natural apostrophes and punctuation. Validators
must encode the actual runtime contract rather than blindly mirror English
typography.

### Items and books deserve specialized sweeps

Item descriptions often hide referent, effect, variant, and UI-length problems.
Books require continuity of authorial voice, paragraph flow, verse, rhyme, and
title/body relationships. Generic dialogue review misses both.

### Naturalness requires a dedicated adversarial pass

Grammatical translations can still smell translated. A source-trigger and
target-trigger audit is useful when every candidate is manually adjudicated and
the reviewer is willing to retain valid hits.

### Show coordinated text before final replacement

For cinematic subtitles, poetry, and other rhythm-sensitive sequences, present
the complete proposed passage before applying the final rewrite. Rhythm cannot
be approved one line at a time.

### Release metadata must move with release content

When replacing an existing release in place, update the repository, checksums,
downloadable assets, and the Git tag that generates automatic source archives.
Then download the public artifacts and compare them with the local build.

## What should remain game-specific

- legal permission and distribution policy;
- extraction and packaging adapters;
- glossary, capitalization, address, gender, and voice rules;
- marker and placeholder semantics;
- file schemas and active scopes;
- font replacement and rendering constraints;
- what counts as debug-only or non-shipping content.
