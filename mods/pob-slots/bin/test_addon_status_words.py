"""#985 d2: the status word a build run shows, replayed from three recorded logs (plain python, or pytest on this file):

    python mods/pob-slots/bin/test_addon_status_words.py

The fixtures are real lines, kept by the filter `grep -E '^(step |loop pass |fixed point check|author |pantheon|  [^ +[]|
jewels:|anoint|final |stopped|vaal|keystones)'` (the candidate, wishlist and tree-step lines are dropped; every kept line is
verbatim):
- `fixtures/status_build_early.log`: a weekly run's build (20261013-0101-P2-core-3, absolution_minions-s4.log) up to its
  `step start: loop opening`: the construction steps.
- `fixtures/status_build_loop.log`: a weekly run's build (same run, regular_viper_strike-s4.log) with its improvement loop
  and fixed point check: the loop moves.
- `fixtures/status_replay.out`: a replay run's output (a copy of artifacts/runs/20261002-1226-proof35r2-replay-base.out).

Checked here: each state gives the word of the #985 table (`addon.STATUS_WORDS`); the generic word «считается» covers
under 30 % of a recorded build's time, the time counted from the log's own step timings (`_time_by_word`); no status is an
English word outside the PoB terms the brief allows.
"""
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()
cat = addon._catalog()
FIX = Path(__file__).resolve().parent / "fixtures"
EARLY, LOOP, REPLAY = FIX / "status_build_early.log", FIX / "status_build_loop.log", FIX / "status_replay.out"
ALLOWED_LATIN = {"Items", "Tree", "Config", "Flasks", "Jewels", "Anoint", "aura", "gems", "build", "PoB", "reference"}
GENERIC = addon.STATUS_WORDS["generic"]


@contextmanager
def _no_weekly_bar():
    """the bar reads the newest weekly run and writes its cache: not under test here (the status is not the bar)."""
    keep, addon.stage_shares = addon.stage_shares, (lambda: None)
    try:
        yield
    finally:
        addon.stage_shares = keep


def _reading(lines: list) -> dict:
    """`build_stage` of a log that holds these lines: a prefix of a recorded log is the build at that moment."""
    with tempfile.TemporaryDirectory() as t, _no_weekly_bar():
        log = Path(t) / "x.log"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return addon.build_stage(log, 0.0, 400.0)


def _lines(path: Path) -> list:
    return path.read_text(encoding="utf-8").splitlines()


def _time_by_word(lines: list) -> dict:
    """seconds per status word over a recorded build log, from the log's own timings. A construction step's stage line
    (`  <step>   14 s ...`) is the step's own time. A loop pass's or the fixed point check's stage line is the sum of its
    moves, so it is not counted; the moves are counted through their summary lines, the ones that start `loop pass N` or
    `fixed point check` and end with `(<n>s)`; the lines between them are parts of those summaries."""
    secs: dict = {}
    step = move = None
    for line in lines:
        if line.startswith("  "):
            m = addon.STAGE_LINE.match(line)
            st = cat.step_of(step) if step is not None else None
            if m and st is not None and st.group != cat.IMPROVEMENT_LOOP:
                word = addon.status_word({"step": step})
                secs[word] = secs.get(word, 0.0) + addon._stage_seconds(m)
            continue
        kind, val = cat.parse_log_line(line)
        if kind == "start":
            step, move = val, None
            continue
        if kind == "loop_move":
            move = val[1]
            continue
        timed = re.search(r"\((\d+)s\)$", line)
        if timed and step is not None and re.match(r"(loop pass \d+|fixed point check) ", line):
            word = addon.status_word({"step": step, "move": move})
            secs[word] = secs.get(word, 0.0) + float(timed[1])
    return secs


def _shares(path: Path) -> dict:
    secs = _time_by_word(_lines(path))
    total = sum(secs.values())
    return {w: s / total for w, s in secs.items()} if total else {}


