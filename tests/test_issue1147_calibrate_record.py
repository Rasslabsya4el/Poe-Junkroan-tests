"""#1147 unit 3b: scripts/repair_calibrate.py `--record-calls DIR`, PoB-free.

A fake PobSession stands in for the real one: it keeps, in order, every call made on it. The option must write
`DIR/<pair name>.calls.jsonl` per pair (from loading the parent build on, the author's preparation left out, as
replay_bench does), must not change which calls the session receives (D95), and without the option must write no
file and never call `begin_recording`. No PobSession is opened."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repair_calibrate as rc  # noqa: E402
from junkroan.optimizer.repair import RepairOutcome, repair_gains, repair_verdict  # noqa: E402

SESSIONS: list["FakeSession"] = []


class FakeSession:
    """Stands in for PobSession: `calls` is what the code under test asked of it, in order."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.calls: list[str] = []
        SESSIONS.append(self)

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def author_prep(self) -> None:
        self.calls.append("author_prep")

    def load_import_code(self, text: str) -> None:
        self.calls.append("load_import_code")

    def stats(self, keys: list[str]) -> dict:
        self.calls.append("stats")
        return {}


def _fake_prepared_author(pob, slug, stat, log):
    pob.author_prep()  # before the recording starts: must not appear in any transcript
    return "prepared"


def _fake_pipeline_state(pob, prepared, *, gear_mode, log, mark_picked=False):
    def repair(working, result, choice):
        working.pob.stats(["CombinedDPS"])  # a PoB call made through the object the repair is given
        start = 1000.0
        values = [1050.0, 1071.0]
        return RepairOutcome(start=start, values=values, gains=repair_gains(start, values),
                             verdict=repair_verdict(start, values), seconds=0.0)

    pipeline = SimpleNamespace(judging=None, objective=SimpleNamespace(maximize="CombinedDPS"), repair=repair)
    return pipeline, SimpleNamespace(class_name="Witch", ascendancy="Elementalist", main_link=["Fireball"]), "gear", "tree"


def _write_row(run: Path, stem: str, *, ours: float, seconds: float, variant: str = "", slug: str = "alpha", seed: int = 4) -> None:
    rows = run / "rows"
    rows.mkdir(parents=True, exist_ok=True)
    (rows / f"{stem}.json").write_text(json.dumps({"ok": True, "slug": slug, "seed": seed, "variant": variant, "ours": ours,
                                                   "seconds": seconds, "stat": "CombinedDPS", "gear_mode": "wishlist"}), encoding="utf-8")
    (run / f"{stem}.pob.txt").write_text("eNpzdummy", encoding="utf-8")


@pytest.fixture()
def run_folder(tmp_path: Path) -> Path:
    """Two forbid pairs: alpha-s4 with its no-foo_bar, beta-s5 with its no-qux."""

    run = tmp_path / "run"
    _write_row(run, "alpha-s4", ours=1000.0, seconds=100.0, slug="alpha")
    _write_row(run, "alpha-s4-no-foo_bar", ours=1200.0, seconds=300.0, variant="no Foo Bar", slug="alpha")
    _write_row(run, "beta-s5", ours=1000.0, seconds=100.0, slug="beta", seed=5)
    _write_row(run, "beta-s5-no-qux", ours=990.0, seconds=50.0, variant="no Qux", slug="beta", seed=5)
    return run


@pytest.fixture(autouse=True)
def fake_pob(monkeypatch: pytest.MonkeyPatch) -> None:
    SESSIONS.clear()
    monkeypatch.setattr(rc, "PobSession", FakeSession)
    monkeypatch.setattr(rc, "_prepared_author", _fake_prepared_author)
    monkeypatch.setattr(rc, "_pipeline_state", _fake_pipeline_state)
    monkeypatch.setattr(rc, "source_info", lambda path: {"slug": "alpha", "stat": "CombinedDPS", "gear_mode": "loot"})


@pytest.fixture()
def begin_spy(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Records each `begin_recording` target and runs the real one (the recording is what the option means)."""

    targets: list[Path] = []
    real = rc.begin_recording

    def spy(pob, target):
        targets.append(target)
        return real(pob, target)

    monkeypatch.setattr(rc, "begin_recording", spy)
    return targets


def _methods(path: Path) -> list[str]:
    return [json.loads(line)["method"] for line in path.read_text(encoding="utf-8").splitlines()]


def _argv(monkeypatch: pytest.MonkeyPatch, run: Path, *extra: str) -> None:
    monkeypatch.setattr(sys, "argv", ["repair_calibrate.py", "--pairs", str(run), "--direction", "forbid",
                                      "--workers", "1", "--tag", "t1147", *extra])


def test_repair_one_with_record_calls_writes_its_pair_from_loading_the_parent_on(run_folder: Path, tmp_path: Path, begin_spy: list[Path]):
    pair = rc.discover_pairs(run_folder, "forbid")[0]
    out = tmp_path / "calls"
    row = rc.repair_one(pair, record_calls=str(out))
    assert row["ok"] is True and row["verdict"] == "climbing"
    assert begin_spy == [out / f"{pair.name}.calls.jsonl"]
    assert _methods(out / f"{pair.name}.calls.jsonl") == ["load_import_code", "stats"]
    assert SESSIONS[-1].calls == ["author_prep", "load_import_code", "stats"]


def test_without_the_option_no_file_is_written_and_begin_recording_is_not_called(run_folder: Path, tmp_path: Path, begin_spy: list[Path]):
    pair = rc.discover_pairs(run_folder, "forbid")[0]
    row = rc.repair_one(pair)
    assert row["ok"] is True
    assert begin_spy == []
    assert list(tmp_path.rglob("*.calls.jsonl")) == []
    assert SESSIONS[-1].calls == ["author_prep", "load_import_code", "stats"]


def test_recording_leaves_the_pob_calls_of_the_repair_unchanged(run_folder: Path, tmp_path: Path):
    """D95: the recording is a wrapper; the session receives the same calls with and without it."""

    pair = rc.discover_pairs(run_folder, "forbid")[0]
    rc.repair_one(pair)
    plain = list(SESSIONS[-1].calls)
    rc.repair_one(pair, record_calls=str(tmp_path / "calls"))
    recorded = list(SESSIONS[-1].calls)
    assert recorded == plain
    assert _methods(tmp_path / "calls" / f"{pair.name}.calls.jsonl") == [call for call in plain if call != "author_prep"]


def test_main_record_calls_writes_one_file_per_pair(run_folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = tmp_path / "calls"
    _argv(monkeypatch, run_folder, "--record-calls", str(out))
    assert rc.main() == 0
    pairs = rc.discover_pairs(run_folder, "forbid")
    assert sorted(path.name for path in out.iterdir()) == sorted(f"{pair.name}.calls.jsonl" for pair in pairs)
    assert all(_methods(out / f"{pair.name}.calls.jsonl") == ["load_import_code", "stats"] for pair in pairs)
    assert (run_folder / "report-repair.md").is_file()


def test_main_without_record_calls_writes_no_calls_file(run_folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, begin_spy: list[Path]):
    _argv(monkeypatch, run_folder)
    assert rc.main() == 0
    assert begin_spy == []
    assert list(tmp_path.rglob("*.calls.jsonl")) == []
    assert (run_folder / "report-repair.md").is_file()
