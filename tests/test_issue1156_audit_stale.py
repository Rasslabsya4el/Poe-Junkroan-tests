"""#1156 audit row 3: the empty-socket check on a build whose skeleton is older than the build.

The delivered build holds a gem group the fill step added (Summon Skitterbots on Gloves) that a stored skeleton (the search
build's sidecar JSON) does not list. Measured on the stale skeleton, the check wrote the build's skills back without that
gem and offered the same gem again for the same socket (old A1 +12.50%, new A1 +12.50%). The check now takes the groups the
build holds from PoB's readback, so a gem already placed is neither lost from the base nor offered again.
"""

from __future__ import annotations

import json
from pathlib import Path

from junkroan.optimizer.audit import audit_empty_sockets, skeleton_beside
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.search.skeleton import Skeleton

OBJECTIVE = Objective(maximize="CombinedDPS", floors={"Life": 100.0})
PRICE = {"Haste": (0.060, 0.0), "Tiny": (0.0, 0.004)}  # objective share, TotalEHP share a gem adds


class _Pob:
    """The fake PoB boundary of tests/test_issue1156_audit.py, with the built groups in the skills readback."""

    def __init__(self, free: dict[str, list[str]], built: dict[str, list[str]]) -> None:
        self.free, self.built = free, built
        self.base_xml = "<PathOfBuilding>the delivered build</PathOfBuilding>"
        self.payloads: list[dict] = []
        self.gems: list[str] = []

    def read_state(self) -> dict:
        slots = {slot: {"item": {"sockets": [{"color": c} for c in colours]}} for slot, colours in self.free.items()}
        groups = [{"slot": slot, "label": gem, "enabled": True, "gems": [{"gem_name": gem, "enabled": True}]}
                  for slot, gems in self.built.items() for gem in gems]
        return {"items_state": {"slots": slots}, "skills_state": {"socket_groups": groups}}

    def export_xml(self) -> str:
        return self.base_xml

    def load_xml(self, xml: str) -> None:
        self.gems = [g for gems in self.built.values() for g in gems]

    def set_skills(self, **kwargs) -> None:
        self.payloads.append(kwargs)
        self.gems = [gem["gem_name"] for group in kwargs["extra_groups"] for gem in group["gems"]]

    def stats(self, keys) -> dict:
        dps = sum(PRICE.get(g, (0.0, 0.0))[0] for g in self.gems)
        ehp = sum(PRICE.get(g, (0.0, 0.0))[1] for g in self.gems)
        return {key: 0.0 for key in keys} | {"CombinedDPS": 1000.0 * (1 + dps), "TotalEHP": 10000.0 * (1 + ehp),
                                             "ManaUnreserved": 500.0, "LifeUnreserved": 100.0, "Life": 100.0}


def _stale_skeleton() -> Skeleton:
    return Skeleton(class_name="Marauder", ascendancy="Juggernaut", main_link=["Cleave"], extra_groups=[])


def _patch(monkeypatch, candidates: set[str]) -> None:
    from junkroan.search.generator import SkeletonGenerator

    monkeypatch.setattr("junkroan.search.generator.fill_candidate_names", lambda: frozenset(candidates))
    monkeypatch.setattr("junkroan.optimizer.empty_socket.gem_colour", lambda name: None)
    monkeypatch.setattr(SkeletonGenerator, "_reserve_pools", staticmethod(lambda name: frozenset()))


def test_a_gem_the_build_holds_but_the_skeleton_lacks_is_not_offered_again(monkeypatch) -> None:
    _patch(monkeypatch, {"Haste", "Tiny"})
    pob = _Pob({"Helmet": ["W", "W"]}, built={"Helmet": ["Haste"]})

    findings = audit_empty_sockets(pob, _stale_skeleton(), Rails.load(), OBJECTIVE)

    assert findings == [], "Haste (+6.00%) is already on the Helmet; Tiny (+0.40% TotalEHP) is under the keep rule"
    trials = [[g["gem_name"] for grp in p["extra_groups"] for g in grp["gems"]] for p in pob.payloads]
    assert trials[0] == ["Haste"], "the base keeps the gem the build holds"
    assert trials[1:] == [["Haste", "Tiny"]], "the only trial adds Tiny, never a second Haste"


