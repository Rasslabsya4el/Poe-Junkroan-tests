"""#573: `--pobbin-backfill` gives a run's link-less ok rows their pobb.in links from disk. No network, no PoB."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
from junkroan import pobbin  # noqa: E402
from test_benchmark_pobbin import Fake  # noqa: E402


def _mk(out: Path, slug: str, code: str | None = "code", ok: bool = True, **extra) -> dict:
    row = {"ok": ok, "slug": slug, "seed": 1, "variant": "", "ours": 1.0, **extra}
    (out / "rows").mkdir(parents=True, exist_ok=True)
    (out / "rows" / f"{slug}-s1.json").write_text(json.dumps(row, indent=1), encoding="utf-8")
    if code is not None:
        (out / f"{slug}-s1.pob.txt").write_bytes(code.encode("utf-8"))
    return row


def _results(out: Path, rows: list[dict]) -> None:
    (out / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


def _setup(monkeypatch, tmp_path: Path, fake: Fake, author: str | None = None) -> Path:
    monkeypatch.setattr(benchmark, "upload_code", fake)
    monkeypatch.setattr(pobbin, "DEFAULT_CACHE", tmp_path / "ids.json")
    if author is None:
        def none(slug):
            raise FileNotFoundError(slug)
        monkeypatch.setattr(benchmark, "fixture_path", none)
    else:
        f = tmp_path / "author.pob.txt"
        f.write_text(author + "\n", encoding="utf-8")
        monkeypatch.setattr(benchmark, "fixture_path", lambda slug: f)
    out = tmp_path / "20261005-1220-gate"
    out.mkdir()
    return out


def _read(out: Path, stem: str) -> dict:
    return json.loads((out / "rows" / f"{stem}.json").read_text(encoding="utf-8"))


def test_row1_only_linkless_rows_are_uploaded_and_results_follows(tmp_path, monkeypatch):
    fake = Fake(lambda c, n: f"id-{c}")
    out = _setup(monkeypatch, tmp_path, fake)
    rows = [_mk(out, "alpha", "A"), _mk(out, "beta", "B", pobbin_id="xyz", pobbin_url="https://pobb.in/xyz"), _mk(out, "gamma", "G")]
    _results(out, rows)
    beta_file = out / "rows" / "beta-s1.json"
    os.utime(beta_file, (1_000_000, 1_000_000))
    line = benchmark.pobbin_backfill(out, "gate")
    assert fake.calls == ["A", "G"]
    assert _read(out, "alpha-s1")["pobbin_id"] == "id-A" and _read(out, "alpha-s1")["pobbin_url"] == "https://pobb.in/id-A"
    assert _read(out, "gamma-s1")["pobbin_id"] == "id-G"
    assert _read(out, "beta-s1")["pobbin_id"] == "xyz" and beta_file.stat().st_mtime == 1_000_000
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert [r["slug"] for r in res] == ["alpha", "beta", "gamma"]
    assert [r["pobbin_id"] for r in res] == ["id-A", "xyz", "id-G"]
    assert line == "pobbin backfill gate: 2 uploaded, 1 already linked, 0 errors, 0 without a .pob.txt, authors 0 uploaded"


def test_row2_an_errored_row_is_retried_and_loses_its_error(tmp_path, monkeypatch):
    fake = Fake(lambda c, n: "fresh")
    out = _setup(monkeypatch, tmp_path, fake)
    _results(out, [_mk(out, "alpha", "A", pobbin_error="HTTP 500")])
    benchmark.pobbin_backfill(out, "gate")
    assert len(fake.calls) == 1
    for data in (_read(out, "alpha-s1"), json.loads((out / "results.json").read_text(encoding="utf-8"))[0]):
        assert data["pobbin_id"] == "fresh" and "pobbin_error" not in data


def test_row3_rows_without_ok_or_pob_txt_are_left_and_counted(tmp_path, monkeypatch):
    fake = Fake()
    out = _setup(monkeypatch, tmp_path, fake)
    rows = [_mk(out, "alpha", None), _mk(out, "beta", "B", ok=False)]
    _results(out, rows)
    before = {p.name: p.read_bytes() for p in (out / "rows").glob("*.json")}
    results_before = (out / "results.json").read_bytes()
    line = benchmark.pobbin_backfill(out, "gate")
    assert fake.calls == []
    assert {p.name: p.read_bytes() for p in (out / "rows").glob("*.json")} == before
    assert (out / "results.json").read_bytes() == results_before
    assert line == "pobbin backfill gate: 0 uploaded, 0 already linked, 0 errors, 2 without a .pob.txt, authors 0 uploaded"


def test_row4_the_author_is_uploaded_once_per_slug(tmp_path, monkeypatch):
    fake = Fake(lambda c, n: f"id-{c}")
    out = _setup(monkeypatch, tmp_path, fake, author="AUTHOR")
    rows = [_mk(out, "alpha", "A")]
    (out / "rows" / "alpha-s2.json").write_text(json.dumps({"ok": True, "slug": "alpha", "seed": 2, "variant": ""}), encoding="utf-8")
    (out / "alpha-s2.pob.txt").write_bytes(b"A2")
    _results(out, rows)
    line = benchmark.pobbin_backfill(out, "gate")
    assert sorted(fake.calls) == ["A", "A2", "AUTHOR"]
    for stem in ("alpha-s1", "alpha-s2"):
        data = _read(out, stem)
        assert data["author_pobbin_id"] == "id-AUTHOR" and data["author_pobbin_url"] == "https://pobb.in/id-AUTHOR"
    assert line.endswith("2 uploaded, 0 already linked, 0 errors, 0 without a .pob.txt, authors 1 uploaded")


def test_row5_a_second_pass_calls_and_rewrites_nothing(tmp_path, monkeypatch):
    fake = Fake(lambda c, n: f"id-{c}")
    out = _setup(monkeypatch, tmp_path, fake)
    _results(out, [_mk(out, "alpha", "A"), _mk(out, "beta", "B")])
    benchmark.pobbin_backfill(out, "gate")
    assert len(fake.calls) == 2
    files = [out / "rows" / "alpha-s1.json", out / "rows" / "beta-s1.json", out / "results.json"]
    for f in files:
        os.utime(f, (1_000_000, 1_000_000))
    line = benchmark.pobbin_backfill(out, "gate")
    assert len(fake.calls) == 2
    assert all(f.stat().st_mtime == 1_000_000 for f in files)
    assert line.startswith("pobbin backfill gate: 0 uploaded, 2 already linked")


def test_rule3_a_pass_after_the_run_overwrote_results_relinks_it_with_no_upload(tmp_path, monkeypatch):
    fake = Fake(lambda c, n: f"id-{c}")
    out = _setup(monkeypatch, tmp_path, fake)
    rows = [_mk(out, "alpha", "A"), _mk(out, "beta", "B")]
    _results(out, rows)
    benchmark.pobbin_backfill(out, "gate")
    _results(out, rows)  # the run's end rewrites results.json from memory, without links
    line = benchmark.pobbin_backfill(out, "gate")
    assert len(fake.calls) == 2
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert [r["pobbin_id"] for r in res] == ["id-A", "id-B"]
    assert line.startswith("pobbin backfill gate: 0 uploaded, 2 already linked")


def test_a_429_is_waited_out_inside_one_backfill(tmp_path, monkeypatch):
    def behavior(code, n):
        if n == 1:
            raise pobbin.HttpStatusError(429)
        return f"id-{code}"

    fake = Fake(behavior)
    out = _setup(monkeypatch, tmp_path, fake)
    sleeps: list[float] = []
    monkeypatch.setattr(benchmark.time, "sleep", sleeps.append)
    _results(out, [_mk(out, "alpha", "A")])
    line = benchmark.pobbin_backfill(out, "gate")
    assert fake.calls == ["A", "A"] and sleeps == [benchmark.BACKFILL_429_WAIT_S]
    assert _read(out, "alpha-s1")["pobbin_id"] == "id-A"
    assert line.startswith("pobbin backfill gate: 1 uploaded, 0 already linked, 0 errors")


def test_a_429_that_never_clears_ends_as_the_rows_error(tmp_path, monkeypatch):
    def behavior(code, n):
        raise pobbin.HttpStatusError(429)

    fake = Fake(behavior)
    out = _setup(monkeypatch, tmp_path, fake)
    sleeps: list[float] = []
    monkeypatch.setattr(benchmark.time, "sleep", sleeps.append)
    _results(out, [_mk(out, "alpha", "A")])
    line = benchmark.pobbin_backfill(out, "gate")
    assert len(fake.calls) == benchmark.BACKFILL_429_TRIES and len(sleeps) == benchmark.BACKFILL_429_TRIES - 1
    assert _read(out, "alpha-s1")["pobbin_error"] == "HTTP 429"
    assert "0 uploaded, 0 already linked, 1 errors" in line
