"""Researched facts the user has not approved (D62, `mechanics/pending_facts.json`).

Three things are tested: the store loads and validates; each hook acts on the optimistic lane
only while its fact is pending and on both once it is approved (and on neither when disputed);
and, PoB in the loop, the two implemented facts on the builds they move -- Trauma on
`static_strike` with the Trauma Support our s3 took, Perforate's overlap on `bleed_perforate`.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from junkroan.mechanics import pending_facts
from junkroan.mechanics.pending_facts import PendingFact, fact, lane_value, load_facts, would_move
from junkroan.optimizer.ramp_inputs import BuildFacts, Gem, LONG_FIGHT, PERFORATE_FACT, perforate_spike_overlap
from junkroan.optimizer.self_cost import TRAUMA_FACT, TRAUMA_STAT, context_for, self_cost_per_second, trauma_lane_note, trauma_self_hit
from junkroan.pob.skill_facts import SKILL_DATA_DIRS, effectiveness_stat

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
needs_skill_data = pytest.mark.skipif(not SKILL_DATA_DIRS[0].is_dir(), reason=f"PoB skill data not present at {SKILL_DATA_DIRS[0]}")


@pytest.fixture
def status(monkeypatch):
    """Set one fact's status for a test ("pending" / "approved" / "disputed"), which is the one-word
    edit the user makes to approve a fact."""

    def _set(fact_id: str, new: str) -> None:
        facts = {k: (replace(v, status=new) if k == fact_id else v) for k, v in load_facts().items()}
        monkeypatch.setattr(pending_facts, "load_facts", lambda *_a, **_k: facts)

    return _set


# -- the store ------------------------------------------------------------------------------------


def test_every_record_carries_a_source_a_status_and_a_hook() -> None:
    facts = load_facts()
    assert facts, "the store is empty"
    for rec in facts.values():
        assert rec.status in pending_facts.STATUSES
        assert rec.sources, rec.id
        assert rec.plug_in, f"{rec.id}: a fact names its hook or it is not stored (D62)"
        assert rec.added in {"2026-09-18", "2026-09-19", "2026-10-04"}
        assert rec.value is not None or rec.range or rec.id == "enemy_hits_per_second", f"{rec.id}: neither a number nor a range"
        if rec.disputed:
            assert rec.range and rec.disagreement, f"{rec.id}: a disputed fact carries its range and the disagreement"


def test_a_fact_without_a_source_or_with_an_unknown_status_does_not_load(tmp_path: Path) -> None:
    def store(**over):
        rec = {"id": "x", "fact": "f", "value": 1, "unit": "u", "sources": ["https://example.invalid"],
               "confidence": "high", "status": "pending", "plug_in": "p", "added": "2026-09-18", **over}
        path = tmp_path / f"{len(list(tmp_path.iterdir()))}.json"
        path.write_text(json.dumps({"facts": [rec]}), encoding="utf-8")
        return str(path)

    load_facts.cache_clear()
    assert load_facts(store())["x"].value == 1.0
    for bad in ({"sources": []}, {"status": "probably"}, {"id": ""}, {"status": "disputed"}):
        load_facts.cache_clear()
        with pytest.raises(ValueError):
            load_facts(store(**bad))
    load_facts.cache_clear()


@pytest.mark.parametrize("state,conservative,optimistic", [("pending", False, True), ("approved", True, True), ("disputed", False, False)])
def test_the_lanes_a_state_acts_on(state: str, conservative: bool, optimistic: bool) -> None:
    rec = PendingFact(id="x", fact="f", value=3, unit="u", sources=("s",), confidence="high", status=state, plug_in="p", added="2026-09-18")
    assert rec.applies("conservative") is conservative
    assert rec.applies("optimistic") is optimistic
    assert rec.binding is conservative
    with pytest.raises(ValueError):
        rec.applies("mapping")


def test_lane_value_names_the_fact_and_its_state(status) -> None:
    status(PERFORATE_FACT, "pending")
    assert lane_value(PERFORATE_FACT, "optimistic", 7, 3)[0] == 3
    assert lane_value(PERFORATE_FACT, "conservative", 7, 3)[0] == 7
    assert PERFORATE_FACT in lane_value(PERFORATE_FACT, "conservative", 7, 3)[1]
    status(PERFORATE_FACT, "approved")
    assert lane_value(PERFORATE_FACT, "conservative", 7, 3)[0] == 3
    status(PERFORATE_FACT, "disputed")
    assert lane_value(PERFORATE_FACT, "optimistic", 7, 3)[0] == 7
    assert lane_value("no.such.fact", "optimistic", 7, 3) == (7, "")


def test_would_move_reports_a_percentage_of_the_conservative_number() -> None:
    note = would_move(TRAUMA_FACT, 120.0, -3_500.0, "idle recovery per second")
    assert "would move the conservative number by -3016.7%" in note and TRAUMA_FACT in note


# -- Trauma: the number is PoB's, the mechanic is the fact -----------------------------------------


@needs_skill_data
def test_pob_carries_the_per_stack_number_and_the_report_confirms_it() -> None:
    """PoB writes the self-damage as a damage-effectiveness stat and maps it to nothing; the value
    it interpolates at level 20, 146, is the number the research quotes (game-knowledge.md 8)."""

    rec = fact(TRAUMA_FACT)
    assert rec is not None and rec.value == 146 and rec.param("duration_seconds") == 6.9
    assert effectiveness_stat("SupportTrauma", TRAUMA_STAT, 20) == rec.value
    assert effectiveness_stat("SupportTrauma", TRAUMA_STAT, 18) == 126, "the rails' gem level"
    assert effectiveness_stat("Boneshatter", TRAUMA_STAT, 20), "innate Trauma carries the same stat"
    assert effectiveness_stat("SupportTrauma", "support_trauma_base_duration_ms", 20) is None, "not an effectiveness stat"
    from junkroan.pob.skill_facts import _blocks

    block = _blocks()["SupportTrauma"]
    statmap = block[block.find("statMap"):block.find("baseMods")]
    assert TRAUMA_STAT not in statmap, "PoB parses the number and maps it to no modifier: it is in no PoB stat"


@needs_skill_data
def test_the_trauma_self_hit_is_per_stack_times_stacks() -> None:
    assert trauma_self_hit([("SupportTrauma", 20)], 6)[0] == 146 * 6
    assert trauma_self_hit([("Boneshatter", 20), ("SupportMeleePhysicalDamage", 20)], 4)[0] == effectiveness_stat("Boneshatter", TRAUMA_STAT, 20) * 4
    assert trauma_self_hit([("SupportTrauma", 20)], 0) is None, "no stacks, no hit"
    assert trauma_self_hit([("Spark", 20)], 6) is None, "nothing in the link applies Trauma"


@needs_skill_data
def test_trauma_is_charged_only_once_the_fact_is_approved(status) -> None:
    """static_strike s3 (the user's reading): our build took Trauma Support and paid 752 physical
    damage per attack that PoB counts nowhere. Pending, the conservative number is untouched and
    the build carries the note; approved, the cost is in `SelfCostPerSecond` and the idle-recovery
    floor prices it."""

    stats = {"Life": 3478, "EnergyShield": 0, "LifeUnreserved": 3478, "Speed": 3.0, "HitSpeed": 3.0,
             "NetLifeRegen": 220.0, "NetEnergyShieldRegen": 0.0}
    link, stacks = [("StaticStrike", 18), ("SupportTrauma", 18)], 6
    per_hit = 126 * stacks  # 756, the user's 752 at their own gem level

    status(TRAUMA_FACT, "pending")
    ctx = context_for("", frozenset({"attack", "melee"}), main_triggered=False, main_gems=["Static Strike", "Trauma"], gem_levels=link, trauma_stacks=stacks)
    assert ctx.per_hit == 0.0 and self_cost_per_second(stats, ctx) == 0.0, "an unapproved fact never moves the conservative number"
    note = trauma_lane_note(stats, link, stacks)
    assert "would move the conservative number by" in note and "126 physical damage per stack" in note

    status(TRAUMA_FACT, "approved")
    ctx = context_for("", frozenset({"attack", "melee"}), main_triggered=False, main_gems=["Static Strike", "Trauma"], gem_levels=link, trauma_stacks=stacks)
    assert ctx.per_hit == per_hit and TRAUMA_FACT in ctx.per_hit_why
    assert self_cost_per_second(stats, ctx) == -per_hit * 3.0
    assert trauma_lane_note(stats, link, stacks) == "", "approved: it is in the number, not in a note"

    status(TRAUMA_FACT, "disputed")
    assert context_for("", frozenset(), main_triggered=False, gem_levels=link, trauma_stacks=stacks).per_hit == 0.0
    assert trauma_lane_note(stats, link, stacks) == ""


@needs_skill_data
def test_a_triggered_skill_pays_no_trauma(status) -> None:
    status(TRAUMA_FACT, "approved")
    ctx = context_for("", frozenset({"attack"}), main_triggered=True, gem_levels=[("SupportTrauma", 20)], trauma_stacks=6)
    assert ctx.per_hit == 0.0, "the player is not the one attacking"


@needs_skill_data
def test_the_trauma_cost_rides_on_the_hit_rate_beside_a_pool_cost(status) -> None:
    """The two kinds add: a share of a pool per use (Sacrifice) at the cast rate, and a flat hit
    per attack hit at the hit rate."""

    status(TRAUMA_FACT, "approved")
    ctx = context_for("", frozenset({"attack"}), main_triggered=False, main_gems=["Sacrifice"], gem_levels=[("SupportTrauma", 20)], trauma_stacks=2)
    stats = {"LifeUnreserved": 4000, "Speed": 2.0, "HitSpeed": 5.0}
    assert self_cost_per_second(stats, ctx) == -(0.2 * 4000 * 2.0 + 146 * 2 * 5.0)


# -- Perforate: a ceiling on the optimistic lane ----------------------------------------------------


def _overlap(budget: float):
    facts = BuildFacts(stats={"Speed": 3.0}, budget=budget, gems=(Gem(name="perforate", effect_id="Perforate", level=18),), main_effect_id="Perforate", stance="BLOOD")
    return perforate_spike_overlap(facts)


@needs_skill_data
def test_the_optimistic_lane_stops_at_the_overlaps_a_boss_can_take(status) -> None:
    """PoB's cap is the gem's spike count (7 at the rails' level) and that is what the optimistic
    lane held; both reports say a boss takes about three. The conservative lane keeps its 1, so
    approving the fact cannot move the number we deliver."""

    status(PERFORATE_FACT, "pending")
    value, why = _overlap(LONG_FIGHT)
    assert value == 3 and PERFORATE_FACT in why
    assert _overlap(2.5)[0] == 1, "the conservative lane is mechanics/notes.json's 1"

    status(PERFORATE_FACT, "approved")
    assert _overlap(LONG_FIGHT)[0] == 3
    assert _overlap(2.5)[0] == 1, "approving a ceiling above the conservative value moves nothing"

    status(PERFORATE_FACT, "disputed")
    assert _overlap(LONG_FIGHT)[0] == 7, "off: PoB's own cap, as before the fact"


@needs_skill_data
def test_sand_stance_has_no_overlap_in_either_lane(status) -> None:
    status(PERFORATE_FACT, "pending")
    facts = BuildFacts(stats={"Speed": 3.0}, budget=LONG_FIGHT, gems=(Gem(name="perforate", effect_id="Perforate", level=18),), stance="SAND")
    assert perforate_spike_overlap(facts)[0] == 0


# -- PoB in the loop: the references each fact moves -------------------------------------------------


# the stats the idle-recovery relation of the rails is made of (D63.3: no leech, no recoup)
RECOVERY_KEYS = ("LifeRegen", "NetLifeRegen", "NetEnergyShieldRegen", "TotalDegen")


@pytest.mark.pob
@needs_pob
def test_the_two_facts_on_the_references_they_move(tmp_path: Path) -> None:
    """One session for both.

    Trauma on `static_strike`, the build the reading found it on (our s3 took Trauma Support where
    the author has none): PoB shows the `traumaStacks` option, the number rises with the stacks --
    and every recovery stat PoB has is byte-identical at 0, 6 and 20 stacks, which is the fact's
    claim: PoB counts the self-damage nowhere. The hook then prices it.

    Perforate on `bleed_perforate`: what the optimistic lane was claiming with every spike against
    the fact's ceiling of three.
    """

    from junkroan.pob.session import PobSession, decode_import_code

    static = decode_import_code((PROJECT_ROOT / "tests/fixtures/tuadh_329/static_strike.pob.txt").read_text(encoding="utf-8").strip())
    perforate = decode_import_code((PROJECT_ROOT / "tests/fixtures/tuadh_329/bleed_perforate.pob.txt").read_text(encoding="utf-8").strip())
    keys = ("HitSpeed", "Speed", "Life", "CombinedDPS", *RECOVERY_KEYS)
    with PobSession(run_id="test-pending-facts", artifacts_root=tmp_path) as pob:
        pob.load_xml(static)
        author = pob.stats(keys)
        pob.set_skills(main_link=["Static Strike", "Trauma", "Melee Physical Damage", "Multistrike"], slot="Body Armour", level=18, quality=0, main_quality=0)
        shown = {str(o.get("var")) for o in pob.config_options({}) if o.get("shown")}
        with_trauma = {}
        for stacks in (0, 6, 20):
            pob.set_config(inputs={"traumaStacks": stacks}, preserve="numeric")
            with_trauma[stacks] = pob.stats(keys)
        pob.load_xml(perforate)
        overlap = {}
        for spikes in (1, 3, 7):
            pob.set_config(inputs={"bloodSandStance": "BLOOD", "perforateSpikeOverlap": spikes}, preserve="numeric")
            overlap[spikes] = pob.stats(("CombinedDPS",))

    assert "traumaStacks" in shown, "PoB offers the option once Trauma is in the link (flag HasTrauma)"
    assert with_trauma[20]["CombinedDPS"] > with_trauma[0]["CombinedDPS"], "the stacks are pure gain in PoB's numbers"
    for key in RECOVERY_KEYS:  # the fact: none of PoB's recovery stats knows about the self-hit
        assert with_trauma[0].get(key) == with_trauma[6].get(key) == with_trauma[20].get(key), key

    per_hit = trauma_self_hit([("StaticStrike", 18), ("SupportTrauma", 18)], 6)
    assert per_hit is not None and per_hit[0] == 126 * 6, per_hit  # the reading measured 752 on our s3
    rate = with_trauma[6].get("HitSpeed") or with_trauma[6]["Speed"]
    recovery = float(author.get("NetLifeRegen") or 0.0) + float(author.get("NetEnergyShieldRegen") or 0.0)
    assert recovery > 0 > recovery - per_hit[0] * rate, "the idle-recovery floor flips: that is what approval would do"
    note = trauma_lane_note({**with_trauma[6], **{k: author[k] for k in ("NetLifeRegen", "NetEnergyShieldRegen") if k in author}},
                            [("StaticStrike", 18), ("SupportTrauma", 18)], 6)
    assert "would move the conservative number by" in note and "756 taken on every attack hit" in note, note

    assert overlap[7]["CombinedDPS"] > overlap[3]["CombinedDPS"] > overlap[1]["CombinedDPS"], overlap
    assert overlap[3]["CombinedDPS"] < 0.6 * overlap[7]["CombinedDPS"], "the ceiling retires about half the optimistic claim"


def test_reason_names_the_facts_own_added_date() -> None:
    rec = PendingFact(id="x_fact", fact="f", value=None, unit="", sources=("s",), confidence="low",
                      status="pending", plug_in="p", added="2026-10-04")
    assert rec.reason().startswith("pending fact x_fact (research 2026-10-04)")


def test_every_shipped_reason_carries_only_its_own_date() -> None:
    import re

    for rec in load_facts().values():
        dates = re.findall(r"\(research (\d{4}-\d{2}-\d{2})\)", rec.reason())
        assert f"(research {rec.added})" in rec.reason()
        assert dates == [rec.added]
