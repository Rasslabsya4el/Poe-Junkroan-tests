"""#1124 unit 4: a candidate node that carries a marked red line is worth its mark's PoB delta in the fast trial.

PoB-free tests use a fake PoB (the patterns of tests/test_trace_greedy_path.py). The one `pob` test at the end runs a
real fast trial with a probe mark and shows CombinedDPS differs from the same trial without it.
"""

from __future__ import annotations

from types import SimpleNamespace

import re

import pytest

from junkroan.optimizer import trace
from junkroan.optimizer.red_line_marks import RedLineMarks
from junkroan.optimizer.trace import TRACE, mark_class
from junkroan.optimizer.tree_optimizer import TreeOptimizer
from junkroan.pob.session import PobSession

LINE = "Probe line on a notable"
LINE_OPT = "Probe line on the optimistic lane only"
LINE_ZERO = "Probe line with a zero record"
MASTERY_LINE = "Probe line on a mastery effect"
MARK = "100% increased Damage"


def _record(line: str, boss: list[str], optimistic: list[str], **extra) -> dict:
    return {
        "line": line, "surfaces": ["notable"], "sources": ["probe"], "group": "probe", "kind": "custom_mod",
        "boss_lane": boss, "optimistic_lane": optimistic, "zero_reason": "" if (boss or optimistic) else "PoB reads all of it",
        "why": "probe", "partial_part": "all", **extra,
    }


def _marks() -> RedLineMarks:
    return RedLineMarks([
        _record(LINE, [MARK], [MARK]),
        _record(LINE_OPT, [], ["50% increased Damage"]),
        _record(LINE_ZERO, [], []),
        _record(MASTERY_LINE, ["20% increased Damage"], ["20% increased Damage"]),
    ])


NODES = {
    10: SimpleNamespace(node_id=10, kind="notable", name="Marked", stats=(LINE,), mastery_effects=()),
    11: SimpleNamespace(node_id=11, kind="notable", name="Twin", stats=(LINE,), mastery_effects=()),
    12: SimpleNamespace(node_id=12, kind="notable", name="OptOnly", stats=(LINE_OPT,), mastery_effects=()),
    13: SimpleNamespace(node_id=13, kind="notable", name="Zero", stats=(LINE_ZERO,), mastery_effects=()),
    14: SimpleNamespace(node_id=14, kind="normal", name="Small", stats=(LINE,), mastery_effects=()),
    15: SimpleNamespace(node_id=15, kind="notable", name="Plain", stats=("+10 to Strength",), mastery_effects=()),
    16: SimpleNamespace(node_id=16, kind="mastery", name="Mastery", stats=(), mastery_effects=((77, (MASTERY_LINE,)), (78, ("+5 to Dexterity",)))),
    17: SimpleNamespace(node_id=17, kind="notable", name="TwoLine", stats=("+1 to Strength\n" + LINE,), mastery_effects=()),
}


class _Adapter:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def trial_stats(self, handle, payload):
        self.payloads.append(payload)
        return [{"ok": True, "stats": {"CombinedDPS": 1.0}, "added_node_ids": t["add"]} for t in payload["trials"]]


class _Pob:
    """The fake PoB the optimizer talks to: a real PobSession payload builder over a fake adapter."""

    def __init__(self, allocated=(), masteries=()) -> None:
        self.adapter = _Adapter()
        self.session = PobSession.__new__(PobSession)
        self.session._adapter, self.session._handle = self.adapter, object()
        self.session.fulldps_shortcut, self.session.mean_parts = False, ()
        self.allocated, self.masteries = list(allocated), list(masteries)
        self.stats_calls: list[tuple] = []

    def tree_light(self):
        return {"class_id": "1", "user_allocated_node_ids": list(self.allocated), "mastery_effect_ids": list(self.masteries)}

    def trial_stats(self, trials, keys, mode="fast"):
        return self.session.trial_stats(trials, keys, mode=mode)

    def stats(self, keys):
        self.stats_calls.append(tuple(keys))
        return {k: 4.0 for k in keys}


@pytest.fixture(autouse=True)
def _trace(monkeypatch):
    monkeypatch.setattr(trace, "default_node_kind", lambda nid: "unknown")
    TRACE.reset()
    yield
    TRACE.reset()


