"""#51 unit 4: the improvement loop's one transaction per attempt, on fakes (no PoB, no pipeline)."""

from __future__ import annotations

import random

import pytest

from junkroan.optimizer.improvement_loop import AttemptTools, _LoopState, accepts
from junkroan.optimizer.objective import Score
from junkroan.pob.headless_runtime_worker import WorkerContractError
from junkroan.pob.host_runtime import PoBHeadlessHostContractError

START = Score(neg_violation=0.0, value=100.0)
BETTER = Score(neg_violation=0.0, value=120.0)
WORSE = Score(neg_violation=0.0, value=90.0)
MARK = object()


class _Rig:
    """A call transcript: every callable the transaction gets appends one entry."""

    def __init__(self, *, lanes_fresh: bool, scores: list[Score], min_gain: float = 0.005) -> None:
        self.calls: list[tuple] = []
        self.rows: list[dict] = []
        self.dropped: list[dict] = []
        self.logs: list[str] = []
        self.scores = list(scores)
        self.fail_restore: Exception | None = None
        self.st = _LoopState(cur=START, lanes_fresh=lanes_fresh, changed_since_picks=False,
                             changed_since_aura_levels=False, changed_since_lanes=False)
        self.lanes_fresh = lanes_fresh
        self.tools = AttemptTools(
            st=self.st, snapshot=self._snapshot, restore=self._restore, rejudge=lambda: self.calls.append(("rejudge",)),
            restore_mark=lambda mark, only: self.calls.append(("restore_mark", mark, only)), score=self._score,
            record=self._record, note_drop=self.dropped.append, log=self.logs.append, min_gain=min_gain)

    def _snapshot(self) -> dict:
        self.calls.append(("snapshot",))
        return {"xml": "xml-before", "lanes_fresh": self.lanes_fresh, "judging": MARK, "cur": self.st.cur}

    def _restore(self, state, *, keep_rejections: bool = False) -> None:
        self.calls.append(("restore", state["xml"], keep_rejections))
        if self.fail_restore is not None:
            raise self.fail_restore
        self.st.cur = state["cur"]

    def _score(self) -> Score:
        self.calls.append(("score",))
        return self.scores.pop(0)

    def _record(self, name, started, before, after, *, kept, reverted_by_judge=False, pass_number=None) -> None:
        self.rows.append({"name": name, "before": before, "after": after, "kept": kept, "reverted_by_judge": reverted_by_judge})

    def undo(self) -> None:
        self.calls.append(("undo",))


def test_enter_takes_the_snapshot_first():
    rig = _Rig(lanes_fresh=False, scores=[])
    with rig.tools.attempt("loop pass 1 x", ledger_name="x", started=1.0) as attempt:
        assert rig.calls == [("snapshot",)]
        assert attempt.state["xml"] == "xml-before"
    assert rig.calls == [("snapshot",)]  # nothing else on a clean exit: no judge, no restore
    assert not attempt.dropped and rig.rows == [] and rig.dropped == []


def test_keep_path_exact():
    rig = _Rig(lanes_fresh=False, scores=[BETTER])
    with rig.tools.attempt("loop pass 1 tree refine", ledger_name="refine", started=1.0) as attempt:
        assert attempt.judge_exact() is True
    assert rig.calls == [("snapshot",), ("rejudge",), ("score",)]
    st = rig.st
    assert (st.cur, st.kept_total, st.judged_reverted_total, st.lanes_fresh) == (BETTER, 1, 0, True)
    assert (st.changed_since_picks, st.changed_since_aura_levels, st.changed_since_lanes) == (True, True, True)
    assert rig.rows == [{"name": "refine", "before": START, "after": BETTER, "kept": True, "reverted_by_judge": False}]
    assert rig.logs[0].startswith("loop pass 1 tree refine: 100 (viol -0.000) -> 120 (viol -0.000) kept (")


def test_keep_path_partial_reconfigured_does_not_rejudge():
    rig = _Rig(lanes_fresh=False, scores=[BETTER])
    with rig.tools.attempt("loop pass 1 Helmet", ledger_name="gear Helmet", started=1.0) as attempt:
        assert attempt.judge_partial(rig.undo, "loop pass 1 Helmet after repair", reconfigured=True) is True
    assert rig.calls == [("snapshot",), ("score",)]
    assert rig.rows[0]["name"] == "gear Helmet" and rig.rows[0]["kept"] is True
    assert rig.logs[0].startswith("loop pass 1 Helmet after repair: ")


