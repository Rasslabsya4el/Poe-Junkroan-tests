"""#784 branch B: the search never links more curses than PoB applies (EnemyCurseLimit).

PoB drops the curses beyond EnemyCurseLimit (spark-s4: limit 1, Conductivity + Sniper's Mark linked, PoB's
CurseList holds only Sniper's Mark, removing Conductivity moves the output 0.00 %), so a candidate that links
one more is a gem slot spent on nothing. The count is the audit's own (`audit_curse_limit`): curse and (hex
or mark), not aura. Rail tests with a stubbed PoB read: `evaluated(curses over the limit) = 0` and
`generated(a second curse where the limit allows it) > 0`, counted at the stub that stands for the PoB boundary
(every stats read sees the linked groups) and by the trace's own classes `curse:linked=<n>` / `curse:over-limit`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.trace import TRACE
from junkroan.search.generator import SkeletonGenerator
from junkroan.search.hypothesis import active_gems
from junkroan.search.skeleton import Skeleton, SocketGroup

CURSES = ("Conductivity", "Frostbite", "Sniper's Mark", "Elemental Weakness")


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def _is_curse(name: str) -> bool:
    """The audit's own count, restated from the corpus tags (not the code under test)."""

    tags = set((active_gems().get(name.lower()) or {}).get("tag_keys") or [])
    return "curse" in tags and bool(tags & {"hex", "mark"}) and "aura" not in tags


