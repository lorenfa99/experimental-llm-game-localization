# Roadmap

The first version intentionally focuses on reliable delimited-text workflows.

## Near term

- config validation with clearer line-specific TOML errors;
- CSV/TSV quoting-aware adapter;
- JSON object-path adapter;
- gettext PO adapter;
- configurable project-specific validator plugins;
- block manifests and export/import helpers for editorial sessions;
- glossary and capitalization candidate indexes;
- HTML summary report that contains no proprietary text by default.

## Game-specific adapter examples

- generic Unity TextAsset adapter interface;
- Unreal localization resource adapter interface;
- package verification protocol with independent read-back;
- optional screenshot/render checks for UI length and font coverage.

## Optional model orchestration

Provider adapters may be explored later, but only behind explicit user action,
local credential handling, redaction controls, reproducible request manifests,
and mandatory human review. The core project will remain usable without any
external API.
