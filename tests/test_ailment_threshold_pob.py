"""The boss ailment threshold our Shock / Chill numbers rest on, as PoB itself computes it (#703).

Guard against a silent change in a PoB bump. The numbers are the measured ones of
docs/research/2026-10-06-ailments-spec.md (Row 2, Row 5 draft F4); this test reads them from PoB's own
data tables and the enemy's modifiers in the live calc environment, with `enemyIsBoss = Pinnacle`
(ConfigOptions.lua:2096), and compares. Nothing in product code types the result.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from xml.etree import ElementTree

import pytest

from junkroan.pob import headless_runtime_worker as worker
from junkroan.pob.session import decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
WRAPPER = PROJECT_ROOT / "src" / "junkroan" / "pob" / "headless_wrapper.lua"
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

EXPECTED = {83: 5_473_455, 84: 6_349_995, 85: 6_741_575}

# The very expression of CalcOffence.lua:5210-5218 (isBoss branch), read from the live calc environment.
_READ_THRESHOLD_LUA = """
local env = build.calcsTab.mainEnv
local lvl = env.enemyLevel
local isBoss = env.configInput["enemyIsBoss"] ~= "None"
local t = data.monsterAilmentThresholdTable[lvl]
local life, ail = 1, 1
if lvl >= 66 then
  life = isBoss and data.mapLevelBossLifeMult[lvl] or data.mapLevelLifeMult[lvl]
  ail = isBoss and data.mapLevelBossAilmentMult[lvl] or 1
end
local v = t * (isBoss and 7.68 or 1) * life * env.enemyDB:More(nil, "Life") * ail * env.enemyDB:More(nil, "AilmentThreshold")
return string.format("%d|%s|%s", lvl, tostring(env.configInput["enemyIsBoss"]), string.format("%.6f", v))
"""


@pytest.fixture(scope="module")
def runtime(tmp_path_factory: pytest.TempPathFactory):
    session_root = tmp_path_factory.mktemp("pob-ailment-threshold")
    os.environ["POB_RUNTIME_ROOT"] = RUNTIME_ROOT.resolve().as_posix()
    os.environ["POB_HEADLESS_USER_PATH"] = session_root.as_posix()
    os.environ["POB_HEADLESS_WORKDIR"] = session_root.as_posix()
    os.environ.setdefault("CI", "1")
    previous_cwd = Path.cwd()
    live = worker.HeadlessLuaRuntime(runtime_root=RUNTIME_ROOT.resolve(), session_root=session_root, wrapper_path=WRAPPER.resolve())
    try:
        yield live
    finally:
        live.close()
        os.chdir(previous_cwd)


def _xml_with(level: int) -> str:
    xml = decode_import_code((FIXTURES / "arc_archmage.pob.txt").read_text(encoding="utf-8").strip())
    root = ElementTree.fromstring(xml)
    config = root.find("Config")
    active = next((s for s in config.findall("ConfigSet") if s.get("id") == (config.get("activeConfigSet") or "1")), None)
    holder = active if active is not None else config
    for node in list(holder.findall("Input")):
        if node.get("name") in ("enemyIsBoss", "enemyLevel"):
            holder.remove(node)
    ElementTree.SubElement(holder, "Input", {"name": "enemyIsBoss", "string": "Pinnacle"})
    ElementTree.SubElement(holder, "Input", {"name": "enemyLevel", "number": str(level)})
    return ElementTree.tostring(root, encoding="unicode")


@needs_pob
@pytest.mark.pob
@pytest.mark.parametrize("level", sorted(EXPECTED))
def test_pob_boss_ailment_threshold_matches_the_measured_values(runtime, level: int) -> None:
    runtime.load_reopen_source(_xml_with(level))
    runtime.read_stats(["Life"])  # runs the calc so the environment is built
    got_level, boss, value = runtime._bridge.execute(_READ_THRESHOLD_LUA, nret=1)[0].split("|")
    assert (int(got_level), boss) == (level, "Pinnacle"), "the config did not reach PoB's calc environment"
    assert round(float(value)) == EXPECTED[level], (
        f"PoB's Guardian/Pinnacle ailment threshold at Enemy Level {level} is {round(float(value)):,}, expected {EXPECTED[level]:,}. "
        "Every Shock / Chill number of our builds rests on it: see vendor/pob/source/src/Modules/CalcOffence.lua:5210-5218 "
        "and ConfigOptions.lua:2096, and docs/research/2026-10-06-ailments-spec.md (Row 2, Row 5) before accepting the change."
    )
