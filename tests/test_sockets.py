import pytest

from junkroan.search.sockets import coloured_max, gem_colour, linked_white, whiten


def test_whiten_basic():
    assert whiten("R-G-B-B R") == "W-W-W-W W"
    assert whiten("R-G-B-B R", {1: "G"}) == "W-G-W-W W"
    assert whiten("R-G-B-B R", {4: "R"}) == "W-W-W-W R"


@pytest.mark.parametrize("s", ["B-B-B B-R", "A", "R G", "R-A-G"])
def test_whiten_keeps_links_and_count(s):
    w = whiten(s)
    assert [c in "- " for c in w] == [c in "- " for c in s]
    assert len(w) == len(s)
    assert all(c in "W-A " for c in w)


def test_whiten_abyss_counts_as_position():
    assert whiten("R-A-G", {2: "B"}) == "W-A-B"
    assert whiten("D-R") == "D-W"


def test_whiten_bad_choice():
    with pytest.raises(ValueError):
        whiten("R-G", {2: "R"})
    with pytest.raises(ValueError):
        whiten("R-A-G", {1: "R"})


def test_linked_white():
    assert linked_white(3) == "W-W-W"
    assert linked_white(1) == "W"
    assert linked_white(0) == ""
    assert linked_white(-2) == ""


def test_gem_colour_from_pob():
    assert gem_colour("Cleave") == "R"
    assert gem_colour("Detonate Dead") == "G"
    assert gem_colour("Fireball") == "B"
    assert gem_colour("Portal") is None
    assert gem_colour("No Such Gem") is None


def test_coloured_max():
    assert coloured_max("day1") == 2
    assert coloured_max("t16") == 4
    assert coloured_max("endgame") == 8
    assert coloured_max("mirror") is None