def test_below_min_gain_is_not_kept():
    rig = _Rig(lanes_fresh=True, scores=[Score(0.0, 100.4), START], min_gain=0.005)
    with rig.tools.attempt("l", ledger_name="refine", started=1.0) as attempt:
        assert attempt.judge_exact() is False
    assert rig.st.kept_total == 0 and rig.st.judged_reverted_total == 1


def test_exact_revert_stale_lanes():
    rig = _Rig(lanes_fresh=False, scores=[WORSE, START])
    with rig.tools.attempt("loop pass 1 tree path swaps", ledger_name="path swaps", started=1.0) as attempt:
        assert attempt.judge_exact() is False
    # the move's lanes are derived once for the verdict; the exact restore needs no second derivation
    assert rig.calls == [("snapshot",), ("rejudge",), ("score",), ("restore", "xml-before", True),
                         ("restore_mark", MARK, ("castability",)), ("score",)]
    st = rig.st
    assert (st.cur, st.kept_total, st.judged_reverted_total) == (START, 0, 1)
    assert st.lanes_fresh is True  # the judge sets it before the verdict, the exact restore does not touch it
    assert rig.rows == [{"name": "path swaps", "before": START, "after": START, "kept": False, "reverted_by_judge": True}]
    assert rig.logs[0].startswith("loop pass 1 tree path swaps: 90 (viol -0.000) vs 100 (viol -0.000), reverted (")


def test_exact_revert_fresh_lanes_restores_the_whole_mark():
    rig = _Rig(lanes_fresh=True, scores=[WORSE, START])
    with rig.tools.attempt("l", ledger_name="refine", started=1.0) as attempt:
        assert attempt.judge_exact() is False
    assert rig.calls == [("snapshot",), ("rejudge",), ("score",), ("restore", "xml-before", True),
                         ("restore_mark", MARK, None), ("score",)]


def test_partial_revert_stale_lanes_rejudges_after_the_undo():
    rig = _Rig(lanes_fresh=False, scores=[WORSE, START])
    with rig.tools.attempt("loop pass 1 kick tree (draw 1 of 3)", ledger_name="kick tree", started=1.0) as attempt:
        assert attempt.judge_partial(rig.undo) is False
    assert rig.calls == [("snapshot",), ("rejudge",), ("score",), ("undo",),
                         ("restore_mark", MARK, ("castability",)), ("rejudge",), ("score",)]
    assert rig.rows == [{"name": "kick tree", "before": START, "after": START, "kept": False, "reverted_by_judge": True}]


def test_partial_revert_stale_lanes_reconfigured_move_rejudges_once():
    rig = _Rig(lanes_fresh=False, scores=[WORSE, START])
    with rig.tools.attempt("l", ledger_name="kick joint", started=1.0) as attempt:
        assert attempt.judge_partial(rig.undo, "l ruined", reconfigured=True) is False
    assert rig.calls == [("snapshot",), ("score",), ("undo",), ("restore_mark", MARK, ("castability",)), ("rejudge",), ("score",)]


def test_partial_revert_fresh_lanes_does_not_rejudge():
    rig = _Rig(lanes_fresh=True, scores=[WORSE, START])
    with rig.tools.attempt("l", ledger_name="gear Helmet", started=1.0) as attempt:
        assert attempt.judge_partial(rig.undo, reconfigured=True) is False
    assert rig.calls == [("snapshot",), ("score",), ("undo",), ("restore_mark", MARK, None), ("score",)]
    rig = _Rig(lanes_fresh=True, scores=[WORSE, START])
    with rig.tools.attempt("l", ledger_name="kick tree", started=1.0) as attempt:
        assert attempt.judge_partial(rig.undo) is False
    assert rig.calls == [("snapshot",), ("rejudge",), ("score",), ("undo",), ("restore_mark", MARK, None), ("score",)]


