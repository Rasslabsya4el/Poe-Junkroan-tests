"""#862 rule 3 (unit 3): `job_failed` with followers and `held_by_failed_predecessor` end in an outcome in code.

No PoB, no network: the keymaster launcher, gh and the label step are fakes; the job store is real.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import store as store_module  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from test_runs_anomalies import make_guard  # noqa: E402
from test_runs_daemon import make_daemon  # noqa: E402

MISSING_TAIL = "python.exe: can't open file 'repo/scripts/new_bench.py': [Errno 2] No such file or directory\n"
GH_FLAKE_TAIL = ("error connecting to api.github.com\n"
                 "check your internet connection or https://githubstatus.com\n")
HEAD = "0150ac84deadbeef"


def _records(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Rig:
    """One guard on a real store: fake clock, a recording gh, a counting label step."""

    def __init__(self, tmp_path: Path, *, issue: int | None = 839) -> None:
        (tmp_path / "d").mkdir()
        self.now = [1000.0]
        self.comments: list[tuple[int, str, float]] = []
        self.labels: list[int] = []
        self.daemon, self.store, _ = make_daemon(tmp_path / "d")
        self.daemon._host_head = lambda: HEAD
        self.guard, self.launcher = make_guard(tmp_path, clock=lambda: self.now[0])
        self.guard.chain_store = self.store
        self.guard.issue_commenter = self._comment
        self.guard.issue_labeler = self.labels.append
        self.guard.missing_script_line = self.daemon._missing_script_line
        self.out = tmp_path / "pred.out"
        self.issue = issue
        self.pred = self.store.submit(host="pc", priority="P2", tag="pred", cmd="python scripts/new_bench.py",
                                      issue=issue)
        self.followers = [
            self.store.submit(host="pc", priority="P2", tag=f"f{n}", cmd=f"echo {n}", issue=issue,
                              after=[self.pred.id])
            for n in (1, 2)]

    def _comment(self, issue: int, body: str) -> bool:
        self.comments.append((issue, body, self.now[0]))
        return True

    def run_pred(self, *, rc: int, tail: str, seconds: float = 10.0) -> None:
        """Start and end the predecessor; its recorded start/end are ``seconds`` apart.

        The store stamps both records itself (`store._now_iso`), so the stamps are fixed here, one second past
        every record already in the log. The log is only appended to: rewriting it in place would fool the
        store's fold cache (`store._fold_all`, a same-size rewrite in one mtime tick keeps its stamp).
        """

        self.out.write_text(tail, encoding="utf-8")
        newest = max(datetime.fromisoformat(r["ts"]) for r in _records(self.store.path))
        start = newest + timedelta(seconds=1)
        stamps = iter([start, start + timedelta(seconds=seconds)])
        with patch.object(store_module, "_now_iso", lambda: next(stamps).isoformat(timespec="microseconds")):
            self.store.start(self.pred.id, out=str(self.out), pid=1)
            self.store.end(self.pred.id, rc=rc, out=str(self.out))

    def tick(self, *, ended: bool = True, held: bool = True) -> list:
        """One daemon-like call: this tick's ended job and the blocked followers, as `tick` passes them."""

        self.now[0] += 10.0
        pred = self.store.get(self.pred.id)
        blocked = [(self.store.get(f.id), pred) for f in self.followers
                   if self.store.get(f.id).state == "queued"] if held else []
        return self.guard.check(ended_jobs=[pred] if ended else [], held=blocked)

    def state(self, job_id: str) -> str:
        return self.store.get(job_id).state


