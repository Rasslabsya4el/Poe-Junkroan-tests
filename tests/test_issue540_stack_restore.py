"""#540: `judge_stack_options` puts the build's config back in place (the worker's config checkpoint /
rollback) instead of `load_xml(snapshot)`, which was the one whole-build load every `read_lanes` paid.

A speed change that moves no number (D113): the PoB-free tests pin the call shape (0 `load_xml` on the
in-place path, the reload path under `JUNKROAN_STACK_RESTORE_BY_RELOAD=1` and for a stand-in without the
pair); the `pob` tests pin the numbers: on each build with a stack option, the session after the judgement
equals the session before it (every stat, every input, both lanes, the export) and the judged values equal
the reload path's.
"""

from __future__ import annotations

import json
import sys
from xml.etree import ElementTree
from pathlib import Path
from typing import Any

import pytest

from junkroan.optimizer import config_rules
from junkroan.pob import headless_runtime_worker as worker
from junkroan.pob.session import PobSession

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

PENDING = [{"var": "intensifyIntensity", "label": "# of Intensity"}]


class _Fake:
    """Enough of a session for `judge_stack_options`: the number rises with the option up to PoB's cap (4)."""

    def __init__(self, *, fail_at: int | None = None) -> None:
        self.value, self.calls, self.fail_at, self.writes = 0, [], fail_at, 0

    def export_xml(self) -> str:
        return "<PathOfBuilding>build</PathOfBuilding>"

    def read_state(self) -> dict:
        return {"config_state": {"bandit": "Alira", "pantheon_major": "None", "pantheon_minor": "None"}}

    def set_config(self, *, inputs=None, **_kw) -> None:
        self.writes += 1
        self.value = min(int(list((inputs or {}).values())[0]), 4) * 100

    def stats(self, keys):
        if self.fail_at is not None and self.writes >= self.fail_at:
            raise RuntimeError("PoB stopped answering")
        return {k: float(self.value) for k in keys}


class _InPlaceFake(_Fake):
    """What a PobSession offers: the checkpoint / rollback pair; a `load_xml` would be a regression."""

    def config_checkpoint(self) -> None:
        self.calls.append("config_checkpoint")

    def config_rollback(self) -> None:
        self.calls.append("config_rollback")

    def load_xml(self, xml: str) -> None:
        self.calls.append("load_xml")


class _ReloadFake(_Fake):
    """A stand-in with `load_xml` and without the pair: the reload path."""

    def load_xml(self, xml: str) -> None:
        self.calls.append("load_xml")


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JUNKROAN_STACK_RESTORE_BY_RELOAD", raising=False)
    config_rules._STACK_JUDGEMENTS.clear()
    yield
    config_rules._STACK_JUDGEMENTS.clear()


def test_a_session_restores_in_place_with_no_load_xml() -> None:
    pob = _InPlaceFake()
    out = config_rules.judge_stack_options(pob, PENDING, ceiling=50)
    assert out["intensifyIntensity"][0] == 50 and out["intensifyIntensity"][2] == 4
    assert pob.calls == ["config_checkpoint", "config_rollback"]  # 0 load_xml: the checkpoint first, the rollback last
    assert pob.writes == 9


def test_the_env_switch_keeps_the_reload_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUNKROAN_STACK_RESTORE_BY_RELOAD", "1")
    pob = _InPlaceFake()
    config_rules.judge_stack_options(pob, PENDING, ceiling=50)
    assert pob.calls == ["load_xml"]  # no checkpoint, no rollback


def test_a_stand_in_without_the_pair_keeps_the_reload_path() -> None:
    pob = _ReloadFake()
    config_rules.judge_stack_options(pob, PENDING, ceiling=50)
    assert pob.calls == ["load_xml"]


def test_the_rollback_runs_when_a_read_fails_and_a_cache_hit_touches_nothing() -> None:
    pob = _InPlaceFake(fail_at=3)
    with pytest.raises(RuntimeError):
        config_rules.judge_stack_options(pob, PENDING, ceiling=50)
    assert pob.calls == ["config_checkpoint", "config_rollback"]
    ok = _InPlaceFake()
    config_rules.judge_stack_options(ok, PENDING, ceiling=50)
    ok.calls.clear()
    config_rules.judge_stack_options(ok, PENDING, ceiling=50)
    assert ok.calls == []  # the cache answers; the build is not touched


def test_the_worker_lua_copies_every_config_set_and_puts_them_back() -> None:
    checkpoint, rollback = "\n".join(worker._CONFIG_CHECKPOINT_LUA), "\n".join(worker._CONFIG_ROLLBACK_LUA)
    for part in ("ct.configSets", "ct.configSetOrderList", "ct.activeConfigSetId", "build.bandit", "build.pantheonMajorGod", "build.pantheonMinorGod"):
        assert part in checkpoint or part.replace("ct.", "") in checkpoint
    assert "copy(ct.configSets)" in checkpoint  # a copy: the probes write into the live sets
    assert rollback.index("ct.configSets = snap.sets") < rollback.index("SetActiveConfigSet") < rollback.index("BuildModList") < rollback.index("OnFrame")


# -- the numbers (pinned PoB runtime) ------------------------------------------------------------------

