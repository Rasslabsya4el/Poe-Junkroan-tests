"""Rulebook c-ascendancy (#431): day1 / t16 search the main ascendancies, endgame adds the alternate ones; Luminary never."""

from junkroan.search.hypothesis import _records, search_ascendancies
from junkroan.search.request import BuildRequest, expand


def _pob_main() -> set[str]:
    return {r["ascendancy_id"] for r in _records("ascendancies.json") if r.get("source_kind") == "class_ascendancy"} - {"Luminary"}


def _pob_alternate() -> set[str]:
    return {r["ascendancy_id"] for r in _records("ascendancies.json") if r.get("source_kind") == "alternate_ascendancy"}


def test_day1_and_t16_list_is_pobs_main_list():
    assert set(search_ascendancies("day1")) == _pob_main()
    assert search_ascendancies("t16") == search_ascendancies("day1")
    assert not set(search_ascendancies("day1")) & _pob_alternate()
    assert "Reliquarian" in search_ascendancies("day1")  # PoB's tree data lists it as a class ascendancy


def test_endgame_adds_the_alternates():
    got = search_ascendancies("endgame")
    assert set(got) == _pob_main() | _pob_alternate()
    assert _pob_alternate() and _pob_alternate() <= set(got)


def test_luminary_absent_everywhere():
    for loadout in ("day1", "t16", "endgame"):
        assert "Luminary" not in search_ascendancies(loadout)


def test_explicit_alternate_on_day1_is_refused():
    alt = sorted(_pob_alternate() - {"Warden"})[0]
    for loadout in ("day1", "t16"):
        exp = expand(BuildRequest.from_dict({"skill": "Fireball", "ascendancy": alt, "loadout": loadout}))
        assert not exp.ok
        assert any("c-ascendancy" in p for p in exp.problems)
    exp = expand(BuildRequest.from_dict({"skill": "Fireball", "ascendancy": alt, "loadout": "endgame"}))
    assert not any("c-ascendancy" in p for p in exp.problems)