def test_the_gem_group_of_the_build_keeps_its_slot_and_label(monkeypatch) -> None:
    _patch(monkeypatch, {"Tiny"})
    pob = _Pob({"Helmet": ["W", "W"]}, built={"Helmet": ["Haste"]})

    audit_empty_sockets(pob, _stale_skeleton(), Rails.load(), OBJECTIVE)

    group = pob.payloads[0]["extra_groups"][0]
    assert (group["slot"], group["label"], group["enabled"]) == ("Helmet", "Haste", True)


def test_a_skeleton_that_already_lists_the_gem_is_measured_as_before(monkeypatch) -> None:
    from junkroan.search.skeleton import SocketGroup

    _patch(monkeypatch, {"Haste", "Tiny"})
    pob = _Pob({"Helmet": ["W", "W"]}, built={"Helmet": ["Haste"]})
    skeleton = _stale_skeleton()
    skeleton.extra_groups = [SocketGroup(gems=["Haste"], slot="Helmet", label="Haste", picked=True)]

    audit_empty_sockets(pob, skeleton, Rails.load(), OBJECTIVE)

    assert [len(p["extra_groups"]) for p in pob.payloads] == [1, 2], "no group is added twice"
    assert skeleton.extra_groups[0].gems == ["Haste"] and len(skeleton.extra_groups) == 1, "the caller's skeleton is not changed"


def test_skeleton_beside_a_search_build_reads_its_sidecar_json(tmp_path: Path) -> None:
    skeleton = Skeleton(class_name="Witch", ascendancy="Occultist", main_link=["Contagion"], extra_groups=[])
    (tmp_path / "01 witch.json").write_text(json.dumps({"skeleton": skeleton.to_json()}), encoding="utf-8")
    (tmp_path / "01 witch.pob.txt").write_text("code", encoding="utf-8")
    (tmp_path / "02 lone.xml").write_text("<x/>", encoding="utf-8")

    loaded = skeleton_beside(tmp_path / "01 witch.pob.txt")

    assert loaded is not None and loaded.ascendancy == "Occultist" and loaded.main_link == ["Contagion"]
    assert skeleton_beside(tmp_path / "02 lone.xml") is None, "a replayed .xml has no sidecar: the check stays off, not guessed"


def test_an_explicit_skeleton_file_wins_over_the_sidecar(tmp_path: Path) -> None:
    other = Skeleton(class_name="Templar", ascendancy="Inquisitor", main_link=["Searing Bond"], extra_groups=[])
    given = tmp_path / "given.json"
    given.write_text(json.dumps({"skeleton": other.to_json()}), encoding="utf-8")

    loaded = skeleton_beside(tmp_path / "02 lone.xml", given)

    assert loaded is not None and loaded.ascendancy == "Inquisitor"


def test_a_vaal_twin_of_a_listed_gem_is_not_a_missing_group(monkeypatch) -> None:
    from junkroan.search.skeleton import SocketGroup

    _patch(monkeypatch, {"Tiny"})
    pob = _Pob({"Helmet": ["W", "W"]}, built={"Helmet": ["Vaal Haste"]})
    skeleton = _stale_skeleton()
    skeleton.extra_groups = [SocketGroup(gems=["Haste"], slot="Helmet", label="Haste", picked=True)]

    audit_empty_sockets(pob, skeleton, Rails.load(), OBJECTIVE)

    assert [len(p["extra_groups"]) for p in pob.payloads] == [1, 2], "the delivered Vaal Haste is the skeleton's Haste, not a second group"


# -- the group held in a listed group, and the script's argv -------------------------------------------------------------

