"""#749 early warning: rows 1-6 on copies of the real 2026-10-05 base rows; no PoB, no real gh."""

import json
import shutil
import sys
from pathlib import Path

import pytest
from conftest import pc_only

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import early_warning as ew  # noqa: E402

REAL = ROOT / "artifacts" / "benchmark" / "20261005-1220-gate-20261005"
WEEK = "20261005"


@pytest.fixture
def bench(tmp_path):
    core = tmp_path / "20261005-1220-gate-20261005"
    core.mkdir()
    shutil.copy(REAL / "results.json", core / "results.json")
    warn = tmp_path / f"20261012-0100-warn-{WEEK}"
    (warn / "rows").mkdir(parents=True)
    for f in (REAL / "rows").glob("*.json"):
        if json.loads(f.read_text(encoding="utf-8")).get("variant"):
            continue
        shutil.copy(f, warn / "rows" / f.name)
    return tmp_path, core, warn


def lower(warn, slug, points):
    for f in (warn / "rows").glob(f"{slug}-s*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        r["ratio_lane"] -= points / 100.0
        f.write_text(json.dumps(r), encoding="utf-8")


def run(bench):
    root, core, _ = bench
    return ew.find_drops(ew._rows(core), ew.week_rows(WEEK, root))


def _slug_th(bench):
    th = ew.thresholds(ew._rows(bench[1]))
    slug = sorted(th)[0]
    return slug, th[slug]["threshold"]


@pc_only
def test_row1_same_rows_no_drop(bench):
    assert len(ew.week_rows(WEEK, bench[0])) == 42
    assert ew.render(run(bench)) == "no drop\n"


@pc_only
def test_row2_lowered_by_threshold_plus_one(bench):
    slug, t = _slug_th(bench)
    lower(bench[2], slug, t + 1.0)
    drops = run(bench)
    assert [d["slug"] for d in drops] == [slug]
    assert drops[0]["delta"] == pytest.approx(-(t + 1.0), abs=0.01)


@pc_only
def test_row3_lowered_by_threshold_minus_one(bench):
    slug, t = _slug_th(bench)
    lower(bench[2], slug, t - 1.0)
    assert ew.render(run(bench)) == "no drop\n"


@pc_only
def test_row4_one_seed_only(bench):
    slug, _ = _slug_th(bench)
    for f in list((bench[2] / "rows").glob(f"{slug}-s[56].json")):
        f.unlink()
    lower(bench[2], slug, 30.0)
    assert ew.render(run(bench)) == "no drop\n"


@pc_only
def test_row5_failed_row(bench):
    slug, _ = _slug_th(bench)
    f = bench[2] / "rows" / f"{slug}-s4.json"
    r = json.loads(f.read_text(encoding="utf-8"))
    r["ok"] = False
    f.write_text(json.dumps(r), encoding="utf-8")
    drops = run(bench)
    assert len(drops) == 1 and drops[0]["kind"] == "failed"
    assert ew.render(drops).count("failed") == 1


@pc_only
def test_row6_post_twice(bench, monkeypatch):
    slug, t = _slug_th(bench)
    lower(bench[2], slug, t + 1.0)
    root, core, _ = bench
    monkeypatch.setattr(ew, "BENCH", root)
    issues, calls = [], []

    def gh(args):
        calls.append(args[:2])
        if args[:2] == ["issue", "list"]:
            return json.dumps(issues)
        if args[:2] == ["issue", "create"]:
            assert "needs-triage" in args and "area:builds" in args
            issues.append({"number": 1, "title": args[args.index("--title") + 1],
                           "body": args[args.index("--body") + 1], "comments": []})
            return "https://github.com/x/y/issues/1\n"
        if args[:2] == ["issue", "comment"]:
            issues[0]["comments"].append({"body": args[-1]})
            return ""
        raise AssertionError(args)

    argv = ["--week", WEEK, "--core", str(core), "--post"]
    assert ew.main(argv, gh=gh) == 0
    assert ew.main(argv, gh=gh) == 0
    assert calls.count(["issue", "create"]) == 1 and calls.count(["issue", "comment"]) == 0
