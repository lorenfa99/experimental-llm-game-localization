# Porting the workflow to another game

## 1. Establish permission and scope

Identify what may be extracted, translated, modified, and redistributed. Keep
proprietary inputs in ignored local directories.

## 2. Extract to stable intermediate files

Prefer a lossless text or table representation with stable row identities. Keep
the extractor and packer separate from linguistic tooling.

## 3. Describe each file pair

Create a `project.toml` entry for every source/baseline pair. Declare:

- delimiter;
- ID field;
- editable field indexes and labels;
- opaque-field reference (`source` or `baseline`);
- pairing confidence;
- protected markers and locked sentinel values.

Do not guess an ambiguous schema. Record it as unresolved.

## 4. Freeze and validate

Run `locpipe inventory`, inspect `work/MANIFEST.tsv`, then run baseline
validation. Keep the report even if the baseline fails.

## 5. Choose an editorial path

- No usable translation: use the independent-candidate prompts.
- Good existing translation: use the final-QA prompt and minimal diffs.
- Mixed corpus: classify files and use the appropriate path per file.

## 6. Record decisions

Store linguistic changes as JSON Lines. A basic record is:

```json
{"pair":"dialogue","line":42,"id":"npc_0042","field":1,"old":"Vecchio testo","new":"Nuovo testo","category":"naturalness","reason":"Remove an English-shaped construction without changing tone."}
```

The tool rejects wrong IDs, fields, old text, duplicate keys, and no-op changes.

## 7. Apply and validate continuously

Apply one reviewed file or batch at a time. Never wait until the entire corpus
is edited before discovering an encoding or schema problem.

## 8. Audit the corpus

Use `locpipe index` as evidence for manual consistency review. Add project-
specific detectors for address forms, player agreement, classes, factions,
locations, UI terminology, false friends, and repeated mechanics.

## 9. Package and read back

Implement a game-specific adapter. Verify the generated package independently,
not only the loose intermediate files.

## 10. Publish reproducibly

Ship installation instructions, checksums, tool notices, AI-use disclosure,
known limitations, and a clear statement of what was reviewed by a human.
