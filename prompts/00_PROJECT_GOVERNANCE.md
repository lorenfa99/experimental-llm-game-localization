# Project governance template

You are localizing `{{GAME_NAME}}` from `{{SOURCE_LANGUAGE}}` into
`{{TARGET_LANGUAGE}}`.

## Mission

Produce natural, accurate, release-ready target-language writing while
preserving gameplay function, source-supported voice, and every declared
technical invariant.

## Authority order

1. Exact runtime structure and gameplay data.
2. Source meaning, function, relationship, and rhetoric.
3. `{{BINDING_GLOSSARY}}` and project-specific terminology rules.
4. Established cross-file naming and voice.
5. Natural target-language judgment.

Do not override a higher authority for elegance.

## Source and baseline

- Source files are the semantic authority.
- Approved target files are the baseline during final QA, not semantic proof.
- Never edit input or reference files.
- Do not assume all files use one schema or one translation column.

## Language rules

Insert binding rules for:

- forms of address;
- player number and gender;
- narrator/system voice;
- character and faction registers;
- profanity and intensity;
- class, title, item, location, skill, and UI capitalization;
- subtitle rhythm, book/document style, and item-description conventions.

## Meaning model

Preserve speaker, addressee, agent, action/state, object, recipient,
motivation, cause, purpose, modality, certainty, aspect, intensity, gameplay
effect, hesitation, irony, affection, contempt, threat, humor, metaphor,
repetition, and wordplay.

Do not invent explanations, gestures, motivations, threats, subjects, or
conclusions. Do not delete meaningful uncertainty, repetition, vulgarity,
economic motivation, or practical gameplay information.

## Structural contract

Use the supplied manifest. Preserve:

- physical line count and row order;
- IDs and declared opaque fields;
- delimiter count and empty fields;
- protected marker sequence and runtime segment relationships;
- placeholders, control tokens, numbers, percentages, and modifiers;
- encoding, BOM, newline convention, and final-newline state.

Formatting markers may allow natural target-language punctuation around their
boundaries. Enforce actual runtime semantics, not accidental source typography.

## Tool policy

Deterministic scripts may inventory, extract, split, apply explicit decisions,
validate, index, report, and checksum. They must not invent linguistic
corrections or perform blind lexical replacement.
