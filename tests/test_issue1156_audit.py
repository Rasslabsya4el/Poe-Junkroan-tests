"""#1156 unit 2: the audit flags a delivered build whose free socket takes a candidate the fill step would keep.

(a) the pure decision (`kept_fill_candidate`, `empty_socket_detail`) on measured numbers: no PoB.
(b) the audit check (`audit_empty_sockets`, `audit_build`'s last term) on a fake PoB layer: the candidate is written
    through `set_skills` exactly as the fill step writes it, measured, and the build is loaded back from its own XML.
"""

from __future__ import annotations

from junkroan.optimizer.audit import audit_empty_sockets
from junkroan.optimizer.empty_socket import EMPTY_SOCKET_CHECK, FillMeasure, empty_socket_detail, kept_fill_candidate
from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.rails import Rails
from junkroan.search.skeleton import Skeleton

GAIN, MAX_LOSS = 0.005, 0.001  # the rails' fill_min_gain and fill_max_objective_loss (rails_default.json)
BASE = (Score(0.0, 1000.0), 10000.0)  # objective 1000, TotalEHP 10000, no floor missed
OBJECTIVE = Objective(maximize="CombinedDPS", floors={"Life": 100.0})


def _m(gem: str, objective: float, ehp: float, *, neg: float = 0.0, slot: str = "Helmet", colour: str = "W") -> FillMeasure:
    return FillMeasure(gem=gem, slot=slot, colour=colour, score=Score(neg, objective), ehp=ehp)


# -- (a) the pure decision ----------------------------------------------------------------------------------------------

def test_a_candidate_with_ehp_plus_0_6_and_objective_minus_0_05_is_a_finding() -> None:
    kept = kept_fill_candidate(BASE, [_m("Tempest Shield", 999.5, 10060.0)], gain=GAIN, max_loss=MAX_LOSS)
    assert kept is not None and kept.gem == "Tempest Shield"


def test_ehp_plus_0_3_with_a_flat_objective_is_no_finding() -> None:
    assert kept_fill_candidate(BASE, [_m("Tiny", 1000.0, 10030.0)], gain=GAIN, max_loss=MAX_LOSS) is None


def test_objective_minus_0_2_is_no_finding_even_with_ehp_plus_0_6() -> None:
    assert kept_fill_candidate(BASE, [_m("Costly", 998.0, 10060.0)], gain=GAIN, max_loss=MAX_LOSS) is None


def test_a_floor_that_gets_worse_is_no_finding() -> None:
    assert kept_fill_candidate(BASE, [_m("Fragile", 1000.0, 10600.0, neg=-0.01)], gain=GAIN, max_loss=MAX_LOSS) is None


def test_no_free_socket_means_no_measure_and_no_finding() -> None:
    assert kept_fill_candidate(BASE, [], gain=GAIN, max_loss=MAX_LOSS) is None


def test_the_best_passing_candidate_is_the_one_the_fill_step_would_keep() -> None:
    measures = [_m("Tempest Shield", 1000.0, 10300.0), _m("Haste", 1060.0, 10000.0), _m("Tiny", 1000.0, 10040.0)]
    kept = kept_fill_candidate(BASE, measures, gain=GAIN, max_loss=MAX_LOSS)
    assert kept is not None and kept.gem == "Haste", "by (Score, TotalEHP): the higher objective wins over the higher EHP"


def test_the_detail_names_slot_colour_gem_and_both_shares_as_pob_writes_them() -> None:
    assert empty_socket_detail(BASE, _m("Tempest Shield", 999.5, 10060.0)) == (
        "Helmet socket W fits Tempest Shield: TotalEHP +0.60% / objective -0.05%")


# -- (b) the audit check on a fake PoB layer ----------------------------------------------------------------------------

PRICE = {  # the fake PoB's price of a gem: (objective share added, TotalEHP share added)
    "Haste": (0.060, 0.0),
    "Tempest Shield": (0.0, 0.030),
    "Tiny": (0.0, 0.004),
}


