"""#510 unit 3: a request's forced directions reach the movers; a forced rare base is never swapped. PoB-free."""

from types import SimpleNamespace

from junkroan.optimizer.objective import Objective
from judging_fakes import pob_judging
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult, forced_lines_of, protected_nodes_of


class _Pob:
    def __init__(self):
        self.trials = 0

    def craft_rare(self, candidate, **_kw):
        return {"raw": f"raw {candidate}"}

    def trial_stats(self, trials, _keys, mode="fast"):
        self.trials += len(trials)
        return [{"ok": False} for _ in trials]


def _run(forced_bases):
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = _Pob()
    p.log = lambda _m: None
    p.judging = pob_judging(p)
    p.objective = Objective(maximize="CombinedDPS")
    p.rails = SimpleNamespace(gear=SimpleNamespace(item_level=84, quality=20))
    p._weapon_raw_base = lambda _raw: "Imbued Wand"
    p._weapon_base_fingerprint = lambda *_a, **_k: "fp"
    p._weapon_item_parts = lambda _raw: ([], [], [], 20, None)
    p._weapon_base_numbers = lambda _raw: {}
    p._weapon_base_candidates = lambda _loot, _base: ["Profane Wand"]
    skeleton = SimpleNamespace(uniques={}, rare_bases={"Weapon 1": "Imbued Wand"}, forced_bases=forced_bases)
    loot = SimpleNamespace(current_raw={"Weapon 1": "raw Imbued Wand"}, item_level_for=lambda _s: 84, rails=SimpleNamespace(gear=SimpleNamespace(wishlist=SimpleNamespace(item_level_for=lambda _s: 84))))
    out = p._weapon_base_move(
        BuildResult(skeleton=skeleton), skeleton, loot, "Weapon 1",
        current_score=None, min_gain=0.0, move_state={}, snapshot_fresh=True, t0=0.0,
        judge=None, restore_move=None, last_rejected={},
    )
    return out, p.pob.trials, skeleton


def test_forced_base_sends_no_trial_and_keeps_the_base() -> None:
    out, trials, skeleton = _run({"Weapon 1": "Imbued Wand"})
    assert out == (False, None)
    assert trials == 0
    assert skeleton.rare_bases["Weapon 1"] == "Imbued Wand"


def test_without_the_forced_base_the_move_tries_candidates() -> None:
    _out, trials, _skeleton = _run({})
    assert trials == 1  # the guard is what held the forced case


def test_forced_nodes_become_the_protected_set() -> None:
    sk = SimpleNamespace(forced_nodes=[5, 9, 5])
    assert protected_nodes_of(sk) == frozenset({5, 9})


def test_forced_affixes_are_copied_per_slot() -> None:
    src = {"Helmet": ["+# to maximum Life"]}
    sk = SimpleNamespace(forced_affixes=src)
    lines = forced_lines_of(sk)
    assert lines == src
    lines["Helmet"].append("x")
    assert src["Helmet"] == ["+# to maximum Life"]
