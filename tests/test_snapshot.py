"""#813 unit 1: `Snapshotter.take` / `restore` hold the five parts of the working build's state; a part a
site did not take is left untouched. No PoB: the holders are stand-ins."""

from __future__ import annotations

from dataclasses import dataclass, field

from junkroan.optimizer.snapshot import FILLER_ALL, FILLER_RAW, SKELETON_IDENTITY, SkeletonFields, Snapshotter, filler_slot


class FakePob:
    def __init__(self) -> None:
        self.xml = "xml0"
        self.exports = 0
        self.loads: list[str] = []

    def export_xml(self) -> str:
        self.exports += 1
        return self.xml

    def load_xml(self, xml: str) -> None:
        self.loads.append(xml)
        self.xml = xml


@dataclass
class FakeSkeleton:
    bandit: str = "none"
    rare_bases: dict = field(default_factory=lambda: {"Helmet": "Iron Hat"})


class FakeFiller:
    def __init__(self) -> None:
        self.current_raw = {"Helmet": "raw-h", "Boots": "raw-b"}
        self.resistance = {"chaos": 1}
        self.results = {("Helmet", "raw-h"): "result-h"}

    def resistance_plan_snapshot(self):
        return {"resistance": dict(self.resistance)}

    def restore_resistance_plan(self, saved):
        self.resistance = dict(saved["resistance"])

    def plan_snapshot(self):
        return {"resistance": self.resistance_plan_snapshot(), "results": dict(self.results)}

    def plan_restore(self, saved):
        self.restore_resistance_plan(saved["resistance"])
        self.results = dict(saved["results"])


class FakeTree:
    def __init__(self) -> None:
        self.history = ["a", "b"]
        self.invalidated: list[bool] = []

    def invalidate_after_recovery(self, *, keep_rejections: bool) -> None:
        self.invalidated.append(keep_rejections)


class FakeJudging:
    def __init__(self) -> None:
        self.objective = "obj0"
        self.restored: list[object] = []
        self.marked: list[str] = []

    def mark(self, scope: str):
        self.marked.append(scope)
        return (scope, self.objective)

    def restore(self, mark) -> None:
        self.restored.append(mark)
        self.objective = mark[1]


def _build():
    pob, skeleton, filler, judging, tree = FakePob(), FakeSkeleton(), FakeFiller(), FakeJudging(), FakeTree()
    return Snapshotter(pob=pob, skeleton=skeleton, filler=filler, judging=judging, trees=lambda: (tree,)), pob, skeleton, filler, judging, tree


def _dirty(pob, skeleton, filler, judging, tree) -> None:
    pob.xml = "xml1"
    skeleton.bandit = "alira"
    skeleton.rare_bases["Helmet"] = "Other"
    filler.current_raw["Helmet"] = "new"
    filler.current_raw.pop("Boots")
    filler.resistance = {"chaos": 9}
    filler.results[("Helmet", "raw-h")] = "changed"
    judging.objective = "obj1"
    tree.history.append("c")


def test_every_part_alone_and_all_together() -> None:
    build, pob, skeleton, filler, judging, tree = _build()
    snap = build.take(xml=True, skeleton=True, filler=FILLER_ALL, history=True, judging="move")
    assert pob.exports == 1 and judging.marked == ["move"]
    _dirty(pob, skeleton, filler, judging, tree)
    build.restore(snap, keep_rejections=True)
    assert pob.xml == "xml0" and pob.loads == ["xml0"]
    assert skeleton.bandit == "none" and skeleton.rare_bases == {"Helmet": "Iron Hat"}
    assert filler.current_raw == {"Helmet": "raw-h", "Boots": "raw-b"} and filler.resistance == {"chaos": 1}
    assert filler.results == {("Helmet", "raw-h"): "result-h"}
    assert tree.history == ["a", "b"] and tree.invalidated == [True]
    assert judging.objective == "obj0"


def test_a_part_the_site_did_not_take_is_left_untouched() -> None:
    for kwargs, untouched in (
        (dict(xml=True), ("skeleton", "filler", "history", "judging")),
        (dict(skeleton=True), ("xml", "filler", "history", "judging")),
        (dict(filler=FILLER_RAW), ("xml", "skeleton", "history", "judging")),
        (dict(history=True), ("xml", "skeleton", "filler", "judging")),
        (dict(judging="move"), ("xml", "skeleton", "filler", "history")),
    ):
        build, pob, skeleton, filler, judging, tree = _build()
        snap = build.take(**kwargs)
        _dirty(pob, skeleton, filler, judging, tree)
        build.restore(snap)
        state = {
            "xml": pob.xml == "xml1", "skeleton": skeleton.bandit == "alira",
            "filler": filler.current_raw.get("Helmet") == "new", "history": tree.history == ["a", "b", "c"],
            "judging": judging.objective == "obj1",
        }
        assert all(state[name] for name in untouched), (kwargs, state)
        assert not all(state.values()), kwargs  # and the one taken part did go back


def test_a_snapshot_with_the_xml_given_exports_nothing() -> None:
    build, pob, *_ = _build()
    snap = build.take(xml="attempt-xml")
    assert pob.exports == 0 and snap.xml == "attempt-xml"
    build.restore(snap)
    assert pob.loads == ["attempt-xml"]


