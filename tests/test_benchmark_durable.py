"""Incremental benchmark artifacts and queue archives without a PoB runtime."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
import run_queue  # noqa: E402


def _row(slug: str, seed: int = 1) -> dict:
    return {
        "ok": True,
        "slug": slug,
        "seed": seed,
        "gear_mode": "loot",
        "variant": "",
        "seconds": 1.0,
        "stat": "CombinedDPS",
        "author_raw": 1000.0,
        "author_lane": 1000.0,
        "author_ramp": None,
        "author_gem_levels": {"level": 18.0, "quality": 0.0},
        "author_gems_normalized": 0,
        "author_life": 100.0,
        "author_ehp": 100.0,
        "author_ehp_raw": 100.0,
        "author_maxhit": 100.0,
        "ours_maxhit": 100.0,
        "ours": 1200.0,
        "ours_optimistic": 1300.0,
        "ours_life": 100.0,
        "ours_ehp": 100.0,
        "ours_ramp": None,
        "ratio_lane": 1.2,
        "ratio_raw": 1.2,
        "keystones": [],
        "audit": [],
        "audit_errors": 0,
        "fixed_point_gain": 0.0,
        "fixed_point_note": "kept nothing",
        "stages": [{"name": "final", "seconds": 1.0, "value": 1200.0, "violation": 0.0, "notes": ""}],
        "summary": f"summary for {slug}",
        "import_code": f"import {slug}",
        "xml": f"<PathOfBuilding>{slug}</PathOfBuilding>",
    }


def _wait_for(path: Path, predicate, *, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if path.is_file() and predicate():
                return
        except PermissionError:  # Windows: the writer is replacing the file right now
            pass
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def _patch_benchmark_main(monkeypatch, tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    stamp = "20260919-1200"
    run_stamp = f"{stamp}-durable"
    monkeypatch.setattr(benchmark, "ROOT", root)
    monkeypatch.setattr(benchmark, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(benchmark.time, "strftime", lambda _format: stamp)
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: 100.0)
    pob_dir = tmp_path / "pob" / "Junkroan" / "benchmark"
    pob_dir.parent.parent.mkdir(parents=True)
    monkeypatch.setattr(benchmark, "_pob_build_dir", lambda _stamp: pob_dir)
    return root / "artifacts" / "benchmark" / run_stamp, run_stamp


def test_completed_rows_are_readable_before_the_benchmark_finishes(tmp_path: Path, monkeypatch) -> None:
    out_dir, stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    release_rest = threading.Event()
    errors: list[BaseException] = []

    def fake_run_one(slug: str, **_kwargs) -> dict:
        if slug != "alpha":
            assert release_rest.wait(120)
        return _row(slug)

    monkeypatch.setattr(benchmark, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "beta", "gamma", "--workers", "3", "--no-variants", "--gear", "loot", "--tag", "durable"])

    def run() -> None:
        try:
            benchmark.main()
        except BaseException as exc:  # the assertion below should make this list stay empty
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    results_path = out_dir / "results.json"
    # persist_completed_row writes results.json BEFORE the PoB xml and report.md, so wait for the last one
    pob_xml = tmp_path / "pob" / "Junkroan" / "benchmark" / "alpha s1.xml"
    _wait_for(results_path, lambda: len(json.loads(results_path.read_text(encoding="utf-8"))) == 1 and pob_xml.is_file() and (out_dir / "report.md").is_file())

    assert json.loads(results_path.read_text(encoding="utf-8"))[0]["slug"] == "alpha"
    assert (out_dir / "alpha-s1.pob.txt").read_text(encoding="utf-8") == "import alpha"
    assert json.loads((out_dir / "rows" / "alpha-s1.json").read_text(encoding="utf-8"))["slug"] == "alpha"
    assert (out_dir / "report.md").read_text(encoding="utf-8").startswith("partial: 1 of 3 builds\n")
    assert (tmp_path / "pob" / "Junkroan" / "benchmark" / "alpha s1.xml").is_file()

    release_rest.set()
    worker.join(120)
    assert not worker.is_alive() and not errors

    complete_rows = json.loads(results_path.read_text(encoding="utf-8"))
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    assert not report.startswith("partial:")
    assert report == benchmark.render_report(complete_rows, stamp=stamp, workers=3, seconds=0.0, gear_mode="loot")


def test_a_run_from_before_the_move_ledger_still_rereports_its_per_build_table() -> None:
    """The frozen campaigns (new18, core14, rules-smoke) were written before the ledger existed, so
    their rows carry no `moves` / `pob_calls` / `tree_churn`. Those three are report-only: their
    absence must cost the rereport nothing but the ledger's own sections."""

    rows = [_row("stormbrand"), _row("cold_dot")]
    assert not any(key in row for row in rows for key in ("moves", "pob_calls", "tree_churn"))

    report = benchmark.render_report(rows, stamp="20260101-0000", rereport=True)

    assert "rewritten median tables only" not in report
    assert "| stormbrand s1 |" in report and "| cold_dot s1 |" in report
    assert "## Loop Moves" not in report


