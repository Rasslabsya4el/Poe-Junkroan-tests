"""gm-links (#426 unit 2): every Skeleton that enters the optimizer has main link <= main_link_max and every extra group <= other_link_max. No PoB."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from junkroan.optimizer.rails import Rails
from junkroan.search.generator import SkeletonGenerator
from junkroan.search.hypothesis import Hypothesis, validate
from junkroan.search.request import BuildRequest, expand
from junkroan.search.skeleton import Skeleton, SocketGroup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

GEMS = ["Fireball", "Spell Echo", "Controlled Destruction", "Increased Critical Strikes", "Elemental Focus", "Faster Casting", "Efficacy"]


def _sg(n: int) -> SocketGroup:
    return SocketGroup(gems=[f"G{i}" for i in range(n)], label="g")


def test_six_gem_main_link_goes_to_five_active_kept() -> None:
    sk = Skeleton(class_name="Witch", ascendancy="None", main_link=GEMS[:6])
    dropped = sk.cap_links(Rails.load())
    assert sk.main_link == GEMS[:5] and len(dropped) == 1


def test_five_gem_extra_group_goes_to_four() -> None:
    sk = Skeleton(class_name="Witch", ascendancy="None", main_link=GEMS[:2], extra_groups=[_sg(5)])
    sk.cap_links(Rails.load())
    assert sk.extra_groups[0].gems == ["G0", "G1", "G2", "G3"]


def test_main_five_plus_extra_five_gives_main_five_extra_four() -> None:
    sk = Skeleton(class_name="Witch", ascendancy="None", main_link=GEMS[:5], extra_groups=[_sg(5)])
    sk.cap_links(Rails.load())
    assert (len(sk.main_link), len(sk.extra_groups[0].gems)) == (5, 4)


def test_fixed_support_survives_the_trim_and_indices_follow() -> None:
    sk = Skeleton(class_name="Witch", ascendancy="None", main_link=GEMS[:6], fixed_supports=["Elemental Focus", "Faster Casting"],
                  disabled_main_gem_indices=[2, 5], main_instance_counts=[1, 2, 3, 4, 5, 6])
    sk.cap_links(Rails.load())
    assert sk.main_link == ["Fireball", "Spell Echo", "Controlled Destruction", "Elemental Focus", "Faster Casting"]
    assert sk.main_instance_counts == [1, 2, 3, 5, 6]
    assert sk.disabled_main_gem_indices == [2, 4]


def test_rails_override_keeps_six() -> None:
    rails = Rails.load()
    rails = dataclasses.replace(rails, gems=dataclasses.replace(rails.gems, main_link_max=6))
    sk = Skeleton(class_name="Witch", ascendancy="None", main_link=GEMS[:6])
    assert sk.cap_links(rails) == [] and len(sk.main_link) == 6


def _fixture_paths() -> list[Path]:
    root = PROJECT_ROOT / "tests" / "fixtures"
    paths = sorted((root / "tuadh_329").glob("*.pob.txt"))
    for d in sorted(root.glob("zizaran_*")):
        paths += sorted(d.glob("*.pob.txt"))
    return paths


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_benchmark_fixture_skeleton_is_capped(path: Path) -> None:
    from build_from_skeleton import skeleton_from_xml
    from junkroan.pob.session import decode_import_code

    rails = Rails.load()
    sk = skeleton_from_xml(decode_import_code(path.read_text(encoding="utf-8").strip()))
    assert len(sk.main_link) <= rails.gems.main_link_max
    assert all(len(g.gems) <= rails.gems.other_link_max for g in sk.extra_groups)


def test_hypothesis_builder_caps_overlong_input() -> None:
    h = Hypothesis.from_dict({"name": "t", "class": "Witch", "ascendancy": "Elementalist", "main_skill": "Fireball",
                              "supports": GEMS[1:7], "extra_groups": [["Herald of Ash", "Spell Echo", "Efficacy", "Faster Casting", "Elemental Focus"]]})
    v = validate(h)
    assert v.skeleton is not None, v.problems
    assert len(v.skeleton.main_link) == 5 and len(v.skeleton.extra_groups[0].gems) == 4


def test_request_builder_caps_overlong_link_head() -> None:
    req = BuildRequest.from_dict({"skill": "Fireball", "mode": "hit", "ascendancy": "Elementalist", "level": 80,
                                  "supports": GEMS[1:5]})
    exp = expand(req, Rails.load())
    assert exp.validations and all(v.skeleton is None or len(v.skeleton.main_link) <= 5 for v in exp.validations)


def test_generator_candidates_cap_overlong_supports(monkeypatch: pytest.MonkeyPatch) -> None:
    gen = object.__new__(SkeletonGenerator)
    gen.rails, gen.pob, gen.log = Rails.load(), None, lambda *_a, **_k: None
    gen.refresh_castability = gen.screen_bases = lambda *_a, **_k: None
    gen.pick_ascendancy_nodes = lambda *_a, **_k: None
    monkeypatch.setattr(Skeleton, "apply", lambda self, *_a, **_k: None)
    out = gen.candidates("Fireball", ascendancy_ids=["Elementalist"], supports=GEMS[1:], extra_groups=[_sg(5)])
    assert out and all(len(s.main_link) <= 5 and len(s.extra_groups[0].gems) <= 4 for s in out)
