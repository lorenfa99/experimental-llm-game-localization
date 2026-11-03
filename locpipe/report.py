from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path

from .config import HarnessError, read_json, write_json


def status(cfg, db):
    if not db.meta("active_snapshot"):
        return {"project": cfg["project"]["name"], "mode": "preparation_only" if cfg["project"]["preparation_only"] else "translation_enabled",
                "snapshot": None, "native_entries": 0, "provisional_in_scope": 0,
                "targets_nonnull_all_units": 0, "stale": 0, "pending_packets": 0, "open_issues": 0,
                "gates": db.gate_status(), "next": "Capture an authorized source snapshot"}
    label, manifest = db.active_snapshot()
    rows = db.rows("SELECT * FROM units WHERE active=1")
    scope = [u for u in rows if u["include"]]
    return {"project": cfg["project"]["name"], "mode": "preparation_only" if cfg["project"]["preparation_only"] else "translation_enabled", "snapshot": label, "native_entries": len(rows), "native_words_whitespace": sum(len(u["source"].split()) for u in rows), "provisional_in_scope": len(scope), "scope_review_needed": sum(u["kind"] == "unclassified" for u in scope), "excluded_pending_scope_review": len(rows)-len(scope), "in_scope_words_whitespace": sum(len(u["source"].split()) for u in scope), "targets_nonnull_all_units": sum(u["target"] is not None for u in db.rows("SELECT target FROM units")), "translated_in_scope": sum(u["target"] is not None for u in scope), "stale": sum(u["stale"] for u in rows), "pilot_units": sum(u["pilot"] for u in scope), "kinds": dict(Counter(u["kind"] for u in rows)), "stage_completion": {s: sum(s in json.loads(u["stages"]) for u in scope) for s in cfg["pipeline"]["stages"]}, "context": db.meta("context_index", {}), "gates": db.gate_status(), "reference_coverage": db.rows("SELECT culture,COUNT(*) entries,SUM(compatible) compatible FROM refs WHERE snapshot=? GROUP BY culture ORDER BY culture", (label,)), "last_import": db.meta("last_import", {}), "open_issues": db.one("SELECT COUNT(*) n FROM issues WHERE status='open'")["n"], "pending_packets": db.one("SELECT COUNT(*) n FROM packets WHERE status IN ('claimed','ready')")["n"], "pak_inventory_count": manifest["entry_count"]}


def diff(db, old, new):
    for label in (old, new):
        if not db.one("SELECT label FROM snapshots WHERE label=?", (label,)):
            raise HarnessError(f"Unknown snapshot {label}")
    a = {r["sid"]: r for r in db.rows("SELECT * FROM snapshot_units WHERE snapshot=?", (old,))}
    b = {r["sid"]: r for r in db.rows("SELECT * FROM snapshot_units WHERE snapshot=?", (new,))}
    added = [b[s] for s in sorted(b.keys()-a.keys())]
    removed = [a[s] for s in sorted(a.keys()-b.keys())]
    changed = [{"sid": s, "before": a[s], "after": b[s]} for s in sorted(a.keys() & b.keys()) if (a[s]["source_sha"], a[s]["source_hash"]) != (b[s]["source_sha"], b[s]["source_hash"])]
    # A same-text replacement ID is only a possible remap, never an automatic transfer.
    hashes = {}
    for r in removed:
        hashes.setdefault(r["source_sha"], []).append(r["sid"])
    candidates = [{"new_sid": r["sid"], "possible_old_sids": hashes[r["source_sha"]]} for r in added if r["source_sha"] in hashes]
    return {"from": old, "to": new, "added": added, "removed": removed, "changed": changed, "unchanged": len(a.keys() & b.keys())-len(changed), "possible_identity_remaps_require_review": candidates}


