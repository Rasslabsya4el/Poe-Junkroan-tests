"""#575: the author's saved flasks' flags are derived from PoB's own uptime calc (never forced), and the run says so."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
from test_benchmark_durable import _row  # noqa: E402
from test_trace_results import XML  # noqa: E402

NO_FLASKS = '<PathOfBuilding><Items><ItemSet id="1"><Slot name="Ring 1" itemId="1"/><Slot name="Flask 1" itemId="0"/></ItemSet></Items></PathOfBuilding>'


def test_memo_key_names_the_regime(tmp_path) -> None:
    key = benchmark.author_memo_path(str(tmp_path), "slug", None)
    assert key.name == "slug-flasks-uptime-100.json"
    assert key.name != "slug.json"  # the pre-regime memo name is never read
    assert benchmark.author_memo_path(str(tmp_path), "slug", "FullDPS", cap_ailment_stacks=False).name == "slug-FullDPS-no-ailment-stack-caps-flasks-uptime-100.json"
    (tmp_path / "slug.json").write_text(json.dumps({"state_xml": "old"}), encoding="utf-8")
    assert benchmark.read_author_memo(key) is None


def test_flask_count_reads_saved_slots() -> None:
    assert benchmark.author_flask_count(XML) == 1
    assert benchmark.author_flask_count(NO_FLASKS) == 0


def _row_for(monkeypatch, tmp_path, note: str) -> dict:
    import junkroan.optimizer.objective as objective_mod
    import junkroan.optimizer.pipeline as pipeline_mod
    import junkroan.pob.session as session_mod

    class FakePob:
        def __init__(self, **_kw) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a) -> None:
            return None

    class FakePipeline:
        def __init__(self, *_a, **_kw) -> None:
            pass

        def run(self, *_a, **_kw):
            return MagicMock(final_stats={}, xml=XML, moves=[], import_code="x")

    monkeypatch.setattr(pipeline_mod, "BuildPipeline", FakePipeline)
    monkeypatch.setattr(session_mod, "PobSession", FakePob)
    monkeypatch.setattr(objective_mod, "bossing_defence", lambda *_a: 0)
    prepared = MagicMock(stat="CombinedDPS", points=1, author_raw={"CombinedDPS": 10.0, "Life": 1, "TotalEHP": 1},
                         author_lane={"CombinedDPS": 10.0, "TotalEHP": 1}, author_ramp=None, author_note=note)
    monkeypatch.setattr(benchmark, "prepare_author", lambda *a, **k: prepared)
    return benchmark.run_one("slug", log_path=str(tmp_path / "x.log"), seed=1, gear_mode="loot")


def test_run_one_row_carries_regime_and_note(monkeypatch, tmp_path) -> None:
    row = _row_for(monkeypatch, tmp_path, "author: no flasks")
    assert row["ok"], row.get("error")
    assert row["author_regime"] == "flasks-uptime-100"
    assert row["author_note"] == "author: no flasks"


def test_results_json_names_the_regime(tmp_path) -> None:
    row = {**_row("alpha"), "author_regime": "flasks-uptime-100", "author_note": ""}
    benchmark.persist_completed_row(tmp_path, stamp="20261003-000000", results=[row], row=row, total_builds=1, workers=1, seconds=1.0, gear_mode="loot")
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved[0]["author_regime"] == "flasks-uptime-100"
    old = {k: v for k, v in _row("beta").items()}  # a pre-regime row keeps its numbers, gains no field
    assert "author_regime" not in benchmark.persisted_row(old)


def test_no_flasks_note_in_the_report() -> None:
    row = {**_row("alpha"), "author_regime": "flasks-uptime-100", "author_note": "author: no flasks"}
    assert "alpha s1 (author: no flasks)" in benchmark.render_report([row], stamp="20261003-000000")
    row["author_note"] = ""
    assert "author: no flasks" not in benchmark.render_report([row], stamp="20261003-000000")


def test_no_forced_flask_activation_remains() -> None:
    assert "set_flasks_active(" not in (ROOT / "scripts" / "benchmark.py").read_text(encoding="utf-8")


@pytest.mark.pob
def test_stormbrand_author_full_dps_under_pob_uptime() -> None:
    """Row 5 of #575: the author's saved flasks are no longer forced active. Read as saved (the author's own config,
    the flags derived: all five False) FullDPS is 1,797,356 (1,806,874 forced); through the benchmark's own author
    path (gem normalisation, buff gems off, main group flagged) it is 1,721,800 (1,730,917 forced, before #575)."""
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="flask-uptime-stormbrand") as pob:
        pob.load_xml(decode_import_code(benchmark.fixture_path("stormbrand").read_text(encoding="utf-8").strip()))
        raw = pob.stats(["FullDPS"])["FullDPS"]
        flags = pob.flasks_active()
        prepared = benchmark.prepare_author(pob, "stormbrand", stat_override="FullDPS", log=lambda _m: None)
    full = prepared.author_raw["FullDPS"]
    print(f"stormbrand author FullDPS as saved {raw:,.0f}, benchmark path {full:,.0f}")
    assert not any(flags.values())
    assert round(raw) == 1_797_356
    assert round(full) == 1_721_800
