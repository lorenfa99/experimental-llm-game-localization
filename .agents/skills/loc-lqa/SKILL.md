---
name: loc-lqa
description: Prepare and track an owner-requested runtime localization playtest from a verified candidate build, with issue evidence and owned-overlay restore receipts.
---

# Runtime localization QA

Read AGENTS.md, docs/RUNTIME-LQA.md, docs/ADAPTERS.md and the current build and status
manifests. Preparation-only mode blocks translated candidates and installation. Running an
audit or report command never authorizes a playtest or an install.

Prepare the concrete candidate, its QA evidence and its binary verification first
(`scripts/candidate_audit.py` records closure, artifact content, format probes, printable
scalars and font coverage). Install only when the owner has requested that live action and
the adapter supports it. Keep a copy of the save or profile before any test that changes
progress.

Keep source, build and revision evidence. Trace every observed text to an actual SID, or
classify it as a coverage gap rather than guessing an identity. Import observations with
`lqa-import`, resolve them through the harness, re-review changed text and retest a fresh
candidate. Use prompts/RUNTIME_FIX.md for focused wording corrections.

Do not describe character-map font coverage or a readable archive as proof of runtime
rendering, routing, fallback or mounting. Restore only through the owned receipt with its
exact path and hash checks, and preserve an externally altered overlay for inspection.
Record the runtime and release gates only after the owner's actual acceptance of the final
target revision.
