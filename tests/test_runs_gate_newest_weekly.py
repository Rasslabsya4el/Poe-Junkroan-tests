"""#642 unit 6, row 7: the newest gate is the newest of the old `-gate-` folders and the weekly core run folders
(`<date>-<time>-P<prio>-core-<n>`, named by `run_name.derive_name` through `benchmark.py` `--tag`), and `gate_sync` copies it.
Pure: fake Popen / run_on_host / clock; no PoB, no ssh."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_runs_gate_copy import BENCH, CFG, Rig  # noqa: E402

from junkroan.runs.gates import newest_gate  # noqa: E402

OLD_GATE = "20261005-1220-gate-20261005"
WEEKLY = "20261013-0101-P2-core-3"


def _mkdirs(bench: Path, *names: str) -> None:
    for n in names:
        (bench / n).mkdir(parents=True)
        (bench / n / "a.txt").write_text("x" * 100, encoding="utf-8")


def test_newest_gate_takes_the_weekly_core_folder(tmp_path):
    _mkdirs(tmp_path / "benchmark", OLD_GATE, WEEKLY)
    assert newest_gate(tmp_path) == WEEKLY


def test_newest_gate_still_takes_a_newer_old_gate_folder(tmp_path):
    _mkdirs(tmp_path / "benchmark", "20261001-0100-P2-core-2", OLD_GATE)
    assert newest_gate(tmp_path) == OLD_GATE


def test_newest_gate_ignores_other_weekly_like_names(tmp_path):
    _mkdirs(tmp_path / "benchmark", OLD_GATE, "20261020-1000-P2-#941", "20261021-1000-warn-20261020")
    assert newest_gate(tmp_path) == OLD_GATE


def test_gate_sync_copies_the_weekly_core_folder(tmp_path):
    rig = Rig(tmp_path, with_gate=False)
    _mkdirs(rig.artifacts / "benchmark", OLD_GATE, WEEKLY)
    rig.daemon.gate_sync_pass()
    assert len(rig.procs) == 1
    argv = rig.procs[0].argv
    assert argv[-2] == str(rig.artifacts / "benchmark" / WEEKLY)
    assert argv[-1] == f"laptop:{BENCH.replace(chr(92), '/')}/{WEEKLY}.partial"
    assert f"{BENCH}\\{WEEKLY}.partial" in rig.scripts[0]
    assert CFG["ssh"] == "laptop"
