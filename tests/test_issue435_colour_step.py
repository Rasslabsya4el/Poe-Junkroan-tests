"""#435 u5: whitening and the colour step of `_finish`, on a fake pob (PoB-free).

The fake scores a build as 100 + the gain of every gem whose socket (PoB's index rule: earlier groups' gems
of the same slot come first) holds the gem's own colour.
"""

from __future__ import annotations

from junkroan.optimizer.objective import Objective, better_score
from junkroan.optimizer.socket_step import ALWAYS_MATCHES, colour_step, slot_groups, whiten_equipped
from junkroan.optimizer.trace import TRACE
from junkroan.pob.session import raw_with_sockets
from junkroan.search.sockets import gem_colour

BODY = "Rarity: Rare\nDoom Shell\nFull Plate\nSockets: R-G-B-B R\nImplicits: 0"
HELM = "Rarity: Rare\nMind Crown\nIron Hat\nSockets: B-B-B-B\nImplicits: 0"
GLOVES = "Rarity: Rare\nGlove Gloves\nIron Gauntlets\nImplicits: 0"
DIALLA = f"Rarity: Unique\nDialla's Malefaction\nUnset Ring\nSockets: R-R-R-R\n{ALWAYS_MATCHES}\nImplicits: 0"


class FakePob:
    def __init__(self, raws, groups, gains):
        self.raws = dict(raws)
        self.groups = groups  # [(slot, [gem names])]
        self.gains = gains  # gem -> gain when its socket matches
        self.equips: list[dict] = []

    def equipped_item_raws(self):
        return dict(self.raws)

    def equip(self, items):
        self.equips.append(dict(items))
        self.raws.update(items)

    def read_state(self):
        return {"skills_state": {"socket_groups": [
            {"slot": slot, "gems": [{"gem_name": g, "enabled": True} for g in gems]} for slot, gems in self.groups
        ]}}

    def sockets(self, slot):
        for line in self.raws[slot].splitlines():
            if line.startswith("Sockets:"):
                return [c for c in line[8:] if c.isalpha()]
        return []

    def stats(self, keys):
        total, offsets = 100.0, {}
        for slot, gems in self.groups:
            off = offsets.get(slot, 0)
            letters = self.sockets(slot)
            always = ALWAYS_MATCHES in self.raws[slot]
            for i, gem in enumerate(gems):
                at = off + i
                if always or (at < len(letters) and letters[at] == gem_colour(gem)):
                    total += self.gains.get(gem, 0.0)
            offsets[slot] = off + len(gems)
        return {"CombinedDPS": total}


def run(pob, logs):
    return colour_step(pob, Objective(), lambda new, cur: better_score(new, cur), logs.append)


def test_whitening_keeps_links_and_count():
    pob = FakePob({"Body Armour": BODY}, [("Body Armour", ["Fireball"])], {})
    changed = whiten_equipped(pob, pob.equipped_item_raws(), slot_groups(pob))
    assert "Sockets: W-W-W-W W" in changed["Body Armour"]
    assert "Sockets: W-W-W-W W" in pob.raws["Body Armour"]


def test_group_in_a_slot_without_sockets_line_gets_white_per_gem():
    pob = FakePob({"Gloves": GLOVES}, [("Gloves", ["Fireball", "Spell Echo", "Controlled Destruction"])], {})
    changed = whiten_equipped(pob, pob.equipped_item_raws(), slot_groups(pob))
    assert changed["Gloves"] == raw_with_sockets(GLOVES, "W-W-W")
    assert "Sockets: W-W-W" in pob.raws["Gloves"] and "Implicits: 0" in pob.raws["Gloves"]


def test_always_matches_item_untouched():
    pob = FakePob({"Ring 1": DIALLA, "Body Armour": BODY}, [("Ring 1", ["Fireball"]), ("Body Armour", ["Fireball"])], {"Fireball": 5})
    changed = whiten_equipped(pob, pob.equipped_item_raws(), slot_groups(pob))
    assert set(changed) == {"Body Armour"} and pob.raws["Ring 1"] == DIALLA


def test_step_picks_the_two_best_in_order_and_logs():
    # body sockets after whitening are W-W-W-W W; group: Fireball(B), Added Fire Damage(R), Greater Multiple Projectiles(G), Spell Echo(B)
    gains = {"Fireball": 1.0, "Added Fire Damage": 7.0, "Greater Multiple Projectiles": 3.0, "Spell Echo": 5.0}
    gems = ["Fireball", "Added Fire Damage", "Greater Multiple Projectiles", "Spell Echo"]
    pob = FakePob({"Body Armour": BODY}, [("Body Armour", gems)], gains)
    TRACE.reset()
    logs: list[str] = []
    result = run(pob, logs)
    assert [(p.gem, p.colour) for p in result.picks] == [("Added Fire Damage", "R"), ("Spell Echo", "B")]
    assert logs == ["sockets coloured: Added Fire Damage R, Spell Echo B, score 105 -> whitened 100 -> 112"]
    assert pob.sockets("Body Armour") == list("WRWB") + ["W"]
    assert pob.stats(())["CombinedDPS"] == 112.0
    # trials restore the whitened string: nothing but the picks stays coloured
    assert sum(c in "RGB" for c in pob.sockets("Body Armour")) == 2


