"""Synthetic checks of collect.cost_cut / period_window / mod_calls: pytest test_cost_cut.py"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"C:\Coding\poe-junkroan-v2")
sys.path.insert(0, r"C:\Coding\poe-junkroan-v2\scripts")
import collect  # noqa: E402
import token_meter as tm  # noqa: E402

PRICES = {"m1": {"input": 1.0, "cache_write": 2.0, "cache_read": 0.5, "output": 10.0},
          "m2": {"input": 3.0, "cache_write": 6.0, "cache_write_1h": 12.0, "cache_read": 0.3, "output": 15.0}}
UTC = timezone.utc
UNTIL = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
SINCE = UNTIL - timedelta(days=7)
_n = [0]


def turn(session="s1", model="m1", ts=None, inp=0, cw=0, cr=0, out=0, cw1h=0, title=None, agent=None, atype=None,
         issue=None, shares=None):
    _n[0] += 1
    return tm.Turn(session_id=session, agent_id=agent, agent_type=atype, message_id=f"m{_n[0]}", model=model,
                   timestamp=ts or UNTIL - timedelta(hours=1), input_tokens=inp, cache_creation_input_tokens=cw,
                   cache_read_input_tokens=cr, output_tokens=out, issue=issue, title=title, turn_index=_n[0],
                   issue_shares=shares, cache_creation_1h_tokens=cw1h)


def cut(turns, mods=(), **kw):
    kw.setdefault("since", SINCE)
    kw.setdefault("until", UNTIL)
    return collect.cost_cut(turns, PRICES, tm, mods=mods, **kw)


def close(a, b):
    return abs(a - b) < 1e-9


def test_kinds():
    t = turn(inp=1_000_000, cw=500_000, cr=2_000_000, out=100_000)
    r = cut([t])
    assert close(r["total"]["cost_usd"], 4.0) and close(tm.turn_cost(t, PRICES), 4.0)
    assert [(k["key"], round(k["cost_usd"], 9)) for k in r["by_kind"]] == [
        ("input", 1.0), ("cache_write", 1.0), ("cache_read", 1.0), ("output", 1.0)]
    assert r["total"]["tokens"] == {"input": 1_000_000, "cache_write": 500_000, "cache_read": 2_000_000, "output": 100_000}


def test_one_hour():
    t = turn(model="m2", cw=1_000_000, cw1h=400_000)
    r = cut([t])
    assert close(r["total"]["cost_usd"], 8.4) and close(tm.turn_cost(t, PRICES), 8.4)
    assert close(r["by_kind"][1]["cost_usd"], 8.4)


def scene_turns():
    ts = UNTIL - timedelta(hours=2)
    out = [turn("b1", title="Brain: PoB", inp=1_000_000, ts=ts), turn("b2", title="Brain: PoB", inp=1_000_000, ts=ts),
           turn("o1", title="orch Poe-Junkroan #5 #6", out=100_000, shares={5: 0.5, 6: 0.5}),
           turn("o2", title="orch #7", out=100_000, issue=7),
           turn("k1", title="keymaster: job_failed j-1", cr=1_000_000),
           turn("u1", model="m2", inp=100_000, issue=5)]
    # subagents carry no title of their own
    out += [turn("o1", agent="a1", atype="worker", out=50_000, issue=5),
            turn("o1", agent="a2", atype="worker", out=50_000, issue=5),
            turn("o1", agent="a3", atype="researcher-find", inp=1_000_000, issue=5),
            turn("o2", agent="a4", atype="worker", out=10_000, issue=7)]
    return out


def test_who():
    r = cut(scene_turns())
    who = {w["key"]: w for w in r["by_who"]}
    assert (who["Brain: PoB"]["sessions"], who["Brain: PoB"]["kind"]) == (2, "chat")
    assert (who["ORCH"]["sessions"], who["ORCH"]["kind"], who["ORCH"]["turns"]) == (2, "orch", 6)
    assert who["keymaster"]["kind"] == "keymaster" and who[""]["kind"] == "untitled"
    # sub cost: 0.5 + 0.5 + 1.0 + 0.1 = 2.1, inside the ORCH row (0.001*... own turns 1.0 + 1.0 + 2.1)
    assert close(who["ORCH"]["sub_usd"], 0.5 + 0.5 + 1.0 + 0.1)
    assert close(who["ORCH"]["cost_usd"], 1.0 + 1.0 + 2.1)
    roles = {x["key"]: x for x in r["by_role"]}
    assert (roles["worker"]["n"], roles["researcher-find"]["n"]) == (3, 1)
    assert close(sum(x["cost_usd"] for x in r["by_role"] if x["group"] == "sub"), sum(w["sub_usd"] for w in r["by_who"]))


def role_scene():
    # the scene + a brain's two non-role subagents, 3 one-turn `<synthetic>` ORCH sessions, an alias-titled brain
    out = scene_turns()
    out += [turn("b1", agent="e1", atype="effort-high", inp=2_000_000), turn("b1", agent="e1", atype="effort-high", inp=1_000_000),
            turn("b2", agent="w1", atype="web-fetch", inp=500_000),
            turn("b3", title="Настройка оркестрации", out=100_000),
            turn("m1", title="MODS", inp=4_000_000), turn("m1", agent="mw", atype="worker", out=200_000)]
    out += [turn(f"dead{i}", model="<synthetic>", title="orch Poe-Junkroan #5") for i in range(3)]
    return out


def test_roles_one_table():
    r = cut(role_scene(), mods=collect.mod_calls(mods_file(), "monitor"))
    roles = {x["key"]: x for x in r["by_role"]}
    assert set(roles) == {"brain", "orch", "keymaster", "other_chat", "worker", "researcher-find", "other_sub", "mod"}
    # (group, units, $): a main role = its sessions' OWN turns; the dead ORCH sessions are no sessions
    assert [(k, roles[k]["group"], roles[k]["n"], round(roles[k]["cost_usd"], 9)) for k in
            ("brain", "orch", "keymaster", "other_chat", "worker", "researcher-find", "other_sub", "mod")] == [
        ("brain", "main", 3, 3.0), ("orch", "main", 2, 2.0), ("keymaster", "main", 1, 0.5),
        ("other_chat", "main", 2, 4.3), ("worker", "sub", 4, 3.1), ("researcher-find", "sub", 1, 1.0),
        ("other_sub", "sub", 2, 3.5), ("mod", "mod", 2, 2.0)]
    assert [(t["key"], t["agents"], round(t["cost_usd"], 9)) for t in roles["other_sub"]["types"]] == [
        ("effort-high", 1, 3.0), ("web-fetch", 1, 0.5)]
    assert roles["orch"]["turns"] == 5 and roles["worker"]["types"] == []
    assert close(sum(x["cost_usd"] for x in r["by_role"]), r["total"]["cost_usd"])
    assert sum(x["tokens"] for x in r["by_role"]) == sum(r["total"]["tokens"].values())
    assert sum(x["turns"] for x in r["by_role"]) == r["total"]["turns"]


def test_spawner():
    r = cut(role_scene(), mods=collect.mod_calls(mods_file(), "monitor"))
    sp = {x["key"]: x for x in r["by_spawner"]}
    assert set(sp) == {"brain", "orch", "keymaster", "other_chat"}
    o = sp["orch"]
    assert (o["sessions"], o["sub"]["agents"], o["own"]["turns"], o["chats"]) == (2, 4, 5, [])
    assert close(o["own"]["cost_usd"], 2.0) and close(o["sub"]["cost_usd"], 2.1) and close(o["cost_usd"], 4.1)
    assert [(x["key"], x["agents"], round(x["cost_usd"], 9), x["tokens"]) for x in o["roles"]] == [
        ("worker", 3, 1.1, 110_000), ("researcher-find", 1, 1.0, 1_000_000)]
    b = sp["brain"]
    assert (b["sessions"], b["sub"]["agents"], b["chats"]) == (3, 2, ["Brain: PoB", "Настройка оркестрации"])
    assert close(b["own"]["cost_usd"], 3.0) and close(b["sub"]["cost_usd"], 3.5)
    assert [(x["key"], x["agents"]) for x in b["roles"]] == [("other_sub", 2)]
    assert [(t["key"], t["agents"]) for t in b["roles"][0]["types"]] == [("effort-high", 1), ("web-fetch", 1)]
    assert (sp["keymaster"]["sub"]["agents"], sp["keymaster"]["roles"]) == (0, [])
    assert (sp["other_chat"]["sessions"], sp["other_chat"]["chats"]) == (2, ["MODS"])
    # every spawner = own + sub; the spawners and the mods together are the total
    for x in r["by_spawner"]:
        assert close(x["own"]["cost_usd"] + x["sub"]["cost_usd"], x["cost_usd"]), x["key"]
        assert close(sum(y["cost_usd"] for y in x["roles"]), x["sub"]["cost_usd"]), x["key"]
        assert sum(y["agents"] for y in x["roles"]) == x["sub"]["agents"], x["key"]
    assert close(sum(x["cost_usd"] for x in r["by_spawner"]) + sum(x["cost_usd"] for x in r["by_mod"]), r["total"]["cost_usd"])
    # #1013 row 4: by_day holds the days the log has records for; `days` is the window's length; the days add to the total
    assert r["days"] == 8 and len(r["by_day"]) <= 8
    assert close(sum(d["cost_usd"] for d in r["by_day"]), r["total"]["cost_usd"])


def test_by_mod():
    p = mods_file()
    ts = (UNTIL - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    q = p.with_name("unslop.jsonl")
    q.write_text("\n".join(json.dumps({"ts": ts, "model": m, "input_tokens": 1_000_000}) for m in ("m1", "m2", "m2")),
                 encoding="utf-8")
    r = cut([turn(inp=1_000_000, title="X")], mods=collect.mod_calls(p, "monitor") + collect.mod_calls(q, "unslop"))
    assert [(m["key"], m["model"], m["calls"], m["unpriced_calls"], m["tokens"], round(m["cost_usd"], 9)) for m in r["by_mod"]] == [
        ("monitor", "m1", 2, 1, 1_100_505, 2.0), ("unslop", "m2", 2, 0, 2_000_000, 6.0), ("unslop", "m1", 1, 0, 1_000_000, 1.0)]
    mods = {w["key"]: w for w in r["by_who"] if w["kind"] == "mod"}
    for k in ("monitor", "unslop"):
        assert close(sum(m["cost_usd"] for m in r["by_mod"] if m["key"] == k), mods[k]["cost_usd"])
    role = next(x for x in r["by_role"] if x["key"] == "mod")
    assert role["n"] == 5 and close(role["cost_usd"], 9.0)


def test_window_by_turn():
    r = cut([turn("s", ts=UNTIL - timedelta(days=8), inp=1_000_000, title="X"),
             turn("s", ts=UNTIL - timedelta(hours=1), inp=1_000_000, title="X")])
    assert r["total"]["turns"] == 1 and close(r["total"]["cost_usd"], 1.0)
    assert turn(ts=UNTIL + timedelta(hours=1)) and cut([turn(ts=UNTIL + timedelta(hours=1))])["total"]["turns"] == 0


def test_local_days():
    tz = timezone(timedelta(hours=3))
    now = datetime(2026, 10, 10, 15, 0, tzinfo=tz)
    since, until = collect.period_window(7, now)
    assert since == datetime(2026, 10, 4, 0, 0, tzinfo=tz) and until == now
    assert collect.period_window(1, now)[0] == datetime(2026, 10, 10, 0, 0, tzinfo=tz)
    r = collect.cost_cut([turn(ts=datetime(2026, 10, 9, 22, 30, tzinfo=UTC), inp=1_000_000)], PRICES, tm,
                         since=since, until=until)
    keys = [d["key"] for d in r["by_day"]]
    assert keys == ["2026-10-10"]  # #1013 row 4: a day the log holds nothing for is no row (it was drawn as $0.00)
    assert r["by_day"][0]["turns"] == 1 and close(r["by_day"][0]["cost_usd"], 1.0)
    assert r["days"] == 7  # the window's length stays: the per-day rates divide by it


def test_a_day_the_log_holds_nothing_for_is_no_row():
    """#1013 row 4: a day with no record is no row of by_day; a day whose records are all zero-token notices (the
    `<synthetic>` lines, 08.10 on the PC) is a row of $0.00 that really was 0; `days` = the window's length."""
    tz = timezone(timedelta(hours=2))
    since, until = collect.period_window(7, datetime(2026, 10, 14, 9, 0, tzinfo=tz))
    r = collect.cost_cut([turn(ts=datetime(2026, 10, 13, 10, 0, tzinfo=tz), inp=1_000_000),
                          turn(ts=datetime(2026, 10, 8, 10, 0, tzinfo=tz))],  # no tokens, cost 0
                         PRICES, tm, since=since, until=until)
    assert [d["key"] for d in r["by_day"]] == ["2026-10-13", "2026-10-08"]
    assert r["by_day"][1]["turns"] == 1 and r["by_day"][1]["cost_usd"] == 0.0 and r["by_day"][1]["tokens"] == 0
    assert r["days"] == 7


