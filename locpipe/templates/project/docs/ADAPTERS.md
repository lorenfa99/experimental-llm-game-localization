# Engine adapters

## Engine-neutral JSON

Set `[adapter] type="json"` and the actual `game.localization_target` identity domain,
`project.source_culture` and `project.target_culture`. `import-source` accepts UTF-8
objects like [the synthetic source](../examples/synthetic/source.json):

```json
{"schema":"locpipe.source.v1","localization_target":"Game","source_culture":"en","units":[{"namespace":"UI","key":"confirm","source":"Confirm {Key}","kind":"ui","wave":"ui","group":"menu"}]}
```

Namespace/key identities must be unique; identical text can occur in different units.
Optional unit fields: unsigned 32-bit `source_hash`, string kind/wave/group/context,
boolean include and `references`. Without a native source_hash, UTF-8 CRC32 is used
as a revision checksum; the separate source SHA-256 still binds exact text.
References map culture to `{text, source_hash}`; the reference's real revision is
required, so incompatible versions stay visible rather than being silently trusted.
Raw sources contain no target field; existing translations enter separately with
explicit version/source bindings. Other opaque JSON fields are retained in candidates.

JSON capture works offline, preserves raw source bytes and performs a semantic
roundtrip. A source-copy build is byte-identical. A candidate adds target values and
target culture, preserves excluded source copies and verifies its file readback.
It is an intermediate for a game's extractor/injector, not an installed game patch.
The adapter refuses install/restore and reports font checks as unsupported.

## Unreal `.locres` / `.pak`

Set adapter.type to unreal. Configure game.project_dir, localization_target,
pak_relative, root, optional steam_install_dir and actual executable process_names.
Configure source culture, native overlay slot, output filename and pak settings.
Local paths belong in ignored config.local.toml.

The native reader/writer supports legacy locres and versions 1-3, retains namespace/
key hashes and source CRCs, bounds input parsing and supports Unicode/surrogate pairs.
The packer supports one unencrypted vanilla `.pak`; it refuses IoStore, existing
patch overlays and unresolved multi-pak precedence. It never bypasses encryption.

Repak is a separately obtained pinned external tool. The Windows bootstrap verifies
archive/executable hashes; other platforms configure a matching local executable.
FontTools is optional for character-map inspection. These dependencies are unnecessary
for engine-neutral JSON use and are not bundled as executables or game assets.

The overlay replaces the configured native-language resource; adding a new culture
or language menu is not implemented generically. Candidate readback is separate from
runtime behavior. Owner-requested install/restore uses exact baseline/overlay hashes,
configured process checks and a receipt-owned destination, preserving foreign files.

## Custom adapters

Set type="custom" and module="your_package.localization_adapter" for explicitly
trusted local Python code. The module must declare INPUT_MODE as source-file or
game-root and implement callable doctor, capture, index_context, roundtrip, build,
verify, fonts, discover, install and restore functions. Signatures match the two
built-ins. A source-file capture receives `(cfg, db, label, input_path)`; game-root
capture receives `(cfg, db, label, game_root_override)`.

A custom adapter may also define `audit_candidate(cfg, db, build)`, called by
`scripts/candidate_audit.py` after the harness checks. It reads the built artifact and
returns a JSON-serializable mapping that is recorded verbatim as `artifact_content`;
include a boolean `artifact_matches_corpus`. It must not mutate the project and should
raise HarnessError when the artifact disagrees with the corpus. Without the hook the
audit records `artifact_matches_corpus: null` and says the artifact was not compared,
rather than guessing.

Reuse extract.import_snapshot and build.preflight to preserve identity/version and
quality invariants. Never silently import target text or waive a core stage. Unsupported
operations must raise HarnessError. Capture must validate before mutation, preserve
immutable inputs and document source-revision semantics. Build must preserve opaque
data and independently read the real artifact back. Installation must remain an
explicit owner action with engine-specific ownership and process safeguards.
