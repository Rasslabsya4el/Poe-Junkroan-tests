"""#174: an open gear line that ends the build's WHOLE violation is bought, however small it is.

The build in the fixture is the one the loop delivered for
`z325_berserker_ground_slam_autocry` seed 4 of the run
`20260927-0322-ziz-tpl-main3-s4` (pipeline pinned at 42565a9): it misses the
rails' idle-recovery relation by `NetLifeRegen+NetEnergyShieldRegen+
SelfCostPerSecond = -15.6` against `Life = 7970`, which is only 0.00195 of
relative violation. Its Helmet (Aventail Helmet, ilvl 72) spent the template's
open_or_craft line on `Strength5` (+30 to Strength).

Measured in PoB v2.67.2 on 2026-09-27: on that Helmet's open line the wishlist's
own median-tier Life Regeneration candidate is `LifeRegeneration5`
("Regenerate (24.1-32) Life per second"), and it takes the relation to +12.4 /s,
the whole violation to 0, at `CombinedDPS` 289,690 against the incumbent's
294,767 -- i.e. at no value gain. Rule 3's fixed 0.01 floor on removed violation
used to refuse exactly this line ("removes only 0.0020 of violation at +0
value"); the threshold is there against noise, and a line that makes the build
feasible is not noise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import (
    WishlistGear,
    WishlistMod,
    _is_attribute_mod,
    _mod_families,
)
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "regressions" / "ground-slam-autocry-tpl-s4.pob.txt"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)

BASE = "Aventail Helmet"
ILVL = 72
SOCKETS = "R-R-R-R"


def _mod(pob: PobSession, mod_id: str) -> WishlistMod:
    """The wishlist's view of one named mod of the fixture's Helmet, read from PoB."""

    row = next(row for row in pob.list_item_mods(BASE, ilvl=ILVL)["mods"] if str(row["mod_id"]) == mod_id)
    lines = tuple(str(line) for line in (row.get("lines") or ()))
    return WishlistMod(
        mod_id, str(row["type"]), str(row["group"]), 1, 1, lines[0] if lines else "", lines=lines,
        families=_mod_families(row.get("mod_id"), row.get("group")), attribute=_is_attribute_mod(row),
    )


def test_the_open_helmet_line_buys_the_life_regeneration_that_ends_the_violation(tmp_path: Path) -> None:
    rails = Rails.load()
    objective = rails.objective()
    with PobSession(run_id="test-174-open-line", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(FIXTURE.read_text(encoding="utf-8").strip()))
        gear = WishlistGear(pob, objective, rails)
        life, resistance = _mod(pob, "IncreasedLife7"), _mod(pob, "ColdResist5")
        strength, regen = _mod(pob, "Strength5"), _mod(pob, "LifeRegeneration5")
        assert regen.lines == ("Regenerate (24.1-32) Life per second",)

        picked = gear._choose_trial(
            "Helmet", BASE, ILVL, [life, resistance], None,
            [(strength, None), (regen, None)], sockets=SOCKETS,
        )
        rows = list(gear._last_choice_rows)

    assert picked is not None and picked[0] is regen
    taken = next(row for row in rows if row.get("taken"))
    refused = next(row for row in rows if not row.get("taken"))
    # the delivered build's own violation, and the whole of it removed
    assert abs(float(taken["before_violation"]) - 0.00195) < 1e-4
    assert float(taken["after_violation"]) == 0.0
    assert abs(float(taken["violation_removed"]) - 0.00195) < 1e-4
    # bought at no value gain: 289,690 against the incumbent's 294,767
    assert float(taken["after"]) < float(taken["before"])
    assert "TAKEN" in str(taken["reason"])
    # +30 to Strength neither removes violation nor adds value
    assert str(refused["reason"]) == "refused: not better than the item as it stands"