class _Pob:
    """The PoB boundary the check touches: the sockets readback, the skills surface, stats, and load_xml as the revert."""

    def __init__(self, free: dict[str, list[str]]) -> None:
        self.free = free
        self.base_xml = "<PathOfBuilding>the delivered build</PathOfBuilding>"
        self.loads: list[str] = []
        self.payloads: list[dict] = []
        self.gems: list[str] = []  # the gems of the skills surface PoB holds now

    def read_state(self) -> dict:
        slots = {slot: {"item": {"sockets": [{"color": c} for c in colours]}} for slot, colours in self.free.items()}
        return {"items_state": {"slots": slots}, "skills_state": {"socket_groups": []}}

    def export_xml(self) -> str:
        return self.base_xml

    def load_xml(self, xml: str) -> None:
        self.loads.append(xml)
        self.gems = []

    def set_skills(self, **kwargs) -> None:
        self.payloads.append(kwargs)
        self.gems = [gem["gem_name"] for group in kwargs["extra_groups"] for gem in group["gems"]]

    def stats(self, keys) -> dict:
        dps = sum(PRICE.get(g, (0.0, 0.0))[0] for g in self.gems)
        ehp = sum(PRICE.get(g, (0.0, 0.0))[1] for g in self.gems)
        return {key: 0.0 for key in keys} | {
            "CombinedDPS": 1000.0 * (1 + dps), "TotalEHP": 10000.0 * (1 + ehp),
            "ManaUnreserved": 500.0, "LifeUnreserved": 100.0, "Life": 100.0,
        }


def _skeleton() -> Skeleton:
    return Skeleton(class_name="Marauder", ascendancy="Juggernaut", main_link=["Cleave"], extra_groups=[])


def _patch(monkeypatch, candidates: set[str], colour: dict[str, str] | None = None) -> None:
    from junkroan.search.generator import SkeletonGenerator

    monkeypatch.setattr("junkroan.search.generator.fill_candidate_names", lambda: frozenset(candidates))
    monkeypatch.setattr("junkroan.optimizer.empty_socket.gem_colour", lambda name: (colour or {}).get(name))
    monkeypatch.setattr(SkeletonGenerator, "_reserve_pools", staticmethod(lambda name: frozenset()))  # no reserving gem here


def test_a_kept_candidate_is_one_warning_finding_and_the_build_is_loaded_back(monkeypatch) -> None:
    _patch(monkeypatch, {"Haste", "Tiny", "Tempest Shield"})
    pob = _Pob({"Helmet": ["W"]})

    findings = audit_empty_sockets(pob, _skeleton(), Rails.load(), OBJECTIVE)

    assert len(findings) == 1
    f = findings[0]
    assert f.check == EMPTY_SOCKET_CHECK and f.severity == "warning"
    assert f.detail == "Helmet socket W fits Haste: TotalEHP +0.00% / objective +6.00%"
    assert str(f).startswith("[warning] empty-socket-with-candidate: ")
    assert len(pob.payloads) == 4, "the base surface and one trial per candidate that fits the socket"
    assert pob.loads == [pob.base_xml], "the trial is reverted from the build's own XML"


def test_a_candidate_that_would_not_be_kept_gives_no_finding(monkeypatch) -> None:
    _patch(monkeypatch, {"Tiny"})

    assert audit_empty_sockets(_Pob({"Helmet": ["W"]}), _skeleton(), Rails.load(), OBJECTIVE) == []


def test_no_free_socket_runs_no_trial(monkeypatch) -> None:
    _patch(monkeypatch, {"Haste"})
    pob = _Pob({})

    assert audit_empty_sockets(pob, _skeleton(), Rails.load(), OBJECTIVE) == []
    assert pob.payloads == [] and pob.loads == []


def test_without_a_skeleton_the_check_does_nothing(monkeypatch) -> None:
    _patch(monkeypatch, {"Haste"})
    pob = _Pob({"Helmet": ["W"]})

    assert audit_empty_sockets(pob, None, Rails.load(), OBJECTIVE) == []
    assert pob.payloads == []