class _Pob:
    """The PoB boundary: every stats read sees the gems linked at that moment. Curses are worth +10 each
    (so the search always wants one more), an aura +5; `over_reads` counts the reads of a build carrying
    more curses than the limit while it was not already over it when the search started."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.linked: list[str] = []
        self.reads = 0
        self.over_reads = 0
        self.max_curses = 0

    def stats(self, keys) -> dict:
        self.reads += 1
        curses = len({g for g in self.linked if _is_curse(g)})
        self.max_curses = max(self.max_curses, curses)
        if curses > self.limit:
            self.over_reads += 1
        dps = 100.0 + 10.0 * curses + (5.0 if "Grace" in self.linked else 0.0)
        return {key: 0.0 for key in keys} | {"CombinedDPS": dps, "Life": 100.0, "TotalEHP": 1.0, "EnemyCurseLimit": float(self.limit)}


def _gen(pob: _Pob) -> SkeletonGenerator:
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.pob = pob
    gen.rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0), utility_max_groups=4, movement_skill_required=False)
    gen.objective = Objective(maximize="CombinedDPS")
    gen.log = lambda _m: None
    gen.picks = []
    gen.castability_context = None
    gen.castability_metrics = CastabilityMetrics()

    def set_link(skeleton, link, **_kw) -> None:
        pob.linked = [*link, *(g for grp in skeleton.extra_groups if grp.enabled for g in grp.gems)]

    gen._set_main_link = set_link
    gen._set_main_link_raw = set_link
    gen._reconfigure = lambda *_a, **_k: None
    gen._restore_castability = lambda *_a, **_k: None
    return gen


def _skeleton(*carried: str) -> Skeleton:
    return Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=["Spark"],
                    extra_groups=[SocketGroup(gems=[name], slot="Helmet", label=name) for name in carried])


def _counter(label: str, cls: str) -> tuple[int, int]:
    row = TRACE.considered()[label].get(cls) or {"generated": 0, "evaluated": 0}
    return row["generated"], row["evaluated"]


def _all(label: str, prefix: str) -> tuple[int, int]:
    rows = [v for c, v in TRACE.considered()[label].items() if c.startswith(prefix)]
    return sum(v["generated"] for v in rows), sum(v["evaluated"] for v in rows)


def test_a_build_at_the_curse_limit_is_offered_no_further_curse() -> None:
    """spark-s4: limit 1 and Sniper's Mark linked: Conductivity, Frostbite and Elemental Weakness are never
    written into PoB; the aura still is."""

    pob = _Pob(limit=1)
    gen = _gen(pob)
    gen.utility_candidates = lambda _sk: {"aura": ["Grace"], "curse": ["Conductivity", "Frostbite", "Elemental Weakness"]}
    skeleton = _skeleton("Sniper's Mark")

    added = gen.pick_utilities(skeleton, max_groups=4)
    TRACE.flush("picks")

    assert [g.gems[0] for g in added] == ["Grace"]
    assert pob.over_reads == 0 and pob.max_curses == 1, "no stats read ever sees a second curse"
    for name in ("Conductivity", "Frostbite", "Elemental Weakness"):
        assert _counter("picks", f"gem:{name}") == (0, 0), name
    assert _counter("picks", "gem:Grace")[1] > 0
    assert _counter("picks", "curse:over-limit")[1] == 0, "the forbidden class is registered and stays 0 evaluated"
    assert _counter("picks", "curse:over-limit")[0] == 0


def test_a_second_curse_is_generated_and_evaluated_where_the_limit_allows_it() -> None:
    """Limit 2, one curse carried: the pool offers curses, one is taken (curse:linked=2 generated > 0 and
    evaluated > 0); at 2 linked the third is not offered (limit reached) and nothing ever reads 3."""

    pob = _Pob(limit=2)
    gen = _gen(pob)
    gen.utility_candidates = lambda _sk: {"aura": ["Grace"], "curse": ["Conductivity", "Frostbite", "Elemental Weakness"]}
    skeleton = _skeleton("Sniper's Mark")

    added = gen.pick_utilities(skeleton, max_groups=4)
    TRACE.flush("picks")

    picked_curses = [g.gems[0] for g in added if _is_curse(g.gems[0])]
    assert len(picked_curses) == 1, picked_curses
    generated, evaluated = _counter("picks", "curse:linked=2")
    assert generated > 0 and evaluated > 0, (generated, evaluated)
    assert _counter("picks", "curse:linked=3") == (0, 0), "a third curse is never offered at limit 2"
    assert _counter("picks", "curse:over-limit")[1] == 0
    assert pob.over_reads == 0 and pob.max_curses == 2


def test_a_build_without_a_curse_gets_one_and_then_no_second_at_limit_1() -> None:
    pob = _Pob(limit=1)
    gen = _gen(pob)
    gen.utility_candidates = lambda _sk: {"curse": ["Conductivity", "Frostbite", "Sniper's Mark"]}
    skeleton = _skeleton()

    added = gen.pick_utilities(skeleton, max_groups=4)
    TRACE.flush("picks")

    assert len([g for g in added if _is_curse(g.gems[0])]) == 1
    assert _counter("picks", "curse:linked=1")[0] > 0 and _counter("picks", "curse:linked=1")[1] > 0
    assert _counter("picks", "curse:linked=2") == (0, 0)
    assert pob.over_reads == 0 and pob.max_curses == 1


def _rejudge(pob: _Pob, monkeypatch: pytest.MonkeyPatch, groups: list[SocketGroup], cands: dict[str, list[str]]) -> Skeleton:
    gen = _gen(pob)
    gen.legal_supports = lambda _sk: []
    gen.utility_candidates = lambda _sk: cands
    gen.drop_reserving_group = lambda *_a, **_k: None
    skeleton = Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=["Spark"], extra_groups=groups)
    monkeypatch.setattr(Skeleton, "refresh_minion_counts", lambda self, *_a, **_k: {})
    gen._set_main_link(skeleton, skeleton.main_link)
    gen.rejudge_picks(skeleton, max_sweeps=1)
    TRACE.flush("picks")
    return skeleton


def test_the_rejudge_never_swaps_a_pick_for_a_curse_the_limit_has_no_room_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """Limit 1, Sniper's Mark linked, the picked group is Grace: swapping it for Frostbite would link a second
    curse. Not offered; the non-curse alternative still is."""

    pob = _Pob(limit=1)
    groups = [SocketGroup(gems=["Sniper's Mark"], slot="Helmet", label="Sniper's Mark"),
              SocketGroup(gems=["Grace"], slot="Gloves", label="Grace", picked=True)]
    _rejudge(pob, monkeypatch, groups, {"aura": ["Haste"], "curse": ["Frostbite", "Elemental Weakness"]})

    assert pob.over_reads == 0 and pob.max_curses == 1
    assert _counter("picks", "gem:Frostbite") == (0, 0) and _counter("picks", "gem:Elemental Weakness") == (0, 0)
    assert _counter("picks", "gem:Haste")[1] > 0
    assert _counter("picks", "curse:over-limit")[1] == 0


def test_the_rejudge_swaps_a_curse_for_a_curse_when_it_is_the_only_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The picked group is the build's only curse: the swap for another curse links one curse, within the limit."""

    pob = _Pob(limit=1)
    groups = [SocketGroup(gems=["Conductivity"], slot="Gloves", label="Conductivity", picked=True)]
    _rejudge(pob, monkeypatch, groups, {"curse": ["Frostbite", "Elemental Weakness"]})

    generated, evaluated = _counter("picks", "curse:linked=1")
    assert generated > 0 and evaluated > 0, (generated, evaluated)
    assert pob.over_reads == 0 and pob.max_curses == 1
    assert _counter("picks", "curse:over-limit")[1] == 0