def _optimizer(pob: _Pob, marks: RedLineMarks | None, lane: str = "boss") -> TreeOptimizer:
    graph = SimpleNamespace(node=lambda nid: NODES.get(int(nid)), class_starts={})
    objective = SimpleNamespace(stat_keys=("CombinedDPS",), describe=lambda: "probe", score=lambda stats: stats)
    opt = TreeOptimizer(pob, objective, graph=graph)
    opt.red_marks = marks
    opt.mark_lane = lane
    return opt


def _measure(opt: TreeOptimizer, *trials: dict) -> list[dict]:
    return opt._measure(list(trials), ("CombinedDPS",), {"CombinedDPS": 1.0})


def _sent(pob: _Pob, batch: int = 0) -> list[dict]:
    return pob.adapter.payloads[batch]["trials"]


def _mark_classes() -> list[str]:
    TRACE.flush("picks")
    return [c for c in TRACE.considered().get("picks", {}) if c.startswith("mark:")]


def test_marked_candidate_sends_the_mark_lines_and_counts_generated_evaluated_once():
    pob = _Pob()
    opt = _optimizer(pob, _marks())
    _measure(opt, {"add": [10], "mastery": {}, "path": [14, 10]})
    sent = _sent(pob)[0]
    assert sent["marks"] == {"add": [MARK], "remove": []}
    assert sent["add"] == [10] and "path" not in sent
    TRACE.flush("picks")
    assert TRACE.considered()["picks"][mark_class(LINE)] == {"generated": 1, "evaluated": 1}


def test_a_normal_node_on_the_path_carries_nothing():
    pob = _Pob()
    _measure(_optimizer(pob, _marks()), {"add": [15], "mastery": {}, "path": [14, 15]})
    assert "marks" not in _sent(pob)[0]


def test_no_marked_line_payload_is_exactly_as_before():
    pob = _Pob()
    _measure(_optimizer(pob, _marks()), {"add": [15], "mastery": {}})
    assert _sent(pob) == [{"add": [15], "remove": [], "mastery": {}, "item": None}]
    assert _mark_classes() == []


def test_no_marks_at_all_payload_is_exactly_as_before_and_pob_is_asked_nothing_extra():
    pob = _Pob(allocated=[11])
    opt = _optimizer(pob, RedLineMarks(()))
    _measure(opt, {"add": [10], "mastery": {}}, {"add": [15], "remove": [11], "mastery": {}})
    assert all(set(t) == {"add", "remove", "mastery", "item"} for t in _sent(pob))
    assert pob.stats_calls == []


def test_a_zero_record_and_a_line_marked_on_the_other_lane_carry_nothing():
    pob = _Pob()
    _measure(_optimizer(pob, _marks(), lane="boss"), {"add": [13], "mastery": {}}, {"add": [12], "mastery": {}})
    assert all("marks" not in t for t in _sent(pob))
    assert _mark_classes() == []
    pob2 = _Pob()
    _measure(_optimizer(pob2, _marks(), lane="optimistic"), {"add": [12], "mastery": {}})
    assert _sent(pob2)[0]["marks"] == {"add": ["50% increased Damage"], "remove": []}


def test_the_memo_does_not_reuse_an_outcome_across_different_marks():
    pob = _Pob()
    opt = _optimizer(pob, _marks())
    trial = {"add": [10], "mastery": {}}
    _measure(opt, trial)
    _measure(opt, trial)
    assert len(pob.adapter.payloads) == 1  # same mark: answered from the memo
    opt.red_marks = RedLineMarks([_record(LINE, ["30% increased Damage"], [])])
    _measure(opt, trial)
    assert len(pob.adapter.payloads) == 2
    assert _sent(pob, 1)[0]["marks"] == {"add": ["30% increased Damage"], "remove": []}


