"""#542 unit 2, #1143: both lanes of a mortar spectre under Greater Volley, read on PoB (D62).

The author's `z327_necromancer_raise_spectre` build is read in both lanes before and after
`spectre_overlap_stats`. The delivered build and its exported XML must not move; each lane's
`FullDPS` there is PoB's own line for this build, `FullDPS` = 57,112 + 108,715 x count (#44), read at
count x the fact's multiplier (the Raise Spectre count PoB is sent is in the transcript). One session
for the module (a few minutes at most).
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from junkroan.mechanics import pending_facts
from junkroan.optimizer import spectre_overlap
from junkroan.optimizer.spectre_overlap import FACT_ID, spectre_overlap_stats, volley_overlap_multiplier
from junkroan.pob.skill_facts import SKILL_DATA_DIRS


def _set(monkeypatch, **over) -> None:
    facts = {k: (replace(v, **over) if k == FACT_ID else v) for k, v in pending_facts.load_facts().items()}
    monkeypatch.setattr(pending_facts, "load_facts", lambda *_a, **_k: facts)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
needs_skill_data = pytest.mark.skipif(not SKILL_DATA_DIRS[0].is_dir(), reason=f"PoB skill data not present at {SKILL_DATA_DIRS[0]}")

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "zizaran_327" / "necromancer_raise_spectre.pob.txt"
ISSUE_44_LINE = (57_112.0, 108_715.0)  # #44's line; the author file as loaded does not reproduce it (printed below)


class _Transcript:
    """The session, with the Raise Spectre `count` of every XML loaded into it written down: the number PoB is
    asked at. Everything else goes through to the session."""

    def __init__(self, pob, group_id: str, socket_index: int):
        self._pob, self._group_no, self._socket = pob, int(group_id.split(".")[-1]), socket_index
        self.counts: list[int] = []

    def load_xml(self, xml):
        skills = ET.fromstring(xml).find("Skills")
        scope = next((s for s in skills.findall("SkillSet") if s.get("id") == skills.get("activeSkillSet")), skills)
        self.counts.append(int(scope.findall("Skill")[self._group_no - 1].findall("Gem")[self._socket - 1].get("count") or 1))
        return self._pob.load_xml(xml)

    def __getattr__(self, name):
        return getattr(self._pob, name)


@pytest.fixture(scope="module")
def read(tmp_path_factory):
    from junkroan.pob.session import PobSession, decode_import_code

    xml = decode_import_code(FIXTURE.read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-issue542-pob", artifacts_root=tmp_path_factory.mktemp("issue542")) as pob:
        pob.load_xml(xml)
        whole = pob.calc("baseline")["FullDPS"]
        # The author's file carries 18 skill sets and PoB's read_state serializes them all (97 s, the
        # session gives it 30); its ~20 passive tree specs are written in hash order on every reopen. A
        # delivered build has one of each: the author's inactive sets and specs are dropped here, and the
        # check below says the active ones' numbers did not move by it.
        root = ET.fromstring(pob.export_xml())
        skills = root.find("Skills")
        for skill_set in list(skills.findall("SkillSet")):
            if skill_set.get("id") != skills.get("activeSkillSet"):
                skills.remove(skill_set)
        tree = root.find("Tree")
        specs = list(tree.findall("Spec"))
        for spec in specs:
            if spec is not specs[int(tree.get("activeSpec")) - 1]:
                tree.remove(spec)
        tree.set("activeSpec", "1")
        pob.load_xml(ET.tostring(root, encoding="unicode"))
        assert pob.calc("baseline")["FullDPS"] == whole, "dropping the inactive skill sets and specs moved the conservative FullDPS"
        found = spectre_overlap._main_spectre(pob.read_state())
        assert found is not None, "the fixture's main skill is no minion skill PoB names"
        group, entry, gem = found
        supports = [str(s.get("name")) for s in entry.get("support_links") or ()]
        before = {"conservative": pob.calc("baseline"), "optimistic": pob.calc("conditional")}
        xml_before = pob.export_xml()
        transcript = _Transcript(pob, str(group["socket_group_id"]), int(gem["socket_index"]))  # the PoB call transcript (D113)
        reading = spectre_overlap_stats(transcript, before["conservative"])
        optimistic, note, delivered_cons = reading.optimistic, reading.note, reading.conservative
        after_cons = pob.calc("baseline")
        after_opt = pob.calc("conditional")
        xml_after = pob.export_xml()
        # PoB's own line on this build as loaded: a second read at twice the count, in both lanes
        c = int(gem["count"])
        pob.load_xml(spectre_overlap._with_gem_count(xml_after, str(group["socket_group_id"]), int(gem["socket_index"]), str(gem["gem_name"]), c, 2 * c))
        twice = {"conservative": pob.calc("baseline"), "optimistic": pob.calc("conditional")}
    out = {
        "twice": twice,
        "count": int(gem["count"]), "minion_skill": str(entry["minion_skill_name"]), "supports": supports,
        "multiplier": volley_overlap_multiplier("optimistic", supports, str(entry["minion_skill_name"])),
        "before": before, "optimistic": optimistic, "delivered_cons": delivered_cons, "note": note, "after_cons": after_cons, "after_opt": after_opt,
        "xml_before": xml_before, "xml_after": xml_after, "sent_counts": transcript.counts,
    }
    fd = lambda stats: float(stats["FullDPS"])  # noqa: E731
    print(f"\nspectre count c = {out['count']}, multiplier m = {out['multiplier']}, minion skill = {out['minion_skill']!r}, supports = {supports}")
    print(f"Raise Spectre count in every XML loaded into PoB by the overlap read: {transcript.counts}")
    print("FullDPS            at count c     delivered (c x m)")
    print(f"conservative  {fd(before['conservative']):>14,.0f}  {fd(delivered_cons) if delivered_cons else float('nan'):>14,.0f}")
    print(f"optimistic    {fd(before['optimistic']):>14,.0f}  {fd(optimistic) if optimistic else float('nan'):>14,.0f}")
    print(f"note: {note}")
    cc = out["count"]
    print(f"read at count {2 * cc}: conservative {fd(twice['conservative']):,.0f}, optimistic {fd(twice['optimistic']):,.0f}")
    print(f"#44's line at count {cc}: {ISSUE_44_LINE[0] + ISSUE_44_LINE[1] * cc:,.0f}; at {cc * out['multiplier']}: {ISSUE_44_LINE[0] + ISSUE_44_LINE[1] * cc * out['multiplier']:,.0f}")
    return out


def _line_at(read, lane: str, count: float) -> float:
    """PoB's own FullDPS line on this build, through its reads at count c and 2c (FullDPS is linear in a
    spectre's count)."""

    c = read["count"]
    at_c, at_2c = float(read["before"][lane]["FullDPS"]), float(read["twice"][lane]["FullDPS"])
    return at_c + (at_2c - at_c) * (count - c) / c


