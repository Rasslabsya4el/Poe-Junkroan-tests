"""#908: the delivered Baseline obeys the audit's own charge proof.

impale_ballista s4 was delivered with `useFrenzyCharges` + `overrideFrenzyCharges` on in Baseline while the audit of
the same build says Frenzy sustains none. The lane was derived on the plain gems; `_deliver_vaal_twins` (the last gem
step) writes Vaal Rain of Arrows, and Frenzy's own `Speed` as the proof reads it goes 0.72 -> 0.00 there, with no
step after it that derives the lane again. `switch_off_unproven_charges` asks the audit's proof on the delivered
build and drops what it flags; `BuildPipeline._enforce_charge_proof` runs it in `_finish` after `_prune_and_deliver`.

The PoB-free tests use a fake session and a stand-in for the audit's proof; the `pob` tests run the real proof on the
delivered codes of run j-20261011-1742-c160 (tests/fixtures/issue908).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from junkroan.optimizer import audit as audit_module
from junkroan.optimizer.audit import Finding, audit_conservative_generator_proofs, baseline_config_inputs
from junkroan.optimizer.config_rules import CHARGE_VARS
from junkroan.optimizer.judging import switch_off_unproven_charges
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "issue908"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

OTHER_FIVE = ("bleed_bow", "burning_arrow_snipe", "cold_dot", "stormbrand", "summon_raging_spirits")
CHARGE_INPUTS = ("usePowerCharges", "useFrenzyCharges", "useEnduranceCharges", "overridePowerCharges", "overrideFrenzyCharges", "overrideEnduranceCharges")

FAKE_XML = """<PathOfBuilding><Config>
<ConfigSet id="1" title="Baseline"><Input name="usePowerCharges" boolean="true"/><Input name="useFrenzyCharges" boolean="true"/><Input name="overrideFrenzyCharges" number="1"/><Input name="enemyLevel" number="84"/></ConfigSet>
<ConfigSet id="2" title="Conditional"><Input name="useFrenzyCharges" boolean="true"/><Input name="usePowerCharges" boolean="true"/></ConfigSet>
</Config></PathOfBuilding>"""


class FakePob:
    def __init__(self, xml: str) -> None:
        self.xml, self.loaded = xml, []

    def export_xml(self) -> str:
        return self.xml

    def stats(self, keys=None) -> dict:
        return {}

    def load_xml(self, xml: str) -> None:
        self.loaded.append(xml)
        self.xml = xml


def _sets(xml: str) -> dict[str, dict[str, dict]]:
    config = ET.fromstring(xml).find("Config")
    return {s.get("title"): {i.get("name"): dict(i.attrib) for i in s if i.tag == "Input"} for s in config.findall("ConfigSet")}


def _fake_proof(monkeypatch: pytest.MonkeyPatch, flagged: list[str], calls: list | None = None) -> None:
    def proof(pob, xml, stats):
        if calls is not None:
            calls.append(xml)
        return [Finding("error", "conservative generator proof", f"{var} is on in Baseline but off: nothing sustains it") for var in flagged]

    monkeypatch.setattr(audit_module, "audit_conservative_generator_proofs", proof)


# -- PoB-free ---------------------------------------------------------------------------------------------------------


def test_a_flagged_var_leaves_baseline_with_its_override_and_an_unflagged_one_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_proof(monkeypatch, ["useFrenzyCharges"])
    pob = FakePob(FAKE_XML)
    before = _sets(pob.xml)

    off = switch_off_unproven_charges(pob)

    after = _sets(pob.xml)
    assert off == ["useFrenzyCharges"]
    assert len(pob.loaded) == 1
    assert "useFrenzyCharges" not in after["Baseline"] and "overrideFrenzyCharges" not in after["Baseline"]
    assert after["Baseline"]["usePowerCharges"] == before["Baseline"]["usePowerCharges"]  # not flagged: stays
    assert after["Baseline"]["enemyLevel"] == before["Baseline"]["enemyLevel"]
    assert after["Conditional"] == before["Conditional"]  # the optimistic lane is not touched


def test_nothing_flagged_loads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _fake_proof(monkeypatch, [], calls)
    pob = FakePob(FAKE_XML)
    assert switch_off_unproven_charges(pob) == []
    assert calls and pob.loaded == []


def test_no_charge_on_in_baseline_does_not_ask_the_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _fake_proof(monkeypatch, ["useFrenzyCharges"], calls)
    xml = FAKE_XML.replace('<Input name="usePowerCharges" boolean="true"/><Input name="useFrenzyCharges" boolean="true"/><Input name="overrideFrenzyCharges" number="1"/>', "", 1)
    pob = FakePob(xml)
    assert switch_off_unproven_charges(pob) == []
    assert calls == [] and pob.loaded == []


def test_only_a_charge_var_is_switched_off_even_when_the_proof_flags_a_buff(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_proof(monkeypatch, ["buffOnslaught", "usePowerCharges"])
    pob = FakePob(FAKE_XML.replace('<Input name="enemyLevel" number="84"/>', '<Input name="buffOnslaught" boolean="true"/>'))
    assert switch_off_unproven_charges(pob) == ["usePowerCharges"]
    assert "buffOnslaught" in _sets(pob.xml)["Baseline"]  # buffs are the audit's, not this step's


def test_the_pipeline_step_logs_what_it_switched_off_and_skips_a_pob_without_the_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_proof(monkeypatch, ["useFrenzyCharges"])
    lines: list[str] = []
    host = SimpleNamespace(pob=FakePob(FAKE_XML), log=lines.append)
    assert BuildPipeline._enforce_charge_proof(host) == ["useFrenzyCharges"]
    assert len(lines) == 1 and "useFrenzyCharges" in lines[0]
    assert BuildPipeline._enforce_charge_proof(SimpleNamespace(pob=SimpleNamespace(), log=lines.append)) == []


def test_finish_runs_the_step_after_the_gems_are_final_and_before_the_delivered_numbers() -> None:
    source = inspect.getsource(BuildPipeline._finish)
    assert source.index("self._prune_and_deliver(") < source.index("self._enforce_charge_proof()") < source.index("self._read_delivered_numbers(")


# -- PoB: the real proof on the delivered codes -----------------------------------------------------------------------


def _code(slug: str) -> str:
    return (FIXTURES / f"{slug}-s4.pob.txt").read_text(encoding="utf-8").strip()


def _proof_errors(pob: PobSession) -> list[str]:
    return [f.detail for f in audit_conservative_generator_proofs(pob, pob.export_xml(), pob.stats()) if f.severity == "error"]


def _plain_gems(xml: str) -> str:
    """The delivered XML with every Vaal twin written back as the plain gem: the form the lane was derived on."""

    root = ET.fromstring(xml)
    for gem in root.iter("Gem"):
        name = gem.get("nameSpec") or ""
        if name.startswith("Vaal "):
            gem.set("nameSpec", name[len("Vaal "):])
            for attr in ("gemId", "skillId", "variantId"):
                gem.attrib.pop(attr, None)
            gem.set("enableGlobal1", "true")
            gem.set("enableGlobal2", "false")
    return ET.tostring(root, encoding="unicode")


def _frenzy_speed(pob: PobSession) -> float:
    return pob.active_skill_stats(("Frenzy",), ("Speed",))["Frenzy"]["Speed"]


@needs_pob
@pytest.mark.pob
@pytest.mark.parametrize("form", ("vaal", "plain"))
def test_frenzy_speed_as_the_proof_reads_it_is_0_725_in_the_vaal_form_and_in_the_plain_form(form: str) -> None:
    """Row 8. Frenzy is triggered by Manaforged Arrows; PoB takes as the trigger source the bow attack with the highest
    rate, the first listed on a tie. In the Vaal form that is Vaal Rain of Arrows (souls, no mana cost) ahead of its own
    twin Rain of Arrows at the same rate, so Frenzy's trigger rate read 0 ("Source skill has no mana cost")."""

    with PobSession(run_id=f"t908-fs-{form}") as pob:
        pob.load_import_code(_code("impale_ballista"))
        if form == "plain":
            pob.load_xml(_plain_gems(pob.export_xml()))
        assert _frenzy_speed(pob) == pytest.approx(0.725)


