# Localization project rules

These rules apply when an agent uses this repository to prepare a localization.

## Authority

1. File structure and runtime data.
2. Source-language meaning and gameplay function.
3. Project glossary and binding references.
4. Established target-language naming and voice.
5. Natural target-language writing.

## Input safety

- Never edit source files, approved baselines, or binding references.
- Work only in `work/`, `reports/`, and `release/`.
- Freeze source, baseline, and reference hashes before editing.
- Do not commit proprietary project inputs or release packages.

## Editorial policy

- Scripts may surface candidates and apply explicit corrections; they must not
  invent translations.
- Review every translatable field source-first and then as target-language
  writing.
- Use minimal-diff judgment during final QA. Preserve a good approved line when
  no demonstrable problem exists.
- Do not use blind global lexical replacements.
- Review repeated strings, connected sequences, runtime fragments, item
  families, titles and bodies, and long documents in their coordinated context.
- Record uncertainty rather than guessing when a schema or source meaning is
  genuinely ambiguous.

## Structural policy

- Declare the schema and editable fields separately for every pair.
- Preserve row order, IDs, delimiter count, opaque fields, protected marker
  sequence, placeholders, numbers, encoding, BOM, newline style, and final
  newline.
- Formatting markers may permit natural target-language punctuation around
  them. Validate runtime semantics, not accidental source typography.
- Rebuild release files from the immutable baseline and a reviewed correction
  list.

## Completion

A localization is complete only when all declared pairs pass release
validation, inputs remain unchanged, changes and unresolved items are recorded,
corpus-wide consistency has been reviewed, checksums exist, and any packaged
game artifact has been independently verified.
