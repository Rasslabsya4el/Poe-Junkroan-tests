"""#1147 unit 5b: scripts/run_bundles.py, PoB-free.

The script runs bundles on stands and writes the catalogue. Here the PoB side is a fake session and a fake pipeline
(`FakePob`, `FakePipeline`), the pool is replaced by an in-process executor, and the stands are import codes built from
a small XML in tmp_path. The real-stand test only reads the three seed-4 stands and the day-1 graph: no PobSession is
opened anywhere in this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_bundles as rb  # noqa: E402
from junkroan.optimizer import catalogue  # noqa: E402
from junkroan.optimizer.bundle_fit import GRAPH_PATH, BundleGraph, BundleNode, Stand  # noqa: E402
from junkroan.optimizer.repair import RepairChoice, RepairOutcome  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph  # noqa: E402
from junkroan.pob.session import decode_import_code, encode_import_code  # noqa: E402

STANDS = ROOT / "artifacts" / "stands-1124"
needs_stands = pytest.mark.skipif(
    not ((ROOT / "var" / "cache").is_dir() and all((STANDS / f"{n}-s4.pob.txt").is_file() for n in ("spark", "smite", "summon_raging_spirits"))),
    reason="var/cache or the seed-4 stand files are not present",
)

# -- a small world: a graph of five parts, two stands, a fake PoB -----------------------------------------------------

def _node(node_id, surface, tree_id=None, ascendancy=None, item_types=()):
    return BundleNode(id=node_id, surface=surface, name=node_id, tree_id=tree_id, ascendancy=ascendancy, item_types=tuple(item_types))


GRAPH = BundleGraph(nodes={n.id: n for n in [
    _node("notable:1", "notable", 1),
    _node("notable:2", "notable", 2),
    _node("keystone:3", "keystone", 3),
    _node("mastery:4", "mastery", 4),
    _node("ascendancy:5", "ascendancy", 5, ascendancy="inquisitor"),
    _node("ascendancy:6", "ascendancy", 6, ascendancy="slayer"),
]})
ALLOCATABLE = frozenset({1, 2, 3, 4, 5, 6})
EDGES = [
    {"from": "notable:1", "to": "notable:2", "kind": "x", "from_line": "", "to_line": ""},
    {"from": "keystone:3", "to": "notable:1", "kind": "x", "from_line": "", "to_line": ""},
    {"from": "mastery:4", "to": "notable:2", "kind": "x", "from_line": "10% increased Life", "to_line": ""},
    {"from": "ascendancy:6", "to": "notable:1", "kind": "x", "from_line": "", "to_line": ""},
]
A = ("notable:1", "notable:2")
B = ("keystone:3", "notable:1")
M = ("mastery:4", "notable:2")
FOREIGN = ("ascendancy:6", "notable:1")


def _xml(ascendancy="Inquisitor") -> str:
    return (f'<PathOfBuilding><Build ascendClassName="{ascendancy}"/><Tree><Spec nodes="100"/></Tree>'
            '<Items activeItemSet="1"><ItemSet id="1"><Slot name="Weapon 1" itemId="1"/></ItemSet></Items></PathOfBuilding>')


def _stand_file(folder: Path, name: str, ascendancy="Inquisitor") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(encode_import_code(_xml(ascendancy)), encoding="utf-8")
    return path


def _graph_json(tmp_path: Path, edges=EDGES) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": [], "edges": edges}), encoding="utf-8")
    return path


def _spec(ids, edge=None, stand=None) -> rb.BundleSpec:
    return rb.BundleSpec(ids=tuple(ids), edge=edge, stand=stand)


def _info(path: Path) -> dict:
    return {"slug": path.name.split("-")[0], "stat": "CombinedDPS", "gear_mode": "wishlist"}


class FakePob:
    """A PoB stand-in: the loaded build is a number; repair moves it; every call is counted."""

    def __init__(self):
        self.loaded = 0
        self.calls = 0
        self.value = 0.0
        self.xml = _xml()

    def load_import_code(self, text):
        self.calls += 1
        self.loaded += 1
        self.value = 100.0

    def stats(self, keys):
        self.calls += 1
        return {"CombinedDPS": self.value}

    def export_xml(self):
        self.calls += 1
        return self.xml

    def pob_calls(self):
        return {"all": {"count": self.calls, "seconds": 0.0}}

    def reset_pob_calls(self):
        self.calls = 0


class FakePipeline:
    def __init__(self, pob, seen, gain=0.1):
        self.pob, self.seen, self.gain = pob, seen, gain
        self.judging = object()
        self.objective = SimpleNamespace(maximize="CombinedDPS", stat_keys=("CombinedDPS",),
                                         score=lambda stats: SimpleNamespace(value=stats["CombinedDPS"]))

    def repair(self, build, result, choice, *, seed=1):
        self.seen.append(SimpleNamespace(build=build, skeleton=build.skeleton, choice=choice, seed=seed))
        start = self.pob.stats(("CombinedDPS",))["CombinedDPS"]
        self.pob.value = start * (1 + self.gain)
        return RepairOutcome(start=start, values=[self.pob.value], gains=[self.gain], verdict="take", seconds=0.0)


def _factory(pob, seen):
    """A state factory that, like `_pipeline_state`, builds everything new on every call."""

    made = []

    def build(pob_, prepared, *, gear_mode, log):
        skeleton = SimpleNamespace(name=f"skeleton-{len(made)}")
        made.append(skeleton)
        return FakePipeline(pob_, seen), skeleton, SimpleNamespace(), SimpleNamespace()

    build.made = made
    return build


@pytest.fixture(autouse=True)
def _cwd_with_the_default_stand(tmp_path, monkeypatch):
    """A job holds the stand's path (the worker reads the file); `_job`'s default stand is a name in the working folder."""

    _stand_file(tmp_path, "spark-s4.pob.txt")
    monkeypatch.chdir(tmp_path)


def _job(ids, edge=None, stand="spark-s4.pob.txt", seed=1):
    return {"index": 0, "stand": stand, "ids": list(ids), "edge": edge, "seed": seed, "stat": "CombinedDPS", "gear_mode": "wishlist", "slug": "spark"}


# -- the bundles file -------------------------------------------------------------------------------------------------

def test_a_bundles_file_is_a_list_of_ids_and_an_edge_or_null(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps([{"ids": list(A), "edge": EDGES[0]}, {"ids": list(B), "edge": None, "stand": "smite-s4.pob.txt"}]), encoding="utf-8")
    specs = rb.load_bundles(path)
    assert specs == [_spec(A, EDGES[0]), _spec(B, None, "smite-s4.pob.txt")]


def test_a_bundles_file_with_unsorted_ids_is_refused(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps([{"ids": ["notable:2", "notable:1"], "edge": None}]), encoding="utf-8")
    with pytest.raises(ValueError, match="sorted"):
        rb.load_bundles(path)


# -- planning: order and fit --------------------------------------------------------------------------------------------

def test_tasks_are_ordered_by_stand_name_then_bundle_ids_whatever_the_input_order(tmp_path):
    stands = [_stand_file(tmp_path, "smite-s4.pob.txt"), _stand_file(tmp_path, "spark-s4.pob.txt")]
    one = rb.plan(stands, [_spec(B), _spec(A)], GRAPH)
    two = rb.plan(list(reversed(stands)), [_spec(A), _spec(B)], GRAPH)
    expected = [("smite-s4.pob.txt", B), ("smite-s4.pob.txt", A), ("spark-s4.pob.txt", B), ("spark-s4.pob.txt", A)]  # B = (keystone:3, ...) sorts before A = (notable:1, ...)
    assert [(t.stand.name, t.spec.ids) for t in one] == expected
    assert [(t.stand.name, t.spec.ids) for t in two] == expected
    assert [t.index for t in one] == [0, 1, 2, 3]


def test_a_bundle_scoped_to_a_stand_is_planned_on_that_stand_only(tmp_path):
    stands = [_stand_file(tmp_path, "smite-s4.pob.txt"), _stand_file(tmp_path, "spark-s4.pob.txt")]
    tasks = rb.plan(stands, [_spec(A, stand="spark-s4.pob.txt"), _spec(B)], GRAPH)
    assert [(t.stand.name, t.spec.ids) for t in tasks] == [("smite-s4.pob.txt", B), ("spark-s4.pob.txt", B), ("spark-s4.pob.txt", A)]


def test_the_fit_check_runs_at_planning_and_names_the_reason(tmp_path):
    stands = [_stand_file(tmp_path, "spark-s4.pob.txt", "Inquisitor")]
    tasks = rb.plan(stands, [_spec(A), _spec(FOREIGN)], GRAPH)
    fits = {t.spec.ids: t.fit for t in tasks}
    assert fits[A].fits
    assert not fits[FOREIGN].fits and "slayer" in fits[FOREIGN].reason


# -- the measurement on one session ------------------------------------------------------------------------------------

def test_a_fresh_build_is_made_for_every_bundle_and_never_reused():
    pob, seen = FakePob(), []
    factory = _factory(pob, seen)
    for ids in (A, B, A):
        rb.measure_with_session(pob, _job(ids), prepared=object(), state_factory=factory)
    assert len(factory.made) == 3  # the build factory once per bundle
    assert pob.loaded == 3  # the stand reloaded into PoB once per bundle
    assert len({id(s.build) for s in seen}) == 3 and len({id(s.skeleton) for s in seen}) == 3  # no build object passed to repair twice


def test_the_stand_is_reloaded_before_the_state_is_rebuilt():
    pob, seen, order = FakePob(), [], []
    factory = _factory(pob, seen)
    load = pob.load_import_code
    pob.load_import_code = lambda text: order.append("load") or load(text)
    inner = factory

    def tracing(*a, **kw):
        order.append("state")
        return inner(*a, **kw)

    tracing.made = inner.made
    rb.measure_with_session(pob, _job(A), prepared=object(), state_factory=tracing)
    assert order == ["load", "state"]


def test_the_repair_gets_the_bundle_the_seed_and_the_mastery_line_of_its_edge():
    pob, seen = FakePob(), []
    rb.measure_with_session(pob, _job(M, EDGES[2], seed=7), prepared=object(), state_factory=_factory(pob, seen))
    choice = seen[0].choice
    assert choice == RepairChoice(direction="force", bundle=M)
    assert dict(choice.mastery_lines) == {"mastery:4": "10% increased Life"}
    assert seen[0].seed == 7


def test_the_measured_result_has_the_numbers_of_the_repair_and_the_code_of_the_rebuilt_stand():
    pob, seen = FakePob(), []
    result = rb.measure_with_session(pob, _job(A), prepared=object(), state_factory=_factory(pob, seen))
    assert result["ok"] and result["metric"] == "CombinedDPS"
    assert result["base_value"] == 100.0 and result["value"] == pytest.approx(110.0)
    assert result["verdict"] == "take" and result["passes"] == 1 and result["seconds"] >= 0
    assert decode_import_code(result["import_code"]) == pob.xml
    assert result["pob_calls"] > 0


def test_a_failure_in_the_repair_is_a_result_not_an_exception():
    pob = FakePob()

    def broken(*a, **kw):
        raise ValueError("no slot for the unique")

    result = rb.measure_with_session(pob, _job(A), prepared=object(), state_factory=broken)
    assert not result["ok"] and "ValueError: no slot for the unique" in result["error"]


def test_the_measuring_code_never_writes_the_catalogue(monkeypatch):
    monkeypatch.setattr(catalogue, "append", lambda *a, **k: pytest.fail("a worker wrote the catalogue"))
    pob, seen = FakePob(), []
    rb.measure_with_session(pob, _job(A), prepared=object(), state_factory=_factory(pob, seen))


# -- the run: records, does_not_fit, order, rerun -----------------------------------------------------------------------

def _fake_measure(job):
    """What a pool worker returns for a job, from the job alone (the base 100, a gain per bundle size, seconds by index)."""

    value = 100.0 * (1 + 0.1 * len(job["ids"]))
    return {"ok": True, "metric": job["stat"], "base_value": 100.0, "value": value, "verdict": "take", "passes": 2,
            "seconds": 3.0 + job["index"], "import_code": encode_import_code(f"<x>{job['ids']}</x>"), "reason": "take: fake", "pob_calls": 11}


def _in_process(measure=_fake_measure, order=None):
    def execute(jobs, workers):
        for job in (jobs if order is None else [jobs[i] for i in order]):
            yield job["index"], measure(job)

    return execute


def _run(tmp_path, bundles, stands=None, **kw):
    stands = stands or [_stand_file(tmp_path / "stands", "spark-s4.pob.txt")]
    out = kw.pop("out", tmp_path / "out" / "day1.jsonl")
    kw.setdefault("execute", _in_process())
    rows = rb.run_bundles(stands, bundles, out, graph=GRAPH, seed=1, workers=1, commit="abc123", info_of=_info, **kw)
    lines = out.read_text(encoding="utf-8").splitlines() if out.exists() else []
    return rows, lines


def test_a_does_not_fit_bundle_writes_its_record_and_makes_no_pob_call(tmp_path):
    def forbidden(job):
        pytest.fail("a PoB job was made for a bundle that does not fit")

    rows, lines = _run(tmp_path, [_spec(FOREIGN)], execute=_in_process(forbidden))
    record = json.loads(lines[0])
    assert record["verdict"] == "does_not_fit" and "slayer" in record["reason"]
    assert record["bundle"] == list(FOREIGN) and record["seconds"] == 0
    assert record["value"] is None and record["base_value"] is None and record["gain"] is None and record["import_code"] is None
    assert rows[0]["pob_calls"] == 0


def test_no_session_is_opened_when_every_bundle_does_not_fit(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(rb, "pool_execute", lambda jobs, workers: opened.append(jobs) or iter(()))
    out = tmp_path / "d.jsonl"
    stands = [_stand_file(tmp_path / "stands", "spark-s4.pob.txt")]
    rb.run_bundles(stands, [_spec(FOREIGN)], out, graph=GRAPH, seed=1, workers=2, commit="c", info_of=_info)
    assert opened == [] and len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_a_measured_record_has_every_field(tmp_path):
    rows, lines = _run(tmp_path, [_spec(A, EDGES[0])])
    record = json.loads(lines[0])
    stand = tmp_path / "stands" / "spark-s4.pob.txt"
    assert set(record) == {"bundle", "edge", "stand", "stand_sha256", "metric", "base_value", "value", "gain", "verdict", "reason",
                           "seconds", "seed", "passes", "commit", "import_code"}
    assert record["bundle"] == list(A) and record["edge"] == EDGES[0]
    assert record["stand"] == "spark-s4.pob.txt" and record["stand_sha256"] == catalogue.stand_sha256(stand)
    assert record["metric"] == "CombinedDPS" and record["base_value"] == 100.0 and record["value"] == pytest.approx(120.0)
    assert record["gain"] == pytest.approx(0.2) and record["verdict"] == "take"
    assert record["seconds"] == 3.0 and record["seed"] == 1 and record["passes"] == 2 and record["commit"] == "abc123"
    assert decode_import_code(record["import_code"]).startswith("<x>")


def test_the_metric_of_a_record_is_the_one_the_measurement_used(tmp_path):
    rows, lines = _run(tmp_path, [_spec(A)], execute=_in_process(lambda job: {**_fake_measure(job), "metric": "FullDPS"}))
    assert json.loads(lines[0])["metric"] == "FullDPS"


def test_records_are_written_in_task_order_whatever_order_the_pool_finishes(tmp_path):
    bundles = [_spec(B), _spec(A), _spec(FOREIGN)]
    _, forward = _run(tmp_path, bundles, out=tmp_path / "f.jsonl")
    _, backward = _run(tmp_path, bundles, out=tmp_path / "r.jsonl", execute=_in_process(order=[1, 0]))
    assert [json.loads(line)["bundle"] for line in forward] == [list(FOREIGN), list(B), list(A)]  # (stand, ids) order
    assert forward == backward  # same bytes: the fake's seconds come from the task index, so they agree too


def test_a_rerun_of_one_record_is_the_same_line_apart_from_seconds(tmp_path):
    out = tmp_path / "day1.jsonl"
    _run(tmp_path, [_spec(A, EDGES[0])], out=out)
    _run(tmp_path, [_spec(A, EDGES[0])], out=out, execute=_in_process(lambda job: {**_fake_measure(job), "seconds": 99.0}))
    first, second = out.read_text(encoding="utf-8").splitlines()
    assert first != second and catalogue.same_apart_from_seconds(first, second)


def test_a_failed_measurement_writes_no_record_and_is_reported(tmp_path):
    rows, lines = _run(tmp_path, [_spec(A)], execute=_in_process(lambda job: {"ok": False, "error": "ValueError: boom", "seconds": 1.0}))
    assert lines == []
    assert rows[0]["ok"] is False and "boom" in rows[0]["error"]


def test_the_job_a_worker_gets_holds_no_output_path(tmp_path):
    jobs = []
    _run(tmp_path, [_spec(A, EDGES[0])], execute=_in_process(lambda job: jobs.append(job) or _fake_measure(job)))
    assert set(jobs[0]) == {"index", "stand", "ids", "edge", "seed", "stat", "gear_mode", "slug"}


# -- the table ---------------------------------------------------------------------------------------------------------

def test_the_table_has_the_columns_the_issue_asks_for_and_human_durations(tmp_path):
    rows, _ = _run(tmp_path, [_spec(A), _spec(FOREIGN)])
    text = rb.render_table(rows)
    for column in ("stand", "bundle", "base_value", "value", "gain", "verdict", "duration"):
        assert column in text
    assert "does_not_fit" in text and "4 s" in text  # A is task 1: the fake gives it 4.0 seconds
    assert "mean" in text and "max" in text


def test_mean_and_max_seconds_count_the_measured_bundles_only(tmp_path):
    rows, _ = _run(tmp_path, [_spec(A), _spec(B), _spec(FOREIGN)])
    assert rb.seconds_summary(rows) == {"measured": 2, "mean": pytest.approx(4.5), "max": 5.0}


# -- workers from the free slots -----------------------------------------------------------------------------------------

def test_a_number_of_workers_is_kept_but_never_wider_than_the_jobs():
    assert rb.resolve_workers("3", jobs=5) == 3
    assert rb.resolve_workers("3", jobs=2) == 2
    assert rb.resolve_workers("4", jobs=0) == 1


def test_auto_takes_the_free_slots_bounded_by_ram_and_jobs():
    pick = lambda jobs, free, ram: rb.resolve_workers("auto", jobs=jobs, free_slots=lambda: free, ram_workers=lambda: ram)
    assert pick(9, 4, 8) == 4  # slots bind
    assert pick(9, 6, 2) == 2  # RAM binds
    assert pick(3, 6, 8) == 3  # jobs bind
    assert pick(9, 0, 8) == 1  # never fewer than one


# -- the acceptance set --------------------------------------------------------------------------------------------------

def test_acceptance_writes_the_two_bundles_and_the_probe_per_stand_and_no_unique_by_default(tmp_path):
    stands = [_stand_file(tmp_path / "s", "smite-s4.pob.txt"), _stand_file(tmp_path / "s", "spark-s4.pob.txt")]
    out = tmp_path / "day1-bundles.json"
    entries = rb.write_acceptance(stands, _graph_json(tmp_path), out, graph=GRAPH, tree_allocatable=ALLOCATABLE, with_unique=False)
    assert json.loads(out.read_text(encoding="utf-8")) == entries
    for name in ("smite-s4.pob.txt", "spark-s4.pob.txt"):
        mine = [e for e in entries if e["stand"] == name]
        assert [tuple(e["ids"]) for e in mine] == [B, A, FOREIGN]
        assert all(e["edge"] is not None for e in mine)
    assert len(entries) == 6
    assert not any(any(i.startswith("unique:") for i in e["ids"]) for e in entries)
    # the same set loads back as bundles scoped to their stands
    assert {(s.stand, s.ids) for s in rb.load_bundles(out)} == {(e["stand"], tuple(e["ids"])) for e in entries}


@needs_stands
def test_acceptance_on_the_real_stands_is_six_measured_bundles_and_three_probes(tmp_path):
    stands = [STANDS / f"{n}-s4.pob.txt" for n in ("smite", "spark", "summon_raging_spirits")]
    out = tmp_path / "day1-bundles.json"
    entries = rb.write_acceptance(stands, GRAPH_PATH, out, graph=rb.load_bundle_graph(), tree_allocatable=TreeGraph.load().allocatable, with_unique=False)
    expected = {  # literals from the 5a tests (independent of this module)
        "spark-s4.pob.txt": [("notable:10115", "notable:14813"), ("notable:18174", "notable:20832")],
        "smite-s4.pob.txt": [("notable:18174", "notable:20832"), ("notable:10115", "notable:21634")],
        "summon_raging_spirits-s4.pob.txt": [("notable:10115", "notable:14813"), ("notable:18174", "notable:20832")],
    }
    assert len(entries) == 9
    for name, ids in expected.items():
        mine = [e for e in entries if e["stand"] == name]
        assert sorted(tuple(e["ids"]) for e in mine[:2]) == sorted(ids)
        assert len(mine) == 3
    tasks = rb.plan(stands, rb.load_bundles(out), rb.load_bundle_graph())
    assert sum(t.fit.fits for t in tasks) == 6 and sum(not t.fit.fits for t in tasks) == 3


def test_the_unique_bundle_is_added_only_behind_the_flag(tmp_path):
    from junkroan.optimizer.bundle_fit import BundleGraph as G

    graph = G(nodes={**GRAPH.nodes, "unique:Wand A, Goat": _node("unique:Wand A, Goat", "unique", None, item_types=("Wand",))})
    edges = EDGES + [{"from": "notable:1", "to": "unique:Wand A, Goat", "kind": "x", "from_line": "", "to_line": ""}]
    stands = [_stand_file(tmp_path / "s", "spark-s4.pob.txt")]
    without = rb.write_acceptance(stands, _graph_json(tmp_path, edges), tmp_path / "a.json", graph=graph, tree_allocatable=ALLOCATABLE, with_unique=False)
    with_unique = rb.write_acceptance(stands, _graph_json(tmp_path, edges), tmp_path / "b.json", graph=graph, tree_allocatable=ALLOCATABLE, with_unique=True)
    assert len(with_unique) == len(without) + 1
    extra = [e for e in with_unique if e not in without]
    assert len(extra) == 1 and "unique:Wand A, Goat" in extra[0]["ids"] and extra[0]["stand"] == "spark-s4.pob.txt"
