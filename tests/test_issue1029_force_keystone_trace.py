"""#1029 unit 2: `benchmark.py --force-keystone` proven by its kind (D113): a search-space rule is shown by the trace
counters at the PoB boundary, a switch that must not touch a plain run is shown by an identical PoB call transcript (D95).

One short build, `cold_dot` seed 4, wishlist gear, `construction_only` (the run ends at the tree rebuild), each run in
its own child process (`python tests/test_issue1029_force_keystone_trace.py <mode> ...`) so no state of one run reaches
the next:

  forced   run_one(force_keystones=["Chaos Inoculation"]) with `StateProbe` between the pipeline and the session.
           (1) Every state PoB evaluates after the skeleton took the keystone holds its node id:
               the state of a `stats` / `calc` call is the session's allocated tree (`tree_light`, read from the live
               build); the state of one `trial_stats` trial is that tree minus the trial's `removed_node_ids` plus its
               `added_node_ids` (PoB's own report of what the trial changed). `evaluated(without keystone) = 0`, and the
               trace counter `node-rm:<id>` (a trial that removes the keystone) is 0 evaluated.
  head / base  run_one WITHOUT the switch, `--record-calls` on, from this commit's `scripts/benchmark.py` and from the
           file at BASE (main just before the switch). (2) The two PoB call transcripts (`recording_pob`, the method and
           the hash of the arguments of every call) are line for line equal. `src/`, `tools/`, `config/` and the other
           scripts are the checkout's own for both sides, which is exactly the comparison while `scripts/benchmark.py` is
           the only file that differs from BASE (checked below; otherwise the test skips).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

SLUG = "cold_dot"
SEED = 4
GEAR = "wishlist"
KEYSTONE = "Chaos Inoculation"
BASE = "a80a5367"  # main right before `--force-keystone` (#1029 unit 1)
RUN_TIMEOUT = 40 * 60  # seconds; a child that runs longer is killed, the test fails (a bounded wait)

EVALUATING = frozenset({"stats", "stats_without_ailment_caps", "active_skill_stats", "calc", "calc_raw"})


class StateProbe:
    """Sits between the pipeline and the session (outermost, transparent) and, for every state PoB evaluates, checks
    whether the allocated tree holds `node_id`. Nothing counts before the skeleton allocated the keystone (`armed`):
    the author's own build is evaluated first, on its own tree. `raw` is the PobSession itself: its `tree_light` is a
    read-only call that no transcript sees."""

    _OWN = frozenset({"_outer", "_raw", "node_id", "armed", "before_armed", "evaluated", "holding", "failed_trials", "missing", "trials_removing_it"})

    def __init__(self, outer, raw, node_id: int) -> None:
        self._outer, self._raw, self.node_id = outer, raw, int(node_id)
        self.armed = False
        self.before_armed = 0
        self.evaluated = 0
        self.holding = 0
        self.failed_trials = 0
        self.missing: list[dict] = []
        self.trials_removing_it = 0

    def __setattr__(self, name: str, value) -> None:  # `pob.mean_parts = ...` lands on the session, as without the probe
        if name in self._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self._outer, name, value)

    def _tree(self) -> set[int]:
        return {int(n) for n in self._raw.tree_light()["user_allocated_node_ids"]}

    def _state(self, call: str, tree: set[int]) -> None:
        if not self.armed:
            self.before_armed += 1
            return
        self.evaluated += 1
        if self.node_id in tree:
            self.holding += 1
        else:
            self.missing.append({"call": call, "evaluated_so_far": self.evaluated})

    def _arm_if_allocated(self, name: str, args: tuple, kwargs: dict) -> None:
        ids: list = []
        if name == "add_nodes":
            ids = list(args[0] if args else kwargs.get("node_ids", ()))
        elif name == "mutate_nodes":
            ids = list(kwargs.get("add", ()))
        elif name == "set_tree":
            ids = list(kwargs.get("keystones", ())) + list(kwargs.get("nodes", ()))
        if not self.armed and self.node_id in {int(n) for n in ids}:
            self.armed = True

    def __getattr__(self, name: str):
        value = getattr(self._outer, name)
        if not callable(value) or isinstance(value, type):
            return value

        def probed(*args, **kwargs):
            if name == "trial_stats":
                trials = list(args[0] if args else kwargs["trials"])
                before = self._tree() if self.armed else set()
                results = value(*args, **kwargs)
                for trial, result in zip(trials, results):
                    if self.armed and self.node_id in {int(n) for n in trial.get("remove", ())}:
                        self.trials_removing_it += 1
                    if not result.get("ok"):
                        self.failed_trials += 1
                        continue
                    state = (before - {int(n) for n in result.get("removed_node_ids", ())}) | {int(n) for n in result.get("added_node_ids", ())}
                    self._state("trial_stats", state)
                return results
            if name in EVALUATING:
                result = value(*args, **kwargs)
                self._state(name, self._tree() if self.armed else set())
                return result
            result = value(*args, **kwargs)
            self._arm_if_allocated(name, args, kwargs)
            return result

        probed.__name__ = name
        return probed

    def summary(self) -> dict:
        return {
            "node_id": self.node_id, "before_armed": self.before_armed, "evaluated": self.evaluated, "holding": self.holding,
            "without": self.evaluated - self.holding, "failed_trials": self.failed_trials, "trials_removing_it": self.trials_removing_it,
            "missing_examples": self.missing[:5],
        }


# ---------------------------------------------------------------------------------------------------------------- child

def _load_benchmark(path: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location("benchmark_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _child_main(mode: str, benchmark_path: str, out_dir: str) -> None:
    from junkroan.optimizer.trace import TRACE

    bench = _load_benchmark(benchmark_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {}
    probe_box: list[StateProbe] = []
    node_id = None
    if mode == "forced":
        from junkroan.optimizer.tree_graph import TreeGraph

        node_id = bench.resolve_keystone_name(TreeGraph.load(), KEYSTONE)[0]
        kwargs["force_keystones"] = [KEYSTONE]
        original = bench._session_for

        def probed_session(session, record_calls, log_path):
            probe_box.append(StateProbe(original(session, record_calls, log_path), session, node_id))
            TRACE.set_forced({"nodes": [node_id]})  # the benchmark does not set the forced classes (the search runner does): the counter reads them
            return probe_box[0]

        bench._session_for = probed_session
    else:
        kwargs["record_calls"] = str(out / "calls")
    t0 = time.perf_counter()
    row = bench.run_one(SLUG, log_path=str(out / f"{SLUG}-s{SEED}.log"), seed=SEED, gear_mode=GEAR, construction_only=True, loop_seconds=None, **kwargs)
    result: dict = {"ok": row.get("ok"), "error": row.get("error"), "trace": row.get("trace"), "keystones": row.get("keystones"),
                    "variant": row.get("variant"), "seconds": time.perf_counter() - t0,
                    "stages": [s["name"] for s in row.get("stages", [])]}
    if mode == "forced":
        considered = TRACE.considered()
        counts: dict[str, dict[str, int]] = {}
        for classes in considered.values():  # every move's classes, summed
            for cls, c in classes.items():
                if cls in (f"node:{node_id}", f"node-rm:{node_id}", f"forced-missing:node:{node_id}", "forced:kept"):
                    for kind in ("generated", "evaluated"):
                        counts.setdefault(cls, {"generated": 0, "evaluated": 0})[kind] += c[kind]
        result["probe"] = probe_box[0].summary() if probe_box else None
        result["trace_counts"] = counts
        result["trace_total_evaluated"] = sum(c["evaluated"] for classes in considered.values() for c in classes.values())
    (out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")


# ------------------------------------------------------------------------------------------------------------- parent

def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout


def _run_child(mode: str, benchmark_path: Path, out: Path) -> dict:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1"}
    done = subprocess.run([sys.executable, str(Path(__file__).resolve()), mode, str(benchmark_path), str(out)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=RUN_TIMEOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert done.returncode == 0, f"{mode} child failed:\n{done.stderr[-3000:]}"
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["ok"], f"{mode} build failed: {result['error']}\n{result['trace']}"
    assert result["stages"][-1] == "tree rebuilt on gear", result["stages"]
    return result


@pytest.fixture(scope="module")
def forced_run(tmp_path_factory) -> dict:
    return _run_child("forced", ROOT / "scripts" / "benchmark.py", tmp_path_factory.mktemp("forced"))


@pytest.fixture(scope="module")
def transcripts(tmp_path_factory) -> tuple[Path, Path]:
    if _git("diff", "--name-only", BASE, "HEAD", "--", "src", "tools", "config", "scripts", ":(exclude)scripts/benchmark.py").strip():
        pytest.skip(f"code other than scripts/benchmark.py moved since {BASE}: the comparison is no longer 'the switch alone'")
    scratch = ROOT / ".scratch"  # the file sits one folder below the checkout root, so its `ROOT` is the checkout (var/, vendor/)
    scratch.mkdir(exist_ok=True)
    base_file = scratch / "benchmark_base_1029.py"
    base_file.write_text(_git("show", f"{BASE}:scripts/benchmark.py"), encoding="utf-8")
    try:
        head_out, base_out = tmp_path_factory.mktemp("head"), tmp_path_factory.mktemp("base")
        _run_child("head", ROOT / "scripts" / "benchmark.py", head_out)
        _run_child("base", base_file, base_out)
    finally:
        base_file.unlink(missing_ok=True)
        try:
            scratch.rmdir()
        except OSError:
            pass
    name = f"{SLUG}-s{SEED}.calls.jsonl"
    return head_out / "calls" / name, base_out / "calls" / name


@pytest.mark.pob
@pytest.mark.slow
def test_every_state_evaluated_after_the_skeleton_holds_the_forced_keystone(forced_run: dict) -> None:
    probe = forced_run["probe"]
    assert forced_run["variant"] == f"with {KEYSTONE}"  # (the row's `keystones` list is read from the delivered build: not filled by a construction-only run)
    assert probe["before_armed"] > 0, "the author's own build is evaluated before the skeleton: the probe saw the run's start"
    assert probe["evaluated"] > 100, probe  # a real search ran after the keystone was allocated, not an empty one
    assert probe["without"] == 0, probe  # evaluated(without keystone) = 0
    assert probe["holding"] == probe["evaluated"]
    counts = forced_run["trace_counts"]
    # the trace counter at the PoB boundary (TRACE.count_trial in PobSession.trial_stats): trials were generated and evaluated,
    # none of them removes the keystone (`node-rm:<id>`, and the forced class `forced-missing:node:<id>`)
    assert counts["forced:kept"]["generated"] > 0 and counts["forced:kept"]["evaluated"] > 0, counts
    for dropped in (f"node-rm:{probe['node_id']}", f"forced-missing:node:{probe['node_id']}"):
        assert counts.get(dropped, {}).get("evaluated", 0) == 0, counts
    assert probe["trials_removing_it"] == 0
    print(f"#1029 trace: {forced_run['trace_total_evaluated']} trials counted by the trace, probe states evaluated {probe['evaluated']}, "
          f"holding {probe['holding']}, without {probe['without']}, failed trials {probe['failed_trials']}, counts {counts}")


@pytest.mark.pob
@pytest.mark.slow
def test_a_run_without_the_switch_makes_the_same_pob_calls_as_before_it(transcripts: tuple[Path, Path]) -> None:
    head, base = (path.read_text(encoding="utf-8").splitlines() for path in transcripts)
    assert len(head) > 100, "a real transcript"
    equal = sum(1 for a, b in zip(head, base) if a == b)
    print(f"#1029 transcript: {equal} of {len(head)} lines equal (base has {len(base)})")
    assert len(head) == len(base) and equal == len(head)


# --------------------------------------------------------------------------------------------- the probe itself, PoB-free

class _FakeSession:
    """tree_light + trial_stats the way PobSession answers them: a trial reports the nodes it added and removed."""

    def __init__(self, tree: set[int]) -> None:
        self.tree = set(tree)

    def tree_light(self) -> dict:
        return {"user_allocated_node_ids": sorted(self.tree)}

    def add_nodes(self, node_ids) -> dict:
        self.tree |= set(node_ids)
        return {}

    def stats(self, keys=None) -> dict:
        return {}

    def trial_stats(self, trials, keys, *, mode="full") -> list[dict]:
        return [{"ok": True, "added_node_ids": sorted(t.get("add", ())), "removed_node_ids": sorted(t.get("remove", ())), "stats": {}} for t in trials]


def test_the_probe_sees_a_state_without_the_keystone_and_ignores_what_came_before_the_skeleton() -> None:
    session = _FakeSession({1, 2})
    probe = StateProbe(session, session, node_id=9)
    probe.stats()  # the author's build, before the keystone is allocated
    probe.trial_stats([{"add": [5]}], ["Life"])
    assert probe.summary()["before_armed"] == 2 and probe.summary()["evaluated"] == 0

    probe.add_nodes([9])
    probe.stats()
    probe.trial_stats([{"add": [5]}, {"remove": [2]}, {"remove": [9]}], ["Life"])  # the last trial evaluates a tree without 9
    summary = probe.summary()
    assert (summary["evaluated"], summary["holding"], summary["without"], summary["trials_removing_it"]) == (4, 3, 1, 1)
    assert summary["missing_examples"] == [{"call": "trial_stats", "evaluated_so_far": 4}]


if __name__ == "__main__":
    _child_main(sys.argv[1], sys.argv[2], sys.argv[3])
