"""The utility picker offers transfigured gems next to their base (rulebook gm-transfigured), no PoB."""

from junkroan.search.generator import SkeletonGenerator
from junkroan.search.skeleton import Skeleton, SocketGroup


def _cands() -> dict[str, list[str]]:
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    return gen.utility_candidates(Skeleton(class_name="Ranger", ascendancy="Deadeye", main_link=["Lightning Arrow", "Added Cold Damage"]))


def test_blink_arrow_family_offers_base_and_transfigured() -> None:
    movement = _cands()["movement"]
    assert "Blink Arrow" in movement and "Blink Arrow of Bombarding Clones" in movement


def test_transfigured_utility_gets_the_same_level_and_quality_as_every_gem() -> None:
    sk = Skeleton(class_name="Ranger", ascendancy="Deadeye", main_link=["Lightning Arrow"],
                  extra_groups=[SocketGroup(gems=[n], slot="Gloves", label=n) for n in ("Blink Arrow", "Blink Arrow of Bombarding Clones", "Herald of Ash")])
    payload = sk.skill_payload(gem_level=18, gem_quality=0)
    gems = {g["gem_name"]: (g["level"], g["quality"]) for grp in payload["extra_groups"] for g in grp["gems"]}
    assert gems["Blink Arrow"] == gems["Blink Arrow of Bombarding Clones"] == gems["Herald of Ash"] == (18, 0)
