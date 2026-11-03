# Runtime LQA, when requested

Preparation and offline closure never include a playtest or an installation. A successful
build, readback or roundtrip does not prove that a game mounts or uses the overlay.

Start from a candidate verified for the exact installed game build, with
`scripts/candidate_audit.py` evidence. Preserve the current save or profile before any
playtest that changes progress. The owner decides when to install, launch and test; this
workflow does not grant that authorization.

1. Close the game. Verify the baseline and candidate manifests. Install only at the owner's
   request, with `locpipe install <candidate-label>` where the adapter supports it. The
   Unreal adapter refuses existing overlays and changed vanilla files and records a single
   owned file receipt. Other adapters hand the candidate to your own injector.
2. Select the language or carrier the adapter documents (the Unreal adapter overlays the
   configured native-language resource, so the matching in-game option is used; a new menu
   entry is not generated). Record whether the overlay actually mounts. Verify source CRC
   matches, language switching, restart, save/load, and fallback for untranslated or
   non-target engine strings.
3. Check title and menus, options, keyboard and controller prompts, rebinding and key
   legends, HUD, inventory, items, names, effects, tutorials, journals, readables,
   dialogue branches, shops, rewards, death, loading screens and credits.
4. Exercise format arguments, plural and gender contexts, signs and percentages, inline
   images, line breaks, long names and accented capitals. Confirm every configured font
   probe renders in the actual styles, including fallback and dynamic atlas behavior.
5. Test the supported aspect ratios, window and fullscreen and UI scales where practical.
   Record clipping, wrapping, overflow, missing glyphs, truncation and unreadable text.
   Measure actual widget constraints rather than treating character ratios as limits.
6. Save observations as JSONL in `work/lqa/`, one object per issue: `sid`, `severity`
   (`critical`, `major`, `minor`, `preferential`), `comment`, and optional `screenshot` and
   `save` evidence paths. Trace unknown screen text to a native unit first, or classify it as
   a coverage gap; never assign a guessed identity.
7. `locpipe lqa-import work/lqa/<file>.jsonl` records the issues and evidence. Resolve them
   with `locpipe next lqa` (prompts/RUNTIME_FIX.md), re-review the changes, rebuild a new
   candidate and retest the affected screens.
8. Record the owner's runtime acceptance against that exact target revision, then the release
   decision. `locpipe build --mode release --label <new-label>` requires both gates.
9. `locpipe restore <installed-label>` removes only the receipt-owned overlay after its path
   and hash check. An externally altered file is preserved for inspection. Vanilla archives
   are never replaced; do not rely on a launcher's file verification to remove a third-party
   overlay, use the owned receipt.

Install, restore and the format checks have synthetic fixture coverage only. Mount priority,
resource hot-reload, menu behavior and restore behavior in a live game stay unverified until
an authorized playtest.
