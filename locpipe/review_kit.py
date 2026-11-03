"""Offline external-review kit: package the finished localization for review in outside chats
(for example Gemini in AI Studio), then bring the answers back as untrusted proposals.

Nothing is uploaded and no model API is called. The kit is private, game-derived data. The
returned findings are proposals: `parse` only checks that each one is bound to the exact
unit version the kit contained, a fresh-context triage decides, `accepted` exports the
approved rows, and `issue-import` records them as ordinary issues for the normal revise
path. A reviewer's answer is never applied to a target automatically.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from . import packets, references
from .config import HarnessError, digest, file_hash, read_json, write_json
from .orchestration import REQUIRED_STAGES, consistent_read, run_cli, utc_now
from .worker_context import ensure_bundle, focused_dialogue

KIT_ROOT = "work/external-review"
STEM_SUFFIXES = ("name", "desc", "description", "title", "text")
DECISIONS = ("accepted", "adapted", "rejected")
BINDINGS = ("namespace", "key", "source_sha", "source_hash", "version")
RESULT_SUFFIXES = (".txt", ".md", ".jsonl", ".json")

CAVEAT = ("Unit notes, scene briefs and dialogue graphs are supporting evidence. Do not count a context citation "
          "as an additional unit to review. Serialization order, array order and offsets do not prove chronology, "
          "execution, reachability or widget size. The approved rules in RULES prevail over any historic note here.")

PROMPT = """# Prompt for a new review chat

Act as a bilingual {source} to {target} reviewer for a game localization. Find concrete
defects, or clearly useful improvements, in the {target} text provided, always comparing it
with the {source} source and the verified context. Do not retranslate automatically and do
not look for a minimum number of changes: a good translation stays, even if you know a
different synonym.

Before judging, read RULES completely: the style guide, every glossary entry, every
character profile and the reference policy. Apply `record_defaults` to every record that
inherits them. Priority: approved glossary, character profiles, style guide, verified
context, source meaning. If you can prove a defect in a rule, report it as such; do not
change a rule silently. Historic proposals, counts and gate states inside context files do
not replace the current rules. Array order, numbers and offsets do not prove dialogue order.

Then examine EVERY unit of the COMPARE file of this chat. Each unit has a SID, namespace,
key, source hash and a target version. Never merge units because their text is identical.
If you cannot read an attachment completely, say so and list the units you actually
examined; never claim full coverage. Ask for the specific missing context before proposing
an uncertain correction. You have no access to the game or to our tooling and must not
simulate tool calls.

Look especially for: meaning errors and omissions, false friends and calques, agreement and
government, unclear antecedents, naturalness and rhythm, register and voice, inconsistent
terms for the same sense, hard-to-read names and menu labels, and links between sentences.
Preserve intentional functional differences and source ambiguity. Do not invent lore,
gender, interlocutor, sequence, reachability, effects or length limits. Placeholders such as
{{name}}, markup, punctuation and numerals must stay exact. Do not mechanically unify strings
that have different functions or senses.

If the source is genuinely ambiguous, consult the REFERENCES file of this chat when attached:
only compatible official-language versions, never a pseudo-locale. Compare meaning; do not
count votes across languages. State which versions you actually read and what they clarify.
Without references, or if they conflict, record the uncertainty: do not present a guess as a
confirmed correction.

Reply with:
1. Coverage: file, number of units read, first and last SID, and any unexamined unit. One
   line of overall judgement, without generic praise.
2. A JSONL block containing ONLY concrete findings, one JSON object per line, never altering
   a SID. Echo `version` and `current_target` exactly as given, including line breaks:
{{"sid":"...","version":1,"current_target":"exact current text","category":"accuracy|fluency|terminology|style|locale|markup|layout|voice","severity":"critical|major|minor|preferential","comment":"the problem and its concrete benefit","suggestion":"complete proposed replacement, or null when evidence is missing","evidence":"source, rule, context and references actually read","confidence":"high|medium|low"}}
3. A short list of genuinely unresolved questions. If you find no defects, write "No
   substantive findings" and do not rewrite good units. Separate a stylistic preference from
   an error and do not raise severity to persuade me.

