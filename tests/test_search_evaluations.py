"""The outer search's durable rows and full-rank recall experiment, without PoB."""

from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import search  # noqa: E402
from junkroan.search.evaluations import format_rho, parse_full_ranks, selected_screen_ranks, spearman  # noqa: E402
from junkroan.search.skeleton import Skeleton  # noqa: E402


def _skeletons(count: int) -> dict[str, dict[str, str]]:
    return {chr(ord("A") + index): {"class_name": "Witch", "ascendancy_id": chr(ord("A") + index)} for index in range(count)}


def _result(skeleton_json: str, *, screen: bool, seed: int = 1) -> dict:
    skeleton = Skeleton.from_json(skeleton_json)
    rank = ord(skeleton.ascendancy) - ord("A") + 1
    value = 6 - rank if screen else rank
    return {
        "ok": True,
        "skeleton": skeleton.to_json(),
        "screen": screen,
        "seed": seed,
        "value": float(value),
        "violation": 0.0,
        "feasible": True,
        "final": {"Life": 1000.0, "TotalEHP": 1000.0, "EffectiveMovementSpeedMod": 1.2},
        "optimistic": 0.0,
        "import_code": f"code-{skeleton.ascendancy}-{seed}",
        "xml": f"<xml>{skeleton.ascendancy}</xml>",
        "stages": ([{"name": "gear pass 2 (with tree)", "seconds": 1.0, "value": float(10 + rank), "violation": 0.0, "notes": ""},
                    {"name": "loop pass 1", "seconds": 2.0, "value": float(20 + rank), "violation": 0.0, "notes": ""}]
                   if not screen else []),
        "config_reasons": {},
        "uniques": [],
        "seconds": float(rank),
        "summary": "fake summary",
        "audit": [],
        "audit_errors": 0,
        "keystones": ["Fake Keystone"],
        "explanation": "",
        "picks": [],
    }


def _patch_search(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, count: int = 5, optimize=None) -> list[tuple[bool, str]]:
    calls: list[tuple[bool, str]] = []
    monkeypatch.setattr(search, "ROOT", tmp_path)
    monkeypatch.setattr(search, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(search.Rails, "load", lambda: SimpleNamespace(level=80, gear=SimpleNamespace(max_uniques=3)))
    monkeypatch.setattr(search, "ascendancies", lambda: _skeletons(count))
    monkeypatch.setattr(search, "rig_supports", lambda *_args, **_kwargs: [])

    def prepare(skeleton_json: str, **_kwargs) -> dict:
        skeleton = Skeleton.from_json(skeleton_json)
        return {"ok": True, "skeleton": skeleton.to_json(), "picks": [],
                "rig": {"value": 0.5, "violation": 0.0, "feasible": True}, "seconds": 0.25}

    def run(skeleton_json: str, *, screen: bool, seed: int = 1, **_kwargs) -> dict:
        skeleton = Skeleton.from_json(skeleton_json)
        calls.append((screen, skeleton.ascendancy))
        return _result(skeleton_json, screen=screen, seed=seed)

    monkeypatch.setattr(search, "prepare_candidate", prepare)
    monkeypatch.setattr(search, "optimize", optimize or run)
    return calls


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["search.py", *argv])
    return search.main()


def test_full_rank_helpers_deduplicate_drop_overflow_and_measure_inverse_order() -> None:
    assert parse_full_ranks("1,3,9,3") == [1, 3, 9]
    assert selected_screen_ranks([1, 3, 9, 3], 5) == [1, 3]
    assert spearman([5, 4, 3, 2, 1], [1, 2, 3, 4, 5]) == -1.0
    with pytest.raises(ValueError):
        parse_full_ranks("1,zero")


def test_spearman_needs_three_pairs_and_is_reported_to_two_decimals() -> None:
    assert spearman([2.0, 1.0], [1.0, 2.0]) is None  # n = 2 is +-1.0 whatever the two builds did
    assert spearman([1.0, 2.0, None], [3.0, 4.0, 5.0]) is None  # the unpaired third does not count
    assert spearman([3.0, 1.0, 2.0], [3.0, 1.0, 2.0]) == 1.0
    assert format_rho(None) == "n/a"
    assert format_rho(spearman([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 4.0, 3.0])) == "0.80"


def test_completed_infeasible_full_builds_rank_after_feasible_ones() -> None:
    feasible = {"feasible": True, "violation": 0.0, "value": 1.0}
    infeasible = {"feasible": False, "violation": 0.01, "value": 1_000_000.0}
    assert search._full_rank_key(feasible) < search._full_rank_key(infeasible)


