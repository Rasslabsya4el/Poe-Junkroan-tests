"""#580: `benchmark.py` writes `<run dir>/variants.json` (the planned D40 keystone variant rows), PoB-free."""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
from test_benchmark_resume import _patch_benchmark_main, _row  # noqa: E402


def _patch_variant_discovery(monkeypatch, tmp_path: Path) -> None:
    import build_from_skeleton
    from junkroan.optimizer.tree_graph import TreeGraph
    from junkroan.pob import session

    fixture = tmp_path / "fixture.txt"
    fixture.write_text("code", encoding="utf-8")
    monkeypatch.setattr(benchmark, "fixture_path", lambda _slug: fixture)
    monkeypatch.setattr(TreeGraph, "load", classmethod(lambda cls, *a, **k: SimpleNamespace(nodes={})))
    monkeypatch.setattr(session, "decode_import_code", lambda _code: "<xml/>")
    monkeypatch.setattr(build_from_skeleton, "skeleton_from_xml", lambda _xml: SimpleNamespace(keystones=[]))


def test_variants_file_is_written_before_the_first_variant(monkeypatch, tmp_path: Path) -> None:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    _patch_variant_discovery(monkeypatch, tmp_path)
    seen: list[dict] = []

    def fake_run_one(slug, **kwargs):
        row = _row(slug)
        forbid = kwargs.get("forbid_keystones")
        if forbid:
            plan_path = out_dir / "variants.json"
            assert plan_path.exists()
            seen.append(json.loads(plan_path.read_text(encoding="utf-8")))
            row["variant"] = f"no {forbid[0]}"
            row["keystones"] = []
        else:
            row["keystones"] = ["Imbalanced Guard"]
        return row

    monkeypatch.setattr(benchmark, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "beta", "--workers", "2", "--gear", "loot", "--tag", "durable"])
    assert benchmark.main() == 0

    plan = json.loads((out_dir / "variants.json").read_text(encoding="utf-8"))
    assert seen, "no variant run_one was called"
    assert plan["base_rows"] == 2
    assert plan["base_done"] == 2
    assert len(plan["planned"]) == 2
    assert plan["written"]
    for entry in plan["planned"]:
        assert entry["variant"] == "no Imbalanced Guard"
        assert entry["stem"] == f"{entry['slug']}-s1-no-imbalanced_guard"
        assert entry["after"] == f"{entry['slug']}-s1"
        assert (out_dir / "rows" / f"{entry['stem']}.json").exists()


def test_no_variants_writes_an_empty_plan(monkeypatch, tmp_path: Path) -> None:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_kw: _row(slug))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "beta", "--workers", "2", "--no-variants", "--gear", "loot", "--tag", "durable"])
    assert benchmark.main() == 0
    plan = json.loads((out_dir / "variants.json").read_text(encoding="utf-8"))
    assert plan["planned"] == []
    assert plan["base_rows"] == 2
    assert plan["base_done"] == 2


def _plan_after_each_base_row(monkeypatch, out_dir: Path) -> list[tuple[str, dict]]:
    """Spy: variants.json as it stands right after each persisted row."""

    snaps: list[tuple[str, dict]] = []
    real = benchmark.persist_completed_row

    def spy(out, **kwargs):
        real(out, **kwargs)
        plan_path = out_dir / "variants.json"
        snaps.append((benchmark.result_stem(kwargs["row"]), json.loads(plan_path.read_text(encoding="utf-8"))))

    monkeypatch.setattr(benchmark, "persist_completed_row", spy)
    return snaps


def test_plan_grows_with_each_base_row_and_a_variant_starts_at_once(monkeypatch, tmp_path: Path) -> None:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    _patch_variant_discovery(monkeypatch, tmp_path)
    snaps = _plan_after_each_base_row(monkeypatch, out_dir)
    events: list[str] = []
    a_variant_submitted = threading.Event()

    class RecordingPool(ThreadPoolExecutor):
        def submit(self, fn, *args, **kwargs):
            if kwargs.get("forbid_keystones"):
                events.append(f"submit {args[0]} variant")
                a_variant_submitted.set()
            return super().submit(fn, *args, **kwargs)

    def fake_run_one(slug, **kwargs):
        row = _row(slug)
        if kwargs.get("forbid_keystones"):
            row["variant"] = f"no {kwargs['forbid_keystones'][0]}"
            row["keystones"] = []
            return row
        if slug == "beta":  # B's base row ends only after A's variant was submitted
            assert a_variant_submitted.wait(10), "A's variant was not submitted before B's base row ended"
            events.append("end beta base")
        row["keystones"] = ["Imbalanced Guard"] if slug == "alpha" else []
        return row

    monkeypatch.setattr(benchmark, "ProcessPoolExecutor", RecordingPool)
    monkeypatch.setattr(benchmark, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "beta", "--workers", "3", "--gear", "loot", "--tag", "durable"])
    assert benchmark.main() == 0

    assert events == ["submit alpha variant", "end beta base"]
    by_stem = dict(snaps)
    after_a = by_stem["alpha-s1"]
    assert after_a["base_done"] == 1 and [e["stem"] for e in after_a["planned"]] == ["alpha-s1-no-imbalanced_guard"]
    assert after_a["planned"][0]["after"] == "alpha-s1"
    after_b = by_stem["beta-s1"]
    assert after_b["base_done"] == 2 and len(after_b["planned"]) == 1
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert [(r["slug"], r["variant"]) for r in results] == [("alpha", ""), ("alpha", "no Imbalanced Guard"), ("beta", "")]


def test_no_variants_base_done_moves_with_each_row(monkeypatch, tmp_path: Path) -> None:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    snaps = _plan_after_each_base_row(monkeypatch, out_dir)
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_kw: _row(slug))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "beta", "--workers", "1", "--no-variants", "--gear", "loot", "--tag", "durable"])
    assert benchmark.main() == 0
    assert [plan["base_done"] for _stem, plan in snaps] == [1, 2]
    assert all(plan["planned"] == [] for _stem, plan in snaps)
