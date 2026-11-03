# Offline external review

An outside model can add a second opinion after the internal pipeline has finished. This
toolkit never calls one: it builds a private kit you carry to a chat by hand (for example
a model in AI Studio), and it receives the reply as untrusted text. Every proposal is then
judged in a separate fresh context and enters the project only through `issue-import`.
Nothing the outside reviewer says is applied to a target automatically.

```text
build  ->  (manual chats)  ->  parse  ->  triage by a fresh context  ->  accepted  ->  issue-import  ->  revise
```

## 1. Build the kit

```text
python scripts/external_review_kit.py build <kit-label> --chats 12 \
    [--context-dir scenes/] [--graphs work/research/dialogue/graphs.json] \
    [--attachment-suffix .txt] [--expect-units N --expect-words N]
```

The command refuses unless every in-scope unit is translated, reviewed and not stale, no
packet is live and no issue is open, so the reviewer sees a settled corpus. It writes
`work/external-review/<kit-label>/` and a verified `.zip`:

- `RULES` - the complete approved style guide, glossary, character profiles and reference
  policy (the same verified rule views the workers read), identical for every chat;
- `PROMPT` - an English review prompt, specifying the coverage report and the JSONL
  finding format;
- `CHATS/CHAT-NN/` - `COMPARE` (source and target pairs in safe code fences),
  `DATA.jsonl` (exact identities, versions and text), `REFERENCES.jsonl` (only compatible
  official-language versions), `CONTEXT` and `START` (prompt plus the assignment);
- `INDEX.md`, `README.md` and `MANIFEST.json` with hashes, the contract and corpus hashes,
  and per-chat SIDs. Every unit appears in exactly one chat; the build proves it.

Chats are contiguous and word-balanced. Units that share a group, namespace and key stem
(`item_name` / `item_desc`) always stay together. `CONTEXT` carries unit `context` notes
and indexed evidence, any scene briefs in `--context-dir` that cite the chat's SIDs
(`index.md` is always included) and, with `--graphs`, the complete linked dialogue
components for those SIDs (the file must match the active snapshot). The prompt tells the
reviewer that none of this proves chronology, reachability or widget size.

The kit is private, game-derived data. Keep it out of public repositories and note in the
HANDOFF that it was transported by hand. It contains no private worker conversations.

## 2. Run the chats

Follow the kit's `README.md`. Save each reply as `CHAT-NN-<anything>.txt`. If a model says it
could not read an attachment completely, believe it: coverage is what it reports, not what
the prompt asked for. Ask it to continue in the same chat.

## 3. Parse the replies

```text
python scripts/external_review_kit.py parse <kit-label> answers/ --label r1
```

The parser reads one JSON object per line. A finding becomes a candidate only if its SID
is in that chat, the unit has not changed since the kit was built, `version` and
`current_target` echo the kit exactly, category and severity are valid, a comment is
present, a suggestion differs from the current target and it is not a duplicate. Everything
else is kept, with the reason, in `rejected-inputs.json` so a human can salvage it.
`PARSE.json` lists chats that returned nothing. The output directory holds
`candidates.jsonl` (already shaped for `issue-import`) and `triage.json`.

## 4. Triage in a fresh context

A genuinely independent context (not the reviewer, and not the writer or reviser of the
text) reads `triage.json` against the current source, rules and context, and sets, for
every row, `decision` to `accepted`, `adapted` or `rejected` with a concrete `reason`. An
adapted row also gets `adapted_suggestion` and/or `adapted_comment`. A model's confidence,
or a majority of models, is not evidence; keep valid wording and record real uncertainty.

## 5. Export and import

```text
python scripts/external_review_kit.py accepted <results-dir>/triage.json
locpipe issue-import <results-dir>/accepted.jsonl --origin <short-id> --by <actual importer> --note <provenance>
```

`accepted` refuses an undecided row, a missing reason, or an `adapted` row with no
replacement, and drops (and counts) rows whose unit changed since the triage. Its output is
aggregate only. `issue-import` records offline issues and reopens only the revise stage;
the ordinary revise, fresh rereview, consistency and fluency path then applies to the
changed versions, and one final complete QA round closes the maintenance.

## What the Queen's Domain run did

Twelve chats produced 28 structured proposals and 21 deduplicated notes. After triage three
targeted corrections were accepted and 25 proposals rejected with evidence. See
[the public example](https://github.com/lorenfa99/experimental-llm-game-localization/tree/main/examples/queens-domain)
for the aggregate record.
