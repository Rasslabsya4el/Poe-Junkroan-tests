"""#995 send-back 1, defect 5: the monitor's «Готово» row of #980 had no kind word and an empty «билды».

#980's runs in the store (artifacts/runs/jobs.jsonl, 14.10): P1-#980 ran `python scripts/legal_supports_stored_vs_fresh.py`
(no builds), P1-#980-2 ran `python scripts/search.py "Shrapnel Ballista" ...` (1 full build). `junkroan build` hands its
request to scripts/search.py (src/junkroan/cli.py), so a search.py run is the kind `request`; its builds are counted off
its `.out` (the monitor add-on's `search_cells`), the lines below copied from that run's `.out` and from an older search
run with a mutation round (artifacts/runs/search-smite-d54.out).
"""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

MOD = Path(__file__).resolve().parents[1] / "mods" / "pob-slots"
sys.path.insert(0, str(MOD / "bin"))
import collect  # noqa: E402,F401  (the add-on imports its helpers from the generic collector)

_spec = importlib.util.spec_from_file_location("monitor_addon_995", MOD / "addon" / "addon.py")
addon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(addon)

T = "2026-10-14T00:00:00+00:00"
SEARCH_980 = """\
| 1 | Duelist/Champion | 219,562 | 0.000 | - |

full optimize: 1 skeletons x 1 seeds = 1 full builds, ~40 min left
  full Champion-0 seed 1: 406,411 (viol 0.000) in 3 h 15 min; uniques []
full optimize done (3 h 15 min; 1 skeletons x 1 seeds)
total 4 h 26 min
"""
SEARCH_MUTATION = """\
full optimize: 2 skeletons x 1 seeds = 2 full builds, ~1 h 20 min left
  full Champion-0 seed 1: 557,861 (viol 0.000) in 25 min; uniques []
  full Slayer-0 seed 1: 499,986 (viol 0.000) in 27 min; uniques []
mutation round: 3 variants of the finished builds (Champion-no-crimson_dance, Slayer-w-void_sceptre, Champion-mut8)
  full Champion-mut8: 708,987 (viol 0.000) in 1502s; uniques []
- full optimize failed Slayer-w-void_sceptre seed 1: boom
mutation round done (40 min; 1 of 3 variants fully optimized)
"""


def job(cmd, out=None, **kw):
    base = dict(id="j-980-2", tag="P1-#980-2", issue=980, priority="P1", host="pc", workers=1, state="done", cmd=cmd,
                argv=cmd.split(), submit_ts=T, start_ts=T, end_ts=T, after=[], run_dir=None, out=out)
    base.update(kw)
    return SimpleNamespace(**base)


SEARCH_CMD = 'python scripts/search.py "Shrapnel Ballista" --ascendancies Champion --top 1 --seeds 1 --workers 2'
OTHER_CMD = "python scripts/legal_supports_stored_vs_fresh.py --stored var/scratch980/stored --out var/scratch980/fresh"


def test_kinds_of_the_two_980_runs():
    s, o = job(SEARCH_CMD), job(OTHER_CMD, id="j-980", tag="P1-#980")
    assert addon.run_kind(s) == "request"
    assert addon.kind_name("request", s) == "билд по запросу"
    assert addon.run_kind(o) == ""
    assert addon.kind_name("", o) == ""  # main's kind_name: an unknown command has an empty name


def test_search_run_counts_its_builds(tmp_path):
    out = tmp_path / "980.out"
    out.write_text(SEARCH_980, encoding="utf-8")
    p = addon.run_cells(job(SEARCH_CMD, out=str(out)))
    assert (p["done"], p["total"]) == (1, 1), p
    assert [(c["ref"], c["seed"], c["state"]) for c in p["cells"]] == [("Champion-0", 1, "done")]


def test_search_run_with_a_mutation_round(tmp_path):
    out = tmp_path / "mut.out"
    out.write_text(SEARCH_MUTATION, encoding="utf-8")
    p = addon.search_cells(job(SEARCH_CMD, out=str(out)))
    # planned: 2 full builds + 3 variants; ended: 3 lines done, 1 failed, Champion-no-crimson_dance never got a line
    assert (p["done"], p["total"]) == (4, 5), p
    states = {c["ref"]: c["state"] for c in p["cells"]}
    assert states == {"Champion-0": "done", "Slayer-0": "done", "Champion-no-crimson_dance": "waiting",
                      "Champion-mut8": "done", "Slayer-w-void_sceptre": "failed"}, states


def test_search_run_before_its_plan_has_no_count(tmp_path):
    out = tmp_path / "early.out"
    out.write_text("prepared 3 skeletons (2.1 s)\n", encoding="utf-8")
    assert addon.search_cells(job(SEARCH_CMD, out=str(out), state="running")) is None


def test_history_counts_carry_the_search_run(tmp_path, monkeypatch):
    monkeypatch.setattr(addon, "HISTORY_CACHE", tmp_path / "history.json")
    out = tmp_path / "980.out"
    out.write_text(SEARCH_980, encoding="utf-8")
    s, o = job(SEARCH_CMD, out=str(out)), job(OTHER_CMD, id="j-980", tag="P1-#980")
    counts = addon._history_counts([o, s])
    assert {k: (v["done"], v["total"]) for k, v in counts.items()} == {"j-980-2": (1, 1)}, counts
    assert json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))["j-980-2"]["out"] == str(out)