def test_full_ranks_writes_all_rungs_and_reports_inverse_spearman(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_search(monkeypatch, tmp_path)

    assert _run(monkeypatch, ["Cold Snap", "--full-ranks", "1,2,3,4,5", "--seeds", "1", "--workers", "1"]) == 0

    assert [asc for screen, asc in calls if not screen] == ["A", "B", "C", "D", "E"]
    rows = [json.loads(line) for line in (tmp_path / "artifacts" / "search-cold_snap" / "evaluations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["rung"] for row in rows} == {"rig", "screen", "full"}
    assert {rung: sum(row["rung"] == rung for row in rows) for rung in ("rig", "screen", "full")} == {"rig": 5, "screen": 5, "full": 5}
    # scripts/search.py walks as_completed(), so the row order of one rung is not promised: pick the row by skeleton.
    fulls = [row for row in rows if row["rung"] == "full"]
    assert sorted(row["features"]["ascendancy"] for row in fulls) == ["A", "B", "C", "D", "E"]
    full = next(row for row in fulls if row["features"]["ascendancy"] == "A")
    assert set(full) == {"request", "skeleton", "rung", "seed", "value", "violation", "feasible", "seconds", "commit", "features"}
    assert full["features"] == {"class": "Witch", "ascendancy": "A", "mode": "", "main_skill": "Cold Snap", "keystones": ["Fake Keystone"], "uniques": {}, "variant": ""}
    report = (tmp_path / "artifacts" / "search-cold_snap" / "report.md").read_text(encoding="utf-8")
    assert "| screen rank | skeleton | screen value | full value | full rank | time |" in report
    assert "Spearman rho (screen value, full value) = -1.00 (n = 5)" in report
    assert "the full-depth winner sits at screen rank 5: inside top 2: no, top 3: no, top 5: yes" in report
    assert "construction / loop pass 1 by screen rank:" in report


def test_full_ranks_optimizes_only_existing_requested_screen_ranks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_search(monkeypatch, tmp_path)

    assert _run(monkeypatch, ["Cold Snap", "--full-ranks", "1,3,9", "--seeds", "1", "--workers", "1"]) == 0

    assert [asc for screen, asc in calls if not screen] == ["A", "C"]


def test_without_full_ranks_keeps_the_existing_top_promotion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_search(monkeypatch, tmp_path)

    assert _run(monkeypatch, ["Cold Snap", "--top", "2", "--seeds", "1", "--workers", "1", "--no-unique-variants", "--no-mutation"]) == 0

    assert [asc for screen, asc in calls if not screen] == ["A", "B"]


def test_the_mutation_rounds_variant_screens_are_recorded_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from junkroan.optimizer.tree_graph import TreeGraph

    calls = _patch_search(monkeypatch, tmp_path, count=3)
    monkeypatch.setattr(TreeGraph, "load", lambda: SimpleNamespace(nodes={}))  # no keystone is the request's own

    assert _run(monkeypatch, ["Cold Snap", "--top", "2", "--seeds", "1", "--workers", "1", "--no-unique-variants"]) == 0

    rows = [json.loads(line) for line in (tmp_path / "artifacts" / "search-cold_snap" / "evaluations.jsonl").read_text(encoding="utf-8").splitlines()]
    screens = [row for row in rows if row["rung"] == "screen"]
    variants = [(screen, asc) for screen, asc in calls if screen][3:]  # the first three are the candidates' own screens
    assert len(variants) == 2  # one "without Fake Keystone" variant per promoted finalist
    assert [row["features"]["variant"] for row in screens] == ["", "", "", "without Fake Keystone", "without Fake Keystone"]
    assert len(screens) == 3 + len(variants)
    assert all(row["seed"] == 1 for row in screens[3:])  # a variant screens on the seed its parent won with
    assert all(set(row) == {"request", "skeleton", "rung", "seed", "value", "violation", "feasible", "seconds", "commit", "features"} for row in screens)


def test_completed_rows_survive_a_later_evaluation_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release_failure = threading.Event()

    def fails_later(skeleton_json: str, *, screen: bool, seed: int = 1, **_kwargs) -> dict:
        skeleton = Skeleton.from_json(skeleton_json)
        if screen and skeleton.ascendancy == "B":
            assert release_failure.wait(5)
            raise RuntimeError("killed during screen B")
        return _result(skeleton_json, screen=screen, seed=seed)

    _patch_search(monkeypatch, tmp_path, count=2, optimize=fails_later)
    monkeypatch.setattr(sys, "argv", ["search.py", "Cold Snap", "--top", "1", "--seeds", "1", "--workers", "2", "--no-unique-variants", "--no-mutation"])
    errors: list[BaseException] = []

    def run() -> None:
        try:
            search.main()
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    path = tmp_path / "artifacts" / "search-cold_snap" / "evaluations.jsonl"
    deadline = time.monotonic() + 5
    rows: list[dict] = []
    while time.monotonic() < deadline:
        if path.is_file():
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            if any(row["rung"] == "screen" and row["features"]["ascendancy"] == "A" for row in rows):
                break
        time.sleep(0.01)
    assert any(row["rung"] == "screen" and row["features"]["ascendancy"] == "A" for row in rows)
    release_failure.set()
    worker.join(5)
    assert not worker.is_alive()
    assert errors and isinstance(errors[0], RuntimeError)
