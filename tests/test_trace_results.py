"""#498: the trace counters and the delivered build's option classes reach the result rows (PoB-free)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
from junkroan.optimizer.trace import TRACE  # noqa: E402
from junkroan.optimizer.trace_output import trace_output_from_xml  # noqa: E402
from replay_bench import render_report, trace_table_lines  # noqa: E402

XML = """<PathOfBuilding>
<Tree activeSpec="1"><Spec nodes="100,200,300"/></Tree>
<Items activeItemSet="1">
<Item id="1">Rarity: RARE
Doom Coil
Coral Ring
</Item>
<Item id="2">Rarity: MAGIC
Quicksilver Flask of Adrenaline
</Item>
<Item id="3">Rarity: RARE
Gloom Eye
Cobalt Jewel
</Item>
<Item id="4">Rarity: RARE
Unused Thing
Coral Ring
</Item>
<ItemSet id="1">
<Slot name="Ring 1" itemId="1"/>
<Slot name="Flask 1" itemId="2"/>
<Slot name="Jewel 5" itemId="3"/>
<Slot name="Ring 2" itemId="0"/>
</ItemSet>
</Items>
</PathOfBuilding>"""


def test_output_from_xml_exact_counts() -> None:
    # classes registered at import (#438's `base-level:` from item_bases) depend on test order; not this test's subject
    counts = {k: v for k, v in trace_output_from_xml(XML).items() if not k.startswith(("base-level:", "unique-tier:", "res-line", "weapon-lines:", "rare-lines:", "loot-base-"))}
    assert counts == {
        "base:Cobalt Jewel": 1,
        "base:Coral Ring": 1,
        "base:Quicksilver Flask": 1,
        "flask": 1,
        "flask-active": 0,
        "flask-bare-base-output": 0,
        "flask-duplicate-base-output": 0,
        "flask-divine-life": 0,
        "flask-slot-empty": 4,
        "node-kind:unknown": 3,
        "node:100": 1,
        "node:200": 1,
        "node:300": 1,
        "rarity:magic": 1,
        "rarity:rare": 2,
        "utility-flask-craft": 0,
    }


def test_output_from_xml_never_raises() -> None:
    assert trace_output_from_xml("not xml") == {}
    assert trace_output_from_xml("") == {}


def test_benchmark_row_carries_considered_and_output(monkeypatch, tmp_path) -> None:
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
            with TRACE.move("tree"):
                TRACE.add_generated(["slot:Ring 1"], 3)
                TRACE.add_evaluated(["slot:Ring 1"], 2)
            return MagicMock(final_stats={}, xml=XML, moves=[], import_code="x")

    monkeypatch.setattr(pipeline_mod, "BuildPipeline", FakePipeline)
    monkeypatch.setattr(session_mod, "PobSession", FakePob)
    monkeypatch.setattr(objective_mod, "bossing_defence", lambda *_a: 0)
    prepared = MagicMock(stat="CombinedDPS", points=1, author_raw={"CombinedDPS": 10.0, "Life": 1, "TotalEHP": 1},
                         author_lane={"CombinedDPS": 10.0, "TotalEHP": 1}, author_ramp=None)
    monkeypatch.setattr(benchmark, "prepare_author", lambda *a, **k: prepared)
    TRACE.reset()
    TRACE.add_generated(["leftover"])  # a previous build in the same worker process
    row = benchmark.run_one("slug", log_path=str(tmp_path / "x.log"), seed=1, gear_mode="loot")
    assert row["ok"], row.get("error")
    assert row["considered"] == {"tree": {"slot:Ring 1": {"generated": 3, "evaluated": 2}}}
    assert row["output"]["flask"] == 1 and row["output"]["node:100"] == 1


CONSIDERED = {
    "gear": {"flask": {"generated": 4, "evaluated": 1}, "slot:Ring 1": {"generated": 7, "evaluated": 7}},
    "tree": {"node:100": {"generated": 2, "evaluated": 0}},
}


def test_trace_table_exact_text() -> None:
    assert trace_table_lines(CONSIDERED) == [
        "| move | flask | node:100 | slot:Ring 1 |",
        "|---|---:|---:|---:|",
        "| gear | 4/1 | - | 7/7 |",
        "| tree | - | 2/0 | - |",
    ]
    assert trace_table_lines({}) == ["(nothing counted)"]


def test_report_has_trace_section_only_with_trace() -> None:
    row = {"ok": True, "reference": "ref", "source": "a.pob.txt", "recorded_value": 1.0, "replayed_value": 1.0, "value_before": 1.0,
           "replayed_over_recorded": 1.0, "value_after": 2.0, "gain_percent": 1.0, "seconds": 5.0, "kept": 1, "judged_and_reverted": 0,
           "not_kept": 0, "violation_before": 0.0, "violation_after": 0.0, "start_infeasible": False, "audit_errors": 0,
           "considered": CONSIDERED, "output": {}}
    kw = dict(stamp="s", move="loop", passes=1, workers=1, seconds=5.0)
    plain = render_report([row], **kw)
    traced = render_report([row], trace=True, **kw)
    assert "Trace" not in plain
    assert traced.startswith(plain.rstrip("\n"))
    assert "| gear | 4/1 | - | 7/7 |" in traced
