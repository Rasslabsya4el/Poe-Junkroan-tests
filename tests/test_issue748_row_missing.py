"""#748 unit 2: `--resume <folder> --row <stem>` makes one row alone; `--missing` lists what can start now. No PoB."""

from __future__ import annotations

import hashlib
import json
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
SLUGS = ["alpha", "beta", "gamma"]


def _stamped(slug: str, seed: int = 1, variant: str = "") -> dict:
    return {**_row(slug, seed), "variant": variant, "commit": A, "host": "pc"}


def _fresh(monkeypatch, tmp_path: Path) -> Path:
    """A folder of 6 base rows (3 slugs x 2 seeds), run with variants off."""
    out_dir, _ = _patch_benchmark_main(monkeypatch, tmp_path)
    monkeypatch.setattr(benchmark, "code_commit", lambda root=None: A)
    monkeypatch.setattr(benchmark.slot_budget, "current_host", lambda root=None: "pc")
    monkeypatch.setattr(benchmark, "run_one", lambda slug, seed=1, **_k: _stamped(slug, seed))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", *SLUGS, "--seeds", "2", "--workers", "2", "--no-variants", "--gear", "loot", "--tag", "durable"])
    assert benchmark.main() == 0
    return out_dir


def _keep_rows(out_dir: Path, keep: set[str]) -> None:
    for path in (out_dir / "rows").glob("*.json"):
        if path.stem not in keep:
            path.unlink()


def _call(monkeypatch, out_dir: Path, *extra: str) -> list[tuple[str, tuple]]:
    called: list[tuple[str, tuple]] = []

    def fake(slug, seed=1, forbid_keystones=None, **_k):
        called.append((slug, tuple(forbid_keystones or ())))
        variant = f"no {', '.join(forbid_keystones)}" if forbid_keystones else ""
        return _stamped(slug, seed, variant)

    monkeypatch.setattr(benchmark, "run_one", fake)
    monkeypatch.setattr(benchmark, "_variant_keystones", lambda row: list(row.get("keystones") or []))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--resume", str(out_dir), *extra])
    return called


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_row4_row_makes_one_new_row_file_and_leaves_results_and_report_alone(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path)
    _keep_rows(out_dir, {"alpha-s1", "beta-s1"})
    before_files = {p.name for p in (out_dir / "rows").glob("*.json")}
    results_before, report_before = _digest(out_dir / "results.json"), _digest(out_dir / "report.md")
    mtime = (out_dir / "results.json").stat().st_mtime_ns
    called = _call(monkeypatch, out_dir, "--row", "gamma-s2")
    assert benchmark.main() == 0
    assert called == [("gamma", ())]
    assert {p.name for p in (out_dir / "rows").glob("*.json")} - before_files == {"gamma-s2.json"}
    assert _digest(out_dir / "results.json") == results_before and _digest(out_dir / "report.md") == report_before
    assert (out_dir / "results.json").stat().st_mtime_ns == mtime  # not even rewritten
    assert json.loads((out_dir / "rows" / "gamma-s2.json").read_text(encoding="utf-8"))["commit"] == A


def test_row4_a_stem_already_in_the_folder_exits_0_with_no_build(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path)
    called = _call(monkeypatch, out_dir, "--row", "alpha-s1")
    assert benchmark.main() == 0
    assert called == []


def test_row4_variant_stem_whose_base_row_is_missing_raises(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path)
    _keep_rows(out_dir, {"beta-s1"})
    called = _call(monkeypatch, out_dir, "--row", "alpha-s1-no-mind_over_matter")
    with pytest.raises(SystemExit):
        benchmark.main()
    assert called == []


def test_row4_unknown_stem_raises(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path)
    _keep_rows(out_dir, {"alpha-s1"})
    called = _call(monkeypatch, out_dir, "--row", "nonsense-s1")
    with pytest.raises(SystemExit):
        benchmark.main()
    assert called == []


def test_row4_variant_row_is_made_when_its_base_row_is_there(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path)
    base = json.loads((out_dir / "rows" / "alpha-s1.json").read_text(encoding="utf-8"))
    base["keystones"] = ["Mind over Matter", "Iron Reflexes"]
    (out_dir / "rows" / "alpha-s1.json").write_text(json.dumps(base), encoding="utf-8")
    args = json.loads((out_dir / "args.json").read_text(encoding="utf-8"))
    args["no_variants"] = False
    (out_dir / "args.json").write_text(json.dumps(args), encoding="utf-8")
    called = _call(monkeypatch, out_dir, "--row", "alpha-s1-no-mind_over_matter")
    assert benchmark.main() == 0
    assert called == [("alpha", ("Mind over Matter",))]
    assert (out_dir / "rows" / "alpha-s1-no-mind_over_matter.json").is_file()


def test_row5_missing_prints_every_missing_base_row_and_variants_of_done_bases(tmp_path, monkeypatch, capsys) -> None:
    out_dir = _fresh(monkeypatch, tmp_path)
    # a folder of 3 base rows (3 slugs, seed 1): one done with 2 known variants, two missing
    args = json.loads((out_dir / "args.json").read_text(encoding="utf-8"))
    args.update(seeds=1, no_variants=False)
    (out_dir / "args.json").write_text(json.dumps(args), encoding="utf-8")
    _keep_rows(out_dir, {"alpha-s1"})
    base = json.loads((out_dir / "rows" / "alpha-s1.json").read_text(encoding="utf-8"))
    base["keystones"] = ["Mind over Matter", "Iron Reflexes"]
    (out_dir / "rows" / "alpha-s1.json").write_text(json.dumps(base), encoding="utf-8")
    called = _call(monkeypatch, out_dir, "--missing")
    capsys.readouterr()
    assert benchmark.main() == 0
    out = capsys.readouterr().out
    assert out.split() == ["beta-s1", "gamma-s1", "alpha-s1-no-mind_over_matter", "alpha-s1-no-iron_reflexes"]
    assert len(out.strip().splitlines()) == 4
    assert called == []


def test_item6_plain_resume_still_writes_results_and_report_from_every_row(tmp_path, monkeypatch) -> None:
    out_dir = _fresh(monkeypatch, tmp_path)
    (out_dir / "results.json").write_text("[]", encoding="utf-8")
    (out_dir / "report.md").write_text("stale", encoding="utf-8")
    called = _call(monkeypatch, out_dir)
    assert benchmark.main() == 0
    assert called == []
    assert len(json.loads((out_dir / "results.json").read_text(encoding="utf-8"))) == 6
    assert (out_dir / "report.md").read_text(encoding="utf-8") != "stale"


@pytest.mark.parametrize("extra", [["--row", "alpha-s1"], ["--missing"]])
def test_row_and_missing_need_resume(monkeypatch, extra) -> None:
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", *extra])
    with pytest.raises(SystemExit) as exc:
        benchmark.main()
    assert exc.value.code == 2
