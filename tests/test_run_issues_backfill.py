"""`runs.py run-issues --backfill` (issue #164, unit 3): Run issues for whole-set jobs that ended earlier. No gh, no PoB."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "run_issue"
SET_CMD = "py -3.12 scripts/benchmark.py --set smoke --seed 7 --seeds 3 --gear loot --tag x"
SLUG_CMD = "py -3.12 scripts/benchmark.py --slugs a b --gear loot"


class FakeGh:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, list[str]]] = []
        self.attached: list[tuple[int, int]] = []

    def create_issue(self, title: str, body: str, labels: list[str]) -> int | None:
        self.created.append((title, body, list(labels)))
        return 900 + len(self.created)

    def add_sub_issue(self, parent: int, child: int) -> bool:
        self.attached.append((parent, child))
        return True


def _fixture_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "jobs.jsonl")
    runs_dirs = sorted(p for p in FIXTURES.iterdir() if p.is_dir())
    assert len(runs_dirs) == 3
    for i, run_dir in enumerate(runs_dirs):
        job = store.submit(host="pc", priority="P1", tag=f"whole{i}", cmd=SET_CMD)
        store.start(job.id, run_dir=str(run_dir))
        store.end(job.id, rc=0, run_dir=str(run_dir))
    for i in range(2):
        job = store.submit(host="pc", priority="P1", tag=f"slugs{i}", cmd=SLUG_CMD)
        store.start(job.id, run_dir=str(runs_dirs[0]))
        store.end(job.id, rc=0, run_dir=str(runs_dirs[0]))
    return store


def _daemon(store: Store, gh: FakeGh):
    return daemon_mod.Daemon(store, host="pc", gh=gh, snapshots=False, archive=False,
                             log=lambda m: None, run_issue_parent=404)


def test_164e_backfill_creates_one_issue_per_whole_set_run_and_a_rerun_creates_none(tmp_path: Path, capsys) -> None:
    store, gh = _fixture_store(tmp_path), FakeGh()
    assert runs.cmd_run_issues(store, ["--backfill"], daemon=_daemon(store, gh)) == 0
    assert len(gh.created) == 3
    assert all(labels == ["needs-triage", "area:builds"] for _, _, labels in gh.created)
    assert gh.attached == [(404, 901), (404, 902), (404, 903)]
    assert sorted(j.run_issue for j in store.jobs() if j.run_issue) == [901, 902, 903]
    assert sum(1 for line in capsys.readouterr().out.splitlines() if "#90" in line) == 3

    assert runs.cmd_run_issues(store, ["--backfill"], daemon=_daemon(store, gh)) == 0
    assert len(gh.created) == 3


def test_164e_dry_run_creates_nothing(tmp_path: Path, capsys) -> None:
    store, gh = _fixture_store(tmp_path), FakeGh()
    assert runs.cmd_run_issues(store, ["--backfill", "--dry-run"], daemon=_daemon(store, gh)) == 0
    assert gh.created == [] and gh.attached == []
    assert all(j.run_issue is None for j in store.jobs())
    assert capsys.readouterr().out.count("would create") >= 3


def test_164e_a_gone_snapshot_falls_back_to_artifacts_benchmark(tmp_path: Path) -> None:
    store, gh = Store(tmp_path / "jobs.jsonl"), FakeGh()
    name = "20261001-0100-filler-smoke-loot-s7"
    gone, nowhere = str(tmp_path / "snap" / name), str(tmp_path / "snap" / "no-such-run")
    job = store.submit(host="pc", priority="P1", tag="gone", cmd=SET_CMD)
    store.start(job.id, run_dir=gone)
    store.end(job.id, rc=0, run_dir=gone)
    lost = store.submit(host="pc", priority="P1", tag="lost", cmd=SET_CMD)
    store.start(lost.id, run_dir=nowhere)
    store.end(lost.id, rc=0, run_dir=nowhere)

    assert runs.cmd_run_issues(store, ["--backfill"], daemon=_daemon(store, gh), benchmark_dir=FIXTURES) == 0
    assert len(gh.created) == 1 and name in gh.created[0][0]
    assert store.get(job.id).run_issue == 901 and store.get(lost.id).run_issue is None


def test_164e_the_control_run_falls_back_too(tmp_path: Path) -> None:
    store, gh = Store(tmp_path / "jobs.jsonl"), FakeGh()
    old, new = "20260929-0100-filler-smoke-loot-s7", "20261001-0100-filler-smoke-loot-s7"
    for name in (old, new):
        gone = str(tmp_path / "snap" / name)
        job = store.submit(host="pc", priority="P1", tag=name, cmd=SET_CMD)
        store.start(job.id, run_dir=gone)
        store.end(job.id, rc=0, run_dir=gone)
    daemon = _daemon(store, gh)
    daemon.benchmark_dir = FIXTURES
    newest = max(store.jobs(), key=lambda j: j.end_ts)
    _, body = daemon.run_issue_text(newest)
    assert f"Compare with `{FIXTURES / old}`" in body