class _XmlPob:
    """The PoB boundary of the skeleton derivation: it reads the XML it is handed; a curse is worth +10, the
    Mark more than a hex (the numbers are the stub's, PoB's pick is what the code takes)."""

    def __init__(self, xml: str) -> None:
        self.xml = xml
        self.loads: list[list[str]] = []

    def export_xml(self) -> str:
        return self.xml

    def load_xml(self, xml: str) -> None:
        import xml.etree.ElementTree as ET

        self.loads.append([g.get("nameSpec") for g in ET.fromstring(xml).iter("Gem") if g.get("enabled", "true") == "true" and _is_curse(g.get("nameSpec") or "")])
        self.xml = xml

    def stats(self, keys) -> dict:
        live = self.loads[-1] if self.loads else []
        value = 100.0 + (30.0 if "Sniper's Mark" in live else 0.0) + (10.0 if "Conductivity" in live else 0.0)
        return {key: value for key in keys}


def test_the_skeleton_keeps_one_of_a_hex_and_a_mark_at_limit_1_and_pob_picks_which(monkeypatch: pytest.MonkeyPatch) -> None:
    """spark: Conductivity + Sniper's Mark in one author group, limit 1. The drop counts the Mark (it did not
    before: 1 curse of 1) and keeps the one PoB scores best; every build it asks PoB about carries 1 curse."""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_from_skeleton as bfs

    xml = ('<PathOfBuilding><Skills><Skill enabled="true"><Gem nameSpec="Conductivity" enabled="true"/>'
           '<Gem nameSpec="Sniper&apos;s Mark" enabled="true"/><Gem nameSpec="Sigil of Power" enabled="true"/></Skill></Skills></PathOfBuilding>')
    pob = _XmlPob(xml)
    monkeypatch.setattr(bfs, "skeleton_limits", lambda *_a, **_k: {"EnemyCurseLimit": 1.0})
    skeleton = Skeleton(class_name="Shadow", ascendancy="Assassin", main_link=["Spark"],
                        extra_groups=[SocketGroup(gems=["Conductivity", "Sniper's Mark", "Sigil of Power"], slot="Helmet", label="curses")])

    lines = bfs.drop_over_limit_gems(pob, skeleton)

    assert skeleton.extra_groups[0].gems == ["Sniper's Mark", "Sigil of Power"], lines
    assert any("kept Sniper's Mark" in l and "dropped Conductivity" in l and "curse limit of 1" in l for l in lines), lines
    subset_loads = pob.loads[1:-1]  # the first load is the author's own build, the last restores it
    assert subset_loads and all(len(set(l)) <= 1 for l in subset_loads), subset_loads
    assert len(set(pob.loads[-1])) == 2, "the build PoB holds is restored exactly as the author left it"
