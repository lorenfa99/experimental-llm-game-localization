# Optional tools

- [repak](https://github.com/trumank/repak), pinned Windows release 0.2.3,
  Apache-2.0 / MIT dual license. `tools.lock.json` records the archive and executable
  SHA-256. The bootstrap retains the upstream license files. No executable is bundled.
- [UnrealLocres](https://github.com/akintos/UnrealLocres), format reference for the
  independently written native reader/writer; no upstream C# code is included.
- [FontTools](https://github.com/fonttools/fonttools), optional 4.53.1 MIT-licensed
  character-map inspection. Runtime rendering and layout remain separate checks.

The core and JSON adapter use Python's standard library. Third-party tools are
obtained only when explicitly requested for an applicable adapter. Game assets,
official text and fonts remain private project inputs under their owners' rights.
