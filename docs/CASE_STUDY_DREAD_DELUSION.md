# Case study: Dread Delusion Italian localization

This case study records methodology and aggregate evidence only. It contains no
extracted game script or packaged game asset.

## Two-phase workflow

The first phase used GPT-5.6-sol at high reasoning in a Web interface:

- five independent translation profiles;
- source-first adjudication rather than majority voting;
- expansive R1 revision;
- isolated R2 final revision;
- block assembly and technical checks.

The second phase used GPT-5.6-sol at xhigh reasoning in Codex:

- explicit inventory and pairing of every file;
- per-schema inspection and baseline validation;
- source-first and Italian-quality sweeps for every translatable field;
- deterministic correction lists and per-file release regeneration;
- specialized audits for items, general data, books, tasks, endings, and each
  major dialogue group;
- corpus-wide glossary, naming, address, gender, repeat, UI, and calque audits;
- binary asset reconstruction and independent read-back verification;
- GitHub source, tag, release asset, and checksum synchronization.

## Final scale

- 20 paired files;
- 12,041 physical rows reviewed;
- 983 linguistic fields corrected in final QA;
- 163 structural row repairs documented;
- 20/20 loose release files passed;
- 21/21 resources inside the packaged asset passed read-back verification.

One debug-only file received structural validation rather than a full linguistic
review. No machine-translation library, external translation service, or
external LLM API was used; linguistic decisions were made interactively, while
scripts handled deterministic operations.

## Most transferable result

The Web prompts produced a strong editorial baseline. The Codex phase made the
work release-ready by adding resumability, traceability, explicit schema
decisions, minimal-diff adjudication, targeted re-audits, whole-corpus evidence,
and verification of the actual downloadable artifact.