def test_history_is_trimmed_without_invalidation_unless_asked() -> None:
    build, pob, skeleton, filler, judging, tree = _build()
    snap = build.take(history=True)
    tree.history.append("c")
    build.restore(snap)
    assert tree.history == ["a", "b"] and tree.invalidated == []
    tree.history.append("d")
    build.restore(snap, keep_rejections=False)
    assert tree.history == ["a", "b"] and tree.invalidated == [False]


def test_the_slot_scope_restores_one_slot_and_the_resistance_plan_only() -> None:
    build, pob, skeleton, filler, judging, tree = _build()
    snap = build.take(filler=filler_slot("Helmet"))
    filler.current_raw["Helmet"] = "new"
    filler.current_raw["Boots"] = "other-boots"
    filler.resistance = {"chaos": 9}
    filler.results[("Helmet", "raw-h")] = "changed"
    build.restore(snap)
    assert filler.current_raw == {"Helmet": "raw-h", "Boots": "other-boots"}
    assert filler.resistance == {"chaos": 1}
    assert filler.results[("Helmet", "raw-h")] == "changed"  # the plan's results are not part of this scope


def test_an_empty_slot_is_emptied_again() -> None:
    build, pob, skeleton, filler, judging, tree = _build()
    del filler.current_raw["Boots"]
    snap = build.take(filler=filler_slot("Boots"))
    filler.current_raw["Boots"] = "rolled"
    build.restore(snap)
    assert "Boots" not in filler.current_raw


def test_the_raw_scope_puts_back_the_whole_dict_and_not_the_results() -> None:
    build, pob, skeleton, filler, judging, tree = _build()
    snap = build.take(filler=FILLER_RAW)
    filler.current_raw = {"Gloves": "x"}
    filler.results[("Helmet", "raw-h")] = "changed"
    build.restore(snap)
    assert filler.current_raw == {"Helmet": "raw-h", "Boots": "raw-b"}
    assert filler.results[("Helmet", "raw-h")] == "changed"


@dataclass
class FakeIdentitySkeleton:
    tuned_choices: dict = field(default_factory=lambda: {"a": "1"})
    pantheon_major: str | None = "Lunaris"
    pantheon_minor: str | None = None
    bandit: str | None = "none"
    rare_bases: dict = field(default_factory=lambda: {"Helmet": "Iron Hat"})  # a field outside the scope


def test_the_skeleton_fields_scope_puts_back_its_fields_and_the_dict_in_place() -> None:
    pob, skeleton, judging, tree = FakePob(), FakeIdentitySkeleton(), FakeJudging(), FakeTree()
    build = Snapshotter(pob=pob, skeleton=skeleton, filler=None, judging=judging, trees=lambda: (tree,))
    held = skeleton.tuned_choices
    snap = build.take(skeleton=SKELETON_IDENTITY)
    skeleton.tuned_choices["b"] = "2"
    skeleton.tuned_choices["a"] = "9"
    skeleton.pantheon_major, skeleton.pantheon_minor, skeleton.bandit = None, "Soul of Gruthkul", "alira"
    skeleton.rare_bases["Helmet"] = "Other"
    build.restore(snap)
    assert skeleton.tuned_choices is held and held == {"a": "1"}  # the same dict object, put back in place
    assert (skeleton.pantheon_major, skeleton.pantheon_minor, skeleton.bandit) == ("Lunaris", None, "none")
    assert skeleton.rare_bases == {"Helmet": "Other"}  # a field outside the scope stays as it is
    assert pob.loads == [] and judging.restored == [] and tree.history == ["a", "b"]  # no other part touched


def test_the_skeleton_fields_scope_reads_a_missing_field_as_none_and_skips_a_missing_dict() -> None:
    @dataclass
    class Bare:
        bandit: str | None = "none"

    skeleton = Bare()
    build = Snapshotter(pob=FakePob(), skeleton=skeleton, filler=None, judging=FakeJudging(), trees=lambda: ())
    snap = build.take(skeleton=SKELETON_IDENTITY)
    assert snap.skeleton_fields == {"pantheon_major": None, "pantheon_minor": None, "bandit": "none", "tuned_choices": {}}
    skeleton.bandit = "alira"
    build.restore(snap)
    assert skeleton.bandit == "none" and getattr(skeleton, "tuned_choices", None) is None


def test_a_custom_fields_scope_and_the_whole_copy_do_not_mix() -> None:
    skeleton = FakeIdentitySkeleton()
    build = Snapshotter(pob=FakePob(), skeleton=skeleton, filler=None, judging=FakeJudging(), trees=lambda: ())
    snap = build.take(skeleton=SkeletonFields(names=("bandit",)))
    assert snap.skeleton is None and snap.skeleton_fields == {"bandit": "none"}
    skeleton.bandit, skeleton.pantheon_major = "alira", None
    build.restore(snap)
    assert skeleton.bandit == "none" and skeleton.pantheon_major is None
    whole = build.take(skeleton=True)
    assert whole.skeleton_fields is None and whole.skeleton is not None