def test_month_percent_is_against_a_month_limit(tmp_path, monkeypatch):
    """#1013 row 5: the limit of a period = the weekly limit x max(days, 7) / 7; a day and a week keep the weekly
    limit, a month (30 days) is against 30/7 of it. The plan price is pinned here (#1094): a temp config holding 16.5."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "orchestration.json").write_text(json.dumps({"limit_usd_per_pct": 16.5}), encoding="utf-8")
    monkeypatch.setattr(collect, "REPO", tmp_path)
    for days in (1, 7, 30):
        since, until = collect.period_window(days, UNTIL)
        r = collect.cost_cut([turn(ts=UNTIL - timedelta(hours=1), inp=1_000_000)], PRICES, tm, since=since, until=until)
        assert close(r["total"]["cost_usd"], 1.0)
        # percent units: $1 against 100 % = 16.5 x 100 x max(days, 7) / 7 dollars
        assert close(r["total"]["limit_pct"], 1.0 / (16.5 * max(days, 7) / 7))
        assert r["total"]["limit_days"] == max(days, 7)


def test_issues():
    ts = [turn(inp=1_000_000, issue=5), turn(inp=1_000_000, shares={6: 0.25, 7: 0.75}), turn(inp=1_000_000, title="x")]
    r = cut(ts, top_issues=2)
    assert [(i["number"], i["turns"], i["tokens"]) for i in r["by_issue"]] == [(5, 1, 1_000_000), (7, 1, 750_000)]
    assert close(r["by_issue"][1]["cost_usd"], 0.75)
    assert (r["issue_rest"]["n"], r["issue_rest"]["tokens"]) == (1, 250_000) and close(r["issue_rest"]["cost_usd"], 0.25)
    assert r["no_issue"]["turns"] == 1 and close(r["no_issue"]["cost_usd"], 1.0)


def test_unpriced():
    r = cut([turn(model="<synthetic>", inp=123, out=7), turn(inp=1_000_000)])
    assert close(r["total"]["cost_usd"], 1.0) and r["total"]["unpriced_turns"] == 1
    assert r["total"]["tokens"]["input"] == 1_000_123 and r["total"]["tokens"]["output"] == 7
    row = next(m for m in r["by_model"] if m["key"] == "<synthetic>")
    assert (row["unpriced_turns"], row["tokens"], row["cost_usd"]) == (1, 130, 0.0)


def mods_file():
    d = tempfile.mkdtemp()
    p = Path(d) / "usage.jsonl"
    ts = (UNTIL - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    p.write_text("\n".join([
        json.dumps({"ts": ts, "model": "m1", "input_tokens": 1_000_000, "output_tokens": 100_000}),
        json.dumps({"ts": ts, "model": "m1", "input_tokens": 500, "output_tokens": 5, "via": "fork"}),
        "{broken"]), encoding="utf-8")
    return p


def test_mods():
    p = mods_file()
    calls = collect.mod_calls(p, "monitor")
    assert len(calls) == 2 and [c["priced"] for c in calls] == [True, False]
    assert collect.mod_calls(p.with_name("nope.jsonl"), "x") == []
    r = cut([], mods=calls)
    w = r["by_who"][0]
    assert (w["key"], w["kind"], w["sessions"], w["turns"]) == ("monitor", "mod", 0, 2)
    m = r["by_model"][0]
    assert m["key"] == "m1" and m["turns"] == 2 and m["unpriced_turns"] == 1 and close(m["cost_usd"], 2.0)
    assert r["no_issue"]["turns"] == 2


def test_invariant():
    r = cut(scene_turns(), mods=collect.mod_calls(mods_file(), "monitor"), top_issues=2)
    tot = r["total"]["cost_usd"]
    assert tot > 0
    for k in ("by_who", "by_model", "by_day", "by_kind"):
        assert close(sum(x["cost_usd"] for x in r[k]), tot), k
        assert sum(x["tokens"] for x in r[k]) == sum(r["total"]["tokens"].values()), k
    assert close(sum(x["cost_usd"] for x in r["by_issue"]) + r["issue_rest"]["cost_usd"] + r["no_issue"]["cost_usd"], tot)


def test_untitled():
    # a session with no custom-title line carries its first message as the title: one `untitled` row, subagents too
    ts = [turn("a1", title="MODS", inp=1_000_000), turn("x1", title="reply with the single word ok", inp=2_000_000),
          turn("x2", title="Bash command=git fetch", inp=1_000_000),
          turn("x2", title=None, inp=1_000_000, agent="ag1", atype="worker")]
    r = cut(ts, titled={"a1"})
    assert [(w["key"], w["kind"], round(w["cost_usd"], 9), w["sessions"]) for w in r["by_who"]] == [
        ("", "untitled", 4.0, 2), ("MODS", "chat", 1.0, 1)]
    assert close(r["by_who"][0]["sub_usd"], 1.0)
    assert [w["key"] for w in cut(ts)["by_who"]] == ["reply with the single word ok", "Bash command=git fetch", "MODS"]
    d = Path(tempfile.mkdtemp())
    (d / "s-yes.jsonl").write_text('{"type":"user","message":{}}\n{"type":"custom-title","customTitle":"MODS"}\n', encoding="utf-8")
    (d / "s-no.jsonl").write_text('{"type":"user","message":{"content":"say {\\"type\\":\\"custom-title\\"}"}}\n', encoding="utf-8")
    assert collect.titled_sessions([d / "s-yes.jsonl", d / "s-no.jsonl", d / "gone.jsonl"]) == {"s-yes"}


def test_role_model_sums():
    r = cut(scene_turns() + [turn("z1", model="<synthetic>", title="orch #9")],
            mods=collect.mod_calls(mods_file(), "monitor"))
    rows = r["by_role_model"]
    assert close(sum(x["cost_usd"] for x in rows), r["total"]["cost_usd"])
    assert sum(x["tokens"] for x in rows) == sum(r["total"]["tokens"].values())
    assert sum(x["turns"] for x in rows) == r["total"]["turns"]
    for sp in r["by_spawner"]:
        mine = [x for x in rows if x["group"] == "main" and x["role"] == sp["key"]]
        assert close(sum(x["spawned"]["cost_usd"] for x in mine), sp["sub"]["cost_usd"]), sp["key"]
        assert sum(x["spawned"]["agents"] for x in mine) == sp["sub"]["agents"], sp["key"]
        assert sum(x["led"] for x in mine) == sp["sessions"], sp["key"]
    for ro in r["by_role"]:
        mine = [x for x in rows if (x["group"] == "mod") == (ro["key"] == "mod") and (ro["key"] == "mod" or x["role"] == ro["key"])]
        assert close(sum(x["cost_usd"] for x in mine), ro["cost_usd"]), ro["key"]
    by = {(x["role"], x["model"]): x for x in rows}
    assert (by[("monitor", "m1")]["group"], by[("monitor", "m1")]["n"], by[("monitor", "m1")]["unpriced_turns"]) == ("mod", 2, 1)
    assert (by[("worker", "m1")]["n"], by[("researcher-find", "m1")]["n"]) == (3, 1)
    # the dead one-turn session: a turn, no unit, no day, no ticket fields without `closed`
    z = by[("orch", "<synthetic>")]
    assert (z["n"], z["led"], z["turns"], z["first"], z["closed"]) == (0, 0, 1, None, None)


def test_role_on_two_models():
    early, late = UNTIL - timedelta(days=5), UNTIL - timedelta(days=1)
    ts = [turn("o1", "m2", ts=early, title="orch #5 #6", out=100_000), turn("o1", "m2", ts=early, title="orch #5 #6", out=100_000),
          turn("o1", "m1", agent="a1", atype="worker", ts=early, out=50_000),
          turn("o1", "m1", agent="a2", atype="worker", ts=early, out=50_000),
          turn("o2", "m1", ts=late, title="orch #7", out=100_000),
          turn("o2", "m1", agent="a3", atype="worker-strong", ts=late, out=10_000),
          # o3 changed model: counted under each, led by the one of most turns
          turn("o3", "m1", ts=late, title="orch #8", out=100_000), turn("o3", "m1", ts=late, title="orch #8", out=100_000),
          turn("o3", "m2", ts=late, title="orch #8", out=100_000),
          turn("o3", "m2", agent="a4", atype="worker", ts=late, out=100_000)]
    r = cut(ts, closed=({"o1": {5, 6}, "o3": {8}}, {"o1", "o3"}))
    by = {(x["role"], x["model"]): x for x in r["by_role_model"]}
    m2, m1 = by[("orch", "m2")], by[("orch", "m1")]
    assert (m2["n"], m2["led"], m2["turns"]) == (2, 1, 3) and close(m2["cost_usd"], 4.5)
    assert (m1["n"], m1["led"], m1["turns"]) == (2, 2, 3) and close(m1["cost_usd"], 3.0)
    assert (m2["spawned"]["agents"], m1["spawned"]["agents"]) == (2, 2)
    assert close(m2["spawned"]["cost_usd"], 1.0) and close(m1["spawned"]["cost_usd"], 0.1 + 1.5)
    assert (m2["ended"], m2["closed"], m1["ended"], m1["closed"]) == (1, 2, 1, 1)
    assert (m2["first"], m2["last"]) == ("2026-10-05", "2026-10-09")
    assert (m1["first"], m1["last"]) == ("2026-10-09", "2026-10-09")
    assert (by[("worker", "m1")]["n"], by[("worker", "m2")]["n"], by[("worker-strong", "m1")]["n"]) == (2, 1, 1)
    assert by[("worker", "m1")]["closed"] is None and by[("worker", "m1")]["led"] == 0


def test_lead_outside_period():
    # the main turns stand before the period, its subagent inside: the spawn goes to the model of all its turns
    ts = [turn("o1", "m2", ts=SINCE - timedelta(hours=1), title="orch #5", out=100_000),
          turn("o1", "m1", agent="a1", atype="worker", out=50_000)]
    r = cut(ts)
    by = {(x["role"], x["model"]): x for x in r["by_role_model"]}
    lead = by[("orch", "m2")]
    assert (lead["n"], lead["led"], lead["turns"], lead["spawned"]["agents"]) == (0, 1, 0, 1)
    assert close(lead["spawned"]["cost_usd"], 0.5) and close(lead["cost_usd"], 0.0)


def test_brain_by_title_start():
    # the brain title is the setting (config/orchestration.json brain_chat_title, the one token_meter reads), not a literal
    brain = json.loads((tm.ROOT / "config" / "orchestration.json").read_text(encoding="utf-8"))["brain_chat_title"]
    ts = [turn("b1", title=brain, inp=1_000_000), turn("b2", title=brain.lower(), inp=1_000_000),
          turn("x1", title="Wayfinder skill for the Brain role", inp=1_000_000),
          turn("x2", title="/wayfinder #63 a pasted hand-off: the brain decides", inp=1_000_000)]
    r = cut(ts)
    by = {x["key"]: x for x in r["by_role"]}
    assert (by["brain"]["n"], by["other_chat"]["n"]) == (2, 2)
    assert next(x for x in r["by_spawner"] if x["key"] == "brain")["chats"] == sorted([brain, brain.lower()])


def test_issue_rows_carry_title_and_state():
    """#683 r5: a ticket the turns reference gets what a row needs to draw by itself (title, open, reason, state)."""
    ts = [turn(inp=1_000_000, issue=5), turn(inp=1_000_000, issue=6), turn(inp=1_000_000, issue=9)]
    info = {5: {"title": "Done one", "open": False, "reason": "COMPLETED"},
            6: {"title": "Dropped one", "open": False, "reason": "NOT_PLANNED"}}
    r = cut(ts, issue_info=info)
    rows = {x["number"]: x for x in r["by_issue"]}
    assert (rows[5]["title"], rows[5]["open"], rows[5]["reason"], rows[5]["state"]) == ("Done one", False, "COMPLETED", "closed")
    assert (rows[6]["title"], rows[6]["reason"]) == ("Dropped one", "NOT_PLANNED")
    assert "title" not in rows[9]  # unknown to the list: the bare row, as before


TIERED = {"h": {"tiers": {"prompt_bound": 100_000,
                          "up_to": {"input": 0.1, "output": 0.5, "cache_write": 0.125, "cache_read": 0.01},
                          "above": {"input": 0.5, "output": 2.5, "cache_write": 0.625, "cache_read": 0.05}}}}


def mod_call(inp, cr=0, out=0):
    return {"key": "unslop", "ts": UNTIL - timedelta(hours=1), "model": "h", "input": inp, "cache_write": 0,
            "cache_read": cr, "output": out, "priced": True}


def test_tiers_only_price_mod_call():
    """D1 (#793): a `tiers`-only entry through cost_cut's mod path raised KeyError('input')."""
    r = collect.cost_cut([], TIERED, tm, since=SINCE, until=UNTIL,
                         mods=[mod_call(1_000_000, out=1_000_000), mod_call(200_000)])
    assert close(r["total"]["cost_usd"], (0.5 + 2.5) + 200_000 * 0.5 / 1e6)