def test_removing_the_only_holder_removes_its_mark_and_a_second_holder_keeps_it():
    pob = _Pob(allocated=[10])
    _measure(_optimizer(pob, _marks()), {"add": [], "remove": [10], "mastery": {}})
    assert _sent(pob)[0]["marks"] == {"add": [], "remove": [MARK]}
    pob2 = _Pob(allocated=[10, 11])
    _measure(_optimizer(pob2, _marks()), {"add": [], "remove": [10], "mastery": {}})
    assert "marks" not in _sent(pob2)[0]


def test_a_line_already_held_by_an_allocated_node_is_not_added_twice():
    pob = _Pob(allocated=[11])
    _measure(_optimizer(pob, _marks()), {"add": [10], "mastery": {}})
    assert "marks" not in _sent(pob)[0]


def test_a_swap_between_two_holders_of_one_line_carries_nothing():
    pob = _Pob(allocated=[11])
    _measure(_optimizer(pob, _marks()), {"add": [10], "remove": [11], "mastery": {}})
    assert "marks" not in _sent(pob)[0]


def test_a_mastery_effect_carries_the_mark_of_the_chosen_effect_only():
    pob = _Pob()
    _measure(_optimizer(pob, _marks()), {"add": [16], "mastery": {16: 77}}, {"add": [16], "mastery": {16: 78}})
    first, second = _sent(pob)
    assert first["marks"] == {"add": ["20% increased Damage"], "remove": []}
    assert "marks" not in second


def test_a_node_stat_line_with_a_newline_is_looked_up_by_its_parts():
    pob = _Pob()
    _measure(_optimizer(pob, _marks()), {"add": [17], "mastery": {}})
    assert _sent(pob)[0]["marks"] == {"add": [MARK], "remove": []}


def test_a_formula_record_reads_its_numbers_from_pob_once_per_state():
    pob = _Pob()
    marks = RedLineMarks([_record(LINE, ["{formula}% increased Damage"], [], formula="Life / 2")])
    _measure(_optimizer(pob, marks), {"add": [10], "mastery": {}}, {"add": [17], "mastery": {}})
    assert [t["marks"] for t in _sent(pob)] == [{"add": ["2% increased Damage"], "remove": []}] * 2
    assert pob.stats_calls == [("Life",)]


# --- the worker half: the Lua that applies a trial's marks (PoB-free: a fake bridge records the chunk) ---------------

class _Bridge:
    def __init__(self) -> None:
        self.chunks: list[str] = []

    def execute(self, chunk: str, nret: int = 1) -> list[str]:
        self.chunks.append(chunk)
        return ["[]"]


def _worker_chunk(trials: list[dict], mode: str = "fast") -> str:
    from junkroan.pob import headless_runtime_worker as worker

    runtime = object.__new__(worker.HeadlessLuaRuntime)
    runtime._bridge = _Bridge()
    runtime.trial_stats({"trials": trials, "keys": ["CombinedDPS"], "mode": mode})
    return runtime._bridge.chunks[-1]


def test_the_worker_forwards_marks_to_the_lua_payload_only_when_a_trial_has_them():
    chunk = _worker_chunk([{"add": [1], "marks": {"add": [MARK], "remove": []}}, {"add": [2]}])
    assert '"marks": {"add": ["100% increased Damage"], "remove": []}' in chunk
    assert chunk.count('"marks"') == 1  # the second trial carries no key at all
    assert '"marks"' not in _worker_chunk([{"add": [2]}])


def test_the_worker_rejects_a_malformed_marks_block():
    from junkroan.pob.headless_runtime_worker import WorkerContractError

    with pytest.raises(WorkerContractError):
        _worker_chunk([{"add": [1], "marks": {"add": "not a list"}}])


def test_the_fast_lua_swaps_the_config_modlist_around_the_calculator_and_puts_it_back_on_error():
    chunk = _worker_chunk([{"add": [1]}])
    swap = chunk.index("build.configTab.modList = ")
    call = chunk.index("calculator_flasked(override, use_full_dps)", swap)
    back = chunk.index("build.configTab.modList = orig_modlist", call)
    assert swap < call < back
    assert chunk.index("pcall(function()") < swap  # the swap is inside the guarded body, the restore after it
    assert back < chunk.index("if not ok then results[i]")
    assert "modLib.parseMod" in chunk and "StripEscapes" in chunk  # the lines are parsed the way ConfigTab:BuildModList does
    assert chunk.count("trial.marks") >= 1


