"""A one-handed weapon in Weapon 2 takes the weapon template, not the shield's.

The template's ``by_type`` keys must be the item classes the base corpus
reports ("One Handed Sword", PoB's spelling). With "One Hand Sword" no sword,
axe or mace matched; Weapon 1 still got the weapon shape through the slot
fallback, but a dual-wielded off-hand fell back to "Shield": life and a
resistance it cannot roll, so ONE open line (smite and regular_viper_strike,
core14-tpl-main3: a Corsair Sword with 122% increased Physical Damage alone).
"""

from __future__ import annotations

import pytest

from junkroan.optimizer.item_bases import type_of
from junkroan.optimizer.wishlist_gear import _templates, template_for

WEAPON_SHAPE = ["open", "open", "craft"]  # weapon_open_lines 2 + one craft = 3 lines (rulebook i-day1-templates, #429)


@pytest.mark.parametrize("base", ["Corsair Sword", "Jewelled Foil", "Karui Axe", "Rock Breaker"])
def test_one_handed_weapon_in_weapon_2_takes_the_weapon_shape(base: str) -> None:
    assert type_of(base).startswith("One Handed")
    assert [line.kind for line in template_for(base, "Weapon 2")] == WEAPON_SHAPE
    assert [line.kind for line in template_for(base, "Weapon 1")] == WEAPON_SHAPE


def test_a_shield_in_weapon_2_keeps_the_armour_shape() -> None:
    assert [line.kind for line in template_for("Crusader Buckler", "Weapon 2")] == ["fixed", "resistance", "open_or_craft"]


def test_every_weapon_alias_names_an_item_class_the_corpus_reports() -> None:
    from junkroan.optimizer import item_bases

    classes = {str(record.get("type")) for record in item_bases._by_name().values()}
    _templates_by_name, aliases = _templates()
    unknown = sorted(alias for alias in aliases if alias not in classes and alias != "Rune Dagger")
    assert unknown == []
