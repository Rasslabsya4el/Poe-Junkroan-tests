"""Golem instances are allocated across golem gems, not copied from the shared limit."""

from pathlib import Path

import pytest

from junkroan.search.skeleton import Skeleton, SocketGroup, derived_counts

from conftest import needs_skill_source


class _Pob:
    def __init__(self, limit: int, **values: float) -> None:
        self.limit = limit
        self.values = values

    def stats(self, keys):
        return {
            key: self.limit if key == "ActiveGolemLimit" else self.values.get(key, 0)
            for key in keys
        }


GOLEMS = [
    "Summon Chaos Golem",
    "Summon Lightning Golem",
    "Summon Flame Golem",
    "Summon Stone Golem",
]


@pytest.mark.parametrize(
    ("names", "limit", "expected"),
    [
        (GOLEMS[:1], 3, [3]),
        (GOLEMS[:3], 3, [1, 1, 1]),
        (GOLEMS[:2], 3, [2, 1]),
        (GOLEMS, 3, [1, 1, 1, 0]),
    ],
)
@needs_skill_source
def test_golem_limit_is_shared_across_gems(names, limit, expected) -> None:
    counts = derived_counts(_Pob(limit), names, links=[[name] for name in names])
    assert [counts[name] for name in names] == expected


@needs_skill_source
def test_non_golem_minion_counts_are_unchanged() -> None:
    assert derived_counts(_Pob(3, ActiveRagingSpiritLimit=20), ["Summon Raging Spirit"]) == {
        "Summon Raging Spirit": 20
    }


@needs_skill_source
def test_numeric_zero_minion_limit_is_preserved() -> None:
    assert derived_counts(_Pob(0, ActiveRagingSpiritLimit=0), ["Summon Raging Spirit"]) == {
        "Summon Raging Spirit": 0
    }


class _SkillPob(_Pob):
    def __init__(self, limit: int) -> None:
        super().__init__(limit)
        self.skills: list[dict] = []

    def set_skills(self, **kwargs) -> None:
        self.skills.append(kwargs)

    def stats(self, keys):
        # The second limit is visible only while the previously unfielded candidate is
        # enabled. This proves refresh probes it before deciding whether to re-enable it.
        if self.limit == 2 and self.skills:
            lightning = self.skills[-1]["extra_groups"][1]["gems"][0]
            if not lightning["enabled"]:
                return {key: 1 if key == "ActiveGolemLimit" else self.values.get(key, 0) for key in keys}
        return super().stats(keys)


@needs_skill_source
def test_zero_count_golem_is_disabled_then_reenabled_by_index() -> None:
    """The reporting count remains zero; the PoB payload represents it as disabled with count one."""

    pob = _SkillPob(1)
    skeleton = Skeleton(
        class_name="Duelist",
        ascendancy="Slayer",
        main_link=["Cyclone"],
        extra_groups=[
            SocketGroup(gems=["Summon Chaos Golem"], slot="Helmet"),
            SocketGroup(gems=["Summon Lightning Golem"], slot="Gloves"),
        ],
    )
    logs: list[str] = []

    assert skeleton.refresh_minion_counts(pob, log=logs.append) == {
        "Summon Chaos Golem": 1,
        "Summon Lightning Golem": 0,
    }
    assert skeleton.gem_counts["Summon Lightning Golem"] == 0
    assert skeleton.extra_groups[1].disabled_gem_indices == [0]
    zero_payload = pob.skills[-1]["extra_groups"][1]["gems"][0]
    assert zero_payload["enabled"] is False and zero_payload["count"] == 1
    assert "Summon Lightning Golem fields 0 instances" in logs[-1]
    assert Skeleton.from_json(skeleton.to_json()).extra_groups[1].disabled_gem_indices == [0]

    pob.limit = 2
    skeleton.refresh_minion_counts(pob, log=logs.append)
    assert skeleton.gem_counts["Summon Lightning Golem"] == 1
    assert skeleton.extra_groups[1].disabled_gem_indices == []
    reenabled_payload = pob.skills[-1]["extra_groups"][1]["gems"][0]
    assert reenabled_payload["enabled"] is True and reenabled_payload["count"] == 1
    assert "Summon Lightning Golem fields 1 instances" in logs[-1]


@needs_skill_source
def test_repeated_golems_keep_the_fielded_occurrence_enabled() -> None:
    """A name is not an occurrence: one shared golem limit fields exactly one duplicate gem."""

    pob = _SkillPob(1)
    skeleton = Skeleton(
        class_name="Duelist",
        ascendancy="Slayer",
        main_link=["Cyclone"],
        extra_groups=[
            SocketGroup(gems=["Summon Chaos Golem"], slot="Helmet"),
            SocketGroup(gems=["Summon Chaos Golem"], slot="Gloves"),
        ],
    )

    assert skeleton.refresh_minion_counts(pob) == {"Summon Chaos Golem": 1}
    assert skeleton.extra_groups[0].disabled_gem_indices == []
    assert skeleton.extra_groups[1].disabled_gem_indices == [0]
    payload = skeleton.skill_payload()
    gems = [group["gems"][0] for group in payload["extra_groups"]]
    assert [gem["enabled"] for gem in gems] == [True, False]
    assert [gem["count"] for gem in gems] == [1, 1]
    restored = Skeleton.from_json(skeleton.to_json())
    assert restored.extra_groups[0].disabled_gem_indices == []
    assert restored.extra_groups[1].disabled_gem_indices == [0]

    pob.limit = 3
    skeleton.refresh_minion_counts(pob)
    payload = skeleton.skill_payload()
    assert [group["gems"][0]["count"] for group in payload["extra_groups"]] == [2, 1]


