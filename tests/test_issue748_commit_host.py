"""#748 unit 1: every row and a fresh run's args.json carry `commit` and `host`; `--resume` refuses other commits. No PoB."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import benchmark  # noqa: E402
from test_benchmark_resume import _patch_benchmark_main, _row  # noqa: E402

A = "a" * 40
B = "b" * 40


def _stamped(slug: str, commit: str | None, seed: int = 1) -> dict:
    return {**_row(slug, seed), "commit": commit, "host": "pc"}


def _fresh(monkeypatch, tmp_path: Path, slugs: list[str], commit: str = A) -> Path:
    out_dir, _ = _patch_benchmark_main(monkeypatch, tmp_path)
    monkeypatch.setattr(benchmark, "code_commit", lambda root=None: commit)
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_k: _stamped(slug, commit))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", *slugs, "--workers", "3", "--no-variants", "--gear", "loot", "--tag", "durable"])
    assert benchmark.main() == 0
    return out_dir


def _resume(monkeypatch, out_dir: Path, commit: str | None) -> list[str]:
    called: list[str] = []
    monkeypatch.setattr(benchmark, "code_commit", lambda root=None: commit)
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_k: called.append(slug) or _stamped(slug, commit))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--resume", str(out_dir)])
    return called


def test_row1_fresh_run_args_json_has_commit_and_host_rows_too(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path, ["alpha"])
    assert json.loads((out_dir / "args.json").read_text(encoding="utf-8"))["commit"] == A
    # run_one itself stamps both a success and a failure row
    monkeypatch.undo()
    monkeypatch.setattr(benchmark, "code_commit", lambda root=None: A)
    monkeypatch.setattr(benchmark.slot_budget, "current_host", lambda root=None: "pc")
    for fake in ({"ok": True, "slug": "x", "seed": 1}, {"ok": False, "slug": "x", "seed": 1, "error": "boom"}):
        monkeypatch.setattr(benchmark, "armed_build", lambda *a, _f=fake, **k: dict(_f))
        row = benchmark.run_one("x", log_path=str(tmp_path / "o" / "logs" / "x.log"), seed=1, gear_mode="loot")
        assert row["commit"] == A and len(row["commit"]) == 40 and row["host"] == "pc"
    monkeypatch.setattr(benchmark, "armed_build", lambda *a, **k: {"deferred": True})
    assert "commit" not in benchmark.run_one("x", log_path=str(tmp_path / "o" / "logs" / "x.log"), seed=1, gear_mode="loot")


def test_code_commit_is_40_hex_clean_and_null_when_tracked_file_changed(tmp_path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    (repo / "f.txt").write_text("1")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    (repo / "untracked.txt").write_text("u")
    (repo / "var").mkdir()
    (repo / "var" / "z").write_text("z")
    assert len(benchmark.code_commit(repo) or "") == 40
    (repo / "f.txt").write_text("2")
    assert benchmark.code_commit(repo) is None


def test_row2_resume_at_a_with_one_row_of_b_raises_naming_it_and_starts_nothing(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path, ["alpha", "beta", "gamma", "delta"])
    (out_dir / "rows" / "delta-s1.json").write_text(json.dumps(_stamped("delta", B)), encoding="utf-8")
    called = _resume(monkeypatch, out_dir, A)
    with pytest.raises(SystemExit) as exc:
        benchmark.main()
    msg = str(exc.value)
    assert "delta-s1" in msg and "alpha-s1" not in msg and "beta-s1" not in msg and "gamma-s1" not in msg
    assert called == []


def test_row2_resume_at_another_commit_than_args_json_raises(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path, ["alpha", "beta"])
    called = _resume(monkeypatch, out_dir, B)
    with pytest.raises(SystemExit):
        benchmark.main()
    assert called == []


def test_row2_a_row_with_no_commit_raises(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path, ["alpha", "beta"])
    row = {k: v for k, v in _row("beta").items() if k != "commit"}  # no commit key at all
    (out_dir / "rows" / "beta-s1.json").write_text(json.dumps(row), encoding="utf-8")
    called = _resume(monkeypatch, out_dir, A)
    with pytest.raises(SystemExit) as exc:
        benchmark.main()
    assert "beta-s1" in str(exc.value)
    assert called == []


def test_row3_folder_without_any_commit_resumes_as_today(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path, ["alpha", "beta"])
    args = json.loads((out_dir / "args.json").read_text(encoding="utf-8"))
    del args["commit"]
    (out_dir / "args.json").write_text(json.dumps(args), encoding="utf-8")
    for path in (out_dir / "rows").glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        row.pop("commit")
        row.pop("host")
        path.write_text(json.dumps(row), encoding="utf-8")
    called = _resume(monkeypatch, out_dir, B)
    assert benchmark.main() == 0
    assert called == []
