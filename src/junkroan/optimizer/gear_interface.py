"""The one interface the loot filler (`LootGear`) and the template filler (`WishlistGear`) both answer (#795).

The improvement loop and the pipeline used to ask "is this gear a template?" in 22 places and to read the
filler's private members in 10. Every such question is a method here. The defaults below are what a filler
with no template does today (an empty list, a no-op, `{}`, `False`): `LootGear` inherits them, `WishlistGear`
overrides each with its template behaviour. `fill_slot`, `fill` and the plain attributes stay as they are.

This module imports neither filler: both import it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    from junkroan.optimizer.wishlist_gear import BaseChoice


class GearInterface(ABC):
    # Attributes both fillers hold (set in their constructors; the pipeline writes `anoint` and `forced_lines`).
    pob: Any
    objective: Any
    rails: Any
    log: Any
    uniques: dict[str, str]
    current_raw: dict[str, str]
    anoint: str | None
    forced_lines: dict[str, list[str]]
    flexible_by_value: bool = False  # only `refills_by_value` gear ever has it set

    # -- what differs by kind and has no default ----------------------------------------------------------

    @abstractmethod
    def item_level_for(self, slot: str) -> int:
        """The item level the filler crafts `slot` at (loot: the gear rail's; template: the wishlist's per slot)."""

    @abstractmethod
    def other_weapon_bases(self, base: str) -> list[str]:
        """The other legal bases of `base`'s item class for the weapon-base move; `[]` for a base with no class."""

    # -- what only a template does; the defaults are the loot filler's answers --------------------------------

    @property
    def refills_by_value(self) -> bool:
        """Does a feasible build re-fill this gear's open lines by value (the loop's gear move)? Loot: no."""

        return False

    def pinned_roll_choices(self, slot: str, base: str) -> list[list[str]]:
        """The mod ids a random roll of `slot` must carry for the template's pinned lines. Loot: none."""

        return []

    def preselect_bases(self, slots: Sequence[str], rare_bases: Mapping[str, str], sockets_of: Mapping[str, str | None]) -> dict[str, "BaseChoice"]:
        """The joint kick's bases for all its victim slots at once, with the resistance plan solved over them.
        Loot has no base choice: `{}` and no plan."""

        return {}

    def refill_victim_slot(self, slot: str, base: str, *, n: int | None, sockets: str | None, seed: int, order: Any, preselected: "BaseChoice | None" = None) -> Any:
        """`fill_slot` for a joint-kick victim, on the base `preselect_bases` chose (None: the filler picks)."""

        return self.fill_slot(slot, base, n=n, sockets=sockets, seed=seed, order=order)  # type: ignore[attr-defined]

    def refill_slot(self, slot: str, base: str, *, n: int | None, sockets: str | None, seed: int, order: Any) -> Any:
        """`fill_slot` for the loop's gear move: a template re-plans its resistance lines for the slot. Loot: plain fill."""

        return self.fill_slot(slot, base, n=n, sockets=sockets, seed=seed, order=order)  # type: ignore[attr-defined]

    def resistance_plan_snapshot(self) -> dict[str, Any]:
        """The resistance plan state a gear move can rewrite, deep-copied. Loot has none: `{}`."""

        return {}

    def restore_resistance_plan(self, saved: Mapping[str, Any]) -> None:
        """Put back what `resistance_plan_snapshot` returned. Loot: nothing to put back."""

    def plan_snapshot(self) -> dict[str, Any]:
        """The plan and bookkeeping surfaces (beside `current_raw`) a later fill reads, for the loop's revert. Loot: `{}`."""

        return {}

    def plan_restore(self, saved: Mapping[str, Any]) -> None:
        """Put back what `plan_snapshot` returned. Loot: nothing."""

    def carry_result(self, slot: str, old_raw: str, new_raw: str, **fields: Any) -> None:
        """The item of `slot` moved from `old_raw` to `new_raw` (an anoint, a weapon base): the template's remembered
        fill result follows it, with `fields` (base, implicit) overwritten. Loot remembers none."""

    def shopping_results(self) -> list[Any]:
        """The shopping lists for raws still equipped. Loot has none."""

        return []