def test_the_swap_is_a_copy_so_the_live_modlist_is_never_edited_in_place():
    chunk = _worker_chunk([{"add": [1]}])
    assert "new('ModList')" in chunk or 'new("ModList")' in chunk
    assert not re.search(r"orig_modlist\s*\[|table\.remove\(\s*orig_modlist", chunk)


def test_the_full_mode_lua_does_not_carry_marks():
    assert "trial.marks" not in _worker_chunk([{"add": [1], "marks": {"add": [MARK], "remove": []}}], mode="full")


# --- the one PoB test: a real fast trial -------------------------------------------------------------------------------

import json
from pathlib import Path

from junkroan.pob.session import decode_import_code

_ROOT = Path(__file__).resolve().parents[1]
_LOCK = json.loads((_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
_RUNTIME = _ROOT / "var" / "cache" / "pob" / _LOCK["tag"] / _LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (_RUNTIME / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {_RUNTIME}")


@pytest.mark.pob
@needs_pob
def test_a_real_fast_trial_takes_its_mark_and_a_trial_without_marks_is_unchanged():
    """Stormbrand reference: the same single-node removal three times. Without marks the stats are the plain trial's and
    the live build is unchanged after; with a held line whose mark is "+100% increased Damage" CombinedDPS rises, the
    trace counts `mark:<line>` generated and evaluated; with the mark removed from a config block that holds it, the
    trial drops it again."""
    from junkroan.optimizer.ramp_inputs import apply_custom_mods

    keys = ("CombinedDPS",)
    held = "Probe held line"
    with PobSession(run_id="test-issue1124-trial", artifacts_root=_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(decode_import_code((_ROOT / "tests" / "fixtures" / "tuadh_329" / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()))
        node = sorted(pob.tree_light()["user_allocated_node_ids"])[0]
        base = pob.stats(keys)["CombinedDPS"]
        plain = pob.trial_stats([{"remove": [node]}], keys, mode="fast")[0]["stats"]["CombinedDPS"]

        TRACE.reset()
        marked = pob.trial_stats([{"remove": [node], "marks": {"add": {held: [MARK]}, "remove": {}}}], keys, mode="fast")[0]["stats"]["CombinedDPS"]
        TRACE.flush("picks")
        counted = TRACE.considered()["picks"][mark_class(held)]
        again = pob.trial_stats([{"remove": [node]}], keys, mode="fast")[0]["stats"]["CombinedDPS"]
        assert pob.stats(keys)["CombinedDPS"] == base  # the live config mod list is back after the marked trial
        assert again == plain  # a trial without marks gives the identical stats, before and after a marked one
        print(f"CombinedDPS plain trial {plain:,.1f} marked {marked:,.1f} (+{marked / plain - 1:.1%})")
        assert marked > plain  # the mark's PoB delta is in the trial
        assert counted["evaluated"] == 1  # `generated` is counted by the optimizer's _measure (the PoB-free tests above), `evaluated` at the PoB boundary

        pob.set_config(bandit="None", pantheon_major="None", pantheon_minor="None", enemy_state={"is_boss": "Pinnacle"},
                       inputs={}, conditional={"inputs": {}}, preserve="numeric")  # a Baseline config set to hold the block
        base = pob.stats(keys)["CombinedDPS"]
        plain = pob.trial_stats([{"remove": [node]}], keys, mode="fast")[0]["stats"]["CombinedDPS"]
        apply_custom_mods(pob, ((MARK, "junkroan: probe block"),))
        with_block = pob.trial_stats([{"remove": [node]}], keys, mode="fast")[0]["stats"]["CombinedDPS"]
        dropped = pob.trial_stats([{"remove": [node], "marks": {"add": {}, "remove": {held: [MARK]}}}], keys, mode="fast")[0]["stats"]["CombinedDPS"]
        assert with_block > plain  # the block is in the live build, so a plain trial has it
        assert dropped == pytest.approx(plain, rel=1e-9)  # the removed mark leaves the what-if without it
        assert pob.stats(keys)["CombinedDPS"] > base  # and the live build keeps the block after the trial that dropped its mark
