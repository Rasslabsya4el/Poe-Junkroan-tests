"""The day-1 bundle graph (#1125 unit 2): parts joined where PoB's own parse says one feeds another.

    python scripts/build_bundle_graph.py                   # writes corpus_data/bundle_graph_day1.json, prints row 4
    python scripts/build_bundle_graph.py --check-vectors   # row 2: enabler -> payoff pairs of scaling_vectors.json

Nodes: every distinct day-1 source (`surface:source` of a row of `day1_lines.py`). Edges: directed A -> B, A != B,
joined on what PoB's parse of A's lines sets and what B's lines read:
- condition: A has a FLAG mod named `Condition:X`; B has a tag {type: Condition, var: X}
- multiplier: A has a mod named `Multiplier:X`; B has a tag {type: Multiplier, var: X}
- per_stat: A has a mod named S (any type, unless S is in STAT_SETTER_TYPES: then only the listed types); B has a tag
  {type: PerStat, stat: S}
- calc_multiplier: A has a mod named X (of a listed type, if X is in STAT_SETTER_TYPES) and PoB's calc code itself
  derives `Multiplier:Y` from X (the table CALC_MULTIPLIER below, one PoB file:line per entry); B has a tag
  {type: Multiplier, var: Y}. The edge also stores `via` (X) and `pob` (the file:line).
One edge per (kind, variable or stat, A, B), carrying the two lines that make it (the smallest pair, so a rerun is
byte-identical). No other kind; no text tags, no shared ModList name (only the table's names).

Inputs (no PobSession): the day-1 rows from `scripts/day1_lines.py` (`day1_rows`, or `--rows` a JSON list of
`{line, surface, source, outcome}`), the mod records `corpus_data/day1_mod_records.json` (`--records`: a JSON object
`{line: [{name, type, value, flags, keyword_flags, tags}]}`), and for `--check-vectors` `corpus_data/scaling_vectors.json`
(`--vectors`).
Out: corpus_data/bundle_graph_day1.json (`--out`): `{nodes, edges, counts}`, sorted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "src" / "junkroan" / "pob" / "corpus_data"
DEFAULT_OUT = CORPUS / "bundle_graph_day1.json"
DEFAULT_RECORDS = CORPUS / "day1_mod_records.json"
DEFAULT_VECTORS = CORPUS / "scaling_vectors.json"
KINDS = ("condition", "multiplier", "per_stat", "calc_multiplier")
# Enabler mod name X -> (Multiplier var Y that PoB's calc code derives from X, PoB file:line where it does so).
# Read from vendor/pob/source/src; no entry without a line read there.
CALC_MULTIPLIER: dict[str, tuple[str, str]] = {
    # output.RageEffect = floor(stacks * calcLib.mod(modDB, nil, "RageEffect")); modDB:NewMod("Multiplier:RageEffect", ...)
    "RageEffect": ("RageEffect", "CalcPerform.lua:887"),
    # output.WarcryPower = Override or Sum("BASE", "WarcryPower"); modDB.multipliers["WarcryPower"] = output.WarcryPower
    # The INC setters of this stat are not joined here: see STAT_SETTER_TYPES below (#1146).
    "WarcryPower": ("WarcryPower", "CalcPerform.lua:1312"),
}
# Mod types PoB adds into the value a stat's readers read. A setter of a listed stat whose mod type is not in its
# set makes no per_stat or calc_multiplier edge (#1146, measured on smite-s4: allocating notable:64226, an INC
# WarcryPower, moved output.WarcryPower 20 -> 20). Stats not listed take every mod type, as before.
STAT_SETTER_TYPES: dict[str, tuple[frozenset[str], str]] = {
    # output.WarcryPower = Override or Sum("BASE", "WarcryPower") (CalcPerform.lua:1311); INC WarcryPower is summed
    # only into the warcry buff's power (CalcPerform.lua:2327), never into output.WarcryPower.
    "WarcryPower": (frozenset({"BASE", "OVERRIDE"}), "CalcPerform.lua:1311"),
}
TAG_KIND = {"PerStat": "per_stat", "Multiplier": "multiplier", "Condition": "condition"}
SURFACES = ("notable", "mastery", "ascendancy", "keystone", "unique", "unique_jewel", "gear_affix", "flask")
TOP = 10

Key = tuple[str, str]  # (kind, variable or stat)
Setter = tuple[str, str, str]  # (node id, line, via): via is the table's mod name for calc_multiplier, else ""


def node_id(surface: str, source: Any) -> str:
    return f"{surface}:{source}"


def _setter_takes(name: str, mod: Mapping[str, Any]) -> bool:
    """False when PoB never adds this mod's type into the stat's value (STAT_SETTER_TYPES, #1146)."""

    listed = STAT_SETTER_TYPES.get(name)
    return listed is None or mod.get("type") in listed[0]


def _setter_keys(mod: Mapping[str, Any]) -> Iterable[tuple[Key, str]]:
    """(key, via) pairs the mod sets."""

    name = str(mod.get("name") or "")
    if not name:
        return
    takes = _setter_takes(name, mod)
    if takes and name in CALC_MULTIPLIER:
        yield ("calc_multiplier", CALC_MULTIPLIER[name][0]), name
    if mod.get("type") == "FLAG" and name.startswith("Condition:"):
        yield ("condition", name[len("Condition:"):]), ""
    if name.startswith("Multiplier:"):
        yield ("multiplier", name[len("Multiplier:"):]), ""
    if takes:
        yield ("per_stat", name), ""


def _reader_keys(mod: Mapping[str, Any]) -> Iterable[Key]:
    for tag in mod.get("tags") or ():
        kind = TAG_KIND.get(tag.get("type"))
        if kind == "per_stat":
            if tag.get("stat"):
                yield ("per_stat", str(tag["stat"]))
        elif kind and tag.get("var"):
            yield (kind, str(tag["var"]))
            if kind == "multiplier":
                yield ("calc_multiplier", str(tag["var"]))


def build_graph(rows: Iterable[Mapping[str, Any]], records: Mapping[str, Any], names: Mapping[str, str] | None = None) -> dict[str, Any]:
    names = names or {}
    nodes: dict[str, dict[str, Any]] = {}
    for row in rows:
        nid = node_id(row["surface"], row["source"])
        node = nodes.setdefault(nid, {"id": nid, "surface": row["surface"], "source": str(row["source"]),
                                      "name": names.get(nid, str(row["source"])), "lines": set()})
        node["lines"].add(str(row["line"]))

    setters: dict[Key, set[Setter]] = defaultdict(set)
    readers: dict[Key, set[tuple[str, str]]] = defaultdict(set)
    for nid, node in nodes.items():
        for line in node["lines"]:
            for mod in records.get(line) or ():
                for key, via in _setter_keys(mod):
                    setters[key].add((nid, line, via))
                for key in _reader_keys(mod):
                    readers[key].add((nid, line))

    found: dict[tuple[str, str, str, str], tuple[str, str, str]] = {}
    for key in set(setters) & set(readers):
        kind, var = key
        for a, a_line, via in setters[key]:
            for b, b_line in readers[key]:
                if a == b:
                    continue
                edge_key = (kind, var, a, b)
                cand = (a_line, b_line, via)
                if edge_key not in found or cand < found[edge_key]:
                    found[edge_key] = cand

    edges = []
    for (kind, var, a, b), (a_line, b_line, via) in sorted(found.items()):
        edge = {"kind": kind, "from": a, "to": b, "from_line": a_line, "to_line": b_line}
        edge["stat" if kind == "per_stat" else "var"] = var
        if kind == "calc_multiplier":
            edge["via"] = via
            edge["pob"] = CALC_MULTIPLIER[via][1]
        edges.append(edge)

    node_list = [{"id": n["id"], "surface": n["surface"], "source": n["source"], "name": n["name"], "lines": sorted(n["lines"])}
                 for n in (nodes[k] for k in sorted(nodes))]
    counts = {
        "nodes": len(node_list),
        "edges": len(edges),
        "nodes_per_surface": {s: sum(1 for n in node_list if n["surface"] == s) for s in SURFACES if any(n["surface"] == s for n in node_list)},
        "edges_per_kind": {k: sum(1 for e in edges if e["kind"] == k) for k in KINDS},
    }
    return {"nodes": node_list, "edges": edges, "counts": counts}


def _vector_node(payoff: Mapping[str, Any], node_ids: set[str]) -> str | None:
    family, source = payoff.get("family"), str(payoff.get("source") or "")
    if family == "unique":
        for surface in ("unique", "unique_jewel"):
            candidate = node_id(surface, payoff.get("name"))
            if candidate in node_ids:
                return candidate
        return None
    parts = source.split(":")
    if family in ("notable", "keystone") and len(parts) == 2:
        return node_id(family, parts[1])
    if family == "mastery" and len(parts) == 3:
        return node_id("mastery", parts[1])
    if family == "ascendancy" and len(parts) >= 3:
        return node_id("ascendancy", parts[-1])
    return None


def check_vectors(graph: Mapping[str, Any], vectors_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Row 2: enabler -> payoff pairs of scaling_vectors whose two sources are both day-1 nodes, and the ones missing."""

    node_ids = {n["id"] for n in graph["nodes"]}
    edges = {(e["kind"], e.get("var") or e.get("stat"), e["from"], e["to"]) for e in graph["edges"]}
    pairs: set[tuple[str, str, str, str]] = set()
    not_kind = same = 0
    by_tag: dict[str, int] = defaultdict(int)
    by_tag_var: dict[tuple[str, str], int] = defaultdict(int)
    for vec in vectors_payload["vectors"].values():
        for enabler in vec.get("enablers") or ():
            a = _vector_node(enabler, node_ids)
            if a is None:
                continue
            for payoff in vec.get("payoffs") or ():
                b = _vector_node(payoff, node_ids)
                if b is None:
                    continue
                tag = payoff.get("tag") or {}
                kind = TAG_KIND.get(tag.get("type"))
                if kind is None:
                    not_kind += 1
                    tag_type = str(tag.get("type") or "(no tag)")
                    by_tag[tag_type] += 1
                    by_tag_var[(tag_type, str(tag.get("var") or tag.get("stat") or tag.get("skillName") or ""))] += 1
                    continue
                if a == b:
                    same += 1
                    continue
                pairs.add((kind, str(tag.get("stat") or tag.get("var") or ""), a, b))
    # a payoff reading Multiplier:Y is met by a multiplier edge or by a calc_multiplier edge (PoB derives Y from the enabler)
    missing = sorted(p for p in pairs if p not in edges and not (p[0] == "multiplier" and ("calc_multiplier",) + p[1:] in edges))
    return {"pairs": len(pairs), "missing": len(missing), "not_graph_kind": not_kind, "same_node": same,
            "not_graph_kind_by_tag": dict(sorted(by_tag.items())),
            "not_graph_kind_by_tag_var": dict(sorted(by_tag_var.items())),
            "missing_examples": [f"{k} {v}: {a} -> {b}" for k, v, a, b in missing[:TOP]]}


def non_kind_table(result: Mapping[str, Any], per_tag: int = 5) -> list[str]:
    """Markdown table of the pairs whose tag is not a graph kind: one row per tag type, with its top variables."""

    total = result["not_graph_kind"]
    by_var = result["not_graph_kind_by_tag_var"]
    lines = ["| tag | pairs | share | distinct vars | top vars (pairs) |", "|---|---:|---:|---:|---|"]
    for tag, count in sorted(result["not_graph_kind_by_tag"].items(), key=lambda kv: (-kv[1], kv[0])):
        vars_ = sorted(((v, c) for (t, v), c in by_var.items() if t == tag), key=lambda vc: (-vc[1], vc[0]))
        top = ", ".join(f"{v or '-'} ({c})" for v, c in vars_[:per_tag])
        lines.append(f"| {tag} | {count} | {count * 100 / (total or 1):.1f}% | {len(vars_)} | {top} |")
    lines.append(f"| total | {total} | 100% | | |")
    return lines


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_rows() -> tuple[list[dict[str, Any]], dict[str, str]]:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import day1_lines  # noqa: E402
    from junkroan.optimizer.rails import Rails  # noqa: E402

    rails = Rails.load()
    corpus = day1_lines.load_corpus(rails)
    rows = list(day1_lines.day1_rows(rails, corpus))
    names: dict[str, str] = {}
    for p in corpus.passives:
        if p.get("is_notable"):
            names[node_id("notable", p["node_id"])] = str(p.get("name"))
        if p.get("is_keystone"):
            names[node_id("keystone", p["node_id"])] = str(p.get("name"))
    for k in corpus.keystones:
        names[node_id("keystone", k["node_id"])] = str(k.get("name"))
    for m in corpus.masteries:
        names[node_id("mastery", m["node_id"])] = str(m.get("name"))
    for a in corpus.ascendancies:
        for n in a.get("nodes") or ():
            names[node_id("ascendancy", n["node_id"])] = str(n.get("name"))
    return rows, names


def report(graph: Mapping[str, Any]) -> list[str]:
    nodes = {n["id"]: n for n in graph["nodes"]}
    out_count: dict[str, int] = defaultdict(int)
    in_count: dict[str, int] = defaultdict(int)
    for e in graph["edges"]:
        out_count[e["from"]] += 1
        in_count[e["to"]] += 1
    lines = [f"nodes: {graph['counts']['nodes']}   edges: {graph['counts']['edges']}", "nodes per surface:"]
    lines += [f"  {s:<14}{c:>7}" for s, c in graph["counts"]["nodes_per_surface"].items()]
    lines.append("edges per kind:")
    lines += [f"  {k:<14}{c:>7}" for k, c in graph["counts"]["edges_per_kind"].items()]
    for title, counts in (("top 10 by out-edges (it sets what others read)", out_count), ("top 10 by in-edges (it reads what others set)", in_count)):
        lines.append(title + ":")
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]
        for nid, c in ranked:
            lines.append(f"  {nodes[nid]['name']} | {nodes[nid]['surface']} | {c}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rows", type=Path, help="day-1 rows as a JSON list (default: day1_lines.py's rows)")
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--vectors", type=Path, default=DEFAULT_VECTORS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check-vectors", action="store_true", help="row 2 only: print the check, write nothing")
    parser.add_argument("--non-kind-table", action="store_true", help="with --check-vectors: also print the pairs whose tag is not a graph kind, grouped by tag")
    args = parser.parse_args(argv)

    if not args.records.is_file():
        print(f"missing mod records: {args.records} (written by the day-1 parse pass, #1119)", file=sys.stderr)
        return 2
    records = _load_json(args.records)
    if args.rows is not None:
        rows, names = _load_json(args.rows), {}
    else:
        rows, names = _default_rows()
    graph = build_graph(rows, records, names)

    if args.check_vectors:
        result = check_vectors(graph, _load_json(args.vectors))
        print(f"scaling_vectors pairs with both sources day-1: {result['pairs']}")
        print(f"missing from the graph: {result['missing']}")
        print(f"pairs whose tag is not a graph kind (not counted): {result['not_graph_kind']}")
        print(f"pairs within one node (not an edge): {result['same_node']}")
        for example in result["missing_examples"]:
            print(f"  missing {example}")
        if args.non_kind_table:
            print()
            for table_line in non_kind_table(result):
                print(table_line)
        return 1 if result["missing"] > 0 else 0

    text = json.dumps(graph, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    args.out.write_bytes(text.encode("utf-8"))
    print(f"wrote {args.out} ({len(text.encode('utf-8')) // 1024} KB)")
    for line in report(graph):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
