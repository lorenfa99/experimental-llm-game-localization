# Independent translation stage

Create one independent premium `{{TARGET_LANGUAGE}}` translation of
`{{SOURCE_FILE}}` using profile `{{PROFILE}}`.

Read only:

- the source;
- project governance;
- the binding glossary and references;
- the file manifest and schema notes.

Do not read another target-language candidate.

## Profiles

- `balanced`: strongest overall faithful and natural solution;
- `semantic`: finest distinctions of agent, modality, aspect, uncertainty,
  intensity, and gameplay function;
- `natural`: idiomatic information order, collocation, oral rhythm, and concise
  interface writing;
- `voice`: character, faction, authorial, ritual, humorous, and rhetorical
  identity;
- `conservative`: lowest-risk solution among equally strong alternatives.

A profile is only a tie-breaker among solutions that already satisfy shared
rules.

## Preparation

Confirm the schema, editable fields, active scope, row identity, locked values,
protected markers, and coordinated contexts. Split deterministically:

- dialogue, task, UI, subtitle, and general strings: small physical-row blocks;
- books/documents: one complete document row per block;
- items: a small number of complete item-family rows per block.

Never split one physical row or coordinated field family.

## First sweep

Process every block in manifest order. Read the current source block first and
adjacent source blocks as read-only context. Reconstruct every editable field,
including its gameplay function, voice, register, rhetoric, and relationship
to sequences, title/body pairs, task stages, item variants, or runtime
fragments. Write and validate the block before continuing.

For medium-risk wording, compare at least two internal strategies. For idiom,
humor, insult, metaphor, ritual language, wordplay, repetition, ambiguity, or
marked rhythm, compare at least three, including functional recreation when
literal transfer fails. Do not output rejected alternatives.

## Mandatory second sweep

Assemble the complete candidate, build cross-block indexes, and review every
block again against the source. Search for omissions, additions, altered
modality/aspect/intensity, calques, weak collocations, translated syntax, voice
drift, broken humor/rhythm, inconsistent formulas, weak item mechanics, broken
sequences, placeholder damage, and cross-file terminology drift.

Revalidate every changed block and the assembled file.

## Output

Return only the complete candidate file and one concise QA confirmation.