def test_a_gem_whose_colour_fits_no_free_socket_is_never_trialled(monkeypatch) -> None:
    _patch(monkeypatch, {"Haste", "Tiny"}, colour={"Haste": "B"})
    pob = _Pob({"Helmet": ["R"]})

    assert audit_empty_sockets(pob, _skeleton(), Rails.load(), OBJECTIVE) == []
    assert all("Haste" not in [g["gem_name"] for grp in p["extra_groups"] for g in grp["gems"]] for p in pob.payloads)


# -- (c) audit_build includes the check ---------------------------------------------------------------------------------
# Every other term of audit_build is stubbed to [] (each has its own tests); what is measured here is only the last
# term's wiring: the check runs inside audit_build, the rail fill_step gates it, and a missing skeleton turns it off.

_OTHER_AUDITS = (
    "audit_xml", "audit_skeleton_uniques", "audit_stats", "audit_castability", "audit_ailment_stack_caps",
    "audit_average_damage", "audit_unsupported_mods", "audit_unsupported_gems", "audit_curse_limit", "audit_golem_limit",
    "audit_elemental_overload", "audit_forbidden_lines", "audit_conservative_generator_proofs", "audit_dead_tree_nodes",
    "audit_dead_implicits", "audit_duration", "audit_flask_uptime",
)


def _quiet_audit_build(monkeypatch) -> None:
    from types import SimpleNamespace

    import junkroan.optimizer.audit as audit

    for name in _OTHER_AUDITS:
        monkeypatch.setattr(audit, name, lambda *args, **kwargs: [])  # raising=True: a renamed term fails here
    monkeypatch.setattr(audit, "castability_context", lambda *args, **kwargs: SimpleNamespace(all_skills=(), skills=()))
    monkeypatch.setattr(audit, "with_castability_floors", lambda pob, objective, **kwargs: objective)
    monkeypatch.setattr(audit, "baseline_config_inputs", lambda xml: None)
    monkeypatch.setattr("junkroan.optimizer.random_parts.apply_mean_parts", lambda pob: None)


def test_audit_build_includes_the_empty_socket_finding(monkeypatch) -> None:
    from junkroan.optimizer.audit import audit_build

    _patch(monkeypatch, {"Haste", "Tiny", "Tempest Shield"})
    _quiet_audit_build(monkeypatch)
    pob = _Pob({"Helmet": ["W"]})

    findings = audit_build(pob, rails=Rails.load(), objective=OBJECTIVE, skeleton=_skeleton())

    assert len(findings) == 1
    assert str(findings[0]).startswith("[warning] empty-socket-with-candidate: ")
    assert "Haste" in findings[0].detail
    assert len(pob.payloads) == 4, "the base surface and one trial per candidate that fits the socket"


def test_audit_build_with_the_fill_step_rail_off_gives_no_empty_socket_finding(monkeypatch) -> None:
    import dataclasses

    from junkroan.optimizer.audit import audit_build

    _patch(monkeypatch, {"Haste", "Tiny", "Tempest Shield"})
    _quiet_audit_build(monkeypatch)
    pob = _Pob({"Helmet": ["W"]})
    rails = dataclasses.replace(Rails.load(), fill_step=False)

    findings = audit_build(pob, rails=rails, objective=OBJECTIVE, skeleton=_skeleton())

    assert findings == [] and pob.payloads == [], "the fill step never runs under the rail, so the check runs no trial"


def test_audit_build_without_a_skeleton_gives_no_empty_socket_finding(monkeypatch) -> None:
    from junkroan.optimizer.audit import audit_build

    _patch(monkeypatch, {"Haste", "Tiny", "Tempest Shield"})
    _quiet_audit_build(monkeypatch)
    pob = _Pob({"Helmet": ["W"]})

    findings = audit_build(pob, rails=Rails.load(), objective=OBJECTIVE, skeleton=None)

    assert findings == [] and pob.payloads == []
