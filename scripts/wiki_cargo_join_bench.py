import collections, json, sys
from pathlib import Path

S = Path(sys.argv[1])
ROOT = Path("C:/Coding/poe-junkroan-v2")
t = (S / "wiki.cargo").read_bytes().decode("utf-8")
assert t.startswith("d=")
b = json.loads(t[2:])
(ROOT / "var/cache/wiki/2026-09-19-bench-pantheon-cargo.json").write_text(json.dumps(b, ensure_ascii=False, indent=0), encoding="utf-8")
series = [s["id"] for s in b["series"]][-5:]
print("series", [(s["id"], s["name"]) for s in b["series"]][-5:])
areas = {a["id"]: a for a in b["areas"]}
tier = collections.defaultdict(dict)  # area id -> series -> base tier
for n in b["atlas_nodes"]:
    if n["series id"] in series and n.get("is off atlas") != "1":
        tier[n["area id"]][n["series id"]] = int(n["tier 0"] or 0)
cur = series[-1]
by_name = collections.defaultdict(list)
for a in b["areas"]:
    by_name[a["name"]].append(a)


def locate(name):
    """-> (kind, area id, current tier)"""
    if not name:
        return ("start", None, 0)
    cands = by_name.get(name) or by_name.get(name + " Map") or []
    on = [a for a in cands if cur in tier.get(a["id"], {})]
    if on:
        return ("map", on[0]["id"], tier[on[0]["id"]][cur])
    maps = [a for a in cands if a.get("is map area") == "1" or a.get("is unique map area") == "1"]
    camp = [a for a in cands if a.get("act") and int(a["act"]) <= 10 and a.get("is map area") != "1" and a.get("is unique map area") != "1"]
    if camp:
        return ("campaign", camp[0]["id"], 0)
    if "Aspirant" in name or "Labyrinth" in name:
        return ("labyrinth", None, 0)
    if name == "Epilogue":
        return ("campaign", None, 0)
    if maps:
        hist = {s: tier[a["id"]].get(s) for a in maps for s in series if s in tier.get(a["id"], {})}
        return ("map-off-atlas", maps[0]["id"], hist)
    return ("unknown", None, 0)


cost = collections.defaultdict(list)
for c in b["costs"]:
    cost[c["option id"]].append(f'{c["amount"]}x {c["name"]}')
rows = []
for o in b["bench"]:
    kind, aid, tr = locate(o.get("recipe unlock location"))
    rows.append({"id": o["id"], "mod_id": o.get("mod id"), "name": o.get("name"), "rank": o.get("rank"), "affix": o.get("affix type"),
                 "location": o.get("recipe unlock location"), "kind": kind, "area_id": aid, "tier_3_29": tr if kind == "map" else None,
                 "tiers": {s: tier.get(aid, {}).get(s) for s in series} if aid and kind.startswith("map") else None,
                 "cost": cost.get(o["id"], []), "classes": o.get("item class categories"), "unveils": o.get("unveils required")})
out = ROOT / "var/cache/wiki/2026-09-19-crafting-bench-unlocks.json"
out.write_text(json.dumps({"fetched": "2026-09-19", "source": "poewiki.net cargo: crafting_bench_options, crafting_bench_options_costs, atlas_nodes, areas",
                           "series": b["series"][-5:], "options": rows}, ensure_ascii=False, indent=0), encoding="utf-8")
print("options", len(rows), collections.Counter(r["kind"] for r in rows))
print("unknown/off:", sorted({(r["location"], r["kind"]) for r in rows if r["kind"] in ("unknown", "map-off-atlas")}))
bucket = collections.Counter()
for r in rows:
    k = r["kind"] if r["kind"] != "map" else ("map T1-10" if r["tier_3_29"] <= 10 else "map T11-16")
    bucket[k] += 1
print(bucket)
cur_cost = collections.Counter()
for r in rows:
    for c in r["cost"]:
        cur_cost[(c.split("x ", 1)[1], "T11+" if (r["kind"] == "map" and r["tier_3_29"] > 10) else "<=T10")] += 1
print("cost currency x bucket:", sorted(cur_cost.items()))
# per location table
loc = collections.defaultdict(list)
for r in rows:
    if r["kind"].startswith("map"):
        loc[r["location"]].append(r)
print("\nlocation | tiers 3.25..3.29 | n options | ranks")
for name, rs in sorted(loc.items(), key=lambda kv: (kv[1][0]["tier_3_29"] or 99, kv[0])):
    ts = rs[0]["tiers"] or {}
    print(f'{name} | {" ".join(str(ts.get(s) or "-") for s in series)} | {len(rs)} | ranks {sorted({r["rank"] for r in rs})}')
# pantheon
print("\nsoul | target area | tiers 3.25..3.29")
for s in sorted(b["pantheon_souls"], key=lambda x: (x["id"], int(x["ordinal"] or 0))):
    aid = s.get("target area id")
    a = areas.get(aid, {})
    ts = tier.get(aid, {})
    print(f'{s["id"]} #{s["ordinal"]} | {a.get("name") or aid} | {" ".join(str(ts.get(x) or "-") for x in series)}')
