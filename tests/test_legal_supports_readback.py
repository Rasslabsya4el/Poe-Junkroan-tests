"""The support-legality readback must leave the build as it found it, and the re-judge must refuse to open on a
build that is not the one it was given (2026-09-15 intake: Arc Archmage 373,571 -> 64,531 at the re-judge's opening,
Pyroclast Mine 249,025 -> 58,554; the first swap of each was accepted against that number). No PoB needed."""

import pytest

from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.search.generator import SkeletonGenerator
from junkroan.search.skeleton import Skeleton

LINK = ["Arc", "Archmage", "Lightning Penetration", "Unleash", "Spell Echo"]


class _Pob:
    """Records every main link set; every candidate support reads back as linked."""

    def __init__(self, values):
        self.values = list(values)
        self.links: list[list[str]] = []
        self._last = list(LINK)

    def set_skills(self, *, main_link, **_kw):
        self._last = list(main_link)
        self.links.append(self._last)

    def read_state(self):
        return {"skills_state": {"socket_groups": [{"active_skill_entries": [{"name": self._last[0], "support_links": [{"name": n} for n in self._last[1:]]}]}]}}

    def stats(self, keys):
        v = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        return {k: 0 for k in keys} | {"CombinedDPS": v}


def _gen(values):
    g = SkeletonGenerator.__new__(SkeletonGenerator)
    g.pob = _Pob(values)
    g.rails = Rails.load()
    g.objective = Objective(maximize="CombinedDPS")
    g.log = lambda _m: None
    g.picks = []
    g.castability_context = None
    g.castability_metrics = CastabilityMetrics()
    return g


def _skeleton():
    # a forbidden support bypasses the on-disk legality cache (and keeps the test from writing one)
    return Skeleton(class_name="Templar", ascendancy="Hierophant", main_link=list(LINK), forbid_supports=["Empower"])


def test_the_readback_restores_the_skeletons_main_link() -> None:
    g = _gen([100_000])
    sk = _skeleton()
    legal = g.legal_supports(sk)
    assert legal and all(len(link) == 2 for link in g.pob.links[:-1])
    assert g.pob.links[-1] == LINK, "the last link written must be the skeleton's own, not the last candidate"
    assert sk.main_link == LINK


def test_the_rejudge_refuses_to_open_on_a_changed_build(monkeypatch) -> None:
    g = _gen([100_000, 10_000])  # measured at 100k by the caller, 10k when the re-judge opens
    with pytest.raises(RuntimeError, match="re-judge opened"):
        g.rejudge_picks(_skeleton())