@pytest.mark.pob
@needs_pob
@needs_skill_data
def test_the_delivered_build_does_not_move(read) -> None:
    """The count swap is undone: the build itself, read again in both lanes, is what it was."""

    assert read["multiplier"] > 1, "the fixture is a mortar spectre under Volley: the fact must act"
    assert read["after_cons"]["FullDPS"] == read["before"]["conservative"]["FullDPS"]
    assert read["after_opt"]["FullDPS"] == read["before"]["optimistic"]["FullDPS"]


@pytest.mark.pob
@needs_pob
@needs_skill_data
def test_the_conservative_read_is_pobs_line_at_count_times_multiplier(read) -> None:
    assert read["delivered_cons"] is not None, "approved: the conservative lane is read at the scaled count too"
    expected = _line_at(read, "conservative", read["multiplier"] * read["count"])
    assert read["delivered_cons"]["FullDPS"] == pytest.approx(expected, rel=0.001)
    assert read["multiplier"] == 5 and read["delivered_cons"]["FullDPS"] > read["before"]["conservative"]["FullDPS"]
    # #1143 row 2: on this build the lanes agree at count c (3,921,731 each), so the conservative read now equals,
    # to the digit, the optimistic read the delivered build carried before the change (19,252,626 at count 100)
    assert read["before"]["conservative"]["FullDPS"] == read["before"]["optimistic"]["FullDPS"]
    assert read["delivered_cons"]["FullDPS"] == read["optimistic"]["FullDPS"]


@pytest.mark.pob
@needs_pob
@needs_skill_data
def test_the_raise_spectre_count_sent_to_pob_is_the_derived_count_times_five_once(read) -> None:
    """D113 trace: one scaled read for both lanes (not 5 x 5 on the optimistic one), then the delivered count back."""

    assert read["sent_counts"] == [read["count"] * 5, read["count"]]


@pytest.mark.pob
@needs_pob
@needs_skill_data
def test_the_optimistic_lane_is_pobs_line_at_count_times_multiplier(read) -> None:
    assert read["optimistic"] is not None
    expected = _line_at(read, "optimistic", read["multiplier"] * read["count"])
    assert read["optimistic"]["FullDPS"] == pytest.approx(expected, rel=0.001)


@pytest.mark.pob
@needs_pob
@needs_skill_data
def test_the_note_names_what_the_fact_does_to_the_conservative_number(read) -> None:
    c, m = read["count"], read["multiplier"]
    before, after = _line_at(read, "conservative", c), _line_at(read, "conservative", c * m)
    share = (after - before) / before * 100.0
    assert FACT_ID in read["note"] and "moved the conservative number by" in read["note"]
    assert f"{share:+.1f}%" in read["note"], (share, read["note"])


@pytest.mark.pob
@needs_pob
@needs_skill_data
def test_the_exported_xml_is_unchanged(read) -> None:
    # PoB writes its hash-ordered lists in a new order on every reopen (the raw text differs after any
    # `set_skills` as well); `canonical_xml` fixes those orders and nothing else
    assert spectre_overlap.canonical_xml(read["xml_after"]) == spectre_overlap.canonical_xml(read["xml_before"])


