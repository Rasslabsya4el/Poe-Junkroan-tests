"""#542 unit 1: the pending fact `mortar_spectre_volley_overlap` and its multiplier (D62)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from junkroan.mechanics import pending_facts
from junkroan.mechanics.pending_facts import applies, load_facts
from junkroan.optimizer.spectre_overlap import FACT_ID, volley_overlap_multiplier
from junkroan.pob.game_corpus import load_game_corpus_bundle

MORTAR = "Mortar"
GV, V = "Greater Volley Support", "Volley Support"


def _set(monkeypatch, **over) -> None:
    facts = {k: (replace(v, **over) if k == FACT_ID else v) for k, v in load_facts().items()}
    monkeypatch.setattr(pending_facts, "load_facts", lambda *_a, **_k: facts)


def test_the_record_is_approved_and_acts_on_both_lanes() -> None:
    """The owner's word, 2026-10-16: overlaps are counted as the reference author counts them."""

    assert applies(FACT_ID, "optimistic") is True
    assert applies(FACT_ID, "conservative") is True


@pytest.mark.parametrize("lane", ["conservative", "optimistic"])
@pytest.mark.parametrize(
    "supports, skill, expected",
    [([GV], MORTAR, 5), ([V], MORTAR, 3), ([V, GV], MORTAR, 5), ([GV], "Cold Projectile", 1), (["Faster Casting Support"], MORTAR, 1), ([GV], None, 1), ([GV], "Spectral Mortar", 5)],
)
def test_multiplier_on_both_lanes(lane, supports, skill, expected) -> None:
    assert volley_overlap_multiplier(lane, supports, skill) == expected


def test_a_pending_record_acts_on_the_optimistic_lane_only_and_disputed_on_neither(monkeypatch) -> None:
    _set(monkeypatch, status="pending")
    assert volley_overlap_multiplier("optimistic", [GV], MORTAR) == 5
    assert volley_overlap_multiplier("conservative", [GV], MORTAR) == 1
    _set(monkeypatch, status="disputed", range=(1.0, 5.0), disagreement="test")
    assert volley_overlap_multiplier("optimistic", [GV], MORTAR) == 1
    assert volley_overlap_multiplier("conservative", [GV], MORTAR) == 1


def test_both_support_gems_exist_in_the_corpus() -> None:
    """The corpus writes the names without the " Support" suffix; the function reads both spellings."""

    names = {r["name"] for r in load_game_corpus_bundle("support_gems")["records"]}
    assert {"Greater Volley", "Volley"} <= names
