"""#1166: a weekly core run finished on the laptop reaches the PC's gate folders. Temp dirs and a fake transport; no ssh, no PoB."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_runs_daemon import make_daemon  # noqa: E402

from junkroan.runs import gate_pull as pull  # noqa: E402
from junkroan.runs import gates  # noqa: E402

NAME = "20261019-0900-P2-core"
CFG = {"ssh": "laptop", "daemon_repo_path": r"C:\Coding\poe-junkroan-v2-daemon"}
FINISHED = {
    "args.json": "{}",
    "results.json": "[]",
    "report.md": "# Benchmark: references rebuilt from their own skeletons\n",
    "rows/ref-s1.json": '{"ok": true, "loop_stop": "converged"}',
    "ref-s1.pob.txt": "PoB import code",
}


def _folder(root: Path, name: str, files: dict[str, str], age: float = 1000.0) -> Path:
    """A laptop folder; its results.json and report.md are `age` seconds old (settled by default)."""
    folder = root / name
    for rel, text in files.items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _age(folder, age)
    return folder


def _age(folder: Path, age: float) -> None:
    stamp = time.time() - age
    for rel in ("results.json", "report.md"):
        if (folder / rel).is_file():
            os.utime(folder / rel, (stamp, stamp))


def _tree(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8")
            for p in folder.rglob("*") if p.is_file()}


class FakeLaptop:
    """The laptop's artifacts/benchmark as a directory on disk. `fail_after` drops the link after that many files."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.fail_after: int | None = None
        self.fetched: list[str] = []
        self.calls = 0

    def list_gates(self) -> list[str]:
        self.calls += 1
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def is_finished(self, name: str) -> bool:
        return pull.folder_settled(self.root / name)

    def fetch(self, name: str, dest: Path) -> None:
        self.fetched.append(name)
        src = self.root / name
        dest.mkdir()
        written = 0
        for p in sorted(src.rglob("*")):
            if not p.is_file():
                continue
            if self.fail_after is not None and written >= self.fail_after:
                raise OSError("link dropped midway")
            target = dest / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
            written += 1


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.laptop = FakeLaptop(tmp_path / "laptop" / "artifacts" / "benchmark")
        self.artifacts = tmp_path / "pc" / "artifacts"
        self.artifacts.parent.mkdir(parents=True)  # the daemon's own store lives beside it
        self.gates = tmp_path / "gates_present.json"
        self.logs: list[str] = []

    @property
    def pc_dir(self) -> Path:
        return self.artifacts / "benchmark"

    def pull(self) -> list[str]:
        return pull.gate_pull(self.artifacts, self.laptop, gates_path=self.gates, log=self.logs.append)


def _pull_daemon(rig: Rig, *, host: str = "pc", artifacts: Path | None = ...):
    daemon, _, _ = make_daemon(rig.artifacts.parent, host=host, hosts_config={"laptop": CFG})
    daemon.clock = lambda: 1000.0
    daemon.log = rig.logs.append
    daemon._gate_artifacts = rig.artifacts if artifacts is ... else artifacts
    daemon._gates_path = rig.gates
    daemon._gate_pull_transport = rig.laptop
    return daemon


def test_row1_finished_laptop_folder_reaches_pc(tmp_path):
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, NAME, FINISHED)
    assert rig.pull() == [NAME]
    assert _tree(rig.pc_dir / NAME) == _tree(rig.laptop.root / NAME)
    assert gates.gates_present("pc", rig.gates) == {NAME}
    assert gates.gates_present("laptop", rig.gates) == {NAME}
    assert gates.newest_gate(rig.artifacts) == NAME
    assert not (rig.pc_dir / (NAME + ".partial")).exists()


def test_row1_reaches_pc_through_the_daemon_hook(tmp_path):
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, NAME, FINISHED)
    daemon = _pull_daemon(rig)
    assert pull.gate_pull_pass(daemon) == [NAME]
    assert _tree(rig.pc_dir / NAME) == _tree(rig.laptop.root / NAME)
    assert gates.gates_present("laptop", rig.gates) == {NAME}


def test_row2_rerun_copies_nothing_and_logs_nothing(tmp_path):
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, NAME, FINISHED)
    assert rig.pull() == [NAME]
    rig.logs.clear()
    rig.laptop.fetched.clear()
    assert rig.pull() == []
    assert rig.laptop.fetched == []
    assert rig.logs == []
    assert gates.gates_present("pc", rig.gates) == {NAME}


@pytest.mark.parametrize("files", [
    {"rows/ref-s1.json": "{}", "ref-s1.pob.txt": "PoB import code"},          # no results.json yet
    {**FINISHED, "report.md": "partial: 1 of 2 builds\n"},                     # still running
])
def test_row3_laptop_folder_without_finished_marker_is_not_taken(tmp_path, files):
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, NAME, files)
    assert rig.pull() == []
    assert rig.laptop.fetched == []
    assert not (rig.pc_dir / NAME).exists()
    assert gates.gates_present("pc", rig.gates) == set()
    assert gates.gates_present("laptop", rig.gates) == set()


