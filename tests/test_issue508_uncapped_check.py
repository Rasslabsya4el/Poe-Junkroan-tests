"""#508: the uncapped-stack check of `derive_config` reads the build without D78's ailment-stack
surfaces in place (the worker lifts them out of the live Baseline config set, reads, puts them back)
instead of two whole-build `load_xml` round trips (~1.7 s of ~3.1 s per `read_lanes`).

A speed change that moves no number (D113): the PoB-free tests pin the call shape (no `load_xml`, no
export, the stand-in path kept for stand-ins); the `pob` test pins the numbers: on each fixture the
in-place reading equals the reload reading to the digit, and the session after the read equals the
session before it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from junkroan.optimizer import config_rules
from junkroan.optimizer.config_rules import uncapped_ailment_stats, uncapped_ailment_stats_by_reload
from junkroan.optimizer.ramp_inputs import AILMENT_STACK_INPUTS, uncapped_ailment_stack_xml
from junkroan.pob import headless_runtime_worker as worker
from junkroan.pob.session import PobSession

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

CAPPED_XML = ('<PathOfBuilding><Config activeConfigSet="1"><ConfigSet id="1" title="Baseline">'
              '<Input name="overrideBleedStackPotential" number="3"/><Input name="multiplierBleedsOnEnemy" number="3"/>'
              '</ConfigSet></Config></PathOfBuilding>')


class _Stand:
    """A stand-in for a session: records the calls the check makes."""

    def __init__(self, xml: str = CAPPED_XML, stats: dict[str, Any] | None = None) -> None:
        self.calls: list[str] = []
        self.xml = xml
        self._stats = stats if stats is not None else {"CombinedDPS": 100.0}

    def export_xml(self) -> str:
        self.calls.append("export_xml")
        return self.xml

    def load_xml(self, xml: str) -> None:
        self.calls.append("load_xml")
        self.xml = xml

    def stats(self) -> dict[str, Any]:
        self.calls.append("stats")
        return dict(self._stats) if "<Input" in self.xml and "overrideBleedStackPotential" in self.xml else {"CombinedDPS": 250.0}


class _InPlace:
    """What a PobSession offers: the in-place reader; any load or export would be a regression."""

    def __init__(self, answer: dict[str, Any] | None) -> None:
        self.answer, self.calls = answer, []

    def stats_without_ailment_caps(self) -> dict[str, Any] | None:
        self.calls.append("stats_without_ailment_caps")
        return self.answer

    def load_xml(self, xml: str) -> None:  # pragma: no cover - failure path
        raise AssertionError("load_xml must not be called")

    def export_xml(self) -> str:  # pragma: no cover - failure path
        raise AssertionError("export_xml must not be called")


def test_a_session_reads_the_uncapped_stats_in_place_without_a_load_or_an_export() -> None:
    stats = {"CombinedDPS": 100.0}
    capped = _InPlace({"CombinedDPS": 250.0})
    assert uncapped_ailment_stats(capped, stats) == {"CombinedDPS": 250.0}
    assert capped.calls == ["stats_without_ailment_caps"]
    clean = _InPlace(None)  # the Baseline set holds none of the surfaces: the first read stands
    assert uncapped_ailment_stats(clean, stats) is stats


def test_a_stand_in_without_the_in_place_reader_keeps_the_reload_path() -> None:
    stand = _Stand()
    assert uncapped_ailment_stats(stand, {"CombinedDPS": 100.0}) == {"CombinedDPS": 250.0}
    assert stand.calls == ["export_xml", "load_xml", "stats", "load_xml"]
    assert "overrideBleedStackPotential" in stand.xml  # the snapshot went back
    assert uncapped_ailment_stats_by_reload(_Stand(xml="<PathOfBuilding/>"), {"CombinedDPS": 1.0}) == {"CombinedDPS": 1.0}


def test_derive_config_asks_the_helper_once() -> None:
    source = Path(config_rules.__file__).read_text(encoding="utf-8")
    assert source.count("uncapped_ailment_stats(pob, stats)") == 1
    assert "pob.load_xml(" not in source.split("def derive_config(", 1)[1].split("\ndef ", 1)[0]


class _Adapter:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result, self.seen = result, []

    def read_stats_uncapped(self, handle: Any, keys: Any, parts: Any) -> dict[str, Any]:
        self.seen.append((handle, keys, parts))
        return self.result


def _session(adapter: _Adapter, mean_parts: tuple[int, ...] | None = None) -> PobSession:
    session = object.__new__(PobSession)
    session._adapter, session._handle = adapter, "h"
    if mean_parts:
        session.mean_parts = mean_parts
    return session


def test_the_session_call_returns_none_when_nothing_was_stripped_and_the_stats_when_something_was() -> None:
    nothing = _Adapter({"changed": False})
    assert _session(nothing).stats_without_ailment_caps() is None
    assert nothing.seen == [("h", None, None)]
    something = _Adapter({"changed": True, "stats": {"CombinedDPS": 7.0}})
    session = _session(something, mean_parts=(1, 2))
    assert session.stats_without_ailment_caps() == {"CombinedDPS": 7.0}
    assert something.seen == [("h", None, [1, 2])]  # the same mean-over-parts reading `stats()` does
    assert session.pob_calls()["stats_uncapped"]["count"] == 1


def test_the_worker_lua_lifts_exactly_what_uncapped_ailment_stack_xml_strips() -> None:
    prelude = "\n".join(worker._UNCAPPED_PRELUDE_LUA)
    names = set(re.findall(r"'((?:override\w+StackPotential)|multiplierBleedsOnEnemy)'", prelude))
    assert names == set(AILMENT_STACK_INPUTS)
    assert "'junkroan: poison stacks'" in prelude
    stripped = uncapped_ailment_stack_xml(
        '<PathOfBuilding><Config><ConfigSet title="Baseline">'
        '<Input name="overrideIgniteStackPotential" number="2"/><Input name="multiplierBleedsOnEnemy" number="2"/>'
        '<CustomModifierBlock title="junkroan: poison stacks 3 of 8.00 inside 2.5 s" enabled="true">x</CustomModifierBlock>'
        "</ConfigSet></Config></PathOfBuilding>")
    assert "junkroan" not in stripped and "Input" not in stripped
    assert "Baseline" in prelude and "title == 'Baseline'" in prelude


def test_the_plain_read_does_not_touch_the_config_and_the_uncapped_one_puts_every_input_back() -> None:
    class Bridge:
        def __init__(self) -> None:
            self.chunks: list[str] = []

        def execute(self, chunk: str, nret: int = 1) -> list[str]:
            self.chunks.append(chunk)
            return ['{"changed":false}']

    runtime = object.__new__(worker.HeadlessLuaRuntime)
    runtime._bridge = Bridge()
    runtime.read_stats(["CombinedDPS"], None)
    plain = runtime._bridge.chunks[-1]
    # #575: the flask-uptime derivation may READ configTab.input.<x>; the plain read never writes the config
    assert not re.search(r"configTab[\w.\[\]'\"]*\s*=(?!=)", plain) and "configTab:" not in plain
    assert "read_body" not in plain
    assert runtime.read_stats_uncapped(["CombinedDPS"], None) == {"changed": False}
    chunk = runtime._bridge.chunks[-1]
    # every removed input, the custom block list and the recalculation are undone after the read, even on an error
    assert "pcall(read_body)" in chunk
    assert chunk.index("base.input[name] = nil") < chunk.index("pcall(read_body)") < chunk.index("base.input[name] = value")
    assert chunk.index("pcall(read_body)") < chunk.index("base.customModsList = orig_mods")
    assert chunk.rstrip().endswith("""return '{"changed":true,"stats":' .. res .. '}'""")
    assert chunk.count("rebuild()") >= 3  # defined once, run after the removal and after the restore


# -- the numbers (pinned PoB runtime) ------------------------------------------------------------------

FIXTURE_FILES = {
    "z329_juggernaut_boneshatter": PROJECT_ROOT / "tests" / "fixtures" / "zizaran_329" / "early" / "juggernaut_boneshatter.pob.txt",
    "poison_spectral_throw": PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "poison_spectral_throw.pob.txt",
    "bleed_perforate": PROJECT_ROOT / "tests" / "fixtures" / "generated" / "bleed_perforate-s3.pob.txt",
    "ignite_penance_brand_forced_cap": PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "ignite_penance_brand.pob.txt",
}
# the lane write leaves no ignite cap on this build; one is written the way the lane write writes it
FORCED_CAPS = {"ignite_penance_brand_forced_cap": {"overrideIgniteStackPotential": 2}}


def _custom_titles(xml: str) -> list[str]:
    return re.findall(r'<CustomModifierBlock title="([^"]*)"', xml)


@pytest.mark.pob
@needs_pob
@pytest.mark.parametrize("name", sorted(FIXTURE_FILES))
def test_the_in_place_read_equals_the_reload_read_to_the_digit_and_leaves_the_session_as_it_was(name: str, tmp_path: Path) -> None:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.config_rules import derive_config
    from junkroan.optimizer.judging import write_lanes
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.ramp_inputs import apply_ailment_stack_caps
    from junkroan.pob.session import decode_import_code

    xml = decode_import_code(FIXTURE_FILES[name].read_text(encoding="utf-8").strip())
    skeleton = skeleton_from_xml(xml)
    with PobSession(run_id=f"test-508-{name}", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        pipe = BuildPipeline(pob, Rails.load())
        derived = derive_config(pob, prefer_rules=True)
        write_lanes(pob, skeleton, derived, log=pipe.log)  # puts D78's caps / poison block into Baseline when the build has stacks

        if name in FORCED_CAPS:
            apply_ailment_stack_caps(pob, FORCED_CAPS[name])
        snapshot = pob.export_xml()
        has_surfaces = uncapped_ailment_stack_xml(snapshot) != snapshot
        before_stats = pob.stats()
        before_calc = {lane: pob.calc(lane) for lane in ("baseline", "conditional")}
        before_inputs, before_titles = pob.config_inputs(), _custom_titles(snapshot)

        in_place = pob.stats_without_ailment_caps()
        after_stats = pob.stats()
        assert (in_place is not None) == has_surfaces
        assert after_stats == before_stats  # the session's stats after the read equal the ones before it
        assert {lane: pob.calc(lane) for lane in ("baseline", "conditional")} == before_calc
        assert pob.config_inputs() == before_inputs
        assert _custom_titles(pob.export_xml()) == before_titles

        by_reload = uncapped_ailment_stats_by_reload(pob, before_stats)
        if has_surfaces:
            assert in_place == by_reload  # every stat PoB gives, to the digit
            assert in_place != before_stats  # the check is not vacuous: the surfaces moved a number
        else:
            assert by_reload == before_stats
        print(f"{name}: surfaces={has_surfaces} inputs={sorted(k for k in before_inputs if k in AILMENT_STACK_INPUTS)} "
              f"titles={before_titles} CombinedDPS capped={before_stats.get('CombinedDPS')} uncapped={(in_place or before_stats).get('CombinedDPS')} "
              f"stats equal={in_place == by_reload if has_surfaces else True} n={len(before_stats)}")
