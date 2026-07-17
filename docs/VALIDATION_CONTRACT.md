# Validation contract

The generic validator checks properties that can be decided deterministically.

## Checked by the core CLI

- source, baseline, and reference fingerprints;
- target existence;
- physical line count;
- delimiter and field count per row;
- IDs and opaque fields;
- locked empty or sentinel cells;
- protected marker sequence;
- numeric token sequence;
- runtime placeholder sequence;
- release encoding, BOM, newline style, and final newline against the baseline.

## Intentionally not checked as universal rules

- translation quality;
- punctuation adjacent to styling markers;
- whether a glossary occurrence is semantically the same word sense;
- maximum UI length without actual rendering data;
- voice, humor, rhythm, rhyme, or naturalness;
- binary package correctness.

Projects should add validators only when the runtime contract is known. A
strict but incorrect validator can damage the localization by forcing English
punctuation or syntax into the target language.

## PASS meaning

`PASS` means that no declared deterministic invariant failed. It does not mean
that the translation is accurate, natural, complete, legally distributable, or
correctly packaged.