def test_states_of_the_early_build_give_the_table_words():
    lines = _lines(EARLY)
    want = {
        "step start: skeleton applied": "собирает скелет",
        "step start: config (conservative lane)": "собирает скелет",
        "step start: gear pass 1 (empty tree)": "подбирает Items",
        "step start: flat-reservation aura levels": "ставит уровни aura",
        "step start: tree greedy": "строит Tree",
        "step start: gear pass 2 (with tree)": "подбирает Items",
        "step start: tree rebuilt on gear": "перестраивает Tree",
        "step start: anoint": "выбирает Anoint",
        "step start: flasks": "подбирает Flasks",
        "step start: jewels": "подбирает Jewels",
    }
    seen = set()
    for i, line in enumerate(lines):
        if line in want:
            assert addon.status_word(_reading(lines[: i + 1])) == want[line], line
            seen.add(line)
    assert seen == set(want), set(want) - seen
    first = next(i for i, line in enumerate(lines) if line.startswith("step start"))
    assert addon.status_word(_reading(lines[:first])) == "читает reference PoB"  # the author lines only
    assert addon.status_word(_reading([])) == "читает reference PoB"  # an empty log: the build has not started
    assert addon.status_word(_reading(lines)) == "подбирает Jewels"  # the log's last state: `jewels` has no stage line yet


def test_states_of_the_loop_build_give_the_table_words():
    lines = _lines(LOOP)
    want = {
        "step start: loop pass 1": "правит Tree",  # no move yet: the loop's first move is refine
        "loop pass 1 move refine": "правит Tree",
        "loop pass 1 move swaps": "правит Tree",
        "loop pass 1 move gear": "улучшает Items",
        "loop pass 1 move picks": "перебирает gems",
        "loop pass 1 move lanes": "финальный Config",
        "loop pass 2 move weapon-base": "улучшает Items",
        "loop pass 2 move kick-tree": "встряхивает Tree",
        "loop pass 2 move kick-joint": "встряхивает Tree, Items",
        "step start: fixed point check": "итоговая проверка",
        "fixed point check move gear": "итоговая проверка",
        "step start: anoint re-pick": "финальный Config",
        "step start: config (final lanes)": "финальный Config",
    }
    seen = set()
    for i, line in enumerate(lines):
        if line in want:
            assert addon.status_word(_reading(lines[: i + 1])) == want[line], line
            seen.add(line)
    assert seen == set(want), set(want) - seen


def test_replay_squares_give_their_words():
    # the replay's `.out` as recorded (6 done), one line added for a failed build; 9 builds, 1 worker: one is running,
    # one waits, the failed one ends its row
    keep = addon.REPLAY_SEEN
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        addon.REPLAY_SEEN = d / "seen.json"
        try:
            names = ("bleed_bow", "burning_arrow_snipe", "cold_dot", "impale_ballista", "spark", "stormbrand",
                     "summon_raging_spirits", "toxic_rain", "winter_orb")
            for n in names:
                (d / f"{n}.pob.txt").write_text("x", encoding="utf-8")
            out = d / "job.out"
            out.write_text(REPLAY.read_text(encoding="utf-8") + "  spark                          FAILED RuntimeError: a line added by this test\n",
                           encoding="utf-8")
            job = SimpleNamespace(id="j-replay", argv=["python", "scripts/replay_bench.py", "--builds", str(d / "*.pob.txt"),
                                                      "--workers", "1"], cmd="python scripts/replay_bench.py", workers=1,
                                  state="running", out=str(out), start_ts="2026-10-10T00:00:00+00:00")
            got = {c["ref"]: (c["state"], c["status"]) for c in addon.run_cells(job)["cells"]}
        finally:
            addon.REPLAY_SEEN = keep
    assert got["stormbrand"] == ("done", "готово"), got
    assert got["spark"] == ("failed", "упал"), got
    assert got["toxic_rain"] == ("running", "пересчитывает build"), got
    assert got["winter_orb"] == ("waiting", "ждёт слот"), got


def test_collector_reads_a_running_log_and_stamps_the_other_states():
    with tempfile.TemporaryDirectory() as t, _no_weekly_bar():
        d = Path(t)
        (d / "logs").mkdir()
        (d / "rows").mkdir()
        shutil.copy(EARLY, d / "logs" / "x-s4.log")
        cell, took = {}, []
        addon._fill_cell(cell, d, "x-s4", took)
        assert (cell["state"], cell["status"], cell["stage"]) == ("running", "подбирает Jewels", "construction: jewels"), cell
        (d / "logs" / "e-s4.log").write_text("", encoding="utf-8")
        cell = {}
        addon._fill_cell(cell, d, "e-s4", took)
        assert cell["status"] == "читает reference PoB", cell
    for state, word in {"waiting": "ждёт слот", "queued": "ждёт слот", "done": "готово", "failed": "упал"}.items():
        cell = {"state": state}
        addon._stamp(cell)
        assert cell["status"] == word, cell
    cell = {"state": "running"}  # a running cell with no log is a replay build: its `.out` has no stage lines
    addon._stamp(cell)
    assert cell["status"] == "пересчитывает build", cell


