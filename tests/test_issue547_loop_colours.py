"""#547: the improvement loop judges the build under the socket colours `_finish` delivers (D60), PoB-free.

burning_arrow_snipe (smoke-14-11, wishlist seed 4): the loop's pass 4 stood at 1,670,361 and `config (final lanes)`
at 1,793,531 (+7.37 %, the bar is 2 %), because the colour step ran only in `_finish`. Here the build is a fake with
the colour step's economics: a socket of the gem's own colour is worth a fixed bonus, the item arrives with one lucky
match, and whitening throws it away.
"""

from __future__ import annotations

from junkroan.optimizer.improvement_loop import LoopPlan
from junkroan.search.sockets import gem_colour

from loop_fakes import _Loot, _Pob, _Tree, _finish_pipeline, _finish_skeleton, _patch_generator, loop_over

BODY = "Rarity: Rare\nDoom Shell\nFull Plate\nSockets: R-G-B-B R\nImplicits: 0"
GEMS = ["Fireball", "Added Fire Damage", "Greater Multiple Projectiles", "Spell Echo"]  # B, R, G, B
BONUS = {"Added Fire Damage": 70.0, "Spell Echo": 50.0}  # worth in DPS when the gem sits in a socket of its colour


class ColourPob(_Pob):
    """`_Pob`'s two numbers plus one item whose sockets decide a bonus; snapshots carry the item too."""

    def __init__(self, value: float) -> None:
        super().__init__(value)
        self.raws = {"Body Armour": BODY}
        self.item_snapshots: dict[str, dict] = {}
        self.equip_calls = 0

    def sockets(self) -> list[str]:
        line = next(ln for ln in self.raws["Body Armour"].splitlines() if ln.startswith("Sockets:"))
        return [c for c in line[8:] if c.isalpha()]

    def stats(self, keys):
        letters = self.sockets()
        bonus = sum(BONUS.get(g, 0.0) for i, g in enumerate(GEMS) if i < len(letters) and letters[i] == gem_colour(g))
        return {k: 0 for k in keys} | {"CombinedDPS": self.value + bonus, "Life": self.life}

    def export_xml(self) -> str:
        token = super().export_xml()
        self.item_snapshots[token] = dict(self.raws)
        return token

    def load_xml(self, token: str) -> None:
        super().load_xml(token)
        self.raws = dict(self.item_snapshots[token])

    def equip(self, items: dict) -> None:
        super().equip(items)
        self.equip_calls += 1
        self.raws.update({slot: raw for slot, raw in items.items() if raw is not None})

    def equipped_item_raws(self) -> dict:
        return dict(self.raws)

    def read_state(self) -> dict:
        return {"skills_state": {"socket_groups": [{"slot": "Body Armour", "gems": [{"gem_name": g, "enabled": True} for g in GEMS]}]}}


def _run(monkeypatch):
    pob = ColourPob(1000.0)  # 1000 + 50 (Spell Echo's lucky B): 1,050 as the construction hands it over
    tree = _Tree(pob, [1100.0])  # pass 1's refine is kept; nothing else moves the number
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    p._take_picks = lambda *_a, **_k: None
    p._tune_lanes = lambda _sk, *, identity=False: {}
    loot = _Loot(pob, {})
    sk = _finish_skeleton()
    sk.rare_bases = {"Body Armour": "Full Plate"}
    sk.main_link = ["Puncture"]  # no support: the picks move is skipped
    _patch_generator(monkeypatch, [])
    rig = loop_over(pob, tree=tree, gear=loot, skeleton=sk, objective=None, tune_lanes=p._tune_lanes, take_picks=p._take_picks,
                    judging=p.judging, log=p.log, rails=p.rails, socket_owner=p)  # the same judging context and colour memory `_finish` reads
    result = rig.started()
    rig.run(LoopPlan(seed=1, max_passes=4, max_seconds=600.0, min_gain=0.005, loot_n=5))
    loop_last = result.stages[-1].score_value
    logs.clear()
    delivered_by_loop = list(pob.raws["Body Armour"].splitlines())
    p._finish(result, sk, 0.0)
    return pob, result, logs, loop_last, delivered_by_loop, loot


def test_the_loops_last_pass_agrees_with_the_final_lanes_stage(monkeypatch) -> None:
    pob, result, _logs, loop_last, _delivered, _loot = _run(monkeypatch)

    final = next(s for s in result.stages if s.name == "config (final lanes)")
    assert [s.name for s in result.stages][-1] == "config (final lanes)"
    assert abs(final.score_value / loop_last - 1.0) < 0.02, f"loop pass {loop_last:,.0f} vs final lanes {final.score_value:,.0f}"
    assert final.score_value == 1100.0 + 70.0 + 50.0  # both colours of the step, on the refined tree


def test_finish_delivers_the_colouring_the_loop_judged_and_picks_nothing_over_it(monkeypatch) -> None:
    pob, result, logs, _loop_last, delivered_by_loop, _loot = _run(monkeypatch)

    assert list(pob.raws["Body Armour"].splitlines()) == delivered_by_loop
    assert pob.sockets() == list("WRWB") + ["W"]
    assert not [m for m in logs if m.startswith("sockets coloured")]  # `_finish` ran no step of its own
    sockets_rows = [m for m in result.moves if m["move"] == "sockets"]
    assert sockets_rows and all(m["kept"] for m in sockets_rows)
    assert sockets_rows[0]["pass"] == 0 and sockets_rows[0]["after"] > sockets_rows[0]["before"]  # judged before pass 1

