import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_coloured_sockets import check_file  # noqa: E402

ALWAYS = "Gems Socketed always have the Quality bonus from Socket Colour"


def _xml(tmp_path, sockets, gems, extra=""):
    gem_xml = "".join(f'<Gem nameSpec="{g}" enabled="true"/>' for g in gems)
    x = f"""<PathOfBuilding>
<Skills activeSkillSet="1"><SkillSet id="1"><Skill slot="Body Armour" enabled="true">{gem_xml}</Skill></SkillSet></Skills>
<Items activeItemSet="1"><Item id="1">
Rarity: RARE
X
Sockets: {sockets}
{extra}
</Item><ItemSet id="1"><Slot itemId="1" name="Body Armour"/></ItemSet></Items></PathOfBuilding>"""
    p = tmp_path / "b.xml"
    p.write_text(x, encoding="utf-8")
    return p


def test_two_coloured_matching(tmp_path):
    assert check_file(_xml(tmp_path, "R-G W", ["Cleave", "Added Cold Damage", "Arc"])) == []


def test_three_coloured_count(tmp_path):
    v = check_file(_xml(tmp_path, "R-R-R", ["Cleave", "Melee Splash", "Fire Penetration"]))
    assert len(v) == 1 and "coloured sockets" in v[0]


def test_wrong_colour(tmp_path):
    v = check_file(_xml(tmp_path, "G W", ["Cleave"]))
    assert len(v) == 1 and "socket 1" in v[0]


def test_always_matches_not_counted(tmp_path):
    assert check_file(_xml(tmp_path, "R-G-B-R", [], extra=ALWAYS)) == []


def test_all_white(tmp_path):
    assert check_file(_xml(tmp_path, "W-W-W", ["Fireball", "Faster Casting"])) == []


def test_trace_builds_runs():
    d = ROOT / "artifacts" / "replay" / "20261002-2147-trace-437c" / "builds"
    script = ROOT / "scripts" / "check_coloured_sockets.py"
    r = subprocess.run([sys.executable, str(script), str(d)], capture_output=True, text=True)
    assert r.returncode in (0, 1)
    assert "total:" in r.stdout
    print(r.stdout[-400:])