Your proposals will be judged in a separate, independent context and nothing is imported
automatically. Do not declare the localization approved or tested in the game.
"""

README = """# External review kit

Each folder under CHATS/ is ONE review chat; the units of the whole corpus appear exactly
once across the chats. Related groups are kept together and units sharing a key stem
(for example name and description) stay in the same chat.

For every chat:
1. Open a new chat and paste CHATS/CHAT-NN/START{suffix}. It already holds the prompt and the assignment.
2. Attach RULES{suffix} (identical for every chat), CHATS/CHAT-NN/COMPARE{suffix} and CHATS/CHAT-NN/CONTEXT{suffix}.
3. REFERENCES.jsonl is optional: attach it when a real ambiguity in the source appears.
4. If the answer is long, ask the reviewer to continue from the units still to be examined in the SAME chat.
5. Save each answer as CHAT-NN-result.txt (one file per reply is fine) and bring them back:
   `python scripts/external_review_kit.py parse <kit-label> <results-folder> --label <results-label>`

Nothing here is uploaded or sent by the toolkit, and no model API is used. The kit is private,
game-derived data: keep it out of public repositories. It contains no private worker
conversations or reasoning. If a model cannot read a complete attachment, the prompt makes it
say so rather than pretend coverage. The model name you select is not a measured quality.
"""


def _label(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise HarnessError("Use a label of letters, digits, hyphens and underscores")
    return value


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def fence(text, language="text"):
    """A tilde fence longer than any tilde run inside the text, so unit text can never close it."""
    longest = max((len(run) for run in re.findall(r"~+", text)), default=0)
    mark = "~" * max(4, longest + 1)
    return f"{mark}{language}\n{text}\n{mark}\n"


def words(unit):
    return len(unit["source"].split())


def key_stem(key, suffixes=STEM_SUFFIXES):
    return re.sub(r"[_.-](?:" + "|".join(map(re.escape, suffixes)) + r")$", "", key, flags=re.I)


def _chunks_needed(weights, limit):
    count, load = 1, 0
    for weight in weights:
        if load and load + weight > limit:
            count, load = count + 1, 0
        load += weight
    return count


def partition(weights, parts):
    """Cut an ordered weight list into exactly min(parts, len) contiguous, non-empty chunks,
    minimizing the heaviest one. Returns the start index of every chunk."""
    parts = min(parts, len(weights))
    low, high = max(weights), sum(weights)
    while low < high:
        middle = (low + high) // 2
        low, high = (low, middle) if _chunks_needed(weights, middle) <= parts else (middle + 1, high)
    starts, load = [0], 0
    for i, weight in enumerate(weights):
        remaining = parts - len(starts) + 1
        if i > starts[-1] and (load + weight > low or len(weights) - i < remaining):
            starts.append(i)
            load = 0
        load += weight
    return starts


def balanced_chats(units, chats, suffixes=STEM_SUFFIXES):
    """Contiguous word-balanced assignments; a group/namespace/key-stem block never splits."""
    blocks = defaultdict(list)
    for unit in units:
        blocks[(unit["grp"], unit["namespace"], key_stem(unit["key"], suffixes))].append(unit)
    ordered = list(blocks.values())
    starts = partition([max(1, sum(map(words, block))) for block in ordered], chats)
    ends = starts[1:] + [len(ordered)]
    return [[unit for block in ordered[a:b] for unit in block] for a, b in zip(starts, ends)]


def title(rows):
    groups = list(dict.fromkeys(u["grp"] for u in rows))
    return groups[0] if len(groups) == 1 else f"{groups[0]} … {groups[-1]} ({len(groups)} groups)"


def compare_markdown(rows, source, target):
    out = []
    for u in rows:
        out.append(f"## {u['sid']} · {u['namespace']} / {u['key']} · {target} v{u['version']}\n")
        out.append(f"Group: {u['grp']} · kind: {u['kind']} · source hash: {u['source_hash']}\n")
        out.append(f"### Source ({source})\n" + fence(u["source"]))
        out.append(f"### Target ({target}), version {u['version']}\n" + fence(u["target"]))
    return "\n".join(out)


def fingerprint(units):
    return digest(json.dumps([(u["sid"], u["version"], u["target"]) for u in sorted(units, key=lambda u: u["sid"])], ensure_ascii=False))


def _nested_sids(value):
    if isinstance(value, dict):
        if isinstance(value.get("sid"), str):
            yield value["sid"]
        for item in value.values():
            yield from _nested_sids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nested_sids(item)


def _briefs(directory):
    if directory is None:
        return {}
    folder = Path(directory)
    if not folder.is_dir():
        raise HarnessError(f"Context directory not found: {folder}")
    return {p.name: p.read_text(encoding="utf-8-sig") for p in sorted(folder.glob("*.md"))}


def _graphs(path, snapshot):
    if path is None:
        return None, set()
    document = read_json(Path(path))
    if not isinstance(document, dict) or "dialogues" not in document:
        raise HarnessError("Graphs file needs a top-level 'dialogues' object (see docs/EXTERNAL-REVIEW.md)")
    if document.get("snapshot") != snapshot:
        raise HarnessError("Dialogue research belongs to a different source snapshot; refresh it before building a kit")
    return document, set(_nested_sids(document["dialogues"]))


def context_text(header, rows, notes, evidence, briefs, graph, graph_sids):
    sids = {u["sid"] for u in rows}
    parts = [header, CAVEAT + "\n"]
    unit_lines = [f"- {u['sid']} ({u['namespace']} / {u['key']}): {notes[u['sid']]}" for u in rows if notes.get(u["sid"])]
    if unit_lines:
        parts.append("## Unit context notes\n\n" + "\n".join(unit_lines) + "\n")
    indexed = [(u, e) for u in rows for e in evidence.get(u["sid"], [])]
    if indexed:
        parts.append("## Indexed context evidence\n\n" + "\n".join(
            f"- {u['sid']} · {e['asset']} @ {e['offset']}: {e['evidence']}" for u, e in indexed) + "\n")
    chosen = sorted(name for name, text in briefs.items() if name == "index.md" or any(sid in text for sid in sids))
    for name in chosen:
        parts.append(f"## Scene brief: {name}\n\n{briefs[name]}\n")
    linked = sorted(sids & graph_sids)
    if linked:
        parts.append("## Complete relevant dialogue graphs\n\n" + fence(json.dumps(focused_dialogue(graph, linked), ensure_ascii=False, indent=1), "json"))
    return "\n".join(parts), chosen, len(linked)


def build(cfg, db, label, chats=12, context_dir=None, graphs=None, suffix=".md", stems=STEM_SUFFIXES,
          expect_units=None, expect_words=None):
    """Build a private, read-only review kit from the finished corpus: rules, prompt, one
    assignment per chat and a manifest that lets `parse` bind every answer to its unit version."""
    label = _label(label)
    if suffix not in (".md", ".txt"):
        raise HarnessError("Attachment suffix must be .md or .txt")
    if type(chats) is not int or not 1 <= chats <= 99:
        raise HarnessError("Chats must be between 1 and 99")
    out = cfg.root / KIT_ROOT / label
    archive = out.parent / (label + ".zip")
    if out.exists() or archive.exists():
        raise HarnessError("An existing kit is preserved; choose a different label")
    source, target = cfg["project"]["source_culture"], cfg["project"]["target_culture"]
    with consistent_read(db):
        units = db.rows("SELECT * FROM units WHERE active=1 AND include=1 ORDER BY grp,ord,sid")
        if not units:
            raise HarnessError("There are no in-scope units to review")
        total = sum(map(words, units))
        if (expect_units is not None and expect_units != len(units)) or (expect_words is not None and expect_words != total):
            raise HarnessError(f"Scope is {len(units)} units / {total} words and differs from the stated expectation")
        unfinished = [u["sid"] for u in units if u["target"] is None or u["stale"] or not set(REQUIRED_STAGES) <= set(json.loads(u["stages"]))]
        if unfinished:
            raise HarnessError(f"{len(unfinished)} in-scope units are not fully translated and reviewed (first: {unfinished[0]}); "
                               "finish the offline stages before an external review")
        if db.one("SELECT id FROM packets WHERE status IN ('claimed','ready') LIMIT 1") or db.one("SELECT id FROM issues WHERE status='open' LIMIT 1"):
            raise HarnessError("Resolve live packets and open issues first, so reviewers see a settled corpus")
        snapshot = db.meta("active_snapshot")
        rules_path, rules = ensure_bundle(cfg)
        refs = {u["sid"]: references.lookup(cfg, db, u["sid"]) for u in units}
        evidence = defaultdict(list)
        for row in db.rows("SELECT sid,asset,offset,evidence FROM contexts WHERE snapshot=? ORDER BY sid,asset,offset", (snapshot,)):
            evidence[row["sid"]].append(row)
        notes = {u["sid"]: json.loads(u["data"]).get("context") for u in units}
        manifest = {"private_game_derived": True, "utc": utc_now(), "snapshot": snapshot, "contract_hash": cfg.contract_hash(),
                    "corpus_hash": db.corpus_hash(), "target_text_fingerprint": fingerprint(units), "units": len(units),
                    "source_words": total, "rules": rules, "attachment_suffix": suffix, "uploaded": False}
    briefs = _briefs(context_dir)
    graph, graph_sids = _graphs(graphs, snapshot)
    assignments = balanced_chats(units, chats, tuple(stems))
    assigned = [u["sid"] for rows in assignments for u in rows]
    if sorted(assigned) != sorted(u["sid"] for u in units):
        raise HarnessError("Internal error: assignments do not cover every unit exactly once")
    rules_text = ["# Approved rules\n", "Read all four sections. `record_defaults` objects are inherited by every record; no entry is omitted.\n"]
    rules_text += [f"## {name}\n\n" + (rules_path / name).read_text(encoding="utf-8-sig") + "\n" for name in rules["required_reads_once_per_batch"]]
    prompt = PROMPT.format(source=source, target=target)
    work = out.parent / (label + ".partial")
    if work.exists():
        shutil.rmtree(work)
    try:
        _write(work / f"RULES{suffix}", "\n".join(rules_text))
        _write(work / f"PROMPT{suffix}", prompt)
        index = ["# Review plan\n", f"{len(assignments)} chats; every unit appears exactly once.\n",
                 "| Chat | Content | Units | Source words |", "|---|---|---:|---:|"]
        chat_records = []
        for number, rows in enumerate(assignments, 1):
            folder = work / "CHATS" / f"CHAT-{number:02d}"
            count, size = len(rows), sum(map(words, rows))
            header = f"# CHAT-{number:02d} — {title(rows)}\n\n{count} units; {size} source words. Every SID listed in COMPARE is to be examined in this chat only.\n\n"
            records = [{**{k: u[k] for k in ("sid", "namespace", "key", "source_sha", "source_hash", "grp", "ord", "kind", "version")},
                        "source": u["source"], "target": u["target"]} for u in rows]
            _write(folder / f"COMPARE{suffix}", header + compare_markdown(rows, source, target))
            _write(folder / "DATA.jsonl", _jsonl(records))
            _write(folder / "REFERENCES.jsonl", _jsonl(
                {"sid": u["sid"], "namespace": u["namespace"], "key": u["key"], "source_hash": u["source_hash"],
                 "references": [{"culture": r["culture"], "text": r["text"], "same_as_source": r["same_as_source"]}
                                for r in refs[u["sid"]]["references"]]} for u in rows))
            context, chosen, linked = context_text(header, rows, notes, evidence, briefs, graph, graph_sids)
            _write(folder / f"CONTEXT{suffix}", context)
            _write(folder / f"START{suffix}", prompt + f"\n\n# Assignment of this chat\n\n{header}"
                   f"I attached RULES{suffix}, COMPARE{suffix} and CONTEXT{suffix} for this package. Read them completely and proceed now. "
                   "Official references are in REFERENCES.jsonl if needed. Return coverage and only reasoned findings in the requested JSONL format. "
                   "Groups: " + ", ".join(sorted({u["grp"] for u in rows})) + ".\n")
            index.append(f"| {number:02d} | {title(rows)} | {count} | {size} |")
            chat_records.append({"chat": number, "title": title(rows), "units": count, "source_words": size, "sids": [u["sid"] for u in rows],
                                 "scene_briefs": chosen, "graph_components": linked})
        _write(work / "INDEX.md", "\n".join(index) + "\n")
        _write(work / "README.md", README.format(suffix=suffix))
        manifest.update(chats=chat_records, coverage_exact_once=True)
        manifest["files"] = {p.relative_to(work).as_posix(): file_hash(p) for p in sorted(work.rglob("*")) if p.is_file()}
        _write(work / "MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        work.rename(out)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                bundle.write(p, p.relative_to(out).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None or any(digest(bundle.read(n)) != h for n, h in manifest["files"].items()):
            raise HarnessError("Kit archive failed verification")
        packaged = [json.loads(line) for n in bundle.namelist() if n.endswith("/DATA.jsonl") for line in bundle.read(n).decode("utf-8").splitlines()]
    if sorted(r["sid"] for r in packaged) != sorted(u["sid"] for u in units):
        raise HarnessError("Kit archive does not contain every unit exactly once")
    return {"folder": str(out), "zip": str(archive), "zip_sha256": file_hash(archive), "chats": len(assignments), "units": len(units),
            "source_words": total, "coverage_verified_exact_once": True, "uploaded": False,
            "assignments": [{k: row[k] for k in ("chat", "title", "units", "source_words")} for row in chat_records]}


# ------------------------------------------------------------------- answers
def _kit(cfg, kit):
    folder = cfg.root / KIT_ROOT / _label(kit)
    manifest = read_json(folder / "MANIFEST.json")
    if manifest is None:
        raise HarnessError(f"No kit named {kit!r} under {KIT_ROOT}")
    for name, expected in manifest["files"].items():
        if not (folder / name).is_file() or file_hash(folder / name) != expected:
            raise HarnessError(f"Kit file changed after it was built: {name}")
    data = {}
    for chat in manifest["chats"]:
        for line in (folder / "CHATS" / f"CHAT-{chat['chat']:02d}" / "DATA.jsonl").read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            data[record["sid"]] = {**record, "chat": chat["chat"]}
    return folder, manifest, data


def _objects(text):
    """JSON objects written one per line, with or without a code fence; returns (objects, bad lines)."""
    found, bad = [], []
    for line in text.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{") or '"sid"' not in line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            bad.append(line[:200])
            continue
        if isinstance(value, dict) and "sid" in value:
            found.append(value)
    return found, bad


def _lines(text):
    return text.replace("\r\n", "\n")


def parse(cfg, db, kit, results, label):
    """Turn reviewer answers into candidate findings bound to the kit's exact unit versions.
    Rows that cannot be bound are kept, with the reason, in rejected-inputs.json."""
    folder, manifest, data = _kit(cfg, kit)
    out = folder.parent / f"{folder.name}.results-{_label(label)}"
    if out.exists():
        raise HarnessError("Existing parsed results are preserved; choose a different label")
    files = sorted(p for p in Path(results).iterdir() if p.is_file() and p.suffix.lower() in RESULT_SUFFIXES)
    if not files:
        raise HarnessError(f"No reviewer answers (*.txt, *.md, *.jsonl, *.json) in {results}")
    numbers = {}
    for path in files:
        match = re.search(r"chat[-_ ]?(\d{1,2})", path.name, re.I)
        if not match or int(match.group(1)) not in {c["chat"] for c in manifest["chats"]}:
            raise HarnessError(f"Name each answer file after its chat (for example CHAT-03-result.txt): {path.name}")
        numbers[path] = int(match.group(1))
    live = {r["sid"]: r for r in db.rows("SELECT sid,namespace,key,source_sha,source_hash,version,target,active,include,stale FROM units")}
    candidates, rejected, triage, seen, unreadable, per_file = [], [], [], set(), [], []
    sequence = Counter()
    for path in files:
        chat = numbers[path]
        objects, bad = _objects(path.read_text(encoding="utf-8-sig"))
        unreadable += [{"file": path.name, "line": line} for line in bad]
        per_file.append({"file": path.name, "chat": chat, "findings_found": len(objects), "unparseable_json_lines": len(bad)})
        for row in objects:
            def reject(reason):
                rejected.append({"file": path.name, "chat": chat, "reason": reason, "row": row})
            record = data.get(row["sid"]) if isinstance(row["sid"], str) else None
            if record is None:
                reject("sid is not in the kit")
                continue
            if record["chat"] != chat:
                reject(f"sid belongs to chat {record['chat']:02d}, not this answer")
                continue
            now = live.get(record["sid"])
            if (now is None or not now["active"] or not now["include"] or now["stale"] or now["target"] != record["target"]
                    or any(now[k] != record[k] for k in BINDINGS)):
                reject("the unit changed after the kit was built")
                continue
            if row.get("version") != record["version"] or not isinstance(row.get("current_target"), str) \
                    or _lines(row["current_target"]) != _lines(record["target"]):
                reject("version or current_target does not echo the kit exactly")
                continue
            if row.get("category") not in packets.CATEGORIES or row.get("severity") not in packets.SEVERITIES:
                reject("invalid category or severity")
                continue
            comment, suggestion = row.get("comment"), row.get("suggestion")
            if not isinstance(comment, str) or not comment.strip() or (suggestion is not None and not isinstance(suggestion, str)):
                reject("needs a concrete comment and a text-or-null suggestion")
                continue
            if suggestion is not None and _lines(suggestion) == _lines(record["target"]):
                reject("suggestion equals the current target")
                continue
            signature = (record["sid"], row["category"], comment)
            if signature in seen:
                reject("duplicate finding")
                continue
            seen.add(signature)
            sequence[chat] += 1
            finding = f"C{chat:02d}-{sequence[chat]:03d}"
            binding = {k: record[k] for k in BINDINGS}
            binding["current_target"] = record["target"]
            candidates.append({"sid": record["sid"], **binding, "category": row["category"], "severity": row["severity"],
                               "comment": comment, "suggestion": suggestion, "finding_id": finding})
            triage.append({"finding_id": finding, "chat": chat, "sid": record["sid"], "category": row["category"], "severity": row["severity"],
                           "confidence": row.get("confidence"), "comment": comment, "suggestion": suggestion, "evidence": row.get("evidence"),
                           "source": record["source"], "current_target": record["target"], "binding": binding,
                           "decision": None, "reason": "", "adapted_comment": None, "adapted_suggestion": None})
    covered = {n for n in numbers.values()}
    summary = {"kit": folder.name, "kit_manifest_sha256": file_hash(folder / "MANIFEST.json"), "utc": utc_now(), "answer_files": per_file,
               "chats_without_answers": sorted({c["chat"] for c in manifest["chats"]} - covered), "candidates": len(candidates),
               "rejected_inputs": len(rejected), "rejected_by_reason": dict(Counter(r["reason"] for r in rejected)),
               "unparseable_json_lines": len(unreadable), "private_game_derived": True}
    write_json(out / "PARSE.json", summary)
    write_json(out / "rejected-inputs.json", {"rejected": rejected, "unparseable_lines": unreadable})
    _write(out / "candidates.jsonl", _jsonl(candidates))
    write_json(out / "triage.json", {"kit": folder.name, "decisions": list(DECISIONS), "private_game_derived": True,
                                      "instructions": "A fresh, independent context sets `decision` and a concrete `reason` on every row. "
                                                      "`adapted` also needs adapted_suggestion and/or adapted_comment. Nothing is imported until `accepted` runs.",
                                      "rows": triage})
    return {"directory": str(out), **{k: v for k, v in summary.items() if k not in ("answer_files", "utc", "private_game_derived")}}


def accepted(cfg, db, triage_path, out_path=None):
    """Export the accepted/adapted rows of a completed triage as an `issue-import` file.
    Only aggregates are returned; units that changed since the triage are excluded and counted."""
    triage_path = Path(triage_path)
    document = read_json(triage_path)
    if not document or not isinstance(document.get("rows"), list) or not document["rows"]:
        raise HarnessError("Triage file has no rows")
    out = Path(out_path) if out_path else triage_path.parent / "accepted.jsonl"
    if out.exists():
        raise HarnessError("Existing accepted export is preserved; choose another --out")
    undecided = [r["finding_id"] for r in document["rows"] if r.get("decision") not in DECISIONS]
    if undecided:
        raise HarnessError(f"{len(undecided)} rows lack a decision (first: {undecided[0]})")
    for row in document["rows"]:
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise HarnessError(f"{row['finding_id']} needs a concrete reason for its decision")
        if row["decision"] == "adapted" and not any(isinstance(row.get(k), str) and row[k].strip() for k in ("adapted_comment", "adapted_suggestion")):
            raise HarnessError(f"{row['finding_id']} is adapted but has no adapted_comment or adapted_suggestion")
    exported, stale = [], []
    for row in document["rows"]:
        if row["decision"] == "rejected":
            continue
        unit = db.one("SELECT * FROM units WHERE sid=?", (row["sid"],))
        binding = row["binding"]
        if (not unit or not unit["active"] or not unit["include"] or unit["stale"] or unit["target"] != binding["current_target"]
                or any(unit[k] != binding[k] for k in BINDINGS)):
            stale.append(row["finding_id"])
            continue
        adapted = row["decision"] == "adapted"
        suggestion = row["adapted_suggestion"] if adapted and row.get("adapted_suggestion") else row["suggestion"]
        exported.append({"sid": row["sid"], **binding, "category": row["category"], "severity": row["severity"],
                         "comment": row["adapted_comment"] if adapted and row.get("adapted_comment") else row["comment"],
                         "suggestion": suggestion, "finding_id": row["finding_id"]})
    _write(out, _jsonl(exported))
    rows = document["rows"]
    return {"file": str(out), "sha256": file_hash(out), "candidates": len(rows), "exported": len(exported),
            "by_decision": dict(Counter(r["decision"] for r in rows)),
            "exported_by_category": dict(Counter(r["category"] for r in exported)),
            "stale_since_triage": stale,
            "next": "locpipe issue-import <file> --origin <short-id> --by <actual importer> --note <provenance>; then the ordinary revise path"}


# ------------------------------------------------------------------------ CLI
def _build_args(p):
    p.add_argument("label", help="New kit name under " + KIT_ROOT)
    p.add_argument("--chats", type=int, default=12, help="Number of review chats (default 12)")
    p.add_argument("--context-dir", help="Folder of *.md scene/area briefs; those that cite a chat's SIDs are included")
    p.add_argument("--graphs", help="Decoded dialogue JSON ({snapshot, dialogues}); must match the active snapshot")
    p.add_argument("--attachment-suffix", default=".md", choices=(".md", ".txt"), help="Use .txt if the chat site rejects .md uploads")
    p.add_argument("--stem-suffix", action="append", help="Key suffix that pairs units into one block (repeatable; default name, desc, description, title, text)")
    p.add_argument("--expect-units", type=int)
    p.add_argument("--expect-words", type=int)


def _parse_args(p):
    p.add_argument("kit", help="Kit label")
    p.add_argument("results", type=Path, help="Folder of saved reviewer answers, each named after its chat (CHAT-03-...)")
    p.add_argument("--label", required=True, help="New name for the parsed results")


def _accepted_args(p):
    p.add_argument("triage", type=Path, help="Completed triage.json")
    p.add_argument("--out", type=Path)


COMMANDS = {
    "build": (build.__doc__, _build_args, True,
              lambda cfg, db, a: build(cfg, db, a.label, a.chats, a.context_dir, a.graphs, a.attachment_suffix,
                                       tuple(a.stem_suffix) if a.stem_suffix else STEM_SUFFIXES, a.expect_units, a.expect_words)),
    "parse": (parse.__doc__, _parse_args, True, lambda cfg, db, a: parse(cfg, db, a.kit, a.results, a.label)),
    "accepted": (accepted.__doc__, _accepted_args, True, lambda cfg, db, a: accepted(cfg, db, a.triage, a.out)),
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    usage = "Usage: external_review_kit.py {" + "|".join(COMMANDS) + "} [-h] ..."
    if argv and argv[0] in ("-h", "--help"):
        print(usage)
        return 0
    if not argv or argv[0] not in COMMANDS:
        print(json.dumps({"error": usage}))
        return 2
    return run_cli(COMMANDS, argv[0], argv[1:])