def test_an_old_or_unknown_log_is_generic_not_a_guessed_state():
    old = _reading(["  skeleton applied                 4.9 s  value        3,201",
                    "  gear pass 1 (empty tree)       2.7 min  value"])
    assert old == {"after": "подбирает Items"} and addon.status_word(old) == GENERIC, old
    unknown = _reading(["step start: a step nobody wrote down"])
    assert addon.status_word(unknown) == GENERIC, unknown


def test_every_catalog_state_has_a_word_and_no_word_is_used_twice():
    assert set(addon._STEP_STATUS) == {s.name for s in cat.STEPS}, set(addon._STEP_STATUS) ^ {s.name for s in cat.STEPS}
    assert set(addon._MOVE_STATUS) == set(cat.LOOP_MOVES), set(addon._MOVE_STATUS) ^ set(cat.LOOP_MOVES)
    used = set(addon._STEP_STATUS.values()) | set(addon._MOVE_STATUS.values()) | {"reference", "waiting", "replay", "done",
                                                                                 "failed", "generic"}
    assert used <= set(addon.STATUS_WORDS), used - set(addon.STATUS_WORDS)
    assert len(set(addon.STATUS_WORDS.values())) == len(addon.STATUS_WORDS), addon.STATUS_WORDS


def test_no_status_is_an_english_word_outside_the_pob_terms():
    for word in addon.STATUS_WORDS.values():
        for tok in re.findall(r"[A-Za-z]+", word):
            assert tok in ALLOWED_LATIN, (word, tok)


PC_BENCH = FIX / "payload" / "bench"


def _pc_run_cells(name: str, state: str) -> list:
    """The cells of a PC-side recorded run (payload fixtures), read as a job of the given state from a copy of its folder."""
    with tempfile.TemporaryDirectory() as t, _no_weekly_bar():
        d = Path(t) / name
        shutil.copytree(PC_BENCH / name, d)
        job = SimpleNamespace(id=f"j-{name}", argv=["python", "scripts/benchmark.py"], cmd="python scripts/benchmark.py",
                              workers=1, state=state, out=str(Path(t) / "artifacts" / "runs" / "x.out"), run_dir=str(d),
                              start_ts=None, end_ts=None)
        got = addon.run_cells(job)
    assert got is not None, name
    return got["cells"]


def test_pc_recorded_runs_stamp_every_cell_with_a_status():
    # #985 (autopilot send-back): the done run (spark-s1 row) and the running run (spark-s1 row, bleed_bow-s1 whose log is
    # named .log since #992, so it reads as running): every cell carries a status word from STATUS_WORDS, in states running and done.
    words = set(addon.STATUS_WORDS.values())
    want = {"20261011-0800-snap-done": {"done": 1}, "20261011-1000-snap-run": {"done": 1, "running": 1}}
    for name, states in want.items():
        cells = _pc_run_cells(name, "done" if "done" in name else "running")
        per = {}
        for c in cells:
            row = per.setdefault(c["state"], [0, 0])  # [cells, without status]
            row[0] += 1
            if "status" not in c:
                row[1] += 1
            else:
                assert c["status"] in words, (name, c)
        print(f"{name}: " + ", ".join(f"{s} {n} cells, {m} without status" for s, (n, m) in sorted(per.items())))
        assert {s: n for s, (n, _) in per.items()} == states, (name, per)
        assert sum(m for _, m in per.values()) == 0, (name, per)


def test_generic_word_covers_under_30_percent_of_a_recorded_build():
    for path in (EARLY, LOOP):
        shares = _shares(path)
        assert shares, path
        assert shares.get(GENERIC, 0.0) < 0.30, (path.name, shares)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