@pytest.mark.parametrize("error", [PoBHeadlessHostContractError("worker_crashed", "boom"), WorkerContractError("bad_command", "boom")])
def test_contract_error_drops_the_move(error):
    rig = _Rig(lanes_fresh=False, scores=[])
    with rig.tools.attempt("loop pass 2 Helmet", ledger_name="gear Helmet", started=5.0) as attempt:
        rig.st.cur = BETTER  # the loop's cur at the exception (a kept replay step moved it after the snapshot)
        raise error
    assert attempt.dropped is True
    # the full restore, default keep_rejections: a contract error is not a judged revert
    assert rig.calls == [("snapshot",), ("restore", "xml-before", False)]
    assert rig.dropped == [{"move": "loop pass 2 Helmet", "exception": type(error).__name__,
                            "failure_state": error.failure_state, "message": "boom"}]
    assert rig.logs == [f"loop pass 2 Helmet: dropped after {type(error).__name__} ({error.failure_state}): boom"]
    # quirk 12: no captured `before` -> the cur at the exception, read before the restore; `after` is the restored cur
    assert rig.rows == [{"name": "gear Helmet", "before": BETTER, "after": START, "kept": False, "reverted_by_judge": False}]


def test_drop_row_carries_the_captured_before():
    rig = _Rig(lanes_fresh=False, scores=[])
    captured = Score(0.0, 77.0)
    with rig.tools.attempt("loop pass 1 picks", ledger_name="picks", started=5.0, before=captured):
        rig.st.cur = BETTER
        raise WorkerContractError("x", "boom")
    assert rig.rows[0]["before"] == captured and rig.rows[0]["after"] == START


def test_drop_without_a_ledger_name_uses_the_label():
    rig = _Rig(lanes_fresh=False, scores=[])
    with rig.tools.attempt("loop pass 1 odd", started=5.0):
        raise WorkerContractError("x", "boom")
    assert rig.rows[0]["name"] == "loop pass 1 odd"


def test_other_errors_propagate_without_a_restore():
    rig = _Rig(lanes_fresh=False, scores=[])
    with pytest.raises(KeyError):
        with rig.tools.attempt("l", ledger_name="refine", started=1.0):
            raise KeyError("not a contract error")
    assert rig.calls == [("snapshot",)] and rig.dropped == [] and rig.rows == []


def test_restore_failure_escapes_and_writes_no_row():
    rig = _Rig(lanes_fresh=False, scores=[])
    rig.fail_restore = RuntimeError("load_xml failed")
    with pytest.raises(RuntimeError, match="load_xml failed") as raised:
        with rig.tools.attempt("l", ledger_name="refine", started=1.0):
            raise PoBHeadlessHostContractError("worker_crashed", "boom")
    assert isinstance(raised.value.__context__, PoBHeadlessHostContractError)
    assert rig.dropped == [] and rig.rows == [] and rig.logs == []


def test_unarmed_attempt_lets_a_precheck_error_through_then_drops_after_arm():
    rig = _Rig(lanes_fresh=False, scores=[])
    with pytest.raises(PoBHeadlessHostContractError):
        with rig.tools.attempt("l", ledger_name="weapon base", started=1.0, armed=False):
            raise PoBHeadlessHostContractError("worker_crashed", "pre-check")  # the fingerprint of quirk 9
    assert rig.calls == [("snapshot",)] and rig.dropped == []
    rig = _Rig(lanes_fresh=False, scores=[])
    with rig.tools.attempt("l", ledger_name="weapon base", started=1.0, armed=False) as attempt:
        attempt.arm()
        raise PoBHeadlessHostContractError("worker_crashed", "in the move")
    assert attempt.dropped is True and len(rig.dropped) == 1


def test_started_defaults_to_the_clock_after_the_snapshot():
    rig = _Rig(lanes_fresh=False, scores=[])
    with rig.tools.attempt("l", ledger_name="lanes") as attempt:
        assert isinstance(attempt.started, float)


def test_accepts_is_the_one_rule():
    assert accepts(Score(0.0, 101.0), Score(0.0, 100.0), min_gain=0.005) is True
    assert accepts(Score(0.0, 100.4), Score(0.0, 100.0), min_gain=0.005) is False  # feasible: must grow by min_gain
    # #553: the loop prices violation and value together (45 against 400); the floors order puts feasibility first
    assert accepts(Score(-0.1, 50.0), Score(-0.2, 500.0), min_gain=0.005) is False
    assert accepts(Score(-0.1, 50.0), Score(-0.2, 500.0), min_gain=0.005, order="floors") is True
    assert accepts(Score(0.0, 0.0), Score(0.0, 100.0), min_gain=0.0) is False  # a dead build never beats a live one
