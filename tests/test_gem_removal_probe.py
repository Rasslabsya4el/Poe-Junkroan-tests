"""#1204 unit 1: `scripts/gem_removal_probe.py` measures what each utility gem contributes by removing it alone.

PoB-free: `probe_gems` takes a fake session (anything with `load_xml(str)` and `stats(keys)`), so no PobSession
starts here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gem_removal_probe as probe  # noqa: E402
from junkroan.optimizer.build_result import REPORT_KEYS  # noqa: E402

# Skill set 1 is active. Group 2 holds the probe gems; group 5 is a disabled group; set 2 is inactive and holds
# Ancestral Cry only.
XML = """<PathOfBuilding>
  <Build level="90" className="Witch" ascendClassName="Elementalist"/>
  <Skills activeSkillSet="1">
    <SkillSet id="1">
      <Skill mainActiveSkill="1" enabled="true" label="Cold Snap">
        <Gem nameSpec="Cold Snap" skillId="ColdSnap" enabled="true" level="20" quality="0"/>
        <Gem nameSpec="Cruelty" skillId="SupportCruelty" enabled="true" level="20" quality="0"/>
      </Skill>
      <Skill mainActiveSkill="1" enabled="true">
        <Gem nameSpec="Dash" skillId="Dash" enabled="true" level="20" quality="0"/>
        <Gem nameSpec="Smite" skillId="Smite" enabled="true" level="20" quality="0"/>
        <Gem nameSpec="Malevolence" skillId="Malevolence" enabled="true" level="20" quality="0"/>
        <Gem nameSpec="Momentum" skillId="Momentum" enabled="true" level="20" quality="0"/>
        <Gem nameSpec="Dust Tiny" skillId="DustTiny" enabled="true" level="20" quality="0"/>
      </Skill>
      <Skill enabled="true">
        <Gem nameSpec="Herald of Ice" skillId="HeraldOfIce" enabled="true" level="20" quality="0"/>
      </Skill>
      <Skill enabled="true">
        <Gem nameSpec="Herald of Ice" skillId="HeraldOfIce" enabled="false" level="20" quality="0"/>
      </Skill>
      <Skill enabled="false">
        <Gem nameSpec="Pact of Ghorr" skillId="PactOfGhorr" enabled="true" level="20" quality="0"/>
      </Skill>
    </SkillSet>
    <SkillSet id="2">
      <Skill enabled="true">
        <Gem nameSpec="Ancestral Cry" skillId="AncestralCry" enabled="true" level="20" quality="0"/>
      </Skill>
    </SkillSet>
  </Skills>
</PathOfBuilding>
"""

# Two sets, the second one active: Dash lives only in the inactive set 1, Smite in the active set 2.
XML_SET2_ACTIVE = """<PathOfBuilding>
  <Skills activeSkillSet="2">
    <SkillSet id="1">
      <Skill enabled="true"><Gem nameSpec="Dash" skillId="Dash" enabled="true" level="20" quality="0"/></Skill>
    </SkillSet>
    <SkillSet id="2">
      <Skill enabled="true"><Gem nameSpec="Smite" skillId="Smite" enabled="true" level="20" quality="0"/></Skill>
    </SkillSet>
  </Skills>