def test_row4_copy_failing_midway_leaves_nothing_and_next_pass_retries(tmp_path):
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, NAME, FINISHED)
    rig.laptop.fail_after = 1
    assert rig.pull() == []
    assert not (rig.pc_dir / NAME).exists()
    assert not (rig.pc_dir / (NAME + ".partial")).exists()
    assert gates.gates_present("pc", rig.gates) == set()
    assert gates.gates_present("laptop", rig.gates) == set()
    assert any("failed" in line for line in rig.logs)
    rig.laptop.fail_after = None
    assert rig.pull() == [NAME]
    assert _tree(rig.pc_dir / NAME) == _tree(rig.laptop.root / NAME)
    assert gates.gates_present("laptop", rig.gates) == {NAME}


def _gate_sync_daemon(rig: Rig):
    procs: list = []
    daemon, _, _ = make_daemon(rig.artifacts.parent, host="pc", hosts_config={"laptop": CFG})
    daemon.clock = lambda: 1000.0
    daemon.log = rig.logs.append
    daemon._gate_artifacts = rig.artifacts
    daemon._gates_path = rig.gates

    def popen(argv, **kw):
        procs.append(argv)
        return SimpleNamespace(poll=lambda: None)

    daemon._gate_popen = popen
    daemon._gate_run_on_host = lambda cfg, script: SimpleNamespace(returncode=0)
    return daemon, procs


def test_row5_gate_sync_starts_no_copy_back_after_pull(tmp_path):
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, NAME, FINISHED)
    assert rig.pull() == [NAME]
    daemon, procs = _gate_sync_daemon(rig)
    daemon.gate_sync_pass()
    assert procs == []


def test_row5_sanity_without_the_laptop_record_gate_sync_copies_back(tmp_path):
    # the laptop record is what stops the copy back: the same PC folder with only the pc record starts one
    rig = Rig(tmp_path)
    (rig.pc_dir / NAME).mkdir(parents=True)
    (rig.pc_dir / NAME / "results.json").write_text("[]", encoding="utf-8")
    gates.record_gate("pc", NAME, rig.gates)
    daemon, procs = _gate_sync_daemon(rig)
    daemon.gate_sync_pass()
    assert len(procs) == 1


@pytest.mark.parametrize("name", ["20261019-0900-week-20261019", "20261019-0900-warn-20261019"])
def test_row6_names_outside_gate_dir_re_are_ignored(tmp_path, name):
    assert not gates.GATE_DIR_RE.match(name)
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, name, FINISHED)
    assert rig.pull() == []
    assert rig.laptop.fetched == []
    assert not (rig.pc_dir / name).exists()


def test_row7_laptop_host_or_no_artifacts_root_does_nothing(tmp_path):
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, NAME, FINISHED)
    assert pull.gate_pull_pass(_pull_daemon(rig, host="laptop")) == []
    assert rig.laptop.calls == 0
    assert pull.gate_pull_pass(_pull_daemon(rig, host="pc", artifacts=None)) == []
    assert rig.laptop.calls == 0
    assert not rig.pc_dir.exists()


@pytest.mark.parametrize("age, copied", [(10, False), (200, True)])
def test_settle_finished_folder_touched_recently_is_not_taken(tmp_path, age, copied):
    # benchmark.py rewrites results.json and report.md after the last row and again at its end (:1686-1687):
    # a marker that reads true 10 s after a write is not yet the end of the run
    assert pull.GATE_PULL_SETTLE_SECONDS == 180
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, NAME, FINISHED, age=age)
    assert rig.pull() == ([NAME] if copied else [])
    assert (rig.pc_dir / NAME).exists() == copied
    assert gates.gates_present("pc", rig.gates) == ({NAME} if copied else set())
    assert gates.gates_present("laptop", rig.gates) == ({NAME} if copied else set())


def test_settle_unsettled_folder_is_taken_by_the_pass_after_it_settles(tmp_path):
    rig = Rig(tmp_path)
    folder = _folder(rig.laptop.root, NAME, FINISHED, age=10)
    assert rig.pull() == []
    _age(folder, 200)
    assert rig.pull() == [NAME]
    assert _tree(rig.pc_dir / NAME) == _tree(rig.laptop.root / NAME)


def test_record_failing_after_the_rename_is_healed_by_the_next_pass(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    _folder(rig.laptop.root, NAME, FINISHED)
    real_record = gates.record_gate

    def laptop_record_fails(host, name, path=None):
        if host == "laptop":
            raise OSError("disk full")
        return real_record(host, name, path)

    monkeypatch.setattr(gates, "record_gate", laptop_record_fails)
    assert rig.pull() == []                       # the rename landed; the record did not
    assert (rig.pc_dir / NAME).is_dir()
    assert gates.gates_present("pc", rig.gates) == {NAME}
    assert gates.gates_present("laptop", rig.gates) == set()
    assert any("recording" in line for line in rig.logs)

    monkeypatch.setattr(gates, "record_gate", real_record)
    assert rig.pull() == []                       # healed: recorded, not copied a second time
    assert gates.gates_present("laptop", rig.gates) == {NAME}
    assert rig.laptop.fetched == [NAME]
    assert _tree(rig.pc_dir / NAME) == _tree(rig.laptop.root / NAME)
