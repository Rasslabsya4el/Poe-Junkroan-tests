"""#523: the bare-base screen (`_rank_bases`) pins a forced affix; no raw lacking it reaches PoB. PoB-free, on the wishlist fakes."""

from __future__ import annotations

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.wishlist_gear import WishlistGear
from junkroan.search.forced import raw_has_affix
from test_wishlist_forced import FORCED, TextPob, _helmet_mods
from test_wishlist_gear import _rails


def _screen(forced: dict[str, list[str]]) -> tuple[WishlistGear, TextPob, list]:
    pob = TextPob(_helmet_mods())
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails(flexible_lines=True))
    gear.forced_lines = forced
    pob.shown.clear()
    choices = gear._rank_bases("Helmet", "Fake Helmet", 84, None)
    return gear, pob, choices


def test_rank_bases_never_sends_an_item_without_the_forced_line() -> None:
    _gear, pob, _choices = _screen({"Helmet": [FORCED]})
    sent = [raw for slot, raw in pob.shown if slot == "Helmet"]
    assert sent
    assert all(raw_has_affix(raw, FORCED) for raw in sent)


def test_rank_bases_without_a_forced_line_sends_the_bare_raws() -> None:
    gear, pob, _choices = _screen({})
    sent = [raw for slot, raw in pob.shown if slot == "Helmet"]
    assert sent and sent[0] == gear._raw("Fake Helmet", 84, [], None, None)
    assert not any(raw_has_affix(raw, FORCED) for raw in sent)


def test_rank_bases_drops_a_base_that_cannot_roll_the_line() -> None:
    _gear, pob, choices = _screen({"Helmet": ["+1 to Level of all Chaos Spell Skill Gems"]})
    assert not [1 for slot, _raw in pob.shown if slot == "Helmet"]
    assert [c.base for c in choices] == ["Fake Helmet"]
