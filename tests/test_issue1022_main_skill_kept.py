"""#1022: a rewrite of the skill groups keeps the main active skill the build held, by identity (the granted effect's
name among the skills of the Main group's first gem), never by position 1. Row 1 on PoB: the saved Spark s4 build (its
gem is Vaal Spark, its main skill Spark, position 2) through the replay's `_pipeline_state`; row 2: builds whose main
skill is not a Vaal twin keep their number; the unit tests run without PoB."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob import headless_runtime_worker as worker  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402

BENCH = ROOT / "artifacts" / "benchmark" / "20261013-0101-P2-core-3"
RUNTIME = ROOT / "var" / "cache" / "pob"


def test_set_skills_asks_the_worker_to_keep_the_main_active_skill() -> None:
    captured: dict = {}
    pob = PobSession.__new__(PobSession)
    pob._fulldps_last_ratio = None
    pob._handle = object()
    pob._adapter = SimpleNamespace(apply_skill_state=lambda _handle, payload: captured.update(payload=payload))
    pob.set_skills(main_link=["Vaal Spark", "Added Lightning Damage"])

    payload = captured["payload"]
    assert payload["keep_main_active_skill"] is True
    assert payload["skill_sets"][0]["socket_groups"][0]["main_active_skill_index"] == 1  # the worker moves it, the payload is the default


def test_the_apply_lua_restores_the_held_skill_by_name() -> None:
    lines = "\n".join(worker._APPLY_SKILLS_LUA)
    assert "p.keep_main_active_skill" in lines
    assert "e.grantedEffect.name == kept_main" in lines and "e.srcInstance == first" in lines
    # captured before the old skill sets are dropped, restored after the recalculation
    assert lines.index("kept_main = ") < lines.index("st.skillSets = {}") < lines.index("if kept_main then")


def _run(name: str) -> dict:
    import replay_bench as rb

    path = BENCH / f"{name}.pob.txt"
    info = rb.source_info(path)
    logs: list[str] = []
    with PobSession(run_id="test-1022") as pob:
        prepared = rb._prepared_author(pob, info["slug"], info["stat"], logs.append)
        pob.load_import_code(path.read_text(encoding="utf-8").strip())
        before = pob.stats(("CombinedDPS", "FullDPS"))
        rb._pipeline_state(pob, prepared, gear_mode=info["gear_mode"], log=logs.append)
        after = pob.stats(("CombinedDPS", "FullDPS"))
        from junkroan.optimizer.vaal_delivery import _main_names

        return {"before": before, "after": after, "main": _main_names(pob)[0]}


@pytest.mark.pob
@pytest.mark.skipif(not (BENCH / "spark-s4.pob.txt").is_file() or not RUNTIME.is_dir(), reason="saved build or pinned PoB runtime not present")
def test_row1_the_saved_spark_s4_build_keeps_spark_as_its_main_skill_after_the_replay_pipeline_state() -> None:
    got = _run("spark-s4")

    assert got["main"] == "Spark"  # was Vaal Spark
    assert got["before"]["CombinedDPS"] == pytest.approx(1_053_483, rel=1e-3)
    assert got["after"]["CombinedDPS"] == pytest.approx(1_053_483, rel=1e-3)  # was 147,190.5


@pytest.mark.pob
@pytest.mark.skipif(not (BENCH / "poison_spectral_throw-s4.pob.txt").is_file() or not RUNTIME.is_dir(), reason="saved build or pinned PoB runtime not present")
@pytest.mark.parametrize("name, main, combined", [("poison_spectral_throw-s4", "Spectral Throw", 63_531.47), ("smite-s4", "Smite", 322_844.69)])
def test_row2_a_build_whose_main_skill_is_not_a_vaal_twin_reads_the_same_number(name: str, main: str, combined: float) -> None:
    got = _run(name)  # the same two numbers on the base commit

    assert got["main"] == main
    assert got["after"]["CombinedDPS"] == pytest.approx(combined, rel=1e-4)
    assert got["after"]["CombinedDPS"] == pytest.approx(got["before"]["CombinedDPS"], rel=1e-4)


def test_the_worker_normalizer_carries_the_flag_and_refuses_a_non_boolean() -> None:
    runtime = object.__new__(worker.HeadlessLuaRuntime)
    base = {
        "active_skill_set_id": "skills.main",
        "main_socket_group_id": "skills.main.socket_group.1",
        "skill_sets": [{"skill_set_id": "skills.main", "socket_groups": [{"gems": [{"gem_name": "Spark"}]}]}],
    }

    assert runtime._normalize_skill_payload(base).get("keep_main_active_skill") is None
    assert runtime._normalize_skill_payload({**base, "keep_main_active_skill": True})["keep_main_active_skill"] is True
    with pytest.raises(worker.WorkerContractError):
        runtime._normalize_skill_payload({**base, "keep_main_active_skill": "yes"})
