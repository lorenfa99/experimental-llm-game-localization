# Methodology

## The central separation

Language judgment and file mutation are different jobs.

The editorial layer reconstructs meaning, voice, rhythm, humor, gameplay
function, and natural target-language phrasing. The deterministic layer knows
nothing about good prose: it inventories, extracts, applies explicit decisions,
checks invariants, records evidence, and creates checksums.

Combining both jobs in an unrestricted text-generation step makes failures hard
to detect and impossible to reproduce.

## Pipeline A: greenfield editorial generation

1. Define source authority, glossary, language rules, voice rules, schemas, and
   protected runtime syntax.
2. Create multiple independent translations only when the expected quality
   gain justifies their cost.
3. Adjudicate source-first. Reject invalid candidates before comparing style;
   majority agreement is not evidence.
4. Run an expansive revision that may rewrite weak but grammatical language.
5. Run an isolated final revision that sees the source and the latest candidate,
   not the complete history.
6. Freeze the accepted result as an approved baseline.

## Pipeline B: release QA for an existing baseline

1. Inventory every file and pair it explicitly.
2. Record encoding, BOM, newline convention, line count, field shapes, editable
   fields, pairing confidence, and SHA-256 fingerprints.
3. Inspect one or more representative rows from every schema.
4. Run baseline validation and record pre-existing failures.
5. Review each field twice:
   - semantic sweep against the source;
   - target-language sweep for grammar, idiom, voice, rhythm, and consistency.
6. Author an explicit correction record with old text, new text, category, and
   reason.
7. Rebuild the release file from the immutable baseline and correction list.
8. Validate the completed file before moving to the next one.
9. Run corpus-wide indexes and human audits for terminology, repeated text,
   character and faction voice, UI formulas, and high-risk calques.
10. Revalidate the whole release, verify frozen inputs, and generate checksums.

## Why the two editing policies differ

Greenfield generation uses status-quo neutrality: no candidate is protected
merely because it already exists. Final QA uses minimal-diff judgment: once a
baseline is approved, a valid line is retained unless a concrete defect exists.

Confusing these stages causes either editorial inertia or needless churn.

## Packaging is a separate adapter

Text validation cannot prove that a Unity asset, Unreal archive, database, or
other package contains the intended data. A game-specific packager should:

1. consume only validated release files;
2. write a new package without modifying the pristine base in place;
3. read the generated package back independently;
4. compare every inserted text resource and auxiliary asset;
5. create a backup and checksum;
6. verify the installed copy when installation is part of the workflow.

The generic toolkit deliberately does not pretend that one packer can support
all games.
