"""Build requests: checklist -> hypotheses, with an echo (docs/REQUEST.md). Corpus-only."""

import json

import pytest

from junkroan.optimizer.objective_select import objective_for
from junkroan.optimizer.rails import Rails
from junkroan.search.request import DEFAULT_SEEDS, MINUTES_PER_FULL_BUILD, MINUTES_PER_SCREEN, BuildRequest, estimate_minutes, expand, load_request


def test_simple_request_expands_to_named_ascendancies() -> None:
    req = BuildRequest.from_dict({"why": "85 build through Lightning Strike", "skill": "Lightning Strike", "ascendancy": ["Slayer", "Deadeye"], "level": 85})
    exp = expand(req, Rails.load())
    assert exp.ok, exp.problems
    assert [h.ascendancy for h in exp.hypotheses] == ["Slayer", "Deadeye"] and all(h.level == 85 for h in exp.hypotheses)
    assert "expands to 2 candidates" in exp.echo and "top 2 x 3 seeds = 6 full builds" in exp.echo and "mode auto" in exp.echo


def test_complex_request_keeps_what_is_fixed_and_names_what_is_not_modelled() -> None:
    req = BuildRequest.from_dict({
        "why": "Spellslinger on several spells, dex stacking", "skill": "Fireball", "delivery": "Spellslinger", "trigger_with": "Kinetic Blast", "mode": ["hit", "poison"],
        "ascendancy": "Deadeye", "scaling": {"stat": "Dex", "seed_points": 0.4}, "uniques": {"Body Armour": "Hyrri's Ire"},
        "damage_links": {"count": [2, 4], "from": {"tags": ["spell"]}}, "forbid_supports": ["Decay"], "weapon_types": ["Wand"], "utilities": ["Grace"],
    })
    exp = expand(req, Rails.load())
    assert exp.ok, exp.problems
    modes = {v.skeleton.mode for v in exp.validations}
    assert modes == {"hit", "poison"}
    sk = exp.validations[0].skeleton
    assert sk.main_link[:2] == ["Spellslinger", "Fireball"] and sk.scaling == {"stat": "Dex", "seed_points": 0.4}
    assert sk.weapon_types == ["Wand"] and sk.forbid_supports == ["Decay"] and sk.uniques == {"Body Armour": "Hyrri's Ire"}
    assert [g.gems for g in sk.extra_groups] == [["Kinetic Blast"], ["Grace"]]
    poison = next(v.skeleton for v in exp.validations if v.skeleton.mode == "poison")
    assert "Chance to Poison" in poison.main_link
    assert any("damage_links" in n for n in exp.notes)
    assert objective_for(Rails.load(), "Fireball", mode="poison").maximize == "TotalPoisonDPS"


@pytest.mark.parametrize("skill, mode, ascendancy", [("Cyclone", "hit", "Slayer"), ("Storm Brand", "hit", "Inquisitor"), ("Summon Raging Spirit", "minion", "Necromancer")])
def test_the_three_acceptance_requests_expand(skill: str, mode: str, ascendancy: str) -> None:
    """ROADMAP 7.4: one melee, one spell, one minion request through `junkroan build`."""

    exp = expand(BuildRequest.from_dict({"skill": skill, "mode": mode, "ascendancy": ascendancy, "level": 80}), Rails.load())
    assert exp.ok, exp.problems
    sk = exp.validations[0].skeleton
    assert sk.main_link[0] == skill and sk.mode == mode and sk.ascendancy == ascendancy and sk.level == 80
    assert "expands to 1 candidates" in exp.echo and "top 1 x 3 seeds = 3 full builds" in exp.echo


def test_a_request_file_with_a_bom_loads(tmp_path) -> None:
    """A request written by a Windows editor (or `--print-request | Out-File`) carries a BOM."""

    f = tmp_path / "r.json"
    f.write_text(json.dumps({"skill": "Storm Brand", "mode": "hit", "top": 1}), encoding="utf-8-sig")
    req = load_request(f)
    assert req.skill == "Storm Brand" and req.modes == ["hit"] and req.top == 1


def test_the_estimate_counts_the_seeds_and_the_workers() -> None:
    """D71: minutes = screening in waves of `workers` + ceil(finalists x seeds / workers) full
    builds. Two finalists x 3 seeds on 5 workers is two waves of full builds."""

    assert estimate_minutes(2, finalists=2, seeds=3, workers=5) == MINUTES_PER_SCREEN + 2 * MINUTES_PER_FULL_BUILD
    assert estimate_minutes(2, finalists=2, seeds=1, workers=5) == MINUTES_PER_SCREEN + MINUTES_PER_FULL_BUILD
    # one worker serializes everything: 6 full builds one after another
    assert estimate_minutes(2, finalists=2, seeds=3, workers=1) == 2 * MINUTES_PER_SCREEN + 6 * MINUTES_PER_FULL_BUILD
    # 19 ascendancies screened 5 at a time, then the two finalists' six builds
    assert estimate_minutes(19, finalists=2, seeds=3, workers=5, extra=10) == 4 * MINUTES_PER_SCREEN + 2 * MINUTES_PER_FULL_BUILD + 10
    assert estimate_minutes(0, finalists=0, seeds=3, workers=5) == 0


def test_the_default_request_stays_inside_the_two_hour_promise() -> None:
    """docs/REQUEST.md promises under 2 hours per request on 5 workers."""

    req = BuildRequest.from_dict({"skill": "Storm Brand", "mode": "hit", "ascendancy": ["Inquisitor", "Hierophant"]})
    assert req.seeds == DEFAULT_SEEDS == 3 and req.top == 2 and req.workers == 5
    exp = expand(req, Rails.load())
    assert exp.ok, exp.problems
    minutes = estimate_minutes(2, finalists=2, seeds=3, workers=5)
    assert minutes == 83 and f"~{minutes:.0f} min on 5 workers" in exp.echo


def test_seeds_are_a_request_field_and_move_the_estimate() -> None:
    one = expand(BuildRequest.from_dict({"skill": "Storm Brand", "mode": "hit", "ascendancy": ["Inquisitor", "Hierophant"], "seeds": 1}), Rails.load())
    assert "top 2 x 1 seeds = 2 full builds" in one.echo and f"~{MINUTES_PER_SCREEN + MINUTES_PER_FULL_BUILD:.0f} min" in one.echo
    six = expand(BuildRequest.from_dict({"skill": "Storm Brand", "mode": "hit", "ascendancy": ["Inquisitor", "Hierophant"], "seeds": 6, "max_builds": 4}), Rails.load())
    assert not six.ok and any("12 full builds, above max_builds=4" in p for p in six.problems)


def test_unknown_names_are_problems_not_guesses() -> None:
    exp = expand(BuildRequest.from_dict({"skill": "Lightning Strke", "ascendancy": "Slayr", "mode": "burn"}), Rails.load())
    assert not exp.ok and any("unknown active skill" in p for p in exp.problems) and any("unknown ascendancy" in p for p in exp.problems) and any("unknown mode" in p for p in exp.problems)
