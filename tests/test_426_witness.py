"""#426 witness (kind A, D113): at the 5-gem cap the main link keeps the best 4 supports, the 5th best is the one left out,
and no link of 6 gems is ever put to the scorer. No PoB."""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.objective import Score
from junkroan.optimizer.rails import Rails
from junkroan.search.generator import SkeletonGenerator

VALUE = {"Best": 50.0, "Second": 40.0, "Third": 30.0, "Fourth": 20.0, "Fifth": 10.0, "Sixth": 5.0}


def test_main_group_at_cap_keeps_best_four_supports_and_never_builds_six() -> None:
    gen = object.__new__(SkeletonGenerator)
    gen.rails, gen.picks, gen.log, gen.castability_context = Rails.load(), [], (lambda *_a, **_k: None), None
    sk = SimpleNamespace(main_link=["Fireball"], fixed_supports=[], enablers=lambda: [])
    state = {"link": ["Fireball"]}
    seen_sizes: list[int] = []
    gen.legal_supports = lambda _sk: list(VALUE)
    gen._set_main_link = lambda _sk, link, **_k: state.update(link=list(link))
    gen._reconfigure = lambda *_a, **_k: None
    gen._restore_castability = lambda *_a, **_k: None

    def score() -> Score:
        seen_sizes.append(len(state["link"]))
        return Score(0.0, sum(VALUE.get(g, 0.0) for g in state["link"]))

    gen._score = score
    link = gen.pick_supports(sk, n_supports=5)  # five supports asked: one more than the rail allows
    assert len(link) == 5
    assert set(link[1:]) == {"Best", "Second", "Third", "Fourth"}
    assert "Fifth" not in link  # the 5th best is the one dropped
    assert max(seen_sizes) <= 5  # no group of 6 reached the scorer


def test_trace_output_counts_delivered_groups_by_gem_count() -> None:
    from junkroan.optimizer.trace_output import trace_output_from_xml

    xml = (
        "<PathOfBuilding><Skills activeSkillSet='1'><SkillSet id='1'>"
        "<Skill enabled='true'><Gem nameSpec='A'/><Gem nameSpec='B'/><Gem nameSpec='C'/><Gem nameSpec='D'/><Gem nameSpec='E'/></Skill>"
        "<Skill enabled='true'><Gem nameSpec='F'/></Skill>"
        "</SkillSet></Skills></PathOfBuilding>"
    )
    out = trace_output_from_xml(xml)
    assert out["links:5"] == 1 and out["links:1"] == 1 and "links:6" not in out
