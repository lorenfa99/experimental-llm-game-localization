"""Propose coarser, source-bound packet groups (`grp`/`ord` context overrides).

Packets are claimed one group at a time. Asset- or file-level groups often hold only a few
units, so related items, enemies, menus and scenes are merged into families while each original
group's units stay contiguous. The proposal is a file for human review; `--merge` combines it
with reviewed scope decisions into data/overrides.json, which `index_context` applies.

Family rules are data, not code. A rules file looks like:

    {"strip_prefix": "Game/Content/", "depth": 2, "prefix": "family:",
     "rules": [{"pattern": "^UI/Menus/([^/]+)", "family": "UI/Menus/\\\\1"},
               {"pattern": "^NPCs/", "family": "NPCs"}]}

The first matching rule (regular expression, `match.expand` template) names the family; a group no rule
matches uses the first `depth` path components. Fallback groups named `key-family:*` or
`namespace:*` merge into one family sorted by key.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .config import HarnessError, read_json, write_json
from .orchestration import run_cli

OVERRIDE_KEYS = ("kind", "wave", "include", "reason")
FALLBACK_FAMILY = "key-and-namespace"


def family(group, rules=None):
    """Family name (without the prefix) for one existing group name."""
    rules = rules or {}
    if group.startswith(("key-family:", "namespace:")):
        return FALLBACK_FAMILY
    path = group[len(rules["strip_prefix"]):] if rules.get("strip_prefix") and group.startswith(rules["strip_prefix"]) else group
    for rule in rules.get("rules", []):
        match = re.search(rule["pattern"], path)
        if match:
            return match.expand(rule["family"])
    depth = rules.get("depth", 2)
    if not isinstance(depth, int) or depth < 1:
        raise HarnessError("Grouping depth must be a positive integer")
    return "/".join(path.split("/")[:depth]) or "(root)"


def read_rules(path):
    if path is None:
        return {}
    rules = read_json(Path(path))
    if not isinstance(rules, dict):
        raise HarnessError("Grouping rules must be a JSON object")
    for rule in rules.get("rules", []):
        if not isinstance(rule, dict) or not isinstance(rule.get("pattern"), str) or not isinstance(rule.get("family"), str):
            raise HarnessError("Each grouping rule needs text 'pattern' and 'family'")
        try:
            re.compile(rule["pattern"])
        except re.error as exc:
            raise HarnessError(f"Grouping rule pattern {rule['pattern']!r} is not a valid regular expression: {exc}") from exc
    return rules


def propose(cfg, db, rules=None, order=None):
    """{sid: {source_sha, grp, ord, from_group}} for the active units.

    `order` optionally maps sid to a structural rank (for example decoded dialogue order), which
    overrides stored order inside a family while each original group stays contiguous."""
    rules = rules or {}
    prefix = rules.get("prefix", "family:")
    structural = {k: int(v) for k, v in (order or {}).items()}
    families = defaultdict(list)
    for u in db.rows("SELECT sid,key,source_sha,grp,ord FROM units WHERE active=1 ORDER BY grp,ord,sid"):
        families[family(u["grp"], rules)].append(u)
    proposal = {}
    for name, members in sorted(families.items()):
        if name == FALLBACK_FAMILY:
            members.sort(key=lambda u: (u["key"], u["sid"]))
        else:
            members.sort(key=lambda u: (u["grp"], structural.get(u["sid"], 10**9), u["ord"], u["sid"]))
        for rank, u in enumerate(members):
            proposal[u["sid"]] = {"source_sha": u["source_sha"], "grp": prefix + name, "ord": rank * 10, "from_group": u["grp"]}
    return proposal


def merge(cfg, proposal, scope, replace=False):
    """Combine a proposal with reviewed scope decisions {sid: {source_sha, kind?, wave?, include?, reason?}}."""
    target = cfg.root / "data/overrides.json"
    if target.exists() and not replace:
        raise HarnessError("data/overrides.json exists; review it and pass --replace to overwrite")
    unknown = sorted(set(scope) - set(proposal))
    if unknown:
        raise HarnessError(f"Scope decisions for units outside the proposal: {', '.join(unknown[:5])}")
    merged = {}
    for sid, item in proposal.items():
        record = {"source_sha": item["source_sha"], "grp": item["grp"], "ord": item["ord"]}
        if sid in scope:
            if scope[sid].get("source_sha") != item["source_sha"]:
                raise HarnessError(f"Scope decision for {sid} is stale; review it against the current source")
            record.update({k: v for k, v in scope[sid].items() if k in OVERRIDE_KEYS})
        merged[sid] = record
    write_json(target, merged)
    return str(target)


def run(cfg, db, out="work/research/grouping/grouping-proposal.json", rules_path=None, merge_path=None, replace=False):
    rules = read_rules(rules_path)
    order = read_json(cfg.root / "work/research/dialogue/order.json", {})
    proposal = propose(cfg, db, rules, order)
    write_json(cfg.path(out), proposal)
    counts = defaultdict(int)
    for item in proposal.values():
        counts[item["grp"]] += 1
    result = {"proposal": str(cfg.path(out)), "units": len(proposal), "families": dict(sorted(counts.items())),
              "next": "Review the proposal, then `--merge <scope.json>` (or write data/overrides.json yourself) and run `index_context`."}
    if merge_path:
        scope = read_json(cfg.path(merge_path), {})
        result["overrides"] = merge(cfg, proposal, scope, replace)
        result["scope_changes"] = len(scope)
    return result


def _args(p):
    p.add_argument("--out", default="work/research/grouping/grouping-proposal.json")
    p.add_argument("--rules", type=Path, help="JSON family rules (see the module documentation)")
    p.add_argument("--merge", help="Reviewed scope overrides JSON {sid: {source_sha, kind?, wave?, include?, reason?}} to combine into data/overrides.json")
    p.add_argument("--replace", action="store_true", help="Overwrite an existing data/overrides.json")


COMMANDS = {"propose": (__doc__, _args, True, lambda cfg, db, a: run(cfg, db, a.out, a.rules, a.merge, a.replace))}


def main(argv=None):
    return run_cli(COMMANDS, "propose", argv)