</PathOfBuilding>
"""

# No activeSkillSet attribute: the first SkillSet is the active one.
XML_NO_ACTIVE_ATTR = XML_SET2_ACTIVE.replace(' activeSkillSet="2"', "")

BASES = {key: 100.0 for key in REPORT_KEYS}
BASES.update({"CombinedDPS": 1000.0, "TotalEHP": 5000.0, "EffectiveMovementSpeedMod": 100.0})


def _enabled_names(xml: str) -> set[str]:
    """Gem names with at least one copy not written enabled=false (the absent attribute reads enabled, as the helper does)."""

    out: set[str] = set()
    for gem in ET.fromstring(xml).iter("Gem"):
        if gem.get("enabled", "true") == "true":
            out.add(str(gem.get("nameSpec") or "").strip().lower())
    return out


class FakeSession:
    """Each enabled gem name adds its contribution to the stats it names; a gem with no entry adds nothing."""

    def __init__(self, contributions: dict[str, dict[str, float]] | None = None) -> None:
        self.contributions = {k.lower(): v for k, v in (contributions or {}).items()}
        self.loads: list[str] = []
        self.stat_keys: list[tuple[str, ...]] = []
        self.current = ""

    def load_xml(self, xml_text: str) -> None:
        self.loads.append(xml_text)
        self.current = xml_text

    def stats(self, keys):
        self.stat_keys.append(tuple(keys))
        enabled = _enabled_names(self.current)
        return {
            key: BASES.get(key, 0.0) + sum(self.contributions.get(name, {}).get(key, 0.0) for name in enabled)
            for key in keys
        }


def _row(rows, gem):
    return next(r for r in rows if r["gem"] == gem)


def test_absent_gem_is_a_row_without_a_run():
    session = FakeSession()
    result = probe.probe_gems(session, XML, ["Summon Chaos Golem"])
    row = result["rows"][0]
    assert row["present"] == "no"
    assert row["enabled"] == "n/a"
    assert row["group_enabled"] == "n/a"
    assert row["note"] == ""
    assert row["delta_CombinedDPS"] is None and row["delta_TotalEHP"] is None and row["delta_EffectiveMovementSpeedMod"] is None
    assert row["moved_keys"] == []
    assert row["zero"] is None and row["zero_all"] is None
    # the only load is the build as it is: no XML with the absent gem disabled, nothing else
    assert session.loads == [XML]


def test_delta_is_with_gem_minus_without_gem_so_its_sign_is_what_the_gem_contributes():
    session = FakeSession({
        "Smite": {"CombinedDPS": 200.0},
        "Dash": {"EffectiveMovementSpeedMod": 30.0},
        "Malevolence": {"TotalEHP": -10.0},
    })
    result = probe.probe_gems(session, XML, ["Smite", "Dash", "Malevolence"])
    assert result["base"]["CombinedDPS"] == 1000.0 + 200.0
    assert result["base"]["TotalEHP"] == 5000.0 - 10.0
    smite = _row(result["rows"], "Smite")
    dash = _row(result["rows"], "Dash")
    malevolence = _row(result["rows"], "Malevolence")
    assert smite["present"] == "yes" and smite["enabled"] == "yes"
    assert smite["delta_CombinedDPS"] == 200.0 and smite["zero"] is False
    assert dash["delta_EffectiveMovementSpeedMod"] == 30.0 and dash["delta_CombinedDPS"] == 0.0
    assert malevolence["delta_TotalEHP"] == -10.0


def test_gem_with_no_change_is_zero_and_a_small_relative_change_is_not():
    session = FakeSession({"Smite": {"CombinedDPS": 1e-3}})  # 1e-3 on a base of 1000 is far above 1e-9 relative
    result = probe.probe_gems(session, XML, ["Momentum", "Smite"])
    momentum = _row(result["rows"], "Momentum")
    assert momentum["zero"] is True
    assert momentum["zero_all"] is True
    assert momentum["delta_CombinedDPS"] == 0.0 and momentum["delta_TotalEHP"] == 0.0 and momentum["delta_EffectiveMovementSpeedMod"] == 0.0
    assert _row(result["rows"], "Smite")["zero"] is False


def test_relative_tolerance_absorbs_float_noise_only():
    session = FakeSession({"Smite": {"CombinedDPS": 1e-12}})  # 1e-12 is under 1e-9 of 1000
    result = probe.probe_gems(session, XML, ["Smite"])
    assert _row(result["rows"], "Smite")["zero"] is True


def test_base_xml_is_reloaded_before_each_gem():
    session = FakeSession({"Dash": {"EffectiveMovementSpeedMod": 30.0}, "Smite": {"CombinedDPS": 200.0}})
    probe.probe_gems(session, XML, ["Dash", "Smite"])
    # base read, then (removal, base) per gem
    assert session.loads[0] == XML
    assert session.loads[2] == XML
    assert session.loads[4] == XML
    assert len(session.loads) == 5
    # each removal load disables that one gem and leaves the other on
    assert "dash" not in _enabled_names(session.loads[1]) and "smite" in _enabled_names(session.loads[1])
    assert "smite" not in _enabled_names(session.loads[3]) and "dash" in _enabled_names(session.loads[3])


def test_one_stats_call_per_load_reads_every_report_key():
    session = FakeSession()
    probe.probe_gems(session, XML, ["Dash", "Smite"])
    # one read after the base load, one after each removal load: 1 + 2 reads
    assert len(session.stat_keys) == 3
    for keys in session.stat_keys:
        assert set(REPORT_KEYS) <= set(keys)
        assert {"CombinedDPS", "TotalEHP", "EffectiveMovementSpeedMod"} <= set(keys)


def test_mixed_enabled_copies_are_reported_as_mixed():
    session = FakeSession({"Herald of Ice": {"CombinedDPS": 300.0}})
    result = probe.probe_gems(session, XML, ["Herald of Ice"])
    row = result["rows"][0]
    assert row["enabled"] == "mixed"
    assert row["present"] == "yes"


def test_all_copies_are_disabled_at_once_for_a_gem_in_two_groups():
    session = FakeSession({"Herald of Ice": {"CombinedDPS": 300.0}})
    result = probe.probe_gems(session, XML, ["Herald of Ice"])
    removal_xml = session.loads[1]
    herald_copies = [g for g in ET.fromstring(removal_xml).iter("Gem") if g.get("nameSpec") == "Herald of Ice"]
    assert len(herald_copies) == 2
    assert all(g.get("enabled") == "false" for g in herald_copies)
    # both copies off, so the contribution is counted once, as the whole gem
    assert _row(result["rows"], "Herald of Ice")["delta_CombinedDPS"] == 300.0


def test_group_names_the_socket_group_of_the_gem():
    session = FakeSession()
    result = probe.probe_gems(session, XML, ["Smite", "Cold Snap"])
    # the 1-based index in the active SkillSet, then the skill's label, else its first gem
    assert _row(result["rows"], "Smite")["group"] == "2: Dash"
    assert _row(result["rows"], "Cold Snap")["group"] == "1: Cold Snap"


def test_moved_keys_list_the_other_keys_a_gem_moves_with_their_delta():
    # Pact of Ghorr moves FireResist only; Malevolence moves Life only. Neither moves a probe key.
    session = FakeSession({
        "Pact of Ghorr": {"FireResist": -5.0},
        "Malevolence": {"Life": 50.0},
    })
    result = probe.probe_gems(session, XML, ["Pact of Ghorr", "Malevolence"])
    pact = _row(result["rows"], "Pact of Ghorr")
    assert pact["moved_keys"] == [{"key": "FireResist", "delta": -5.0}]
    assert pact["zero"] is True  # the probe keys stay still
    assert pact["zero_all"] is False  # but a key moved
    malevolence = _row(result["rows"], "Malevolence")
    assert malevolence["moved_keys"] == [{"key": "Life", "delta": 50.0}]
    assert malevolence["zero"] is True and malevolence["zero_all"] is False


def test_zero_all_is_true_only_when_no_key_at_all_moved():
    session = FakeSession()
    result = probe.probe_gems(session, XML, ["Momentum"])
    momentum = _row(result["rows"], "Momentum")
    assert momentum["moved_keys"] == []
    assert momentum["zero"] is True and momentum["zero_all"] is True


def test_group_enabled_comes_from_the_skill_element_and_enabled_from_the_gem():
    session = FakeSession()
    result = probe.probe_gems(session, XML, ["Pact of Ghorr", "Smite"])
    pact = _row(result["rows"], "Pact of Ghorr")
    assert pact["enabled"] == "yes"  # the Gem's own flag
    assert pact["group_enabled"] == "no"  # its Skill group is disabled
    smite = _row(result["rows"], "Smite")
    assert smite["group_enabled"] == "yes"


def test_gem_only_in_an_inactive_skill_set_is_absent_with_a_note_and_no_run():
    session = FakeSession()
    result = probe.probe_gems(session, XML_SET2_ACTIVE, ["Dash", "Smite"])
    dash = _row(result["rows"], "Dash")
    assert dash["present"] == "no"
    assert dash["note"] == "only in an inactive skill set"
    assert dash["enabled"] == "n/a"
    smite = _row(result["rows"], "Smite")
    assert smite["present"] == "yes"
    # the base load and the one removal of Smite (with its reload): Dash never gets a run
    assert len(session.loads) == 3


def test_missing_active_attribute_means_the_first_skill_set_is_active():
    session = FakeSession()
    result = probe.probe_gems(session, XML_NO_ACTIVE_ATTR, ["Dash", "Smite"])
    assert _row(result["rows"], "Dash")["present"] == "yes"
    smite = _row(result["rows"], "Smite")
    assert smite["present"] == "no" and smite["note"] == "only in an inactive skill set"


def test_rows_are_json_serialisable_with_a_real_delta():
    session = FakeSession({"Smite": {"CombinedDPS": 200.0}})
    result = probe.probe_gems(session, XML, ["Smite"])
    loaded = json.loads(json.dumps(result))
    assert loaded["rows"][0]["gem"] == "Smite"
    assert loaded["rows"][0]["delta_CombinedDPS"] == 200.0


def test_markdown_states_the_delta_direction_and_the_n_a_cells():
    session = FakeSession({"Pact of Ghorr": {"FireResist": -5.0}})
    result = probe.probe_gems(session, XML, ["Pact of Ghorr", "Summon Chaos Golem"])
    text = probe.markdown_table(result)
    assert "with gem − without gem" in text
    assert "FireResist -5.0" in text
    golem_line = next(line for line in text.splitlines() if line.startswith("| Summon Chaos Golem"))
    assert "| n/a |" in golem_line