FIXTURE_FILES = {
    "spark": PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "spark.pob.txt",
    "kinetic_fusillade": PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "kinetic_fusillade.pob.txt",
    "archmage_volatile_dead": PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "archmage_volatile_dead.pob.txt",  # three options, one PoB does not cap
}


def _config_of(xml: str) -> dict[str, Any]:
    """The export's whole config, order-free (PoB writes the <Input> rows in `pairs()` order, which moves
    with the table's history, not with its content): every set with its inputs, placeholders and custom
    blocks, the active set and the build-level bandit / pantheon."""

    root = ElementTree.fromstring(xml)
    config, build = root.find("Config"), root.find("Build")
    sets = {}
    for cs in config.findall("ConfigSet"):
        sets[cs.get("id")] = {
            "title": cs.get("title"),
            "inputs": sorted(tuple(sorted(n.attrib.items())) for n in cs.findall("Input")),
            "placeholders": sorted(tuple(sorted(n.attrib.items())) for n in cs.findall("Placeholder")),
            "blocks": [(b.get("title"), b.get("enabled"), b.text) for b in cs.findall("CustomModifierBlock")],
        }
    attrs = {k: build.get(k) for k in ("bandit", "pantheonMajorGod", "pantheonMinorGod")}
    return {"active": config.get("activeConfigSet"), "sets": sets, "build": attrs, "order": [cs.get("id") for cs in config.findall("ConfigSet")]}


def _state(pob: PobSession) -> dict[str, Any]:
    return {"stats": pob.stats(), "inputs": pob.config_inputs(), "baseline": pob.calc("baseline"), "conditional": pob.calc("conditional"), "config": _config_of(pob.export_xml())}


@pytest.mark.pob
@needs_pob
@pytest.mark.parametrize("name", sorted(FIXTURE_FILES))
def test_the_in_place_restore_equals_the_reload_restore_and_the_state_before(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.judging import write_lanes
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.ramp_inputs import apply_ailment_stack_caps, apply_custom_mods
    from junkroan.pob.session import decode_import_code

    if not FIXTURE_FILES[name].is_file():
        pytest.skip(f"{FIXTURE_FILES[name]} not present")
    xml = decode_import_code(FIXTURE_FILES[name].read_text(encoding="utf-8").strip())
    skeleton = skeleton_from_xml(xml)
    seen: list[tuple[list[dict[str, Any]], int, str]] = []
    real = config_rules.judge_stack_options

    def spy(pob: Any, pending: list[dict[str, Any]], *, ceiling: int, boss: str = "Pinnacle") -> Any:
        seen.append((list(pending), ceiling, boss))
        return real(pob, pending, ceiling=ceiling, boss=boss)

    with PobSession(run_id=f"test-540-{name}", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        pipe = BuildPipeline(pob, Rails.load())
        monkeypatch.setattr(config_rules, "judge_stack_options", spy)
        derived = config_rules.derive_config(pob, prefer_rules=True)
        monkeypatch.setattr(config_rules, "judge_stack_options", real)
        pending, ceiling, boss = seen[-1]
        assert pending, f"{name} has no stack option"
        write_lanes(pob, skeleton, derived, log=pipe.log)  # two lanes that differ, the poison block / caps where the build has stacks
        # what only the Baseline set holds and `set_config` (the judgement's probes) rewrites away: a custom block, a native cap
        apply_custom_mods(pob, [("10% increased Spell Damage", "junkroan: test block 540", "the probes drop it, the restore brings it back")])
        apply_ailment_stack_caps(pob, {"overrideIgniteStackPotential": 2})
        before = _state(pob)
        assert any(b[0] == "junkroan: test block 540" for b in before["config"]["sets"]["1"]["blocks"])

        config_rules._STACK_JUDGEMENTS.clear()
        loads = pob.pob_calls().get("load_xml", {}).get("count", 0)
        rollbacks = pob.pob_calls().get("config_rollback", {}).get("count", 0)
        in_place = config_rules.judge_stack_options(pob, pending, ceiling=ceiling, boss=boss)
        after_in_place = _state(pob)
        assert pob.pob_calls().get("config_rollback", {}).get("count", 0) == rollbacks + 1
        assert pob.pob_calls().get("load_xml", {}).get("count", 0) == loads  # no whole-build load

        monkeypatch.setenv("JUNKROAN_STACK_RESTORE_BY_RELOAD", "1")
        config_rules._STACK_JUDGEMENTS.clear()
        by_reload = config_rules.judge_stack_options(pob, pending, ceiling=ceiling, boss=boss)
        after_reload = _state(pob)

        assert in_place == by_reload  # the judged values, to the digit
        assert any(v[0] is not None for v in in_place.values())  # not vacuous: PoB capped one of them
        for key in ("stats", "inputs", "baseline", "conditional", "config"):
            assert after_in_place[key] == before[key], key  # the session after the judgement is the one before it
            assert after_in_place[key] == after_reload[key], key  # and the one the reload restore gives
        print(f"{name}: pending={[p['var'] for p in pending]} judged={ {k: v[:1] + v[2:3] for k, v in in_place.items()} } stats n={len(before['stats'])} "
              f"inputs={len(before['inputs'])} sets={len(before['config']['sets'])} blocks={[b[0][:30] for s in before['config']['sets'].values() for b in s['blocks']]}")