# -- PoB-free: the stand-in sessions ------------------------------------------------------------------


class _Stub:
    """A session that can be read but must not be loaded into: any PoB call beyond the read fails."""

    def __init__(self, state):
        self._state = state

    def read_state(self):
        return self._state

    def __getattr__(self, name):
        raise AssertionError(f"PoB call {name!r} where none is allowed")


def _state(minion_skill, supports):
    return {"skills_state": {"main_socket_group_id": "skills.2.socket_group.1", "socket_groups": [{
        "socket_group_id": "skills.2.socket_group.1", "main_active_skill_index": 1,
        "gems": [{"gem_entry_id": "g1", "gem_name": "Raise Spectre", "socket_index": 1, "count": 4}],
        "active_skill_entries": [{"name": "Raise Spectre", "source_gem_entry_id": "g1", "minion_skill_name": minion_skill,
                                  "support_links": [{"name": n} for n in supports]}]}]}}


@pytest.mark.parametrize("state", [
    {},  # no skills surface
    _state(None, ["Greater Volley"]),  # the main skill summons no minion skill PoB names
    _state("Cold Projectile", ["Greater Volley"]),  # a spectre skill that is no mortar
    _state("Ice Mortar", ["Faster Casting"]),  # a mortar without Volley
])
def test_no_pob_call_and_no_change_when_the_fact_does_not_act(state) -> None:
    assert spectre_overlap_stats(_Stub(state)) is None


class _Fake:
    """A session with a loaded XML: `calc` answers from the Raise Spectre count in the XML it holds, so the
    transcript of loads shows the count PoB is asked at."""

    XML = ('<PathOfBuilding><Skills activeSkillSet="2"><SkillSet id="2"><Skill label="a">'
           '<Gem nameSpec="Raise Spectre" count="4"/></Skill></SkillSet></Skills></PathOfBuilding>')

    def __init__(self, state):
        self._state, self.xml, self.loads, self.reads = state, self.XML, [], []

    def read_state(self):
        return self._state

    def export_xml(self):
        return self.xml

    def load_xml(self, xml):
        self.xml = xml
        self.loads.append(int(re.search(r'count="(\d+)"', xml).group(1)))

    def calc(self, lane):
        count = int(re.search(r'count="(\d+)"', self.xml).group(1))
        self.reads.append((lane, count))
        return {"FullDPS": (100.0 if lane == "baseline" else 150.0) * count}


def test_both_lanes_are_read_at_count_times_the_projectiles_and_the_build_is_loaded_back() -> None:
    pob = _Fake(_state("Ice Mortar", ["Greater Volley Support"]))
    reading = spectre_overlap_stats(pob, {"FullDPS": 400.0})
    assert reading.conservative == {"FullDPS": 2000.0} and reading.optimistic == {"FullDPS": 3000.0}  # 4 x 5 = 20, not 100
    assert sorted(pob.reads) == [("baseline", 20), ("conditional", 20)]
    assert pob.loads == [20, 4] and pob.xml == _Fake.XML  # one scaled read, then the delivered build back
    assert "+400.0%" in reading.note and "400 -> 2,000" in reading.note


def test_volley_support_scales_by_three_on_both_lanes() -> None:
    pob = _Fake(_state("Ice Mortar", ["Volley Support"]))
    reading = spectre_overlap_stats(pob, {"FullDPS": 400.0})
    assert (reading.conservative["FullDPS"], reading.optimistic["FullDPS"]) == (1200.0, 1800.0)


def test_while_pending_only_the_optimistic_lane_is_scaled(monkeypatch) -> None:
    _set(monkeypatch, status="pending")
    pob = _Fake(_state("Ice Mortar", ["Greater Volley Support"]))
    reading = spectre_overlap_stats(pob, {"FullDPS": 400.0})
    assert reading.conservative is None and reading.optimistic == {"FullDPS": 3000.0}
    assert "would move the conservative number by" in reading.note


def test_the_count_edit_touches_only_that_gem_tag() -> None:
    xml = ('<PathOfBuilding><Skills activeSkillSet="2"><SkillSet id="2"><Skill label="a"><Gem nameSpec="X" count="1"/></Skill>'
           '<Skill label="b"><Gem nameSpec="Y" count="1"/><Gem nameSpec="Raise Spectre" count="4"/></Skill></SkillSet></Skills></PathOfBuilding>')
    out = spectre_overlap._with_gem_count(xml, "skills.2.socket_group.2", 2, "Raise Spectre", 4, 20)
    assert out == xml.replace('nameSpec="Raise Spectre" count="4"', 'nameSpec="Raise Spectre" count="20"')
    with pytest.raises(RuntimeError):
        spectre_overlap._with_gem_count(xml, "skills.2.socket_group.2", 2, "Raise Spectre", 5, 20)
