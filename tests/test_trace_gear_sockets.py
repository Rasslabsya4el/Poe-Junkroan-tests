"""PoB-free tests of Trace.incumbent_sockets and the `gear-sockets:*` classes (#548)."""

from junkroan.optimizer.trace import Trace


def gloves(sockets=None):
    return "Rarity: Rare\nDoom Grip\nTitan Gauntlets\nItem Level: 80\n" + (f"Sockets: {sockets}\n" if sockets else "") + "Implicits: 0\n+80 to maximum Life\n"


def shield(sockets=None):
    return "Rarity: Rare\nDoom Wall\nVaal Spirit Shield\nItem Level: 80\n" + (f"Sockets: {sockets}\n" if sockets else "")


def quiver(sockets=None):
    return "Rarity: Rare\nDoom Case\nTwo-Point Arrow Quiver\nItem Level: 80\n" + (f"Sockets: {sockets}\n" if sockets else "")


def trial(slot, raw):
    return {"item": {"slot": slot, "raw": raw}}


def sock(t, tr):
    return {c for c in tr._classes(t) if c.startswith("gear-sockets:")}


def test_incumbent_missing_and_other_line():
    tr = Trace()
    with tr.incumbent_sockets("Gloves", gloves("R-G-B-B")):
        assert sock(trial("Gloves", gloves("R-G-B-B")), tr) == {"gear-sockets:incumbent"}
        assert sock(trial("Gloves", gloves()), tr) == {"gear-sockets:missing"}
        assert sock(trial("Gloves", gloves("W-W-W-W")), tr) == {"gear-sockets:missing"}
        assert sock(trial("Boots", gloves()), tr) == set()


def test_outside_context_none():
    tr = Trace()
    assert sock(trial("Gloves", gloves("R-G-B-B")), tr) == set()
    with tr.incumbent_sockets("Gloves", gloves("R-G-B-B")):
        pass
    assert sock(trial("Gloves", gloves()), tr) == set()


def test_incumbent_without_sockets_no_class():
    tr = Trace()
    with tr.incumbent_sockets("Gloves", gloves()), tr.incumbent_sockets("Boots", None):
        assert sock(trial("Gloves", gloves("R-G-B-B")), tr) == set()
        assert sock(trial("Boots", gloves()), tr) == set()


def test_other_class():
    tr = Trace()
    with tr.incumbent_sockets("Weapon 2", shield("R-G")):
        assert sock(trial("Weapon 2", quiver("R-G")), tr) == {"gear-sockets:other-class"}
        assert sock(trial("Weapon 2", shield("R-G")), tr) == {"gear-sockets:incumbent"}


def test_nesting_and_restore():
    tr = Trace()
    with tr.incumbent_sockets("Gloves", gloves("R-G")):
        with tr.incumbent_sockets("Gloves", gloves("B-B")), tr.incumbent_sockets("Weapon 2", shield("R-G")):
            assert sock(trial("Gloves", gloves("B-B")), tr) == {"gear-sockets:incumbent"}
            assert sock(trial("Weapon 2", shield("R-G")), tr) == {"gear-sockets:incumbent"}
        assert sock(trial("Gloves", gloves("R-G")), tr) == {"gear-sockets:incumbent"}
        assert sock(trial("Gloves", gloves("B-B")), tr) == {"gear-sockets:missing"}
        assert sock(trial("Weapon 2", shield("R-G")), tr) == set()
    assert sock(trial("Gloves", gloves("R-G")), tr) == set()


def test_reset_clears():
    tr = Trace()
    with tr.incumbent_sockets("Gloves", gloves("R-G")):
        tr.reset()
        assert sock(trial("Gloves", gloves()), tr) == set()


def test_considered_counts():
    tr = Trace()
    with tr.incumbent_sockets("Gloves", gloves("R-G-B-B")), tr.move("recraft"):
        tr.count_candidates([trial("Gloves", gloves("R-G-B-B")), trial("Gloves", gloves())])
        tr.count_trial(trial("Gloves", gloves("R-G-B-B")))
    c = tr.considered()["recraft"]
    assert c["gear-sockets:incumbent"] == {"generated": 1, "evaluated": 1}
    assert c["gear-sockets:missing"] == {"generated": 1, "evaluated": 0}


def test_a_failing_classification_is_counted_unclassified(monkeypatch):
    import junkroan.optimizer.trace as trace_mod

    def boom(_raw):
        raise ValueError("parser broke")

    tr = Trace()
    with tr.incumbent_sockets("Gloves", gloves("R-G-B-B")):
        monkeypatch.setattr(trace_mod, "_sockets_of", boom)  # after the note is taken: only the trial's parse fails
        assert sock(trial("Gloves", gloves("R-G-B-B")), tr) == {"gear-sockets:unclassified"}
