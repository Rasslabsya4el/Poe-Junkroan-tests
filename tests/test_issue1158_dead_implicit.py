"""#1158 unit 1: the audit removes each gear item's implicit in PoB and flags a dead one.

The PoB-free half uses a fake session: the raw helper, the 0.1 % rule on both the objective and TotalEHP,
the slot filter (tree-socket jewels cannot take a trial item) and the finding text. The `pob` half decodes
A2 (the Void Sceptre under Contagion) and A1 (the Prophecy Wand) and checks the flag on each.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_dead_implicits
from junkroan.optimizer.dead_implicit import IMPLICIT_SLOTS, dead_implicits, implicit_removals, raw_without_implicits
from junkroan.optimizer.objective import Objective

PROJECT_ROOT = Path(__file__).resolve().parents[1]
A1 = PROJECT_ROOT / "artifacts" / "search-contagion" / "20261015-0336" / "01 witch_occultist_no_iron_will_prophecy_wand.pob.txt"
A2 = PROJECT_ROOT / "artifacts" / "search-contagion" / "20261015-0336" / "02 witch_occultist_void_sceptre.pob.txt"
OBJECTIVE = Objective(maximize="CombinedDPS")
BASE = {"CombinedDPS": 1000.0, "TotalEHP": 5000.0}

UNIQUE_SCEPTRE = """Rarity: UNIQUE
Void Sceptre
Imbued Wand
Implicits: 1
40% increased Elemental Damage
Adds 10 to 20 Physical Damage
Quality: 20
"""


def _rare(base: str, implicits: list[str], mods: list[str] = ()) -> str:
    head = f"Rarity: RARE\nGrim Bane\n{base}\n"
    if not implicits:
        return head + "Implicits: 0\n" + "\n".join(mods) + "\n"
    return head + f"Implicits: {len(implicits)}\n" + "\n".join(implicits) + "\n" + "\n".join(mods) + "\n"


class _FakePob:
    """`equipped_item_raws`, `stats` and `trial_stats` only. `removals[slot] = (objective change, TotalEHP change)`
    as fractions; each trial must carry the item with its implicit removed, and nothing else changed."""

    def __init__(self, raws: dict[str, str], removals: dict[str, tuple[float, float]], *, outcome_ok: bool = True) -> None:
        self.raws = dict(raws)
        self.removals = removals
        self.outcome_ok = outcome_ok
        self.trial_calls: list[tuple[list, tuple, str]] = []

    def equipped_item_raws(self) -> dict[str, str]:
        return dict(self.raws)

    def stats(self, keys) -> dict:
        return {k: BASE[k] for k in keys if k in BASE}

    def trial_stats(self, trials, keys, *, mode="full") -> list[dict]:
        self.trial_calls.append((list(trials), tuple(keys), mode))
        out = []
        for trial in trials:
            slot = trial["item"]["slot"]
            assert trial["item"]["raw"] == raw_without_implicits(self.raws[slot])
            obj, ehp = self.removals[slot]
            stats = {**BASE, "CombinedDPS": BASE["CombinedDPS"] * (1 + obj), "TotalEHP": BASE["TotalEHP"] * (1 + ehp)}
            out.append({"ok": self.outcome_ok, "error": None if self.outcome_ok else "boom", "stats": stats})
        return out


# -- the raw helper -----------------------------------------------------------------------------------------------

def test_the_implicit_lines_go_and_the_header_reads_zero_every_other_line_is_kept() -> None:
    expected = ("Rarity: UNIQUE\nVoid Sceptre\nImbued Wand\nImplicits: 0\n"
                "Adds 10 to 20 Physical Damage\nQuality: 20\n")
    assert raw_without_implicits(UNIQUE_SCEPTRE) == expected


def test_two_implicit_lines_are_both_removed() -> None:
    raw = _rare("Hubris Circlet", ["+10% to Fire Resistance", "+20 to Intelligence"], ["Some Mod"])
    assert raw_without_implicits(raw) == "Rarity: RARE\nGrim Bane\nHubris Circlet\nImplicits: 0\nSome Mod\n"


def test_a_raw_with_no_implicit_gives_none() -> None:
    assert raw_without_implicits("Rarity: RARE\nGrim Bane\nHubris Circlet\nImplicits: 0\nSome Mod\n") is None
    assert raw_without_implicits("Rarity: RARE\nGrim Bane\nHubris Circlet\nSome Mod\n") is None


# -- the rule ----------------------------------------------------------------------------------------------------

def test_the_zero_point_one_percent_rule_needs_both_stats_under_it() -> None:
    raws = {
        "Helmet": _rare("Hubris Circlet", ["+10% to Fire Resistance"]),      # nothing moves: dead
        "Body Armour": _rare("Glorious Plate", ["+30 to Armour"]),            # 0.5 % objective: live
        "Ring 1": _rare("Opal Ring", ["+5 to Strength"]),                      # 0.2 % TotalEHP alone: live
        "Amulet": _rare("Onyx Amulet", ["+8% to Chaos Resistance"]),           # under 0.1 % on both: dead
    }
    pob = _FakePob(raws, {
        "Helmet": (0.0, 0.0),
        "Body Armour": (0.005, 0.0),
        "Ring 1": (0.0, 0.002),
        "Amulet": (0.0004, -0.0009),
    })
    rows = dead_implicits(pob, objective=OBJECTIVE)
    assert [r.slot for r in rows] == ["Helmet", "Amulet"]
    assert rows[1].judged_change == pytest.approx(0.0004)
    assert rows[1].ehp_change == pytest.approx(-0.0009)
    assert rows[1].implicit == "+8% to Chaos Resistance"
    assert rows[1].base == "Onyx Amulet"


def test_only_gear_slots_with_an_implicit_are_trialled() -> None:
    raws = {
        "Helmet": _rare("Hubris Circlet", ["+10% to Fire Resistance"]),
        "Body Armour": _rare("Glorious Plate", []),                        # no implicit: never trialled
        "Flask 1": _rare("Divine Life Flask", ["+1 to Charges"]),          # not a gear slot
        "Jewel 1": _rare("Ruby", ["+5 to Strength"]),                      # tree-socket jewel: the worker refuses it
    }
    pob = _FakePob(raws, {"Helmet": (0.0, 0.0), "Body Armour": (0.0, 0.0), "Flask 1": (0.0, 0.0), "Jewel 1": (0.0, 0.0)})
    dead_implicits(pob, objective=OBJECTIVE)
    trialled = [t["item"]["slot"] for call in pob.trial_calls for t in call[0]]
    assert trialled == ["Helmet"]
    assert set(IMPLICIT_SLOTS) >= {"Weapon 1", "Weapon 2", "Helmet", "Body Armour", "Gloves", "Boots", "Amulet", "Ring 1", "Ring 2", "Belt"}
    assert all(call[2] == "full" for call in pob.trial_calls)  # a real removal, as the ascendancy check does


def test_no_implicit_anywhere_runs_no_trial() -> None:
    pob = _FakePob({"Helmet": _rare("Hubris Circlet", [])}, {"Helmet": (0.0, 0.0)})
    assert dead_implicits(pob, objective=OBJECTIVE) == []
    assert pob.trial_calls == []


def test_a_failed_removal_trial_raises() -> None:
    pob = _FakePob({"Helmet": _rare("Hubris Circlet", ["+10% to Fire Resistance"])}, {"Helmet": (0.0, 0.0)}, outcome_ok=False)
    with pytest.raises(RuntimeError, match="Helmet"):
        dead_implicits(pob, objective=OBJECTIVE)


# -- the audit check ---------------------------------------------------------------------------------------------

def test_the_audit_reports_the_slot_base_and_implicit_line_as_a_warning() -> None:
    pob = _FakePob({"Helmet": _rare("Hubris Circlet", ["+10% to Fire Resistance"])}, {"Helmet": (0.0, 0.0)})
    findings = audit_dead_implicits(pob, OBJECTIVE)
    assert len(findings) == 1
    f = findings[0]
    assert f.check == "dead implicit" and f.severity == "warning"
    assert "Helmet" in f.detail and "Hubris Circlet" in f.detail and "+10% to Fire Resistance" in f.detail
    assert "0.1%" in f.detail


def test_the_finding_text_takes_its_share_from_the_constant(monkeypatch) -> None:
    from junkroan.optimizer import dead_implicit

    monkeypatch.setattr(dead_implicit, "DEAD_IMPLICIT_SHARE", 0.005)
    pob = _FakePob({"Helmet": _rare("Hubris Circlet", ["+10% to Fire Resistance"])}, {"Helmet": (0.002, 0.0)})
    findings = audit_dead_implicits(pob, OBJECTIVE)
    assert len(findings) == 1 and "0.5%" in findings[0].detail and "0.1%" not in findings[0].detail


# -- the decoded builds (PoB) ------------------------------------------------------------------------------------

@pytest.mark.pob
def test_the_audit_flags_the_void_sceptre_implicit_on_A2_and_passes_the_prophecy_wand_on_A1() -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="issue1158-dead-implicit") as pob:
        pob.load_xml(decode_import_code(A2.read_text(encoding="utf-8").strip()))
        removals_a2 = implicit_removals(pob, objective=None)
        findings_a2 = audit_dead_implicits(pob, None)
        pob.load_xml(decode_import_code(A1.read_text(encoding="utf-8").strip()))
        removals_a1 = implicit_removals(pob, objective=None)
        findings_a1 = audit_dead_implicits(pob, None)
    print("\nA2 implicit removals (all gear implicits):", [(r.slot, r.base, r.implicit, f"{r.judged_change:+.4%}", f"{r.ehp_change:+.4%}", r.dead) for r in removals_a2])
    print("A1 implicit removals (all gear implicits):", [(r.slot, r.base, r.implicit, f"{r.judged_change:+.4%}", f"{r.ehp_change:+.4%}", r.dead) for r in removals_a1])
    sceptre = next(r for r in removals_a2 if r.slot == "Weapon 1")
    wand = next(r for r in removals_a1 if r.slot == "Weapon 1")
    assert sceptre.base == "Void Sceptre" and sceptre.implicit == "40% increased Elemental Damage" and sceptre.dead
    assert any("Void Sceptre" in f.detail and "40% increased Elemental Damage" in f.detail for f in findings_a2)
    assert wand.base == "Prophecy Wand" and wand.implicit == "38% increased Spell Damage" and not wand.dead
    assert not any("Prophecy Wand" in f.detail for f in findings_a1)
