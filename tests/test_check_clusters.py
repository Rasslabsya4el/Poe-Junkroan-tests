"""Row 5 of #433: scripts/check_clusters.py on the zizaran_326 trickster fixture (no PoB session)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_clusters import check_build  # noqa: E402
from junkroan.optimizer.rails import ClusterRails  # noqa: E402
from junkroan.pob.session import decode_import_code  # noqa: E402

# #602: T16 carries day 1's old cluster rules (rulebook t-cluster, t16 cells)
T16 = ClusterRails(count_max=2, sizes=["large", "medium"], passives={"large": 12, "medium": 6}, notables_max=2, screen_keep=6)

FIXTURE = ROOT / "tests" / "fixtures" / "zizaran_326" / "early" / "trickster_blight_of_contagion.pob.txt"

LARGE_12 = """Rarity: RARE
Day-1 Large Cluster
Large Cluster Jewel
Item Level: 72
Cluster Jewel Skill: affliction_chaos_damage
Cluster Jewel Node Count: 12
Implicits: 3
{crafted}Adds 12 Passive Skills
{crafted}2 Added Passive Skills are Jewel Sockets
{crafted}Added Small Passive Skills grant: 12% increased Chaos Damage
1 Added Passive Skill is Unwaveringly Evil
1 Added Passive Skill is Wicked Pall
"""


def _xml() -> str:
    return decode_import_code(FIXTURE.read_text(encoding="utf-8").strip())


def _replace_large(xml: str, text: str) -> str:
    return re.sub(r'(<Item id="14">).*?(</Item>)', lambda m: m[1] + "\n" + text + m[2], xml, count=1, flags=re.S)


def test_fixture_large_with_10_passives_is_a_violation() -> None:
    jewels, verdict = check_build(_xml(), rails=T16)
    assert jewels[0][:2] == ("large", 10)
    assert "10 passives, not 12" in verdict


def test_fixture_with_large_12_is_ok() -> None:
    jewels, verdict = check_build(_replace_large(_xml(), LARGE_12), rails=T16)
    assert verdict == "OK", verdict
    assert [j[:2] for j in jewels] == [("large", 12)]
    assert jewels[0][2] == ["Unwaveringly Evil", "Wicked Pall"]


def test_small_also_grant_and_third_notable_are_violations() -> None:
    small = LARGE_12.replace("Large Cluster Jewel", "Small Cluster Jewel").replace("Node Count: 12", "Node Count: 2")
    assert "size not allowed" in check_build(_replace_large(_xml(), small))[1]
    also = LARGE_12.replace("Passive Skills grant:", "Passive Skills also grant:")
    assert "also grant" in check_build(_replace_large(_xml(), also))[1]
    three = LARGE_12 + "1 Added Passive Skill is Pain Attunement\n"
    assert "3 notables, max 2" in check_build(_replace_large(_xml(), three))[1]


def test_day1_rails_allow_no_cluster_jewel() -> None:
    """#602: day 1 has none; the T16 rule is the old day-1 rule and matches the rulebook t16 cells."""

    assert "max 0" in check_build(_replace_large(_xml(), LARGE_12))[1]
    from test_rulebook_rails_drift import rulebook_machine_values

    v = rulebook_machine_values()
    assert (v["sizes.t16"], v["passives.large.t16"], v["passives.medium.t16"]) == (T16.sizes, 12, 6)
