"""From-scratch numeric config inputs (D26): values only with proof from the build, numbers from the rails."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import derive_config
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")]
def _load_without_author_config(pob: PobSession, slug: str) -> None:
    pob.load_xml(decode_import_code((FIXTURES / f"{slug}.pob.txt").read_text(encoding="utf-8").strip()))
    state = pob.read_state()["config_state"]
    pob.set_config(bandit=state.get("bandit") or "None", pantheon_major=state.get("pantheon_major") or "None", pantheon_minor=state.get("pantheon_minor") or "None", preserve="none")


def test_trinity_and_rage_are_derived_from_pob_numbers(tmp_path: Path) -> None:
    with PobSession(run_id="test-numeric-smite", artifacts_root=tmp_path) as pob:
        _load_without_author_config(pob, "smite")
        d = derive_config(pob)
        assert d.conservative.inputs.get("configResonanceCount") == 50  # Trinity + fire/cold/lightning hits (PoB per-element averages)
        # rage is ramp arithmetic (2026-09-18): "Gain 1 Rage on Melee Hit" x one hit per 0.5 s (PoB's reminder
        # text; Smite attacks 4.42 times a second) x 2.5 s = 5 of PoB's MaximumRage 30, where the rails' 50% stood
        assert d.conservative.inputs.get("multiplierRage") == 5 and d.optimistic.inputs.get("multiplierRage") == 30
        assert "one hit per 0.5 s" in d.conservative.reasons["multiplierRage"]
        assert "Trinity" in d.conservative.reasons["configResonanceCount"]


def test_withered_and_chill_seconds(tmp_path: Path) -> None:
    with PobSession(run_id="test-numeric-poison", artifacts_root=tmp_path) as pob:
        _load_without_author_config(pob, "poison_spectral_throw")
        d = derive_config(pob)
        # withered stacks are arithmetic now (D62 amendment): one per hit at PoB's 5.19 hits/s
        # inside the 2.5 s budget, 12 of Wither's 15, where the rails' 9 stood
        assert d.conservative.inputs.get("multiplierWitheredStackCount") == 12
        assert "per hit" in d.conservative.reasons["multiplierWitheredStackCount"]
        _load_without_author_config(pob, "cold_dot")
        d = derive_config(pob)
        assert d.conservative.inputs.get("multiplierChilledByYouSeconds") == 10
        assert d.conservative.inputs.get("conditionEnemyChilled") is True


def test_consecrated_ground_needs_a_source_and_ascendancy_text_counts(tmp_path: Path) -> None:
    with PobSession(run_id="test-numeric-cg", artifacts_root=tmp_path) as pob:
        _load_without_author_config(pob, "stormbrand")  # Inquisitor: Sanctuary makes consecrated ground
        d = derive_config(pob)
        assert d.conservative.inputs.get("conditionOnConsecratedGround") is True
        _load_without_author_config(pob, "cold_dot")  # Elementalist: no consecrated ground source
        d = derive_config(pob)
        assert "conditionOnConsecratedGround" not in d.conservative.inputs


def test_sustained_conditions_need_the_matching_gem(tmp_path: Path) -> None:
    with PobSession(run_id="test-sustained-gem", artifacts_root=tmp_path) as pob:
        _load_without_author_config(pob, "cold_dot")  # no warcry gem in the build
        d = derive_config(pob)
        assert d.conservative.inputs.get("conditionUsedWarcryRecently") is not True
        assert "needs a warcry gem" in d.conservative.reasons.get("conditionUsedWarcryRecently", "needs a warcry gem")