def test_862_12_26_case_missing_script_cancels_the_chain_and_tells_the_ticket(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run_pred(rc=2, tail=MISSING_TAIL, seconds=10.0)
    failed_at = rig.now[0]

    rig.tick()

    states = [rig.state(f.id) for f in rig.followers]
    print(f"followers: {states}; comments {len(rig.comments)}; label step {len(rig.labels)}; "
          f"keymaster starts {len(rig.launcher.started)}")
    assert states == ["cancelled", "cancelled"]
    assert [j for j in rig.store.jobs() if j.state == "queued"] == []
    assert len(rig.comments) == 1
    issue, body, at = rig.comments[0]
    assert issue == 839
    assert all(f.id in body for f in rig.followers)
    assert "rc 2 after 10 s" in body
    assert f"the script does not exist on this host at {HEAD[:12]}" in body
    assert "Cancelled 2 follower(s)" in body
    assert rig.labels == [839]
    assert rig.launcher.started == []
    assert rig.store.get(rig.followers[0].id).reason == f"predecessor {rig.pred.id} failed"
    assert at - failed_at <= 300.0          # (e) one tick, in the test's clock
    print(f"failure -> comment: {at - failed_at} s in the test clock")


def test_862_run_pred_only_appends_to_the_log_so_the_store_sees_the_seconds(tmp_path: Path) -> None:
    """The rig gives the predecessor its start and end through the store's own clock; it never rewrites the log.

    The store's fold cache (`store.py` `_fold_all`) takes an unchanged (size, mtime_ns) as an unchanged log. A
    same-size in-place rewrite inside one mtime tick keeps that stamp: the store then answers the old start ts and
    the comment says "rc 2 after 0 s" (var/agentops/full_run/7dd00145.out).
    """
    rig = Rig(tmp_path)
    before = rig.store.path.read_bytes()
    rig.run_pred(rc=2, tail=MISSING_TAIL, seconds=10.0)
    assert rig.store.path.read_bytes().startswith(before)
    job = rig.store.get(rig.pred.id)
    assert (datetime.fromisoformat(job.end_ts) - datetime.fromisoformat(job.start_ts)).total_seconds() == 10.0


def test_862_a_second_tick_adds_nothing(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run_pred(rc=2, tail=MISSING_TAIL)
    rig.tick()
    rig.tick()
    assert len(rig.comments) == 1 and rig.labels == [839] and rig.launcher.started == []


def test_862_missing_script_is_never_requeued_even_when_the_tail_also_shows_a_flake(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run_pred(rc=2, tail=GH_FLAKE_TAIL + MISSING_TAIL)
    rig.tick()
    assert rig.state(rig.pred.id) == "failed"
    assert [rig.state(f.id) for f in rig.followers] == ["cancelled", "cancelled"]


def test_862_mechanical_gh_failure_is_requeued_once_then_the_chain_is_cancelled(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run_pred(rc=1, tail=GH_FLAKE_TAIL)

    rig.tick()

    pred = rig.store.get(rig.pred.id)
    assert pred.state == "queued"                          # requeued: the same id, its followers follow it
    assert [rig.state(f.id) for f in rig.followers] == ["queued", "queued"]
    assert all(rig.store.get(f.id).after == (rig.pred.id,) for f in rig.followers)
    assert len(rig.comments) == 1 and "Requeued once" in rig.comments[0][1]
    assert all(f.id in rig.comments[0][1] for f in rig.followers)
    assert rig.labels == [] and rig.launcher.started == []
    print(f"first failure: pred {pred.state}, followers queued 2/2, comments 1, requeues 1")

    rig.run_pred(rc=1, tail=GH_FLAKE_TAIL)               # the requeued job fails the same way
    assert rig.store.get(rig.pred.id).attempts == 2
    rig.tick()

    assert rig.state(rig.pred.id) == "failed"              # never a second requeue
    assert [rig.state(f.id) for f in rig.followers] == ["cancelled", "cancelled"]
    assert len(rig.comments) == 2 and "Cancelled 2 follower(s)" in rig.comments[1][1]
    assert rig.labels == [839] and rig.launcher.started == []
    print("second failure: pred failed, followers cancelled 2/2, comments 2, label step 1, keymaster starts 0")


def test_862_a_job_with_requeued_from_is_never_requeued(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    copy = rig.store.submit(host="pc", priority="P2", tag="copy", cmd="echo c", requeued_from="j-other")
    rig.store.submit(host="pc", priority="P2", tag="g1", cmd="echo g", after=[copy.id])
    rig.pred = copy
    rig.followers = [j for j in rig.store.jobs() if copy.id in j.after]
    rig.run_pred(rc=1, tail=GH_FLAKE_TAIL)
    rig.tick()
    assert rig.state(copy.id) == "failed" and [rig.state(f.id) for f in rig.followers] == ["cancelled"]


def test_862_the_chain_is_cancelled_recursively(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    deep = rig.store.submit(host="pc", priority="P2", tag="deep", cmd="echo d", after=[rig.followers[0].id])
    rig.run_pred(rc=2, tail="Traceback: boom\n")
    rig.tick()
    assert rig.state(deep.id) == "cancelled"
    assert [j for j in rig.store.jobs() if j.state == "queued"] == []
    assert all(j.id in rig.comments[0][1] for j in (*rig.followers, deep))   # the comment names the whole chain


def test_862_held_by_failed_predecessor_alone_has_the_same_outcome(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run_pred(rc=2, tail=MISSING_TAIL)
    rig.tick(ended=False)                                  # only the held anomalies fire
    assert [rig.state(f.id) for f in rig.followers] == ["cancelled", "cancelled"]
    assert len(rig.comments) == 1 and rig.labels == [839] and rig.launcher.started == []


def test_862_both_anomalies_of_one_chain_in_one_tick_give_one_comment(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run_pred(rc=2, tail=MISSING_TAIL)
    detected = rig.guard.detect(ended_jobs=[rig.store.get(rig.pred.id)],
                                held=[(rig.store.get(f.id), rig.store.get(rig.pred.id)) for f in rig.followers])
    assert sorted(a.kind for a in detected) == ["held_by_failed_predecessor"] * 2 + ["job_failed"]
    rig.tick()
    print(f"3 anomalies of one chain: comments {len(rig.comments)}, label step {len(rig.labels)}")
    assert len(rig.comments) == 1 and rig.labels == [839] and rig.launcher.started == []


def test_862_job_failed_without_followers_keeps_the_keymaster_path(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    for follower in rig.followers:
        rig.store.cancel(follower.id)
    rig.run_pred(rc=2, tail="Traceback: boom\n")
    started = rig.tick(held=False)
    assert [a.kind for a in started] == ["job_failed"]
    assert len(rig.launcher.started) == 1
    assert rig.comments == [] and rig.labels == []


def test_862_a_ticketless_job_is_closed_without_comment_or_label(tmp_path: Path) -> None:
    rig = Rig(tmp_path, issue=None)
    rig.run_pred(rc=2, tail=MISSING_TAIL)
    rig.tick()
    assert [rig.state(f.id) for f in rig.followers] == ["cancelled", "cancelled"]
    assert rig.comments == [] and rig.labels == [] and rig.launcher.started == []


def test_862_a_lost_laptop_link_still_opens_no_session_and_no_comment(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    (tmp_path / "g").mkdir()
    guard, launcher = make_guard(tmp_path / "g", host_prober=lambda: False, clock=lambda: rig.now[0])
    guard.chain_store = rig.store
    guard.issue_commenter = rig._comment
    for _ in range(4):
        rig.now[0] += 400.0
        guard.check()
    assert launcher.started == [] and rig.comments == []
