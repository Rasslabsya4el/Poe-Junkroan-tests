"""Scaling vector index: derived, not authored (DECISIONS D5).

Every mod line of every unique, passive, keystone, mastery effect and support gem
goes through PoB's parser. A *vector* is a stat key that mods scale "per"
(PerStat / Multiplier tags: per Frenzy Charge, per 100 Evasion, per Intelligence,
per jewel ...) or a condition that mods require (Condition tags: while
Leeching, if you've Killed Recently ...). For each vector we list:

  - payoffs: sources whose reward depends on the vector
  - enablers: sources that provide the vector's stat (parsed mods whose name
    equals the stat) -- best effort, the search verifies in PoB anyway

Out: src/junkroan/pob/corpus_data/scaling_vectors.json (machine)
     src/junkroan/pob/corpus_data/scaling_vectors.md   (index for hypothesis generation)
Run: python scripts/build_scaling_vectors.py
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.pob.session import PobSession  # noqa: E402

CORPUS = Path(__file__).resolve().parents[1] / "src" / "junkroan" / "pob" / "corpus_data"
VECTOR_TAGS = ("PerStat", "Multiplier", "MultiplierThreshold", "StatThreshold", "PercentStat")
CONDITION_TAGS = ("Condition", "ActorCondition", "EnemyCondition")


def load(name: str) -> list[dict]:
    payload = json.loads((CORPUS / name).read_text(encoding="utf-8"))
    return payload["records"] if isinstance(payload, dict) else payload


def gather_sources() -> list[dict]:
    """(source_id, family, name, lines) for everything worth indexing."""

    out: list[dict] = []
    for r in load("uniques.json"):
        out.append({"id": f"unique:{r['key']}", "family": "unique", "name": r["name"], "base": r["base"], "type": r["type"], "lines": r["lines"]})
    for r in load("passives.json"):
        if r.get("is_mastery") or r.get("ascendancy_name") or r.get("class_start_index") is not None:
            continue
        kind = "keystone" if r.get("is_keystone") else ("notable" if r.get("is_notable") else "passive")
        if kind == "passive":
            continue  # small nodes: too many, too generic; notables and keystones carry the vectors
        out.append({"id": f"{kind}:{r['node_id']}", "family": kind, "name": r["name"], "lines": list(r.get("stats", []))})
    for r in load("keystones.json"):
        out.append({"id": f"keystone:{r['node_id']}", "family": "keystone", "name": r["name"], "lines": list(r.get("stats", []))})
    for r in load("masteries.json"):
        for e in r.get("mastery_effects", []):
            out.append({"id": f"mastery:{r['node_id']}:{e['effect_id']}", "family": "mastery", "name": f"{r['name']}: {'; '.join(e.get('stats', []))[:60]}", "lines": list(e.get("stats", []))})
    for r in load("ascendancies.json"):
        for node in r.get("nodes", []) if isinstance(r.get("nodes"), list) else []:
            out.append({"id": f"ascendancy:{r.get('name')}:{node.get('node_id')}", "family": "ascendancy", "name": f"{r.get('name')} {node.get('name')}", "lines": list(node.get("stats", []))})
    for r in load("support_gems.json"):
        lines = r.get("stats") or r.get("stat_text") or []
        if isinstance(lines, str):
            lines = [lines]
        out.append({"id": f"support:{r.get('name')}", "family": "support", "name": r.get("name"), "lines": [str(x) for x in lines]})
    # dedupe by id
    seen, uniq = set(), []
    for s in out:
        if s["id"] in seen:
            continue
        seen.add(s["id"]); uniq.append(s)
    return uniq


def _tag_key(tag: dict) -> str:
    """PerStat/Condition tags carry stat, var, statList or varList (a Lua array -> {"1": ...})."""

    for k in ("stat", "var"):
        if tag.get(k):
            return str(tag[k])
    for k in ("statList", "varList"):
        lst = tag.get(k)
        if isinstance(lst, dict):
            return "|".join(str(v) for _, v in sorted(lst.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0))
        if isinstance(lst, list):
            return "|".join(str(v) for v in lst)
    return "?"


def enablers_for(provided: dict[str, list], stat: str) -> list:
    """Every source that provides `stat`, in source order (no cap)."""

    return list(provided.get(stat, []))


def main() -> int:
    t0 = time.perf_counter()
    sources = gather_sources()
    lines = sorted({l for s in sources for l in s["lines"] if l})
    print(f"{len(sources)} sources, {len(lines)} distinct lines")
    parsed: dict[str, dict] = {}
    with PobSession(run_id="scaling-vectors") as pob:
        for i in range(0, len(lines), 500):
            for res in pob.parse_mods(lines[i:i + 500]):
                parsed[res["line"]] = res
    print(f"parsed in {time.perf_counter() - t0:.1f}s; unsupported lines: {sum(1 for r in parsed.values() if r['unsupported'])}")

    vectors: dict[str, dict] = defaultdict(lambda: {"kind": "", "payoffs": [], "enablers": []})
    provided: dict[str, list] = defaultdict(list)  # stat name -> sources that grant it
    for s in sources:
        for line in s["lines"]:
            res = parsed.get(line)
            if not res:
                continue
            for m in res.get("mods", []):
                name = str(m.get("name") or "")
                if name and m.get("type") in ("BASE", "INC", "MORE") and not m.get("tags"):
                    provided[name].append({"source": s["id"], "family": s["family"], "name": s["name"], "line": line})
                for tag in m.get("tags", []):
                    ttype = tag.get("type")
                    if ttype in VECTOR_TAGS:
                        key = _tag_key(tag)
                        vec = vectors[f"per:{key}"]
                        vec["kind"] = "per"
                        vec["payoffs"].append({"source": s["id"], "family": s["family"], "name": s["name"], "line": line, "stat": name, "tag": tag})
                    elif ttype in CONDITION_TAGS:
                        key = _tag_key(tag)
                        vec = vectors[f"cond:{key}"]
                        vec["kind"] = "condition"
                        vec["payoffs"].append({"source": s["id"], "family": s["family"], "name": s["name"], "line": line, "stat": name, "tag": tag})
    # enablers: sources that provide the per-stat directly
    for key, vec in vectors.items():
        if vec["kind"] == "per":
            stat = key.split(":", 1)[1]
            vec["enablers"] = enablers_for(provided, stat)

    ranked = sorted(vectors.items(), key=lambda kv: -len(kv[1]["payoffs"]))
    (CORPUS / "scaling_vectors.json").write_text(json.dumps({
        "corpus_id": "scaling_vectors", "source": "PoB modLib.parseMod over uniques, notables, keystones, masteries, ascendancies, supports",
        "vector_count": len(vectors), "vectors": {k: v for k, v in ranked},
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    md = ["# Scaling vectors (derived from PoB's mod parser)", "",
          f"{len(vectors)} vectors over {len(sources)} sources. `per:X` = rewards scale with X; `cond:X` = rewards need condition X.",
          "Payoff counts by family; top payoff sources named. Use this to propose skeletons; PoB verifies.", ""]
    for key, vec in ranked:
        fam = defaultdict(int)
        for p in vec["payoffs"]:
            fam[p["family"]] += 1
        top = []
        seen = set()
        for p in vec["payoffs"]:
            if p["name"] in seen:
                continue
            seen.add(p["name"]); top.append(p["name"])
            if len(top) >= 6:
                break
        md.append(f"- **{key}** ({len(vec['payoffs'])} payoffs: {', '.join(f'{k} {v}' for k, v in sorted(fam.items()))}; {len(vec['enablers'])} direct enablers): {'; '.join(top)}")
    (CORPUS / "scaling_vectors.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{len(vectors)} vectors; top:", [(k, len(v["payoffs"])) for k, v in ranked[:15]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
