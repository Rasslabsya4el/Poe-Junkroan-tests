"""A support gem that applies to none of its group's active skills is PoB's own verdict
(the skills tab's red "Cannot apply to any of the active skills", `supportEffect.isSupporting`
empty after the main calc), read back by `PobSession.unsupported_gems` and reported by the
audit. Needs the pinned PoB runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_build
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")


def _group(gems: list[str], slot: str) -> dict:
    return {
        "label": "Utility",
        "slot": slot,
        "enabled": True,
        "include_in_full_dps": False,
        "group_count": 1,
        "main_active_skill_index": 1,
        "gems": [{"gem_name": g, "level": 18, "quality": 0, "enabled": True, "count": 1} for g in gems],
    }


@pytest.fixture(scope="module")
def pob():
    with PobSession(run_id="test_unsupported_gems", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(decode_import_code((FIXTURES / "cold_dot.pob.txt").read_text(encoding="utf-8").strip()))
        yield session


@pytest.mark.pob
@needs_pob
def test_the_authors_build_has_every_support_applying_to_something(pob: PobSession) -> None:
    """Cold DoT's Efficacy sits with Vortex and Creeping Frost and supports both; the
    weapon-swap "Arcane Surge + Elemental Focus" group is slot-disabled and not judged."""

    assert pob.unsupported_gems() == []
    assert [f for f in audit_build(pob) if f.check == "support fits no active gem"] == []


@pytest.mark.pob
@needs_pob
def test_a_spell_support_on_an_attack_is_pobs_cannot_apply(pob: PobSession) -> None:
    """Spell Echo beside Shield Charge (an attack) supports nothing: PoB's verdict, one row,
    and the audit's warning names the gem and the group; Faster Attacks beside it is fine."""

    pob.set_skills(
        main_link=["Cold Snap", "Bonechill", "Controlled Destruction"],
        level=18,
        quality=0,
        extra_groups=[_group(["Shield Charge", "Faster Attacks", "Spell Echo"], "Gloves")],
    )
    rows = pob.unsupported_gems()
    assert [(r["gem"], r["reason"], r["slot"]) for r in rows] == [("Spell Echo", "cannot apply to any of the active skills", "Gloves")]
    found = [f for f in audit_build(pob) if f.check == "support fits no active gem"]
    assert len(found) == 1 and found[0].severity == "warning"
    assert "Spell Echo" in found[0].detail and "Utility" in found[0].detail
