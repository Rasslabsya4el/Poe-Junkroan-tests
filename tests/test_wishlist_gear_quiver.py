"""Template v4 piece a1: the quiver takes the weapon shape (docs/specs/2026-09-23-template-v4a1-quiver-code.md).

Only the quiver part of the reference flexible-lines suite: the rails switch
``quiver_weapon_shape`` (default true here), its parsing, the quiver branch in
``template_for`` and ``_buys_value`` reading the per-instance rails. No PoB
runtime needed: ``FakePob`` (from test_wishlist_gear) fakes the item tables.
"""

from __future__ import annotations

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails, _wishlist_rails
from junkroan.optimizer.wishlist_gear import WishlistGear, template_for
from test_wishlist_gear import FakePob, _rails


def test_wishlist_rails_quiver_switch_defaults_on_and_parses() -> None:
    assert _wishlist_rails({}).quiver_weapon_shape is True
    assert _wishlist_rails({"quiver_weapon_shape": False}).quiver_weapon_shape is False
    assert _wishlist_rails({"quiver_weapon_shape": True}).quiver_weapon_shape is True


def test_rails_default_json_ships_the_quiver_switch_on() -> None:
    assert Rails.load().gear.wishlist.quiver_weapon_shape is True


def test_quiver_takes_the_armour_shape_when_the_switch_is_off() -> None:
    template = template_for("Blazing Arrow Quiver", "Weapon 2", quiver_weapon_shape=False)
    assert [line.kind for line in template] == ["fixed", "resistance", "open_or_craft"]


def test_quiver_weapon_shape_switch_gives_the_weapon_shape() -> None:
    """Requirement 1: a quiver follows the weapon rule (natural open lines + one craft)."""

    template = template_for("Blazing Arrow Quiver", "Weapon 2", quiver_weapon_shape=True)
    assert [line.kind for line in template] == ["open", "open", "craft"]


def test_buys_value_recognises_a_flexible_quiver_as_a_weapon_shape() -> None:
    """``_buys_value`` (rule 2's value-first switch) must read the per-instance rails,
    not the bare module default, or a quiver under the switch would still be judged
    violation-first like an armour slot."""

    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails(quiver_weapon_shape=True))
    assert gear._buys_value("Blazing Arrow Quiver", "Weapon 2") is True
    gear_off = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails(quiver_weapon_shape=False))
    assert gear_off._buys_value("Blazing Arrow Quiver", "Weapon 2") is False