def export(cfg, db, output: Path, fmt="jsonl"):
    rows = db.rows("SELECT sid,namespace,key,source,source_sha,source_hash,kind,wave,grp,ord,include,reason,pilot,target,version,stale,locked FROM units WHERE active=1 ORDER BY grp,ord,sid")
    output.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "jsonl":
        output.write_text("".join(json.dumps(u, ensure_ascii=False) + "\n" for u in rows), encoding="utf-8")
    elif fmt == "tsv":
        with output.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["sid", "source", "target", "source_sha", "version"], delimiter="\t")
            w.writeheader()
            w.writerows(rows)
    else:
        raise HarnessError("Export format must be jsonl or tsv")
    return {"path": str(output), "units": len(rows), "targets_nonblank": sum(bool(u["target"]) for u in rows)}


def render(cfg, db):
    result = status(cfg, db)
    write_json(cfg.root / "reports/status.json", result)
    label, _ = db.active_snapshot()
    references = {}
    for r in db.rows("SELECT sid,culture,text,compatible FROM refs WHERE snapshot=? ORDER BY culture", (label,)):
        references.setdefault(r["sid"], []).append(r)
    rows = db.rows("SELECT * FROM units WHERE active=1 ORDER BY grp,ord,sid")
    esc = lambda v: html.escape(str(v if v is not None else ""))
    table = []
    for u in rows:
        refs = "".join(f"<div><b>{esc(r['culture'])}</b>{' [stale reference]' if not r['compatible'] else ''}: {esc(r['text'])}</div>" for r in references.get(u["sid"], []))
        table.append(f"<tr data-kind='{esc(u['kind'])}' data-scope='{u['include']}'><td><code>{esc(u['sid'])}</code><br><small>{esc(u['key'])}</small></td><td>{esc(u['kind'])}<br><small>{'pilot · ' if u['pilot'] else ''}{'in scope' if u['include'] else 'scope review'}</small></td><td class='source'>{esc(u['source'])}<details><summary>Source evidence &amp; official references</summary><p><code>{esc(u['namespace'])}</code><br>{esc(u['grp'])}<br>Source revision: {u['source_hash']:08X}<br>{esc(u['reason'])}</p>{refs}</details></td><td class='target'>{esc(u['target']) or '<span class=muted>Not translated</span>'}</td></tr>")
    kinds = "".join(f"<option value='{esc(k)}'>{esc(k)} ({n})</option>" for k, n in sorted(result["kinds"].items()))
    stats = [("Native entries", result["native_entries"]), ("Provisional scope", result["provisional_in_scope"]), ("target-language targets", result["targets_nonnull_all_units"]), ("Asset-linked entries", result["context"].get("units_with_context", 0))]
    cards = "".join(f"<div class=card><strong>{v:,}</strong><span>{esc(k)}</span></div>" for k,v in stats)
    coverage = "".join(f"<li>{esc(r['culture'])}: {r['compatible']} matching / {r['entries']} entries</li>" for r in result["reference_coverage"])
    gates = " · ".join(esc(g["name"]) + ": " + esc(g["effective_status"]) for g in result["gates"])
    fonts = read_json(cfg.root / "reports/fonts.json", {})
    font_text = f"{len(fonts.get('fonts', []))} font files audited; see fonts.json for per-font results. Runtime routing and layout remain unverified."
    page = """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>PROJECT_TITLE · Localization workbench</title>
<style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#111616;color:#e5e9e6;font:15px/1.5 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:38px 28px}h1{font:500 34px Georgia,serif;margin:8px 0}h2{font-size:18px;margin-top:30px}.eyebrow{color:#bbce9d;font-size:12px;letter-spacing:.16em;text-transform:uppercase}.muted,small{color:#9baaa3}small{overflow-wrap:anywhere}.notice{border-left:3px solid #cdbb84;padding:12px 18px;background:#1e2521;margin:22px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#1b2420;border:1px solid #344139;padding:18px}.card strong{font-size:30px;display:block;color:#cfdeb7}.card span{color:#b4c0b8}details{font-size:13px;margin:8px 0;color:#bdc8c0}details div{white-space:pre-wrap;margin:7px 0}summary{cursor:pointer;color:#bace9c}.filters{display:flex;gap:12px;margin:28px 0 14px;position:sticky;top:0;background:#111616;padding:12px 0;flex-wrap:wrap}input,select{background:#1b2420;border:1px solid #455448;color:#edf1ec;border-radius:3px;padding:10px;font:inherit}input{flex:1;min-width:240px}table{width:100%;border-collapse:collapse;table-layout:fixed}th{text-align:left;color:#c2d3b1;font-size:12px;text-transform:uppercase;letter-spacing:.1em}td,th{border-bottom:1px solid #344039;padding:13px 12px;vertical-align:top}th:nth-child(1){width:20%}th:nth-child(2){width:13%}th:nth-child(3){width:45%}.source,.target{white-space:pre-wrap;overflow-wrap:anywhere}.source details{white-space:normal}code{font-size:12px;color:#b7caa4;overflow-wrap:anywhere}a{color:#ceddb7}footer{color:#9baaa3;margin-top:25px}tr[hidden]{display:none}@media(max-width:760px){main{padding:20px 12px}.stats{grid-template-columns:repeat(2,1fr)}table{font-size:12px}td,th{padding:9px 6px}h1{font-size:28px}}</style>
<main><div class=eyebrow>Source preparation · snapshot SNAPSHOT</div><h1>PROJECT_TITLE</h1><p class=muted>SOURCE_CULTURE → TARGET_CULTURE localization workbench</p><div class=notice>MODE. The native resource is preserved. Scope and linguistic decisions remain provisional. No runtime verification is implied by a successful file build.</div><div class=stats>CARDS</div><details><summary>Technical findings &amp; reference coverage</summary><p>FONT</p><ul>COVERAGE</ul><p>The shipped en-US-POSIX locale is a length-stress test, excluded from reference packets. Asset order is serialization order; dialogue branches and speaker identity need verification.</p><p>GATES</p></details><div class=filters><input id=q aria-label='Search source, key, target or references' placeholder='Search source, key, target or references'><select id=kind aria-label='Filter by kind'><option value=''>All kinds</option>KINDS</select><select id=scope aria-label='Filter by scope'><option value=''>All entries</option><option value=1>Provisional scope</option><option value=0>Scope review</option></select></div><p id=count class=muted></p><table><thead><tr><th>Identity</th><th>Kind</th><th>Source &amp; context</th><th>Target</th></tr></thead><tbody>ROWS</tbody></table><footer>Generated locally by locpipe report. data/localization.sqlite remains authoritative; editing this report does not change the project.</footer></main>
<script>const rows=[...document.querySelectorAll('tbody tr')];const texts=rows.map(r=>r.textContent.toLocaleLowerCase());const q=document.querySelector('#q'),k=document.querySelector('#kind'),s=document.querySelector('#scope');function filter(){let n=0;const t=q.value.toLocaleLowerCase();rows.forEach((r,i)=>{r.hidden=!!((t&&!texts[i].includes(t))||(k.value&&r.dataset.kind!==k.value)||(s.value&&r.dataset.scope!==s.value));if(!r.hidden)n++});document.querySelector('#count').textContent=n+' of '+rows.length+' entries'}[q,k,s].forEach(e=>e.addEventListener('input',filter));filter();</script></html>"""
    replacements = {"SNAPSHOT": esc(label), "MODE": "Preparation only — target-language is disabled" if cfg["project"]["preparation_only"] else "Translation enabled", "CARDS": cards, "FONT": esc(font_text), "COVERAGE": coverage, "GATES": gates, "KINDS": kinds, "ROWS": "".join(table)}
    for key, value in replacements.items():
        page = page.replace(key, value)
    page = page.replace("PROJECT_TITLE", esc(cfg["project"]["name"])).replace("SOURCE_CULTURE", esc(cfg["project"]["source_culture"])).replace("TARGET_CULTURE", esc(cfg["project"]["target_culture"]))
    output = cfg.root / "reports/index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return {"report": str(output), "status": str(cfg.root / "reports/status.json")}
