from collections import Counter

from junkroan.optimizer.anoint_candidates import OIL_ORDER, anoint_candidates


def test_counts_per_tier():
    assert len(anoint_candidates("Black")) == 208
    assert len(anoint_candidates("Silver")) == 351
    assert len(anoint_candidates("Prismatic")) == 472


def test_day1_by_highest_oil():
    got = Counter(c.highest_oil for c in anoint_candidates("Black"))
    assert dict(got) == {
        "Clear": 1, "Sepia": 3, "Amber": 6, "Verdant": 10, "Teal": 15,
        "Azure": 21, "Indigo": 21, "Violet": 34, "Crimson": 43, "Black": 54,
    }
    assert set(got) <= set(OIL_ORDER[:10])


def test_order_and_shape():
    cands = anoint_candidates("Black")
    assert [c.node_id for c in cands] == sorted(c.node_id for c in cands)
    assert all(len(c.recipe) == 3 for c in cands)
