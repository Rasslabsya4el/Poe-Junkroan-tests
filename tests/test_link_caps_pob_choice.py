"""gm-links (#426 unit 3): an over-cap group loses the support PoB scores least, not the last one."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from junkroan.optimizer.rails import Rails
from junkroan.search.skeleton import Skeleton, SocketGroup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import build_from_skeleton as bfs  # noqa: E402

MAIN = ["Fireball", "Spell Echo", "Controlled Destruction", "Increased Critical Strikes", "Elemental Focus", "Faster Casting"]
EXTRA = ["Arc", "Added Fire Damage", "Efficacy", "Faster Casting", "Concentrated Effect"]
# value factor of each support; Elemental Focus (main) and Efficacy (extra) are worth least and are not last
WORTH = {"Spell Echo": 1.5, "Controlled Destruction": 1.4, "Increased Critical Strikes": 1.3, "Elemental Focus": 1.01, "Faster Casting": 1.2,
         "Added Fire Damage": 1.3, "Efficacy": 1.02, "Concentrated Effect": 1.25}


def _xml() -> str:
    def skill(names: list[str]) -> str:
        return '<Skill enabled="true">' + "".join(f'<Gem nameSpec="{n}" enabled="true"/>' for n in names) + "</Skill>"

    return f'<PathOfBuilding><Build mainSocketGroup="1"/><Skills activeSkillSet="1"><SkillSet id="1">{skill(MAIN)}{skill(EXTRA)}</SkillSet></Skills></PathOfBuilding>'


class FakePob:
    """export_xml / load_xml / stats; every stat multiplies the WORTH of the enabled gems."""

    def __init__(self) -> None:
        self.xml = _xml()

    def export_xml(self) -> str:
        return self.xml

    def load_xml(self, xml: str) -> None:
        self.xml = xml

    def stats(self, keys):
        value = 1000.0
        for gem in ET.fromstring(self.xml).iter("Gem"):
            if gem.get("enabled") == "true":
                value *= WORTH.get(gem.get("nameSpec"), 1.0)
        return {k: value for k in keys}


def _skeleton() -> Skeleton:
    return Skeleton(class_name="Witch", ascendancy="None", main_link=list(MAIN), extra_groups=[SocketGroup(gems=list(EXTRA), label="aura", source_index=2)])


def test_pob_drops_the_cheapest_support_not_the_last() -> None:
    pob, sk = FakePob(), _skeleton()
    original = pob.xml
    lines = bfs.drop_over_cap_gems(pob, sk, 1, rails=Rails.load())
    assert sk.main_link == ["Fireball", "Spell Echo", "Controlled Destruction", "Increased Critical Strikes", "Faster Casting"]
    assert sk.extra_groups[0].gems == ["Arc", "Added Fire Damage", "Faster Casting", "Concentrated Effect"]
    assert len(lines) == 2 and "Elemental Focus" in lines[0] and "Efficacy" in lines[1]
    assert "with" in lines[0] and "without" in lines[0]
    assert pob.xml == original and 'enabled="false"' not in pob.xml  # every gem enabled again
    assert sk.cap_links(Rails.load()) == []  # the end-trim after it is a no-op


def test_a_group_pob_cannot_address_is_left_to_the_end_trim() -> None:
    sk = _skeleton()
    sk.extra_groups[0].source_index = 0
    bfs.drop_over_cap_gems(FakePob(), sk, 1, rails=Rails.load())
    assert len(sk.main_link) == 5 and len(sk.extra_groups[0].gems) == 5  # untouched here
    sk.cap_links(Rails.load())
    assert sk.extra_groups[0].gems == EXTRA[:4]


@pytest.mark.pob
def test_real_zizaran_build_main_link_five_and_log_names_dropped_gem() -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    path = PROJECT_ROOT / "tests" / "fixtures" / "zizaran_327" / "assassin_poison_spark.pob.txt"
    xml = decode_import_code(path.read_text(encoding="utf-8").strip())
    logs: list[str] = []
    with PobSession(run_id="test_link_caps_pob_choice") as pob:
        pob.load_xml(xml)
        sk = bfs.skeleton_from_xml(xml, pob, log=logs.append, rails=Rails.load())
    assert len(sk.main_link) == 5
    dropped = [l for l in logs if "gm-links cap: dropped" in l and " with, " in l and " without)" in l]
    assert dropped, logs
    print("\n".join(dropped))
