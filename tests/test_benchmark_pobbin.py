"""The benchmark uploads each finished build to pobb.in and the row carries the link (#572). No network."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
from junkroan import pobbin  # noqa: E402


def _row(slug: str, code: str | None = None, ok: bool = True) -> dict:
    from test_benchmark_durable import _row as durable_row

    row = durable_row(slug)
    if code:
        row["import_code"] = code
    if not ok:
        row = {"ok": False, "slug": slug, "seed": 1, "variant": "", "error": "boom"}
    return row


class Fake:
    def __init__(self, behavior=None):
        self.calls: list[str] = []
        self.behavior = behavior or (lambda code, n: f"id-{code}")

    def __call__(self, code: str) -> str:
        self.calls.append(code)
        return self.behavior(code, len(self.calls))


def _setup(monkeypatch, tmp_path: Path, fake: Fake, author_code: str | None = None):
    monkeypatch.setattr(benchmark, "upload_code", fake)
    monkeypatch.setattr(pobbin, "DEFAULT_CACHE", tmp_path / "ids.json")
    pob = tmp_path / "pob" / "Junkroan" / "bench"
    pob.parent.parent.mkdir(parents=True)
    monkeypatch.setattr(benchmark, "_pob_build_dir", lambda _s: pob)
    if author_code is None:
        def no_fixture(slug):
            raise FileNotFoundError(slug)
        monkeypatch.setattr(benchmark, "fixture_path", no_fixture)
    else:
        f = tmp_path / "author.pob.txt"
        f.write_text(author_code + "\n", encoding="utf-8")
        monkeypatch.setattr(benchmark, "fixture_path", lambda slug: f)
    out = tmp_path / "out"
    (out / "rows").mkdir(parents=True)
    return out, benchmark.new_pobbin_run(), []


def _persist(out, run, results, row):
    results.append(row)
    benchmark.persist_completed_row(out, stamp="20260101-0000", results=results, row=row,
                                    total_builds=3, workers=1, seconds=1.0, gear_mode="loot", pobbin_run=run)


def _read(out: Path, stem: str) -> dict:
    return json.loads((out / "rows" / f"{stem}.json").read_text(encoding="utf-8"))


def test_row1_an_ok_row_carries_id_and_url(tmp_path, monkeypatch):
    fake = Fake(lambda c, n: "abc123")
    out, run, results = _setup(monkeypatch, tmp_path, fake)
    _persist(out, run, results, _row("alpha"))
    data = _read(out, "alpha-s1")
    assert data["pobbin_id"] == "abc123" and data["pobbin_url"] == "https://pobb.in/abc123"
    assert "pobbin_error" not in data and data["ok"] is True
    assert len(fake.calls) == 1


def test_row2_a_server_error_is_on_the_row_and_the_build_stays_ok(tmp_path, monkeypatch):
    def behavior(code, n):
        if n <= 2:
            raise pobbin.HttpStatusError(500)
        return "id2"

    fake = Fake(behavior)
    out, run, results = _setup(monkeypatch, tmp_path, fake)
    _persist(out, run, results, _row("alpha"))
    _persist(out, run, results, _row("beta"))
    first, second = _read(out, "alpha-s1"), _read(out, "beta-s1")
    assert first["pobbin_error"] == "HTTP 500" and first["ok"] is True
    assert second["pobbin_id"] == "id2"
    assert len(fake.calls) == 3


def _offline(code, n):
    raise ConnectionError("down")


def test_row3_offline_skips_the_rest_and_the_pass_fixes_nothing(tmp_path, monkeypatch):
    fake = Fake(_offline)
    out, run, results = _setup(monkeypatch, tmp_path, fake)
    for slug in ("alpha", "beta", "gamma"):
        _persist(out, run, results, _row(slug))
    assert _read(out, "beta-s1")["pobbin_error"].startswith("skipped: offline since alpha-s1: ConnectionError:")
    assert _read(out, "gamma-s1")["pobbin_error"].startswith("skipped: offline since alpha-s1")
    assert len(fake.calls) == 2
    assert benchmark.pobbin_retry_pass(out, results, run) == 0
    assert len(fake.calls) == 3


def test_row3b_the_end_pass_fixes_all_three(tmp_path, monkeypatch):
    state = {"down": True}

    def behavior(code, n):
        if state["down"]:
            raise ConnectionError("down")
        return f"id-{code}"

    fake = Fake(behavior)
    out, run, results = _setup(monkeypatch, tmp_path, fake)
    for slug in ("alpha", "beta", "gamma"):
        _persist(out, run, results, _row(slug))
    state["down"] = False
    assert benchmark.pobbin_retry_pass(out, results, run) == 3
    assert len(fake.calls) == 5
    for slug in ("alpha", "beta", "gamma"):
        data = _read(out, f"{slug}-s1")
        assert data["pobbin_id"] == f"id-import {slug}" and "pobbin_error" not in data


def test_row4_a_row_equal_to_its_author_uploads_once(tmp_path, monkeypatch):
    fake = Fake()
    out, run, results = _setup(monkeypatch, tmp_path, fake, author_code="same code")
    _persist(out, run, results, _row("alpha", code="same code"))
    data = _read(out, "alpha-s1")
    assert data["pobbin_id"] == data["author_pobbin_id"] == "id-same code"
    assert len(json.loads((tmp_path / "ids.json").read_text(encoding="utf-8"))) == 1
    assert len(fake.calls) == 1


def test_row6_a_failed_build_makes_no_call_of_its_own(tmp_path, monkeypatch):
    fake = Fake()
    out, run, results = _setup(monkeypatch, tmp_path, fake)
    _persist(out, run, results, _row("alpha", ok=False))
    data = _read(out, "alpha-s1")
    assert not any(k.startswith("pobbin_") for k in data)
    assert fake.calls == []


def test_row5_main_uploads_every_build_and_prints_the_summary(tmp_path, monkeypatch, capsys):
    fake = Fake()
    monkeypatch.setattr(benchmark, "upload_code", fake)
    monkeypatch.setattr(pobbin, "DEFAULT_CACHE", tmp_path / "ids.json")
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(benchmark, "ROOT", root)
    monkeypatch.setattr(benchmark, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(benchmark.time, "strftime", lambda _f: "20260919-1200")
    pob = tmp_path / "pob" / "Junkroan" / "benchmark"
    pob.parent.parent.mkdir(parents=True)
    monkeypatch.setattr(benchmark, "_pob_build_dir", lambda _s: pob)

    def no_fixture(slug):
        raise FileNotFoundError(slug)

    monkeypatch.setattr(benchmark, "fixture_path", no_fixture)
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_k: {**_full_row(slug)})
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "beta", "--workers", "2", "--no-variants", "--gear", "loot", "--tag", "pb"])
    benchmark.main()
    out = root / "artifacts" / "benchmark" / "20260919-1200-pb"
    for slug in ("alpha", "beta"):
        assert _read(out, f"{slug}-s1")["pobbin_url"] == f"https://pobb.in/id-import {slug}"
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert {r["pobbin_url"] for r in results} == {"https://pobb.in/id-import alpha", "https://pobb.in/id-import beta"}
    assert "pobbin: 2 uploaded, 0 errors, 0 fixed at the end" in capsys.readouterr().out
    assert len(fake.calls) == 2


def _full_row(slug: str) -> dict:
    from test_benchmark_durable import _row as durable_row

    return durable_row(slug)
