import base64
import importlib.util
import json
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("count_vaal_gems", ROOT / "scripts" / "count_vaal_gems.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

KEYS = mod.vaal_keys(json.loads(mod.CORPUS.read_text(encoding="utf-8"))["records"])


def _code(gems: list[tuple[str, str]]) -> str:
    body = "".join(f'<Gem nameSpec="{n}" gemId="{g}" skillId="x" variantId="x"/>' for n, g in gems)
    xml = f"<PathOfBuilding><Build/><Skills><SkillSet><Skill>{body}</Skill></SkillSet></Skills></PathOfBuilding>"
    return base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode()


def test_vaal_gem_counted():
    code = _code([("Vaal Grace", "Metadata/Items/Gems/SkillGemVaalGrace"), ("Fireball", "Metadata/Items/Gems/SkillGemFireball")])
    assert mod.vaal_gems_in_code(code, KEYS) == ["Vaal Grace"]


def test_no_vaal_gem():
    code = _code([("Fireball", "Metadata/Items/Gems/SkillGemFireball")])
    assert mod.vaal_gems_in_code(code, KEYS) == []