def test_a_gem_the_build_added_into_a_listed_group_is_kept_in_the_base_and_not_offered(monkeypatch) -> None:
    from junkroan.search.skeleton import SocketGroup

    _patch(monkeypatch, {"Haste", "Tiny"})
    pob = _Pob({"Helmet": ["W", "W", "W"]}, built={})
    pob.read_state = lambda: {  # the build's Helmet group holds Anger (listed) and Haste (placed by the fill step)
        "items_state": {"slots": {"Helmet": {"item": {"sockets": [{"color": "W"}] * 3}}}},
        "skills_state": {"socket_groups": [{"slot": "Helmet", "label": "Anger", "gems": [
            {"gem_name": "Anger", "enabled": True}, {"gem_name": "Haste", "enabled": True}]}]}}
    skeleton = _stale_skeleton()
    skeleton.extra_groups = [SocketGroup(gems=["Anger"], slot="Helmet", label="Anger", picked=True)]

    findings = audit_empty_sockets(pob, skeleton, Rails.load(), OBJECTIVE)

    assert findings == []
    trials = [[g["gem_name"] for grp in p["extra_groups"] for g in grp["gems"]] for p in pob.payloads]
    assert trials[0] == ["Anger", "Haste"], "the base keeps the gem the build holds in the listed group"
    assert trials[1:] == [["Anger", "Haste", "Tiny"]], "Haste is not offered again"
    assert skeleton.extra_groups[0].gems == ["Anger"], "the caller's group is not extended in place"


def test_a_group_with_no_slot_is_kept_not_dropped(monkeypatch) -> None:
    _patch(monkeypatch, {"Tiny"})
    pob = _Pob({"Helmet": ["W"]}, built={})
    pob.read_state = lambda: {
        "items_state": {"slots": {"Helmet": {"item": {"sockets": [{"color": "W"}]}}}},
        "skills_state": {"socket_groups": [{"label": "Haste", "gems": [{"gem_name": "Haste"}]}]}}

    audit_empty_sockets(pob, _stale_skeleton(), Rails.load(), OBJECTIVE)

    assert [g["gem_name"] for grp in pob.payloads[0]["extra_groups"] for g in grp["gems"]] == ["Haste"]


def _script():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "audit_build.py"
    spec = importlib.util.spec_from_file_location("audit_build_script_1156", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _no_pob(monkeypatch, module) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("PoB must not start on a bad command line")

    monkeypatch.setattr(module, "PobSession", boom)


def test_skeleton_with_two_build_paths_is_an_error_before_any_pob(monkeypatch, capsys) -> None:
    module = _script()
    _no_pob(monkeypatch, module)

    code = module.main(["--skeleton", "s.json", "a.xml", "b.xml"])

    assert code == 3 and "--skeleton" in capsys.readouterr().err


def test_skeleton_as_the_last_argument_is_an_error_not_an_index_error(monkeypatch, capsys) -> None:
    module = _script()
    _no_pob(monkeypatch, module)

    code = module.main(["a.xml", "--skeleton"])

    assert code == 3 and "--skeleton" in capsys.readouterr().err


def test_a_sidecar_without_a_skeleton_key_is_no_skeleton(tmp_path: Path) -> None:
    (tmp_path / "01 x.json").write_text(json.dumps({"seconds": 1.0}), encoding="utf-8")

    assert skeleton_beside(tmp_path / "01 x.pob.txt") is None


def test_the_script_runs_a_build_with_a_keyless_sidecar_and_says_no_skeleton(tmp_path: Path, monkeypatch, capsys) -> None:
    module = _script()
    (tmp_path / "01 x.json").write_text("{}", encoding="utf-8")
    build = tmp_path / "01 x.xml"
    build.write_text("<PathOfBuilding/>", encoding="utf-8")
    seen: list = []

    class _Session:
        def __init__(self, **kwargs) -> None: ...
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def load_xml(self, xml) -> None: ...

    monkeypatch.setattr(module, "PobSession", _Session)
    monkeypatch.setattr(module, "audit_build", lambda pob, **kwargs: seen.append(kwargs["skeleton"]) or [])

    assert module.main([str(build)]) == 0
    assert seen == [None] and "no skeleton" in capsys.readouterr().out
