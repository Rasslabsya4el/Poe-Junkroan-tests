"""#753: rows the laptop finished reach the PC's week folder. A stub of the laptop; no PoB, no ssh."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import benchmark  # noqa: E402
from test_issue748_row_missing import A, SLUGS, _call, _fresh, _keep_rows  # noqa: E402
from test_runs_daemon import make_daemon  # noqa: E402

from junkroan.runs.row_sync import ROW_SYNC_SECONDS, RowSync  # noqa: E402

B = "b" * 40


class StubLaptop:
    """rows: {stem: row dict}; `up` False = every call raises like a dead ssh."""

    def __init__(self, rows: dict[str, dict]):
        self.rows = rows
        self.up = True
        self.pushed: list[list[str]] = []

    def list_rows(self, name):
        if not self.up:
            raise RuntimeError("ssh rc 255")
        return {s: {k: r.get(k) for k in ("commit", "loop_stop", "ok")} | {"has_pob": True} for s, r in self.rows.items()}

    def fetch(self, name, stem, dest, with_pob):
        (dest / f"{stem}.json").write_text(json.dumps(self.rows[stem]), encoding="utf-8")
        if with_pob:
            (dest / f"{stem}.pob.txt").write_text(f"laptop-code-{stem}", encoding="utf-8")

    def push(self, folder, files):
        if not self.up:
            raise RuntimeError("ssh rc 255")
        self.pushed.append(files)


def _laptop_row(commit: str, loop_stop: str) -> dict:
    return {"commit": commit, "loop_stop": loop_stop, "ok": True, "host": "laptop"}


def _missing(monkeypatch, capsys, out_dir: Path) -> list[str]:
    _call(monkeypatch, out_dir, "--missing")
    capsys.readouterr()
    assert benchmark.main() == 0
    return capsys.readouterr().out.split()


def test_row1_one_copied_two_refused_missing_one_fewer(tmp_path, monkeypatch, capsys) -> None:
    out_dir = _fresh(monkeypatch, tmp_path)
    _keep_rows(out_dir, set())
    for pob in out_dir.glob("*.pob.txt"):
        pob.unlink()
    before = _missing(monkeypatch, capsys, out_dir)
    assert before == ["alpha-s1", "beta-s1", "gamma-s1", "alpha-s2", "beta-s2", "gamma-s2"]
    laptop = StubLaptop({"alpha-s1": _laptop_row(B, "converged"),
                         "beta-s1": _laptop_row(A, "time"),
                         "gamma-s1": _laptop_row(A, "converged")})
    logs: list[str] = []
    assert RowSync(laptop, logs.append).run(out_dir, 1000.0) == 1
    refused = [m for m in logs if "refused" in m]
    assert len(refused) == 2
    assert "alpha-s1" in refused[0] and "is not the cut" in refused[0]
    assert "beta-s1" in refused[1] and "'time'" in refused[1]
    assert (out_dir / "rows" / "gamma-s1.json").is_file() and (out_dir / "gamma-s1.pob.txt").is_file()
    assert not (out_dir / "rows" / "alpha-s1.json").exists() and not (out_dir / "rows" / "beta-s1.json").exists()
    after = _missing(monkeypatch, capsys, out_dir)
    assert after == [s for s in before if s != "gamma-s1"] and len(after) == len(before) - 1
    assert RowSync(laptop, logs.append).run(out_dir, 1000.0) == 0   # nothing left to take; no leftovers
    assert not [p for p in out_dir.iterdir() if p.name.startswith(".row_sync_")]


def test_row2_same_stem_on_both_machines_pc_file_unchanged(tmp_path) -> None:
    folder = tmp_path / "20261012-0001-week-20261012"
    (folder / "rows").mkdir(parents=True)
    (folder / "args.json").write_text(json.dumps({"commit": A}), encoding="utf-8")
    mine = folder / "rows" / "gamma-s1.json"
    mine.write_text('{"commit": "%s", "loop_stop": "converged", "ok": true, "host": "pc"}' % A, encoding="utf-8")
    (folder / "gamma-s1.pob.txt").write_text("pc-code", encoding="utf-8")
    before = mine.read_bytes()
    laptop = StubLaptop({"gamma-s1": _laptop_row(A, "converged")})
    assert RowSync(laptop, lambda m: None).run(folder, 0.0) == 0
    assert mine.read_bytes() == before and (folder / "gamma-s1.pob.txt").read_text() == "pc-code"
    assert laptop.pushed == [["args.json"]]                          # the laptop keeps its own row of that stem


def test_row3_link_down_three_passes_then_up_copied_on_the_fourth(tmp_path) -> None:
    folder = tmp_path / "artifacts" / "benchmark" / "20261012-0001-week-20261012"
    (folder / "rows").mkdir(parents=True)
    (folder / "args.json").write_text(json.dumps({"commit": A}), encoding="utf-8")
    daemon, _store, _queue = make_daemon(tmp_path, host="pc", hosts_config={"laptop": {"ssh": "laptop"}})
    logs: list[str] = []
    now = [10_000.0]
    daemon.clock = lambda: now[0]
    daemon.log = logs.append
    daemon.timestamp = lambda: datetime(2026, 10, 11, 12, 0)
    daemon._cut_repo = tmp_path
    laptop = StubLaptop({"gamma-s1": _laptop_row(A, "converged")})
    laptop.up = False
    daemon._row_transport = laptop
    copied = []
    for _ in range(3):
        copied.append(daemon.row_sync_pass())
        now[0] += ROW_SYNC_SECONDS
    assert copied == [0, 0, 0] and logs == []
    assert daemon.remote_failed_ago("laptop") is None               # no failure noted, nothing for an anomaly
    laptop.up = True
    assert daemon.row_sync_pass() == 1
    assert (folder / "rows" / "gamma-s1.json").is_file()
    assert logs == ["row_sync: took gamma-s1 from the laptop"]


def test_off_the_pc_and_inside_the_throttle(tmp_path) -> None:
    folder = tmp_path / "artifacts" / "benchmark" / "20261012-0001-week-20261012"
    (folder / "rows").mkdir(parents=True)
    (folder / "args.json").write_text(json.dumps({"commit": A}), encoding="utf-8")
    daemon, _s, _q = make_daemon(tmp_path, host="laptop", hosts_config={"laptop": {"ssh": "laptop"}})
    daemon.timestamp = lambda: datetime(2026, 10, 11, 12, 0)
    daemon._cut_repo = tmp_path
    laptop = StubLaptop({"gamma-s1": _laptop_row(A, "converged")})
    daemon._row_transport = laptop
    assert daemon.row_sync_pass() == 0 and not (folder / "rows" / "gamma-s1.json").exists()
    sync = RowSync(laptop, lambda m: None)
    assert sync.run(folder, 0.0) == 1
    (folder / "rows" / "gamma-s1.json").unlink()
    assert sync.run(folder, 100.0) == 0                              # inside 5 min
    assert sync.run(folder, 300.0) == 1
