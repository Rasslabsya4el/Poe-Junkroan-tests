"""Plain-python check of collect.run_cells with variant rows: python test_run_cells.py"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()  # the project's add-on: the subject of this file


def test_variants(monkeypatch):
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "rows").mkdir()
        (d / "logs").mkdir()
        (d / "args.json").write_text(json.dumps({"slugs": ["bleed_bow", "spark"], "seed": 4, "seeds": 1}))
        for n in ("bleed_bow-s4", "spark-s4", "bleed_bow-s4-no-imbalanced_guard"):
            (d / "rows" / f"{n}.json").write_text(json.dumps({"ok": True, "seconds": 100}))
        (d / "logs" / "spark-s4-no-roiling_tempest.log").write_text("x")
        job = SimpleNamespace(argv=["x", "--tag", "t", "--workers", "2"], cmd="", workers=2, state="running")
        monkeypatch.setattr(addon, "bench_dir_for", lambda j: d)
        r = addon.run_cells(job)
        assert (r["done"], r["total"], r["total_open"]) == (3, 4, True), r
        names = [c["name"] for c in r["cells"] if c.get("variant")]
        assert names == ["Bleed Bow · no Imbalanced Guard", "Spark · no Roiling Tempest"], names
        job.state = "done"
        assert addon.run_cells(job) is None  # #587: a finished job without run_dir or start never takes a tag's folder
        job.run_dir = str(d)
        assert addon.run_cells(job)["total_open"] is False
        job.state = "running"
        plan = [{"slug": "spark", "seed": 4, "variant": "no-x", "stem": s} for s in
                ("bleed_bow-s4-no-imbalanced_guard", "spark-s4-no-roiling_tempest", "spark-s4-no-mind_over_matter")]
        (d / "variants.json").write_text(json.dumps({"planned": plan}))
        r = addon.run_cells(job)
        assert (r["done"], r["total"], r["total_open"]) == (3, 5, False), r
        assert sum(c["state"] == "queued" for c in r["cells"]) == 1
        # #580 rule 3: open only while a base row has not ended; queued cells keep the order of `planned`.
        (d / "variants.json").write_text(json.dumps({"planned": plan, "base_rows": 3, "base_done": 2}))
        r = addon.run_cells(job)
        assert r["total_open"] is True, r
        (d / "variants.json").write_text(json.dumps({"planned": plan[::-1], "base_rows": 3, "base_done": 3}))
        r = addon.run_cells(job)
        assert r["total_open"] is False, r
        assert [c["variant"] for c in r["cells"] if c.get("variant")][0] == "no-mind_over_matter", r["cells"]


def test_stage_and_class():
    """#711: a running build's step = its log's last `step start:` line, never a guessed one; the bar's three groups
    are as wide as their measured shares; class/ascendancy from its reference fixture."""
    shares = {"run": "x", "builds": 1, "groups": {"construction": 0.471, "improvement loop": 0.528, "finish": 0.001},
              "steps": {"skeleton applied": 0.01, "gear pass 1 (empty tree)": 0.09, "tree greedy": 0.1,
                        "gear pass 2 (with tree)": 0.1, "tree rebuilt on gear": 0.1, "jewels": 0.1}}
    keep, addon.stage_shares = addon.stage_shares, lambda: shares
    try:
        with tempfile.TemporaryDirectory() as t:
            log = Path(t) / "x.log"
            log.write_text("author raw 1 CombinedDPS\n")
            assert addon.build_stage(log) == {}, "no start line: no step is named (the row reads «запускается»)"
            old = ["  skeleton applied                 4.9 s  value        3,201",
                   "  config (conservative lane)       1.3 s  value",
                   "  gear pass 1 (empty tree)       2.7 min  value"]
            log.write_text("\n".join(old) + "\n")  # every line ends with its newline, as the writer does (#992)
            assert addon.build_stage(log) == {"after": "подбирает Items"}, "an older pipeline's log: the last ended stage"
            # a recorded log cut right after the "jewels" line, with the new loop lines (#711 row 1)
            lines = ["step start: skeleton applied", old[0], "step start: config (conservative lane)", old[1],
                     "step skipped: rig gear", "step start: gear pass 1 (empty tree)", old[2],
                     "step start: tree greedy", "  tree greedy                    2.3 min  value"]
            log.write_text("\n".join(lines + ["step start: gear pass 2 (with tree)"]) + "\n")
            st = addon.build_stage(log, 0.0, 400.0)
            assert (st["stage"], st["group"], st["bar"]["at"]) == ("construction: gear pass 2 (with tree)", "construction", 0), st
            assert st["bar"]["w"] == [0.471, 0.528, 0.001] and st["bar"]["fill"] == [0.4, 0.0, 0.0], st
            lines += ["step start: jewels", "  jewels                         2.5 min  value", "step skipped: utility links"]
            log.write_text("\n".join(lines) + "\n")
            assert addon.build_stage(log, 0.0, 600.0)["stage"] == "construction: jewels", "the step after jewels has not started"
            lines += ["step start: loop opening", "step start: loop pass 1", "loop pass 1 move refine"]
            log.write_text("\n".join(lines) + "\n")
            st = addon.build_stage(log, 0.0, 600.0)
            assert st["stage"] == "improvement loop, pass 1, refine" and st["move"] == "refine", st
            # construction took 4.9 + 1.3 + 162 + 138 + 150 = 456.2 s, so the loop is expected to take 456.2 * 528 / 471
            spent = 4.9 + 1.3 + 162 + 138 + 150
            assert st["bar"]["fill"] == [1.0, round((600 - spent) / (spent * 0.528 / 0.471), 3), 0.0], st
            log.write_text("\n".join(lines + ["  loop pass 1    4 min  value", "step start: anoint re-pick"]) + "\n")
            assert addon.build_stage(log, 0.0, 900.0)["stage"] == "finish: anoint re-pick"
            log.write_text("\n".join(lines + ["step start: fixed point check", "fixed point check move gear"]) + "\n")
            st = addon.build_stage(log, 0.0, 900.0)
            assert st["stage"] == "fixed point check, gear" and st["bar"]["fill"] == [1.0, 0.98, 1.0], st
    finally:
        addon.stage_shares = keep
    assert addon.build_class("bleed_bow") == {"class": "Duelist", "asc": "Gladiator"}, addon.build_class("bleed_bow")
    assert addon.build_class("summon_raging_spirits") == {"class": "Templar", "asc": "Guardian"}
    assert addon.build_class("no_such_build") == {}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_replay_cells_from_out_lines(tmp_path=None):
    # #683 r5 (c): a replay_bench run: one square per --builds file, done / failed from its .out lines, the first
    # --workers unfinished ones running; an ended run with no output built nothing.
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        for n in ("spark-s4", "smite-s4", "smite-s5", "toxic_rain-s4"):
            (d / f"{n}.pob.txt").write_text("x")
        out = d / "job.out"
        out.write_text("  smite                          646,456 -> 438,262 -32.21% 12 min\n"
                       "  spark                          FAILED boom\n", encoding="utf-8")
        job = SimpleNamespace(argv=["python", "scripts/replay_bench.py", "--builds", str(d / "*.pob.txt"), "--workers", "1"],
                              cmd="python scripts/replay_bench.py", workers=1, state="running", out=str(out),
                              start_ts="2026-10-10T00:00:00+00:00")
        r = addon.run_cells(job)
        got = [(c["name"], c["seed"], c["state"], c.get("took") if c["state"] == "done" else None) for c in r["cells"]]
        assert got == [("Smite", 4, "done", "12 min"), ("Smite", 5, "running", None), ("Spark", 4, "failed", None),
                       ("Toxic Rain", 4, "waiting", None)], got
        assert (r["done"], r["total"], "dir" in r) == (2, 4, False), r
        job.state, job.out = "cancelled", str(d / "none.out")
        assert addon.run_cells(job) is None


def test_running_replay_squares_carry_delta_start_and_expected_time():
    # #683 r5 (owner 10.10 02:1x): a running replay's done square carries its main stat before -> after (the only fact
    # before results.json); a running build's start is rebuilt from the pool order: the first --workers start with the
    # job, a later one when a build ends (first sight of its line, else job start + took); expected = median took.
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        old = addon.REPLAY_SEEN
        addon.REPLAY_SEEN = d / "seen.json"
        try:
            for n in ("a-s4", "b-s4", "c-s4"):
                (d / f"{n}.pob.txt").write_text("x")
            out = d / "job.out"
            out.write_text("  a                              1,288,274 -> 1,381,385 +7.23% 5.3 min\n", encoding="utf-8")
            job = SimpleNamespace(id="j-1", argv=["python", "scripts/replay_bench.py", "--builds", str(d / "*.pob.txt"),
                                                 "--workers", "2"], cmd="python scripts/replay_bench.py", workers=1,
                                  state="running", out=str(out), start_ts="2026-10-10T00:00:00+00:00")
            t0 = addon.parse_ts(job.start_ts).timestamp()
            cells = {c["ref"]: c for c in addon.run_cells(job)["cells"]}
            assert cells["a"]["delta"] == "1,288,274 -> 1,381,385 (+7.23 %)", cells["a"]
            assert (cells["b"]["state"], cells["b"]["started_est"], cells["b"]["expect_s"]) == ("running", int(t0), 318), cells["b"]
            # c is the third in path order with 2 workers: it starts when a ends (first wave: start + took)
            assert (cells["c"]["state"], cells["c"]["started_est"]) == ("running", int(t0 + 318)), cells["c"]
            assert "_s" not in cells["a"]
        finally:
            addon.REPLAY_SEEN = old


def _xml(dps, life):
    return ('<?xml version="1.0" encoding="UTF-8"?><PathOfBuilding><Build mainSocketGroup="1" level="78" '
            'className="Duelist" ascendClassName="Slayer">'
            f'<PlayerStat value="{dps}" stat="CombinedDPS"/><PlayerStat value="{life}" stat="Life"/></Build>'
            '<Skills activeSkillSet="1"><SkillSet id="1"><Skill mainActiveSkill="1"><Gem nameSpec="Smite" skillId="Smite"/>'
            '</Skill></SkillSet></Skills></PathOfBuilding>')


def test_replay_square_opens_its_stats_panel():
    # #683 r5: an ended replay run's square: `dir` = its artifacts/replay/<stamp> (named by the .out `report:` line);
    # `build` compares the final build with the author's of the benchmark run it started from, plus its before -> after.
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        old = addon.REPO, addon.BENCH
        addon.REPO, addon.BENCH = root, root / "artifacts" / "benchmark"
        try:
            bench = addon.BENCH / "20261005-1220-gate"
            (bench / "author").mkdir(parents=True)
            (bench / "rows").mkdir()
            (bench / "smite-s4.pob.txt").write_text("x")
            (bench / "author" / "smite.json").write_text(json.dumps({"state_xml": _xml(561000, 4000)}))
            (bench / "rows" / "smite-s4.json").write_text(json.dumps({"author_pobbin_url": "https://pobb.in/abc"}))
            rep = root / "artifacts" / "replay" / "20261010-0046-b632"
            (rep / "builds").mkdir(parents=True)
            (rep / "builds" / "smite.xml").write_text(_xml(438262, 5000), encoding="utf-8")
            (rep / "results.json").write_text(json.dumps({"move": "loop", "rows": [
                {"ok": True, "reference": "smite", "source": r"artifacts\benchmark\20261005-1220-gate\smite-s4.pob.txt",
                 "stat": "CombinedDPS", "value_before": 646456.0, "value_after": 438262.0, "gain_percent": -32.2056,
                 "seconds": 700, "final_build": "artifacts/replay/20261010-0046-b632/builds/smite.xml"}]}))
            out = root / "job.out"
            out.write_text("  smite                          646,456 -> 438,262 -32.21% 12 min\n"
                           r"report: C:\x\snapshots\20261010-0046-b632\artifacts\replay\20261010-0046-b632\report.md" "\n",
                           encoding="utf-8")
            job = SimpleNamespace(argv=["python", "scripts/replay_bench.py", "--builds", str(bench / "*.pob.txt")],
                                  cmd="python scripts/replay_bench.py", workers=1, state="done", out=str(out))
            p = addon.run_cells(job)
            assert p["dir"] == str(rep), p
            b = addon.build(p["dir"], "smite", "4", "")
            assert (b["skill"], b["class"], b["author"], b["author_pobbin_url"]) == ("Smite", "Duelist / Slayer", True, "https://pobb.in/abc"), b
            main = b["groups"][0]["rows"][0]
            assert main[1:] == ["438k", "561k", 78], main
            assert b["note"].startswith("replay loop: ") and "646k -> 438k (-32.21 %)" in b["note"], b["note"]
            assert addon.build(p["dir"], "smite", "5", "")["error"]== "этого билда нет в итогах рана"
        finally:
            addon.REPO, addon.BENCH = old


def test_request_build_opens_its_panel_and_pob():
    # #730: a build of a `junkroan build` request queued for reading: its folder has `<ref>.pob.txt` beside report.md
    # and no rows/; the panel = PoB's own stats of that code, no author; Open PoB goes by the queue row's pobb.in id.
    from junkroan.pob.session import encode_import_code

    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        old = addon.REPO, addon.READINGS, addon.POB_EXE, addon._launch_pob
        launched = []
        addon.REPO, addon.READINGS = root, root / "artifacts" / "readings" / "queue.json"
        addon.POB_EXE, addon._launch_pob = Path(sys.executable), lambda link=None: launched.append(link)
        try:
            ref = "01 marauder_chieftain_imperial_staff"
            req = root / "artifacts" / "search-volcanic_fissure" / "20261010-0221"
            req.mkdir(parents=True)
            xml = _xml(231397, 4513).replace('<PlayerStat value="231397"', '<PlayerStat value="216282" stat="TotalDotDPS"/>'
                                                                         '<PlayerStat value="231397"')
            (req / f"{ref}.pob.txt").write_text(encode_import_code(xml), encoding="utf-8")
            (req / "report.md").write_text("# Search: Volcanic Fissure\n", encoding="utf-8")
            addon.READINGS.parent.mkdir(parents=True)
            addon.READINGS.write_text(json.dumps({"updated": None, "rows": [
                {"run_dir": "artifacts/search-volcanic_fissure/20261010-0221", "ref": ref, "seed": 2, "variant": "",
                 "pobbin_id": "vINWTHiqpsye", "ratio_pct": None, "metric": "TotalDotDPS", "ours": 216282, "life": 4513,
                 "rank": 1, "audit": "0 errors / 3 warnings", "floors": "ok", "run_name": "Volcanic Fissure Chieftain"}]}))
            b = addon.build(str(req), ref, "2", "")
            assert "error" not in b, b
            assert (b["skill"], b["author"], b["pobbin_id"], b["author_pobbin_url"]) == ("Smite", False, "vINWTHiqpsye", None), b
            assert b["groups"][0]["title"] == "Main skill" and b["groups"][0]["rows"][0][1] == "216k", b["groups"][0]
            assert b["note"] == "rank 1 · audit: 0 errors / 3 warnings · floors: ok", b["note"]
            o = addon.openpob(str(req), ref, "2", "ours", "")
            assert o == {"ok": True, "link": "pob://pobbin/vINWTHiqpsye", "where": "pobb.in/vINWTHiqpsye"}, o
            assert launched == ["pob://pobbin/vINWTHiqpsye"], launched
            assert "error" in addon.openpob(str(req), ref, "2", "author", "")
            assert addon.build(str(req), "09 nothing", "2", "")["error"] == "билд не досчитан: итогового PoB нет"
        finally:
            addon.REPO, addon.READINGS, addon.POB_EXE, addon._launch_pob = old


def test_crit_multiplier_reads_as_pob_shows_it():
    # #1013 row 2: PoB saves CritMultiplier as a ratio (<PlayerStat value="1.5">) and its sidebar shows 150%
    # (BuildDisplayStats.lua `pc = true`); the panel showed "2%". Read from the repo's PoB when the owner's is absent.
    from junkroan.pob.session import encode_import_code

    crit = '<PlayerStat value="{}" stat="CritMultiplier"/><PlayerStat value="9.4" stat="CritChance"/></Build>'
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "20261013-0101-P2-core-3"
        (d / "rows").mkdir(parents=True)
        (d / "author").mkdir()
        (d / "spark-s5.pob.txt").write_text(encode_import_code(_xml(70462, 4032).replace("</Build>", crit.format(1.5))))
        (d / "rows" / "spark-s5.json").write_text(json.dumps({"stat": "CombinedDPS", "author_regime": "r"}))
        (d / "author" / "spark-r.json").write_text(json.dumps({"state_xml": _xml(128924, 4007).replace("</Build>", crit.format(1.82))}))
        old = addon.POB_DISPLAY, addon._PC, addon._LABELS
        addon.POB_DISPLAY, addon._PC, addon._LABELS = Path(t) / "no PoB here.lua", None, None
        try:
            b = addon.build(str(d), "spark", "5", "")
            rows = {r[0]: r for r in b["groups"][0]["rows"]}
            assert rows["Crit Multiplier"][1:] == ["150%", "182%", None], rows
            assert rows["Effective Crit Chance"][1:3] == ["9%", "9%"], rows  # a percent PoB saves as is stays as is
            assert addon.pc_stats() == {"CritMultiplier"}, addon.pc_stats()
        finally:
            addon.POB_DISPLAY, addon._PC, addon._LABELS = old


def test_run_kind_from_the_command():
    # #683 r5: what a run executes, read from its command line; an unknown script reads as no kind, never guessed.
    k = lambda cmd, argv=(): addon.run_kind(SimpleNamespace(cmd=cmd, argv=list(argv)))
    assert k("py -3.12 scripts/benchmark.py --set smoke --seed 7") == "benchmark"
    assert k("C:/Python312/junkroan.exe scripts/replay_bench.py --builds x --against y") == "replay"
    assert k("python -m pytest -q -rfE") == "tests"
    assert k('junkroan build --skill "Raise Spectre"') == "request"
    assert k("python -m junkroan.cli build --skill Fireball") == "request"
    assert k("python scripts/build_from_skeleton.py --from-fixture bleed_bow") == ""
    assert k("python scripts/probe_ramp_audit.py --build bleed_bow-s4") == ""


def test_replay_cell_whose_stem_has_a_space(monkeypatch):
    # w1178 (#1178): a `junkroan build` file is named `NN <slug>.pob.txt` (a space); its `.out` line belongs to the whole
    # stem, not its first word; a stem with no -s<seed> takes the job's --seed.
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        monkeypatch.setattr(addon, "REPLAY_SEEN", d / "seen.json")
        (d / "01 templar_inquisitor_demon_dagger.pob.txt").write_text("x", encoding="utf-8")
        out = d / "job.out"
        out.write_text("  01 templar_inquisitor_demon_dagger 396,197 -> 396,197 +0.00% 6.3 min\n", encoding="utf-8")
        job = SimpleNamespace(id="j-1", argv=["python", "scripts/replay_bench.py", "--builds", str(d / "*.pob.txt"),
                                             "--seed", "2", "--workers", "1"], cmd="python scripts/replay_bench.py",
                              workers=1, state="running", out=str(out), start_ts="2026-10-10T00:00:00+00:00")
        r = addon.run_cells(job)
        assert (r["done"], r["total"]) == (1, 1), r
        (c,) = r["cells"]
        assert (c["ref"], c["state"], c["took"], c["delta"], c["seed"]) == (
            "01 templar_inquisitor_demon_dagger", "done", "6.3 min", "396,197 -> 396,197 (+0.00 %)", 2), c


def test_replay_failed_cell_whose_stem_has_a_space(monkeypatch):
    # w1178 row 2: a FAILED line of a spaced stem -> failed; a longer stem that starts with a shorter one keeps its own line.
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        monkeypatch.setattr(addon, "REPLAY_SEEN", d / "seen.json")
        for n in ("01 spark", "01 spark mind", "02 smite x"):
            (d / f"{n}.pob.txt").write_text("x", encoding="utf-8")
        out = d / "job.out"
        out.write_text("  01 spark FAILED boom\n"
                       "  01 spark mind 1 -> 2 +1.00% 1 min\n", encoding="utf-8")
        job = SimpleNamespace(id="j-2", argv=["python", "scripts/replay_bench.py", "--builds", str(d / "*.pob.txt"),
                                             "--seed", "2", "--workers", "1"], cmd="python scripts/replay_bench.py",
                              workers=1, state="running", out=str(out), start_ts="2026-10-10T00:00:00+00:00")
        r = addon.run_cells(job)
        got = {c["ref"]: (c["state"], c["seed"]) for c in r["cells"]}
        assert got == {"01 spark": ("failed", 2), "01 spark mind": ("done", 2), "02 smite x": ("running", 2)}, got
        assert (r["done"], r["total"]) == (2, 3), r
