"""#392 witness: the day-1 unique screen keeps the best allowed (tier 5) unique and never offers a tier 3/4 one next to it. PoB-free."""

from junkroan.optimizer.rails import Rails
from junkroan.search.generator import SkeletonGenerator

T5_BEST, T4_BETTER, T3_BETTER = "Honourhome", "Natural Hierarchy", "Dyadian Dawn"  # corpus tiers 5 / 4 / 3


class _FakePob:
    """unique_item returns the plain name inside the raw text; trial_stats scores by name: the forbidden tiers would score higher."""

    SCORE = {T5_BEST: 2000.0, T4_BETTER: 9000.0, T3_BETTER: 9500.0}

    def __init__(self) -> None:
        self.offered: list[str] = []

    def read_state(self) -> dict:
        return {}

    def unique_item(self, name: str) -> dict:
        return {"raw": f"Rarity: Unique\n{name}\nBase"}

    def trial_stats(self, trials, keys, mode="fast"):
        out = []
        for t in trials:
            name = t["item"]["raw"].splitlines()[1]
            self.offered.append(name)
            out.append({"ok": True, "stats": {"CombinedDPS": self.SCORE.get(name, 0.0), "Life": 5000.0}})
        return out


def test_t5_unique_kept_and_t3_t4_refused_next_to_it() -> None:
    rails = Rails.load()
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.rails = rails
    gen.objective = rails.objective()
    gen.pob = _FakePob()
    gen._score = lambda: gen.objective.score({"CombinedDPS": 1000.0, "Life": 5000.0})
    kept = gen.screen_uniques(top=500, min_gain=0.03)
    names = {n for _, n, _, _ in kept}
    assert T5_BEST in names  # the allowed T5 option beats the current item and is kept
    assert not ({T4_BETTER, T3_BETTER} & names)
    assert not ({T4_BETTER, T3_BETTER} & set(gen.pob.offered))  # refused before PoB ever scores them
    assert T5_BEST in set(gen.pob.offered)
