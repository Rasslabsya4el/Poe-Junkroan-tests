"""D57 rule 1, no PoB: brands are instance-counted, the count is derived (attach base + attached-brand mods, capped by
ActiveBrandLimit), and the benchmark writes that count into the author's main gem."""

import sys
from pathlib import Path

from junkroan.optimizer.objective_select import counts_instances
from junkroan.pob.skill_facts import brand_attach_base
from junkroan.search import skeleton as skeleton_mod
from junkroan.search.skeleton import derived_counts

from conftest import needs_skill_source

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark import flag_main_group_for_full_dps  # noqa: E402

ATTACHED = "You can have an additional Brand Attached to an Enemy"


class _Pob:
    def __init__(self, limit):
        self.limit = limit

    def stats(self, keys):
        return {k: (self.limit if k == "ActiveBrandLimit" else 0) for k in keys}


@needs_skill_source
def test_brand_skills_carry_an_attach_base_and_count_instances() -> None:
    assert brand_attach_base("StormBrand") == 1
    assert brand_attach_base("PenanceBrand") == 1
    assert brand_attach_base("Fireball") is None
    assert counts_instances("Storm Brand") and counts_instances("Penance Brand")
    assert not counts_instances("Fireball")


@needs_skill_source
def test_the_count_is_the_base_plus_attached_mods_capped_by_the_active_limit(monkeypatch) -> None:
    import junkroan.optimizer.config_rules as config_rules

    monkeypatch.setattr(config_rules, "build_text", lambda pob, graph=None: f"Runebinder\n{ATTACHED}\n+10 to Strength")
    assert derived_counts(_Pob(5), ["Storm Brand", "Flame Dash"]) == {"Storm Brand": 2}
    monkeypatch.setattr(config_rules, "build_text", lambda pob, graph=None: "+10 to Strength")
    assert derived_counts(_Pob(5), ["Storm Brand"]) == {"Storm Brand": 1}
    monkeypatch.setattr(config_rules, "build_text", lambda pob, graph=None: f"{ATTACHED}\n{ATTACHED}")
    assert derived_counts(_Pob(2), ["Penance Brand"]) == {"Penance Brand": 2}, "capped by ActiveBrandLimit, as PoB caps it"
    assert derived_counts(_Pob(5), ["Fireball"]) == {}


def test_the_benchmark_writes_the_derived_count_into_the_authors_main_gem() -> None:
    xml = ('<PathOfBuilding><Build mainSocketGroup="2"/><Skills activeSkillSet="1"><SkillSet id="1">'
           '<Skill enabled="true" slot="Gloves"><Gem nameSpec="Flame Dash" count="nil"/></Skill>'
           '<Skill enabled="true" slot="Body Armour"><Gem nameSpec="Storm Brand" count="7"/><Gem nameSpec="Concentrated Effect"/></Skill>'
           '</SkillSet></Skills></PathOfBuilding>')
    out = flag_main_group_for_full_dps(xml, count=2)
    assert 'includeInFullDPS="true"' in out and 'nameSpec="Storm Brand" count="2"' in out
    assert 'nameSpec="Flame Dash" count="nil"' in out
    assert skeleton_mod._BRAND_ATTACHED_LINE.search(ATTACHED)