def test_trial_link_does_not_disable_a_new_support_at_an_old_main_index() -> None:
    skeleton = Skeleton(
        class_name="Duelist",
        ascendancy="Slayer",
        main_link=["Cyclone", "Summon Chaos Golem"],
        disabled_main_gem_indices=[1],
        main_instance_counts=[1, 0],
    )

    trial = skeleton.skill_payload(main_link=["Cyclone", "Fortify Support"])

    assert "main_disabled_indices" not in trial
    assert trial["main_instance_counts"] == []


def test_set_skills_defensively_clamps_supplied_main_and_extra_counts() -> None:
    """A caller outside Skeleton cannot send a zero numeric gem field to the worker either."""

    from types import SimpleNamespace

    from junkroan.pob.session import PobSession

    captured: dict = {}
    pob = PobSession.__new__(PobSession)
    pob._fulldps_last_ratio = None
    pob._handle = object()
    pob._adapter = SimpleNamespace(apply_skill_state=lambda _handle, payload: captured.update(payload=payload))
    pob.set_skills(
        main_link=["Cyclone"],
        main_counts={"Cyclone": 0},
        main_disabled_indices=[0],
        extra_groups=[{
            "label": "Golem",
            "slot": "Boots",
            "gems": [{"gem_name": "Summon Lightning Golem", "count": 0, "enabled": False}],
        }],
    )

    groups = captured["payload"]["skill_sets"][0]["socket_groups"]
    assert groups[0]["gems"][0]["enabled"] is False and groups[0]["gems"][0]["count"] == 1
    assert groups[1]["gems"][0]["enabled"] is False and groups[1]["gems"][0]["count"] == 1

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")
@pytest.mark.pob
def test_cold_dot_golem_counts_are_allocated_from_pob_limit() -> None:
    from junkroan.pob.session import PobSession, decode_import_code
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml

    xml = decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "cold_dot.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-golem-counts") as pob:
        pob.load_xml(xml)
        skeleton = skeleton_from_xml(xml)
        links = [skeleton.main_link, *(group.gems for group in skeleton.extra_groups)]
        names = [name for link in links for name in link]
        counts = derived_counts(pob, names, links=links)
        assert pob.stats(("ActiveGolemLimit",))["ActiveGolemLimit"] == 4
        assert {name: counts[name] for name in GOLEMS} == {
            "Summon Chaos Golem": 1,
            "Summon Lightning Golem": 1,
            "Summon Flame Golem": 1,
            "Summon Stone Golem": 1,
        }


@pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")
@pytest.mark.pob
def test_srs_fixture_count_is_unchanged_without_golems() -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    xml = decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "summon_raging_spirits.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-golem-counts-srs") as pob:
        pob.load_xml(xml)
        assert derived_counts(pob, ["Summon Raging Spirit"]) == {"Summon Raging Spirit": 20}


@pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")
@pytest.mark.pob
def test_slayer_cyclone_golem_zero_is_disabled_before_the_worker_payload() -> None:
    """The incident regression: one live PoB worker must receive no zero numeric gem field."""

    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession
    from junkroan.search.generator import SkeletonGenerator

    rails = Rails.load()
    skeleton = Skeleton(
        class_name="Duelist",
        ascendancy="Slayer",
        level=80,
        main_link=["Cyclone"],
        extra_groups=[
            SocketGroup(gems=["Battlemage's Cry"], slot="Helmet"),
            SocketGroup(gems=["Summon Chaos Golem"], slot="Gloves"),
            SocketGroup(gems=["Summon Lightning Golem"], slot="Boots"),
        ],
    )
    logs: list[str] = []
    with PobSession(run_id="test-golem-zero-slayer") as pob:
        skeleton.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        assert pob.stats(("ActiveGolemLimit",))["ActiveGolemLimit"] == 1
        assert skeleton.refresh_minion_counts(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality,
                                              main_quality=rails.gems.main_quality, log=logs.append) == {
            "Summon Chaos Golem": 1,
            "Summon Lightning Golem": 0,
        }
        SkeletonGenerator(pob, rails)._set_main_link_raw(skeleton, skeleton.main_link)

    payload = skeleton.skill_payload(gem_level=rails.gems.level, gem_quality=rails.gems.quality,
                                    main_quality=rails.gems.main_quality)
    lightning = payload["extra_groups"][2]["gems"][0]
    assert lightning["enabled"] is False and lightning["count"] == 1
    assert all(gem["count"] >= 1 for group in payload["extra_groups"] for gem in group["gems"])
    assert "Summon Lightning Golem fields 0 instances" in "\n".join(logs)
