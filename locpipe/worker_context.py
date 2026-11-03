"""Reusable, contract-bound worker rules without repeated research provenance.

All glossary entries and character profiles remain present. Every non-provenance
field is preserved, including unknown fields, rationale, notes and examples.
The complete original records remain available for focused evidence lookups.
This module never changes the corpus, canonical rules, approvals or packet files.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path

from .config import Config, HarnessError, digest, file_hash

FORMAT = "locpipe-worker-rules-v1"
INPUTS = {
    "glossary/glossary.json": "canonical/glossary.json",
    "style/characters.json": "canonical/characters.json",
    "style/style-guide.md": "style-guide.md",
    "docs/MULTILINGUAL-REFERENCES.md": "reference-policy.md",
}
OUTPUTS = set(INPUTS.values()) | {"glossary.rules.json", "characters.rules.json"}
PROVENANCE = {"evidence", "merged_from"}
DEFAULT_FIELDS = {"status", "gender", "number", "case_sensitive", "do_not_translate",
                  "qa", "forms_source", "forms_target", "alternatives"}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def resolved_for_containment(path):
    # Windows can retain the extended prefix during a concurrent ancestor rename.
    # Normalize only that prefix after resolving junctions; retain the real target.
    value = str(path.resolve())
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
    return Path(value)


def readable_compact_json(value, columns=180):
    """Remove indentation noise; wrap at JSON commas, never inside a string.

    This keeps ordinary file readers from truncating long minified record lines.
    JSON values, including embedded punctuation/line breaks, are unchanged.
    """
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    out, quoted, escaped, width = [], False, False, 0
    for char in text:
        out.append(char)
        width += 1
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "," and width >= columns:
            out.append("\n")
            width = 0
    return "".join(out) + "\n"


def working_rules(value):
    """Move only named, string-array provenance to lookup; keep all other fields."""
    if isinstance(value, dict):
        return {k: working_rules(v) for k, v in value.items()
                if not (k in PROVENANCE and isinstance(v, list)
                        and all(isinstance(item, str) for item in v))}
    if isinstance(value, list):
        return [working_rules(v) for v in value]
    return value


def compact(document, field):
    if not isinstance(document, dict) or not isinstance(document.get(field), list):
        raise HarnessError(f"Rules need an object with a {field} array")
    projected = working_rules(document)
    rows = projected[field]
    if not all(isinstance(row, dict) for row in rows):
        raise HarnessError(f"Every {field} record must be an object")
    ids = [r.get("id") for r in rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise HarnessError(f"{field} record IDs must be present and unique")
    defaults = {}
    common = set.intersection(*(set(row) for row in rows)) if rows else set()
    for key in sorted(common & DEFAULT_FIELDS):
        values = Counter(encoded(row[key]) for row in rows)
        value, count = values.most_common(1)[0]
        # Hoist only exact, typed duplicates with a useful reduction in input.
        if count > 2 and count * (len(key) + len(value) + 5) > len(key) + len(value) + 40:
            defaults[key] = json.loads(value)
    out = {
        "format": FORMAT,
        "reading_rule": "Read every record. Each record inherits record_defaults; explicit fields override them. No entry is filtered. Only evidence/merged_from string arrays moved to full-source lookup. Notes, rationale, examples, all forms and unknown fields remain.",
        "source_metadata": {k: v for k, v in projected.items() if k != field},
        "record_defaults": defaults,
        field: [{k: v for k, v in row.items()
                 if k not in defaults or encoded(v) != encoded(defaults[k])} for row in rows],
    }
    if encoded(expand(out, field)) != encoded(projected):
        raise HarnessError("Working rules failed semantic reconstruction")
    return out


def expand(document, field):
    if document.get("format") != FORMAT:
        raise HarnessError("Unknown worker rules format")
    return {**document["source_metadata"], field: [
        {**copy.deepcopy(document["record_defaults"]), **copy.deepcopy(row)}
        for row in document[field]
    ]}


def bundle_path(cfg, contract):
    if len(contract) != 64 or any(c not in "0123456789abcdef" for c in contract):
        raise HarnessError("Expected a full lowercase contract hash")
    path = cfg.root / "work/worker-context" / FORMAT / contract
    resolved_path, root_path = resolved_for_containment(path), resolved_for_containment(cfg.root)
    if not resolved_path.is_relative_to(root_path):
        raise HarnessError(f"Worker context path is outside this project: {resolved_path} / {root_path}")
    return path


def load_bundle(cfg, contract, expected_sources=None):
    path = bundle_path(cfg, contract)
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if (manifest.get("format") != FORMAT or manifest.get("contract_hash") != contract
                or set(manifest.get("files", {})) != OUTPUTS):
            raise HarnessError("Worker context manifest has an unexpected identity/file set")
        if expected_sources is not None and manifest.get("source_hashes") != expected_sources:
            raise HarnessError("Worker context sources do not match the current rules")
        for original, snapshot in INPUTS.items():
            if manifest["files"][snapshot]["sha256"] != manifest["source_hashes"][original]:
                raise HarnessError("Worker context snapshot does not match its source hash")
        for name in OUTPUTS:
            if file_hash(path / name) != manifest["files"][name]["sha256"]:
                raise HarnessError(f"Worker context was modified: {name}; preserve and investigate target")
        for field, original, view in (
                ("entries", "canonical/glossary.json", "glossary.rules.json"),
                ("characters", "canonical/characters.json", "characters.rules.json")):
            source = json.loads((path / original).read_text(encoding="utf-8-sig"))
            rendered = json.loads((path / view).read_text(encoding="utf-8"))
            if encoded(expand(rendered, field)) != encoded(working_rules(source)):
                raise HarnessError(f"Worker context changed a rule in {view}")
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HarnessError(f"Incomplete/corrupt worker context {path}: {exc}") from exc


def ensure_bundle(cfg, expected_contract=None):
    before = cfg.contract_hash()
    if expected_contract is not None and before != expected_contract:
        raise HarnessError("Rules changed since claim; preserve the draft and rebase deliberately")
    try:
        sources = {name: (cfg.root / name).read_bytes() for name in INPUTS}
        glossary = json.loads(sources["glossary/glossary.json"].decode("utf-8-sig"))
        characters = json.loads(sources["style/characters.json"].decode("utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise HarnessError(f"Rules are still being written or invalid; retry after they settle: {exc}") from exc
    if cfg.contract_hash() != before:
        raise HarnessError("Rules changed while reading; retry after the writer finishes")
    source_hashes = {name: digest(data) for name, data in sources.items()}
    path = bundle_path(cfg, before)
    if path.exists():
        return path, load_bundle(cfg, before, source_hashes)
    views = {
        "glossary.rules.json": compact(glossary, "entries"),
        "characters.rules.json": compact(characters, "characters"),
    }
    data = {target: sources[source] for source, target in INPUTS.items()}
    data.update({name: readable_compact_json(value).encode("utf-8")
                 for name, value in views.items()})
    reads = ["style-guide.md", "glossary.rules.json", "characters.rules.json", "reference-policy.md"]
    original_size = sum(map(len, sources.values()))
    working_size = sum(len(data[name]) for name in reads)
    manifest = {
        "format": FORMAT, "contract_hash": before, "source_hashes": source_hashes,
        "files": {name: {"sha256": digest(value), "bytes": len(value)} for name, value in data.items()},
        "required_reads_once_per_batch": reads,
        "statistics": {
            "glossary_records": len(glossary["entries"]),
            "character_records": len(characters["characters"]),
            "canonical_input_bytes": original_size, "working_input_bytes": working_size,
            "input_bytes_saved": original_size - working_size,
            "input_byte_reduction_percent": round(100 * (1 - working_size / max(1, original_size)), 1),
            "unit": "UTF-8 bytes, not measured model tokens",
        },
        "all_non_provenance_fields_reconstructed": True,
        "lookup": "python scripts/worker_context.py lookup glossary <term-id> --contract " + before,
        "character_lookup": "python scripts/worker_context.py lookup characters <id> --contract " + before,
        "authority_note": "A cached view is not gate approval. Canonical sources remain authoritative; existing submit/QA and owner gates are unchanged.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Publish a complete immutable directory, so concurrent workers never see half a bundle.
    with tempfile.TemporaryDirectory(prefix=".building-", dir=path.parent) as temp:
        temporary = Path(temp)
        for name, value in data.items():
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        (temporary / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if cfg.contract_hash() != before:
            raise HarnessError("Rules changed during context build; no bundle published")
        try:
            temporary.rename(path)
        except OSError:
            if not path.exists():
                raise
    return path, load_bundle(cfg, before, source_hashes)


def lookup(cfg, kind, ids, contract=None):
    if kind not in ("glossary", "characters"):
        raise HarnessError("Lookup kind must be glossary or characters")
    if contract is None:
        path, manifest = ensure_bundle(cfg)
        contract = manifest["contract_hash"]
    else:
        path = bundle_path(cfg, contract)
        load_bundle(cfg, contract)
    file, field = ("glossary.json", "entries") if kind == "glossary" else ("characters.json", "characters")
    document = json.loads((path / "canonical" / file).read_text(encoding="utf-8-sig"))
    by_id = {row["id"]: row for row in document[field]}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise HarnessError("Unknown record IDs: " + ", ".join(missing))
    return {"contract_hash": contract, "is_current_contract": contract == cfg.contract_hash(),
            "records": [by_id[i] for i in ids]}


def validate_batch(cfg, packet_ids):
    """Read-only validation; no claim, prepare, submission or attempt-counter change."""
    if not packet_ids:
        return {"packets": [], "preview_only": True, "contract_hash": cfg.contract_hash()}
    if len(set(packet_ids)) != len(packet_ids) or len(packet_ids) > cfg["packets"]["batch_packets"]:
        raise HarnessError("Batch needs distinct packets within configured batch_packets")
    # Use the harness's read-only DB connection: no writable schema initializer.
    from .db import Database
    from . import packets
    db = Database(cfg, readonly=True)
    try:
        claimed = [packets.get(db, pid) for pid in packet_ids]
        if len({p["worker"] for p in claimed}) != 1 or len({p["stage"] for p in claimed}) != 1:
            raise HarnessError("One worker and one role per batch; keep reviewer contexts independent")
        total = 0
        out = []
        for p in claimed:
            check_result = {"packet": p["id"], "worker": p["worker"],
                            "units": [{"sid": sid} for sid in p["payload"]["sids"]]}
            packets._preflight(cfg, db, p, check_result)
            file = cfg.root / "work/packets" / (p["id"] + ".json")
            frozen = json.loads(file.read_text(encoding="utf-8-sig"))
            if (frozen.get("payload") != p["payload"] or frozen.get("id") != p["id"]
                    or frozen.get("worker") != p["worker"] or frozen.get("stage") != p["stage"]):
                raise HarnessError("Frozen packet differs from claim; preserve target and investigate")
            total += file.stat().st_size
            out.append({"id": p["id"], "input": str(file),
                        "result": str(cfg.root / "work/results" / (p["id"] + ".json"))})
        if len(claimed) > 1 and total > cfg["packets"]["batch_max_input_bytes"]:
            raise HarnessError("Batch exceeds frozen input byte limit; split target without dropping context")
        return {"packets": out, "worker": claimed[0]["worker"], "stage": claimed[0]["stage"],
                "contract_hash": claimed[0]["payload"]["contract_hash"], "frozen_input_bytes": total,
                "oversized_single_read_fully": total > cfg["packets"]["batch_max_input_bytes"]}
    except (OSError, ValueError) as exc:
        raise HarnessError(f"Cannot read frozen batch: {exc}") from exc
    finally:
        db.close()


def focused_dialogue(document, identifiers):
    """Return entire statically linked graph components, never source-language-text matches."""
    graphs = document.get("dialogues")
    if not isinstance(graphs, dict) or not all(isinstance(v, dict) for v in graphs.values()):
        raise HarnessError("Dialogue research lacks the expected complete dialogue records")

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from strings(item)

    def sids(value):
        if isinstance(value, dict):
            if isinstance(value.get("sid"), str):
                yield value["sid"]
            for item in value.values():
                yield from sids(item)
        elif isinstance(value, list):
            for item in value:
                yield from sids(item)

    sid_index = {name: set(sids(value)) for name, value in graphs.items()}
    selected = set()
    for identifier in identifiers:
        matches = {name for name in graphs if name == identifier or identifier in sid_index[name]}
        if not matches:
            raise HarnessError(f"No decoded dialogue for {identifier}; consult scene/asset evidence. This is not proof the text is unreachable.")
        selected.update(matches)
    adjacent = {name: set() for name in graphs}
    for name, value in graphs.items():
        for text in strings(value):
            for ref in re.findall(r"/Game/[^\s\x22\x27<>,;()\[\]{}]+", text):
                target = ref.split(".", 1)[0]
                if target in graphs:
                    adjacent[name].add(target)
                    adjacent[target].add(name)
    pending = list(selected)
    while pending:
        for neighbor in adjacent[pending.pop()] - selected:
            selected.add(neighbor)
            pending.append(neighbor)
    return {"snapshot": document.get("snapshot"), "generator": document.get("generator"),
            "source_notes": document.get("notes"),
            "selection_note": "Complete decoded records and all known statically linked dialogue components in both directions; no branch/condition/step is truncated. Static links and array order do not prove runtime reachability or chronology. Native selector/Blueprint behavior may remain undecoded.",
            "dialogues": {name: graphs[name] for name in sorted(selected)}}


def dialogue_lookup(cfg, identifiers):
    from .db import Database
    source = cfg.root / "work/research/dialogue/graphs.json"
    try:
        raw = source.read_bytes()
        document = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise HarnessError(f"Cannot read decoded dialogue research: {exc}") from exc
    with closing(Database(cfg, readonly=True)) as db:
        if document.get("snapshot") != db.meta("active_snapshot"):
            raise HarnessError("Dialogue research belongs to a different source snapshot; refresh research")
        resolved = [value if value.startswith("/Game/") else db.unit(value)["sid"] for value in identifiers]
    result = focused_dialogue(document, resolved)
    result["source_file_sha256"] = digest(raw)
    data = readable_compact_json(result).encode("utf-8")
    directory = cfg.root / "work/worker-context/dialogue-v1" / digest(raw)
    resolved_path, root_path = resolved_for_containment(directory), resolved_for_containment(cfg.root)
    if not resolved_path.is_relative_to(root_path):
        raise HarnessError(f"Dialogue context path is outside this project: {resolved_path} / {root_path}")
    directory.mkdir(parents=True, exist_ok=True)
    query = directory / digest(encoded(sorted(set(resolved))))
    path = query / "context.json"
    if not query.exists():
        with tempfile.TemporaryDirectory(prefix=".dialogue-", dir=directory) as temp:
            temporary = Path(temp)
            (temporary / "context.json").write_bytes(data)
            try:
                temporary.rename(query)
            except OSError:
                if not query.exists():
                    raise
    if path.read_bytes() != data:
        raise HarnessError("Saved dialogue context was modified; preserve target and investigate")
    return {"read_complete_file": str(path), "dialogues": list(result["dialogues"]),
            "bytes": len(data), "complete_research_bytes": len(raw),
            "source_sha256": digest(raw), "note": result["selection_note"]}
