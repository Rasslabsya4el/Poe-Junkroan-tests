"""#963: a brand gem reaches PoB with instance count 1, whoever built the PoB.

PoB multiplies a Brand-type skill's TotalDPS by AttachedBrandCount itself (CalcOffence.lua:2423-2425; Wintertide
Brand part 1 puts the same number into its Damage MORE, Data/Skills/act_int.lua:21108-21134), and FullDPS multiplies
again by the gem's count (Calcs.lua:289). The PoB boundary (`PobSession.load_xml` / `set_skills`) writes count 1 on
every brand gem. Rows 1 (trace counter), 2 and 3 (PoB numbers) of the ticket.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from conftest import needs_skill_source
from junkroan.optimizer.trace import TRACE
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
SAVED = FIXTURES / "issue963"
ATTACHED = "You can have an additional Brand Attached to an Enemy"
GEM = re.compile(r"<Gem\b[^>]*>")


def _brand_counts(xml: str) -> dict[str, int]:
    return {
        re.search(r'nameSpec="([^"]*)"', tag).group(1): int(re.search(r'\bcount="(\d+)"', tag).group(1))
        for tag in GEM.findall(xml)
        if "Brand" in tag and re.search(r'\bcount="(\d+)"', tag)
    }


def _fake_session(captured: dict) -> PobSession:
    pob = PobSession.__new__(PobSession)
    pob._fulldps_last_ratio = None
    pob._handle = object()
    pob._adapter = SimpleNamespace(
        apply_skill_state=lambda _handle, payload: captured.update(skills=payload),
        load_build_xml=lambda _handle, xml: captured.update(xml=xml),
    )
    return pob


@needs_skill_source
def test_every_brand_skill_is_known_by_id_and_by_name() -> None:
    from junkroan.pob.skill_facts import brand_skill_ids, brand_skill_names

    ids, names = brand_skill_ids(), brand_skill_names()
    assert {"StormBrand", "PenanceBrand", "ArmageddonBrand", "BrandSupport", "WintertideBrand"} <= ids
    assert {"storm brand", "penance brand", "armageddon brand", "arcanist brand", "wintertide brand"} <= names
    assert "Fireball" not in ids and "fireball" not in names


@needs_skill_source
@pytest.mark.parametrize("fixture", ["tuadh_329/hit_penance_brand", "tuadh_329/stormbrand", "issue963/hit_penance_brand-s4", "issue963/ignite_penance_brand-s4"])
def test_load_xml_hands_the_adapter_a_brand_gem_with_count_one(fixture: str) -> None:
    xml = decode_import_code((FIXTURES / f"{fixture}.pob.txt").read_text(encoding="utf-8").strip())
    assert max(_brand_counts(xml).values()) == 2, "the input must carry the defect, or the test proves nothing"
    captured: dict = {}
    _fake_session(captured).load_xml(xml)
    assert set(_brand_counts(captured["xml"]).values()) == {1}
    assert GEM.sub("", captured["xml"]) == GEM.sub("", xml), "only Gem tags may change"


@needs_skill_source
def test_load_xml_leaves_a_build_without_a_brand_byte_for_byte() -> None:
    xml = decode_import_code((FIXTURES / "tuadh_329" / "spark.pob.txt").read_text(encoding="utf-8").strip())
    captured: dict = {}
    _fake_session(captured).load_xml(xml)
    assert captured["xml"] == xml


@needs_skill_source
def test_load_xml_clamps_only_brand_gems_whatever_the_attribute_order_and_the_variant() -> None:
    xml = (
        '<PathOfBuilding><Skills><SkillSet id="1">'
        '<Skill enabled="true"><Gem nameSpec="Wintertide Brand" skillId="WintertideBrand" count="3"/>'
        '<Gem count="4" nameSpec="Penance Brand of Dissipation" skillId="PenanceBrandAltX"/>'
        '<Gem count="5" nameSpec="Arcanist Brand"/></Skill>'
        '<Skill enabled="true"><Gem nameSpec="Raise Zombie" skillId="RaiseZombie" count="6"/>'
        '<Gem nameSpec="Concentrated Effect" skillId="SupportConcentratedEffect" count="7"/></Skill>'
        '</SkillSet></Skills></PathOfBuilding>'
    )
    captured: dict = {}
    _fake_session(captured).load_xml(xml)
    counts = {g.get("nameSpec"): int(g.get("count")) for g in ElementTree.fromstring(captured["xml"]).iter("Gem")}
    assert counts == {"Wintertide Brand": 1, "Penance Brand of Dissipation": 1, "Arcanist Brand": 1, "Raise Zombie": 6, "Concentrated Effect": 7}


@needs_skill_source
def test_set_skills_writes_count_one_on_a_brand_gem_in_the_main_link_and_in_an_extra_group() -> None:
    captured: dict = {}
    pob = _fake_session(captured)
    pob.set_skills(
        main_link=["Penance Brand", "Arcane Surge"],
        main_counts={"Penance Brand": 2, "Arcane Surge": 1},
        main_instance_counts=[2, 1],
        extra_groups=[{"label": "g", "slot": "Boots", "gems": [
            {"gem_name": "Storm Brand", "count": 2}, {"gem_name": "Raise Zombie", "count": 5}]}],
    )
    main, extra = captured["skills"]["skill_sets"][0]["socket_groups"]
    assert [g["count"] for g in main["gems"]] == [1, 1]
    assert [g["count"] for g in extra["gems"]] == [1, 5], "a minion keeps its limit count; only a brand is held to one"


@needs_skill_source
@pytest.mark.parametrize("main", ["Penance Brand", "Storm Brand"])
def test_row1_trace_counter_a_generation_shaped_like_junkroan_build(main: str, monkeypatch) -> None:
    """Row 1: the skeleton derives count 2 for the brand (generated), PoB is never handed a count above 1 (evaluated)."""

    import junkroan.optimizer.config_rules as config_rules
    from junkroan.search.skeleton import Skeleton

    monkeypatch.setattr(config_rules, "build_text", lambda pob, graph=None: f"Runebinder\n{ATTACHED}\n+10 to Strength")
    captured: dict = {}
    pob = _fake_session(captured)
    pob.stats = lambda keys: {k: (5 if k == "ActiveBrandLimit" else 0) for k in keys}  # type: ignore[method-assign]
    skeleton = Skeleton(class_name="Templar", ascendancy="Inquisitor", main_link=[main, "Arcane Surge"])
    TRACE.reset()
    skeleton.apply_skills(pob)
    skeleton.refresh_minion_counts(pob)
    TRACE.flush("generation")
    cells = TRACE.considered()["generation"]

    assert skeleton.gem_counts[main] == 2, "the derivation itself is unchanged: base 1 + 1 attached"
    assert cells["brand-gem"]["generated"] > 0 and cells["brand-gem"]["evaluated"] > 0
    assert cells["brand-gem:count>1"]["generated"] > 0, "the skeleton did ask for more than one"
    assert cells["brand-gem:count>1"]["evaluated"] == 0, "PoB was never handed it"
    assert all(g["count"] == 1 for sg in captured["skills"]["skill_sets"][0]["socket_groups"] for g in sg["gems"])


# -- PoB tests: rows 2 and 3 -------------------------------------------------------------------------------------

needs_runtime = pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")


def _load_as_the_replay_bench_does(name: str, keys: tuple[str, ...]) -> dict:
    TRACE.reset()
    with PobSession(run_id=f"test-issue963-{name}", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_import_code((SAVED / f"{name}.pob.txt").read_text(encoding="utf-8").strip())
        return pob.stats(keys)


@needs_runtime
@pytest.mark.pob
def test_row2_hit_penance_brand_s4_fulldps_is_totaldps() -> None:
    stats = _load_as_the_replay_bench_does("hit_penance_brand-s4", ("AttachedBrandCount", "TotalDPS", "FullDPS"))
    assert stats["AttachedBrandCount"] == 2
    assert stats["FullDPS"] == pytest.approx(1_163_543, rel=1e-3), "main: 2,327,429 (counted for four brands)"
    assert stats["FullDPS"] == pytest.approx(stats["TotalDPS"], rel=1e-3)
    TRACE.flush("load")
    assert TRACE.considered()["load"]["brand-gem:count>1"] == {"generated": 1, "evaluated": 0}


@needs_runtime
@pytest.mark.pob
def test_row3_ignite_penance_brand_s4_fulldps() -> None:
    stats = _load_as_the_replay_bench_does("ignite_penance_brand-s4", ("AttachedBrandCount", "FullDPS"))
    assert stats["AttachedBrandCount"] == 2
    assert stats["FullDPS"] == pytest.approx(1_278_027, rel=1e-3), "main: 1,480,854 (counted for four brands)"