def test_gem_index_follows_earlier_groups_of_the_same_slot():
    # second group's gem sits in socket 2 (two gems before it), not socket 0
    pob = FakePob({"Body Armour": BODY}, [("Body Armour", ["Fireball", "Spell Echo"]), ("Body Armour", ["Added Fire Damage"])],
                  {"Added Fire Damage": 4.0})
    logs: list[str] = []
    result = run(pob, logs)
    assert [(p.slot, p.position, p.gem) for p in result.picks] == [("Body Armour", 2, "Added Fire Damage")]
    assert pob.sockets("Body Armour") == list("WWRW") + ["W"]


def test_no_gain_no_colour():
    pob = FakePob({"Body Armour": BODY, "Helmet": HELM}, [("Body Armour", ["Fireball"]), ("Helmet", ["Spell Echo"])],
                  {"Fireball": 0.0, "Spell Echo": -2.0})
    logs: list[str] = []
    result = run(pob, logs)
    assert result.picks == [] and logs == ["sockets coloured: none, score 98 -> whitened 100"]
    assert not any(c in "RGB" for slot in pob.raws for c in pob.sockets(slot))


def test_trace_counts_candidates_and_trials_by_colour():
    gains = {"Fireball": 1.0, "Added Fire Damage": 7.0, "Greater Multiple Projectiles": 3.0}
    gems = ["Fireball", "Added Fire Damage", "Greater Multiple Projectiles", "Lesser Poison"]  # Lesser Poison is white: no candidate
    pob = FakePob({"Body Armour": BODY}, [("Body Armour", gems)], gains)
    TRACE.reset()
    result = run(pob, [])
    counts = TRACE.considered()["(unattributed)"]
    assert {c: v for c, v in counts.items() if c.startswith("socket-colour:")} == {
        "socket-colour:B": {"generated": 2, "evaluated": 2},  # round 1, and again in round 2 after the red pick
        "socket-colour:R": {"generated": 1, "evaluated": 1},  # picked in round 1, not tried again
        "socket-colour:G": {"generated": 2, "evaluated": 2},
    }
    generated = sum(v["generated"] for c, v in counts.items() if c.startswith("socket-colour:"))
    evaluated = sum(v["evaluated"] for c, v in counts.items() if c.startswith("socket-colour:"))
    assert generated == 5 and evaluated == result.trials == 5


def test_four_candidates_two_picks_generated_equals_evaluated_per_class():
    gains = {"Fireball": 1.0, "Added Fire Damage": 7.0, "Greater Multiple Projectiles": 3.0, "Spell Echo": 5.0}
    gems = ["Fireball", "Added Fire Damage", "Greater Multiple Projectiles", "Spell Echo"]
    pob = FakePob({"Body Armour": BODY}, [("Body Armour", gems)], gains)
    TRACE.reset()
    run(pob, [])
    counts = {c: v for c, v in TRACE.considered()["(unattributed)"].items() if c.startswith("socket-colour:")}
    assert all(v["evaluated"] <= v["generated"] for v in counts.values())
    assert sum(v["generated"] for v in counts.values()) == 4 + 3
    assert sum(v["evaluated"] for v in counts.values()) == 4 + 3


def test_swap_slot_group_is_no_candidate():
    pob = FakePob({"Weapon 1 Swap": BODY, "Body Armour": BODY}, [("Weapon 1 Swap", ["Fireball"])], {"Fireball": 5.0})
    logs: list[str] = []
    result = run(pob, logs)
    assert result.picks == [] and pob.raws["Weapon 1 Swap"] == BODY


class Holder:
    """Just what `BuildPipeline._ensure_sockets` reads: pob, objective, log."""

    def __init__(self, pob):
        from junkroan.optimizer.pipeline import BuildPipeline

        self.pob, self.objective, self.logs = pob, Objective(), []
        self._ensure = BuildPipeline._ensure_sockets.__get__(self)
        self._sockets_stale = BuildPipeline._sockets_stale.__get__(self)

    def log(self, message):
        self.logs.append(message)


def _coloured(pob):
    return [(slot, i) for slot in pob.raws for i, c in enumerate(pob.sockets(slot)) if c in "RGB"]


def test_ensure_runs_the_step_again_after_an_unwhitened_load():
    gems = ["Fireball", "Added Fire Damage", "Greater Multiple Projectiles", "Spell Echo"]
    pob = FakePob({"Body Armour": BODY}, [("Body Armour", gems)], {"Added Fire Damage": 7.0, "Spell Echo": 5.0})
    h = Holder(pob)
    h._ensure(None)
    assert len(_coloured(pob)) == 2
    pob.raws["Body Armour"] = BODY  # the revert loads the entry build back: R-G-B-B R
    h._ensure(None)
    assert len(_coloured(pob)) == 2 and pob.sockets("Body Armour") == list("WRWB") + ["W"]
    assert sum("sockets coloured" in m for m in h.logs) == 2  # the first step and the revert's


def test_ensure_after_a_rerolled_item_and_idle_when_untouched():
    gems = ["Fireball", "Added Fire Damage"]
    pob = FakePob({"Body Armour": BODY}, [("Body Armour", gems)], {"Added Fire Damage": 7.0})
    h = Holder(pob)
    h._ensure(None)
    TRACE.reset()
    calls = len(pob.equips)
    h._ensure(None)  # nothing changed: no trial, no equip
    assert len(pob.equips) == calls and TRACE.considered() == {}
    pob.raws["Body Armour"] = raw_with_sockets(BODY.replace("Full Plate", "Plate Vest"), "G-G-R-B R")  # a re-roll with rails sockets
    h._ensure(None)
    assert pob.sockets("Body Armour") == list("WRWW") + ["W"] and len(_coloured(pob)) == 1