@needs_pob
@pytest.mark.pob
def test_impale_ballista_delivered_code_keeps_its_frenzy_toggle_with_audit_errors_0_and_its_numbers() -> None:
    """Row 10. The delivered build (Vaal Rain of Arrows written) carries `useFrenzyCharges`; the proof reads Frenzy's
    sustained rate right, so nothing is switched off and the numbers are the delivered ones."""

    with PobSession(run_id="t908-ib") as pob:
        pob.load_import_code(_code("impale_ballista"))
        held = baseline_config_inputs(pob.export_xml())
        assert held["useFrenzyCharges"] is True and held["overrideFrenzyCharges"] == 1
        assert _proof_errors(pob) == []

        assert switch_off_unproven_charges(pob) == []

        assert baseline_config_inputs(pob.export_xml())["useFrenzyCharges"] is True
        stats = pob.stats(("CombinedDPS", "FullDPS"))
        assert round(stats["FullDPS"]) == 573364 and round(stats["CombinedDPS"]) == 110060  # not 538,776 / 103,445


@needs_pob
@pytest.mark.pob
def test_an_unsustained_charge_is_still_switched_off_when_the_generators_speed_is_truly_0() -> None:
    """Row 11. The plain form with Lifetap on both bow attacks: neither spends mana, Frenzy's Manaforged trigger has no
    source cost to count, its Speed is 0 in the plain form too. The enforcement step cuts the toggle."""

    with PobSession(run_id="t908-zero") as pob:
        pob.load_import_code(_code("impale_ballista"))
        root = ET.fromstring(_plain_gems(pob.export_xml()))
        for group in list(root.find("Skills").iter("Skill"))[:2]:
            ET.SubElement(group, "Gem", {"nameSpec": "Lifetap", "level": "20", "quality": "0", "enabled": "true", "enableGlobal1": "true", "enableGlobal2": "false", "count": "1"})
        pob.load_xml(ET.tostring(root, encoding="unicode"))
        assert _frenzy_speed(pob) == 0
        before = _sets(pob.export_xml())
        held = baseline_config_inputs(pob.export_xml())
        assert held["useFrenzyCharges"] is True and held["overrideFrenzyCharges"] == 1
        errors = _proof_errors(pob)
        assert len(errors) == 1 and errors[0].startswith("useFrenzyCharges is on in Baseline but"), errors

        assert switch_off_unproven_charges(pob) == ["useFrenzyCharges"]

        assert _proof_errors(pob) == []
        after = _sets(pob.export_xml())
        assert "useFrenzyCharges" not in after["Baseline"] and "overrideFrenzyCharges" not in after["Baseline"]
        assert {k: v for k, v in after["Baseline"].items() if k not in ("useFrenzyCharges", "overrideFrenzyCharges")} == \
            {k: v for k, v in before["Baseline"].items() if k not in ("useFrenzyCharges", "overrideFrenzyCharges")}
        assert {t: v for t, v in after.items() if t != "Baseline"} == {t: v for t, v in before.items() if t != "Baseline"}
        # a second call has nothing left to switch off
        assert switch_off_unproven_charges(pob) == []