def test_benchmark_report_uses_human_time_columns() -> None:
    row = _row("stormbrand")
    row["seconds"] = 2856.0

    report = benchmark.render_report([row], stamp="20260101-0000", workers=1, seconds=2856.0)

    assert "| build | author (own config)" in report and "| time |" in report
    assert "| stormbrand s1 |" in report and "48 min |" in report
    assert "| reference | seeds | median ours / author (our lane) | min | max | median time |" in report
    assert not re.search(r"\d{3,} ?s\b", report)
    assert "| seconds |" not in report


def test_completed_rows_survive_a_future_that_raises(tmp_path: Path, monkeypatch) -> None:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    raise_third = threading.Event()
    errors: list[BaseException] = []

    def fake_run_one(slug: str, **_kwargs) -> dict:
        if slug == "gamma":
            assert raise_third.wait(120)
            raise RuntimeError("killed during gamma")
        return _row(slug)

    monkeypatch.setattr(benchmark, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "beta", "gamma", "--workers", "3", "--no-variants", "--gear", "loot", "--tag", "durable"])

    def run() -> None:
        try:
            benchmark.main()
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    results_path = out_dir / "results.json"
    _wait_for(results_path, lambda: len(json.loads(results_path.read_text(encoding="utf-8"))) == 2)
    raise_third.set()
    worker.join(120)

    assert not worker.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
    assert {row["slug"] for row in json.loads(results_path.read_text(encoding="utf-8"))} == {"alpha", "beta"}
    assert (out_dir / "alpha-s1.pob.txt").is_file() and (out_dir / "beta-s1.pob.txt").is_file()
    assert (out_dir / "rows" / "alpha-s1.json").is_file() and (out_dir / "rows" / "beta-s1.json").is_file()


def test_queue_archives_benchmark_artifacts_without_mutating_the_source(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    run_dir = tmp_path / "benchmark" / "20260919-1200-durable"
    rows, logs = run_dir / "rows", run_dir / "logs"
    rows.mkdir(parents=True)
    logs.mkdir()
    sources = {
        run_dir / "results.json": "[]",
        run_dir / "report.md": "report",
        run_dir / "alpha-s1.pob.txt": "import",
        rows / "alpha-s1.json": "{\"slug\": \"alpha\"}",
        logs / "alpha-s1.log": "log",
    }
    for path, text in sources.items():
        path.write_text(text, encoding="utf-8")
    output = runs / "20260919-1200-durable.out"
    runs.mkdir()
    output.write_text("queue output", encoding="utf-8")
    source_before = {path: path.read_bytes() for path in sources} | {output: output.read_bytes()}
    archive = tmp_path / "archive"
    monkeypatch.setattr(run_queue, "RUNS", runs)
    monkeypatch.setenv("JUNKROAN_ARCHIVE", str(archive))

    assert run_queue.archive_benchmark_run(run_dir, output) == 6

    target = archive / "benchmark" / run_dir.name
    assert (target / "results.json").read_text(encoding="utf-8") == "[]"
    assert (target / "report.md").read_text(encoding="utf-8") == "report"
    assert (target / "alpha-s1.pob.txt").read_text(encoding="utf-8") == "import"
    assert (target / "rows" / "alpha-s1.json").is_file()
    assert (target / "logs" / "alpha-s1.log").is_file()
    assert (target / output.name).read_text(encoding="utf-8") == "queue output"
    assert {path: path.read_bytes() for path in sources} | {output: output.read_bytes()} == source_before


def test_queue_logs_a_missing_benchmark_directory_and_continues(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(run_queue, "RUNS", runs)

    assert run_queue.archive_benchmark_run(tmp_path / "missing", runs / "missing.out") == 0

    assert "archive benchmark: run directory missing" in (runs / "queue.log").read_text(encoding="utf-8")
