"""#38: `benchmark.py --resume` continues a run that stopped mid-way, without a PoB runtime."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402


def _row(slug: str, seed: int = 1) -> dict:
    return {
        "ok": True,
        "commit": benchmark.code_commit(),  # what the real run_one stamps (#748)
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
        "loop_stop": "converged",
        "stages": [{"name": "final", "seconds": 1.0, "value": 1200.0, "violation": 0.0, "notes": ""}],
        "summary": f"summary for {slug}",
        "import_code": f"import {slug}",
        "xml": f"<PathOfBuilding>{slug}</PathOfBuilding>",
    }


def _patch_benchmark_main(monkeypatch, tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    stamp = "20260926-1200"
    run_stamp = f"{stamp}-durable"
    monkeypatch.setattr(benchmark, "ROOT", root)
    monkeypatch.setattr(benchmark, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(benchmark.time, "strftime", lambda _format: stamp)
    pob_dir = tmp_path / "pob" / "Junkroan" / "benchmark"
    pob_dir.parent.parent.mkdir(parents=True)
    monkeypatch.setattr(benchmark, "_pob_build_dir", lambda _stamp: pob_dir)
    return root / "artifacts" / "benchmark" / run_stamp, run_stamp


def _run_fresh(monkeypatch, tmp_path: Path, slugs: list[str]) -> Path:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_kwargs: _row(slug))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", *slugs, "--workers", "3", "--no-variants", "--gear", "loot", "--tag", "durable"])
    assert benchmark.main() == 0
    return out_dir


def test_resume_runs_only_the_builds_without_a_complete_row(tmp_path: Path, monkeypatch) -> None:
    slugs = ["alpha", "beta", "gamma", "delta"]
    out_dir = _run_fresh(monkeypatch, tmp_path, slugs)
    full_results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert {row["slug"] for row in full_results} == set(slugs)

    (out_dir / "rows" / "beta-s1.json").unlink()
    (out_dir / "rows" / "delta-s1.json").unlink()

    called: list[str] = []

    def fake_run_one(slug: str, **_kwargs) -> dict:
        called.append(slug)
        return _row(slug)

    monkeypatch.setattr(benchmark, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--resume", str(out_dir)])

    assert benchmark.main() == 0
    assert sorted(called) == ["beta", "delta"], "only the two builds without a row were rerun"

    resumed_results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    resumed_results.sort(key=lambda r: r["slug"])
    full_results.sort(key=lambda r: r["slug"])
    assert resumed_results == full_results, "the rebuilt results.json equals an uninterrupted run's, row by row"


def test_resume_prints_how_many_builds_were_already_done(tmp_path: Path, monkeypatch, capsys) -> None:
    slugs = ["alpha", "beta", "gamma", "delta"]
    out_dir = _run_fresh(monkeypatch, tmp_path, slugs)
    (out_dir / "rows" / "beta-s1.json").unlink()
    (out_dir / "rows" / "delta-s1.json").unlink()
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_kwargs: _row(slug))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--resume", str(out_dir)])

    benchmark.main()

    assert "resumed: 2 of 4 builds already done" in capsys.readouterr().out


def test_resume_refuses_a_mismatched_seeds(tmp_path: Path, monkeypatch) -> None:
    out_dir = _run_fresh(monkeypatch, tmp_path, ["alpha", "beta"])
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_kwargs: _row(slug))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--resume", str(out_dir), "--seeds", "2"])

    try:
        benchmark.main()
        raised = False
    except SystemExit:
        raised = True
    assert raised, "--resume with a --seeds that does not match the recorded run must be refused"


def test_resume_refuses_a_mismatched_loop_seconds(tmp_path: Path, monkeypatch) -> None:
    out_dir = _run_fresh(monkeypatch, tmp_path, ["alpha", "beta"])
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_kwargs: _row(slug))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--resume", str(out_dir), "--loop-seconds", "60"])

    try:
        benchmark.main()
        raised = False
    except SystemExit:
        raised = True
    assert raised, "--resume with a --loop-seconds that does not match the recorded run must be refused"


def test_resume_accepts_a_matching_seeds_argument(tmp_path: Path, monkeypatch) -> None:
    out_dir = _run_fresh(monkeypatch, tmp_path, ["alpha", "beta"])
    (out_dir / "rows" / "alpha-s1.json").unlink()
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_kwargs: _row(slug))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--resume", str(out_dir), "--seeds", "1"])

    assert benchmark.main() == 0  # matches the recorded run's own --seeds 1: not a mismatch


def test_a_run_without_args_json_needs_its_own_arguments_on_the_command_line(tmp_path: Path, monkeypatch) -> None:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    out_dir.mkdir(parents=True)
    (out_dir / "rows").mkdir()
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--resume", str(out_dir)])

    try:
        benchmark.main()
        raised = False
    except SystemExit:
        raised = True
    assert raised, "a folder with no args.json cannot tell --resume what to run without slugs on the command line"