@needs_pob
@pytest.mark.pob
def test_a_build_whose_frenzy_is_sustained_keeps_its_toggle() -> None:
    """The same build on the plain gems: Frenzy's own Speed reads above 0, the proof holds, the toggle stays."""

    with PobSession(run_id="t908-plain") as pob:
        pob.load_import_code(_code("impale_ballista"))
        pob.load_xml(_plain_gems(pob.export_xml()))
        assert _proof_errors(pob) == []
        before = pob.export_xml()
        held = baseline_config_inputs(before)
        assert held["useFrenzyCharges"] is True and held["overrideFrenzyCharges"] == 1

        assert switch_off_unproven_charges(pob) == []

        assert pob.export_xml() == before
        assert baseline_config_inputs(pob.export_xml())["useFrenzyCharges"] is True


@needs_pob
@pytest.mark.pob
@pytest.mark.parametrize("slug", OTHER_FIVE)
def test_the_other_delivered_codes_have_audit_errors_0_before_and_after_and_keep_their_toggles(slug: str) -> None:
    with PobSession(run_id=f"t908-{slug}") as pob:
        pob.load_import_code(_code(slug))
        assert _proof_errors(pob) == []
        before = {k: v for k, v in (baseline_config_inputs(pob.export_xml()) or {}).items()}

        assert switch_off_unproven_charges(pob) == []

        assert _proof_errors(pob) == []
        after = baseline_config_inputs(pob.export_xml()) or {}
        assert {k: after.get(k) for k in CHARGE_INPUTS} == {k: before.get(k) for k in CHARGE_INPUTS}
        assert after == before
