"""#750 unit 1: the weekly cut, its folder, its args. Temp git repos, no PoB."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from junkroan.runs import weekly_cut as wc  # noqa: E402

TZ = timezone(timedelta(hours=3))
MONDAY = date(2026, 10, 12)  # cut = Fri 2026-10-09 20:00 +03:00


def sh(repo: Path, *args: str, when: str | None = None) -> str:
    env = dict(os.environ)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env).stdout.strip()


def commit(work: Path, name: str, when: str) -> str:
    (work / "f.txt").write_text(name)
    sh(work, "add", "-A")
    sh(work, "commit", "-q", "-m", name, when=when)
    return sh(work, "rev-parse", "HEAD")


@pytest.fixture
def pair(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    sh(work, "init", "-q", "-b", "main")
    sh(work, "config", "user.email", "t@t")
    sh(work, "config", "user.name", "t")
    early = commit(work, "early", "2026-10-02T12:00:00+03:00")
    before = commit(work, "fri1950", "2026-10-09T19:50:00+03:00")
    after = commit(work, "fri2010", "2026-10-09T20:10:00+03:00")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(origin)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    sh(clone, "config", "user.email", "t@t")
    sh(clone, "config", "user.name", "t")
    return work, origin, clone, early, before, after


def test_row1_cut_is_friday_1950_commit_whenever_asked(pair):
    work, origin, clone, early, before, after = pair
    # asked "at Fri 20:00:10" and "at Sat 03:00": the function has no `now`, both calls read history
    assert wc.cut_for_week(clone, MONDAY, TZ) == before
    assert wc.cut_for_week(clone, MONDAY, TZ) == before
    later = commit(work, "sat", "2026-10-10T03:00:00+03:00")
    sh(work, "push", "-q", str(origin), "main")
    sh(clone, "fetch", "-q")
    assert wc.cut_for_week(clone, MONDAY, TZ) == before != later


def test_cut_raises_when_no_commit_is_that_old(pair):
    _, _, clone, *_ = pair
    with pytest.raises(RuntimeError, match="no commit"):
        wc.cut_for_week(clone, date(2026, 9, 7), TZ)


def test_row2_folder(tmp_path):
    root = tmp_path / "repo"
    cut = "c" * 40
    f = wc.open_week_folder(root, MONDAY, cut, now=datetime(2026, 10, 9, 20, 1))
    assert f.name == "20261009-2001-week-20261012"
    a = json.loads((f / "args.json").read_text())
    assert len(a["slugs"]) == 14 and a["seeds"] == 3 and a["seed"] == 4 and a["loop_seconds"] is None  # #956: no clock
    assert a["gear"] == "wishlist" and a["commit"] == cut
    assert list((f / "rows").iterdir()) == [] and sorted(p.name for p in f.iterdir()) == ["args.json", "rows"]
    assert wc.find_week_folder(root, MONDAY) == f
    assert wc.open_week_folder(root, MONDAY, "d" * 40, now=datetime(2026, 10, 10, 9, 0)) == f
    assert wc.find_week_folder(root, date(2026, 10, 19)) is None


def test_drop_aside_then_fresh_folder(tmp_path):
    old = "abcdef1234" + "0" * 30
    f = wc.open_week_folder(tmp_path, MONDAY, old, now=datetime(2026, 10, 9, 20, 1))
    new = wc.drop_week_folder(f, old)
    assert new.name == f.name + "-dropped-abcdef1" and new.is_dir() and not f.exists()
    assert wc.find_week_folder(tmp_path, MONDAY) is None
    g = wc.open_week_folder(tmp_path, MONDAY, "e" * 40, now=datetime(2026, 10, 10, 9, 0))
    assert g != new and wc.find_week_folder(tmp_path, MONDAY) == g


def test_row6_second_checkout_reads_same_cut_and_override(pair, tmp_path):
    work, origin, clone, early, before, after = pair
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
    assert wc.cut_for_week(other, MONDAY, TZ) == wc.cut_for_week(clone, MONDAY, TZ) == before
    wc.record_override(work, MONDAY, after)
    sh(work, "add", "-A")
    sh(work, "commit", "-q", "-m", "recut", when="2026-10-11T10:00:00+03:00")
    sh(work, "push", "-q", str(origin), "main")
    for repo in (clone, other):
        sh(repo, "fetch", "-q")
        assert wc.cut_for_week(repo, MONDAY, TZ) == after
        assert wc.cut_for_week(repo, date(2026, 10, 19), TZ) != after  # other weeks untouched


def test_record_override_updates(tmp_path):
    wc.record_override(tmp_path, MONDAY, "a" * 40)
    wc.record_override(tmp_path, date(2026, 10, 19), "b" * 40)
    wc.record_override(tmp_path, MONDAY, "c" * 40)
    assert json.loads((tmp_path / "config" / "weekly_cut.json").read_text()) == {"20261012": "c" * 40, "20261019": "b" * 40}


@pytest.mark.parametrize("when,expected", [
    (datetime(2026, 10, 9, 19, 59), MONDAY), (datetime(2026, 10, 9, 20, 0), MONDAY),
    (datetime(2026, 10, 10, 3, 0), MONDAY), (datetime(2026, 10, 11, 23, 0), MONDAY),
    (datetime(2026, 10, 12, 8, 0), MONDAY), (datetime(2026, 10, 13, 9, 0), date(2026, 10, 19)),
])
def test_monday_of(when, expected):
    assert wc.monday_of(when) == expected


def test_weekly_args_match_benchmark_keys():
    import benchmark

    a = wc.weekly_args()
    assert set(a) == set(benchmark._RESUMABLE_ARG_FIELDS) | {"template_path"}
    assert a["slugs"] == benchmark.SETS["core14"] and a["loop_seconds"] is benchmark.LOOP_SECONDS_DEFAULT is None
    assert wc.WEEKLY_ARGV == ["--set", "core14", "--gear", "wishlist", "--seed", "4", "--seeds", "3", "--workers", "auto"]


def test_folder_is_resumable_at_the_cut(tmp_path, monkeypatch):
    import benchmark

    cut = "c" * 40
    f = wc.open_week_folder(tmp_path, MONDAY, cut, now=datetime(2026, 10, 9, 20, 1))
    ns = argparse.Namespace(resume=str(f), slugs=[], set="core14", seeds=3, loop_seconds=None)
    monkeypatch.setattr(benchmark, "code_commit", lambda root=None: cut)
    out, _ = benchmark._prepare_resume(ns)
    assert out == f and ns.seed == 4 and ns.gear == "wishlist" and len(ns.slugs) == 14
    monkeypatch.setattr(benchmark, "code_commit", lambda root=None: "d" * 40)
    with pytest.raises(SystemExit):
        benchmark._prepare_resume(argparse.Namespace(resume=str(f), slugs=[], set="core14", seeds=3, loop_seconds=None))
