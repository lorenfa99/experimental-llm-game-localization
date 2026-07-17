# Game-specific packaging and verification

The loose release files have already passed deterministic validation. Do not
perform linguistic editing in this stage.

## Required adapter behavior

1. Identify the exact pristine package and supported game build.
2. Work on a copy and create a recoverable backup.
3. Inject only declared, validated release resources.
4. Preserve all unrelated package objects and metadata.
5. Read the generated package with an independent verification path.
6. Compare every inserted text resource byte for byte after extraction or
   canonical decoding.
7. Verify fonts, atlases, textures, or auxiliary resources separately.
8. Install only after pre-install verification passes.
9. Read back the installed package when installation is automated.
10. Generate checksums and record tool/library notices.

## Failure policy

Never replace the installed game file when package generation or verification
fails. Report the exact resource and mismatch. Do not hide unsupported game
versions or silently continue with a partial package.
