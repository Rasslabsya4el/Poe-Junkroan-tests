"""gm-links rail (#426): the main link is at most main_link_max gems, every other group at most other_link_max. No PoB."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from junkroan.optimizer.objective import Score
from junkroan.optimizer.rails import Rails
from junkroan.search import runner
from junkroan.search.generator import SkeletonGenerator


def _gen(rails: Rails) -> tuple[SkeletonGenerator, SimpleNamespace]:
    """A generator whose scorer rewards every extra support (the greedy fills any link it is allowed to)."""

    gen = object.__new__(SkeletonGenerator)
    gen.rails, gen.picks, gen.log = rails, [], lambda *_a, **_k: None
    gen.castability_context = None
    sk = SimpleNamespace(main_link=["Fireball"], fixed_supports=[], enablers=lambda: [])
    state = {"link": ["Fireball"]}
    gen.legal_supports = lambda _sk: [f"Support {i}" for i in range(12)]
    gen._set_main_link = lambda _sk, link, **_k: state.update(link=list(link))
    gen._reconfigure = lambda *_a, **_k: None
    gen._restore_castability = lambda *_a, **_k: None
    gen._score = lambda: Score(0.0, float(len(state["link"])))
    return gen, sk


def test_rail_loads_day1_values() -> None:
    rails = Rails.load()
    assert rails.gems.main_link_max == 5
    assert rails.gems.other_link_max == 4


def test_pick_supports_never_exceeds_main_link_max() -> None:
    gen, sk = _gen(Rails.load())
    assert len(gen.pick_supports(sk, n_supports=5)) == 5  # 1 active + 4 supports, though 5 supports were asked
    gen, sk = _gen(Rails.load())
    assert len(gen.pick_supports(sk)) == 5  # default = the rail


def test_rail_override_lets_six_through() -> None:
    rails = Rails.load()
    wide = dataclasses.replace(rails, gems=dataclasses.replace(rails.gems, main_link_max=6))
    gen, sk = _gen(wide)
    assert len(gen.pick_supports(sk, n_supports=5)) == 6  # 5 supports + the active
    gen, sk = _gen(wide)
    assert len(gen.pick_supports(sk)) == 6
    gen, sk = _gen(wide)
    assert len(gen.pick_supports(sk, n_supports=9)) == 6


def test_prepare_candidate_slice_keeps_at_most_main_link_max(monkeypatch) -> None:
    """prepare_candidate clamps n_supports to the rail before its `[: 1 + n_supports]` slice."""

    class Stop(Exception):
        pass

    nop = lambda *_a, **_k: None  # noqa: E731

    class FakeSession:
        def __init__(self, **_k): ...
        def __enter__(self): return self
        def __exit__(self, *_a): return False

    class FakeGen:
        def __init__(self, *_a, **_k): ...
        refresh_castability = screen_bases = pick_ascendancy_nodes = lambda self, *_a, **_k: None  # noqa: E731

    def stop(*_a, **_k):
        raise Stop

    sk = SimpleNamespace(ascendancy="X", main_link=["Fireball"], mode=None, ascendancy_nodes=[1] * 8, apply=nop, apply_skills=stop,
        forced_uniques={}, forced_bases={}, forced_affixes={},  # #510: a request with no forced slot
    )
    monkeypatch.setattr(runner, "PobSession", FakeSession)
    monkeypatch.setattr(runner, "SkeletonGenerator", FakeGen)
    monkeypatch.setattr(runner, "_log_to", lambda _p: nop)
    monkeypatch.setattr(runner, "objective_for", nop)
    monkeypatch.setattr(runner.Skeleton, "from_json", classmethod(lambda cls, _j: sk))
    out = runner.prepare_candidate("{}", log_path="unused", shared_supports=[f"S{i}" for i in range(9)], n_supports=9)
    assert out["ok"] is False and "Stop" in out["error"]  # stopped at apply_skills, after the slice
    assert len(sk.main_link) == 5
