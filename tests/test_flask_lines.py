from collections import Counter

from junkroan.optimizer.flask_lines import FlaskCandidate, flask_bases, flask_mods


def _first(kind):
    return next(b for b in flask_bases(70) if b.kind == kind and b.drop_level >= (50 if kind != "tincture" else 0))


def test_bases_by_kind_at_70():
    bases = flask_bases(70)
    counts = Counter(b.kind for b in bases)
    print(dict(counts), len(bases))
    assert counts["tincture"] >= 1 and counts["life"] and counts["mana"] and counts["utility"]
    assert all(b.drop_level <= 70 for b in bases)
    assert {b.item_class for b in bases} == {"Flask", "Tincture"}
    assert len(flask_bases(70)) <= len(flask_bases(100))


def test_mods_respect_item_level_and_affix():
    for kind in ("life", "tincture"):
        base = _first(kind)
        mods = flask_mods(base, 72)
        assert mods and all(m.level <= 72 and m.affix in ("prefix", "suffix") for m in mods)
        assert {m.affix for m in mods} == {"prefix", "suffix"}
        higher = flask_mods(base, 100)
        excluded = [m for m in higher if m.level > 72]
        assert excluded, kind
        print(kind, base.name, len(mods), "excluded e.g.", excluded[0].id, excluded[0].level)
        assert excluded[0].id not in {m.id for m in mods}


def test_raw_shape_of_a_magic_flask():
    base = _first("life")
    prefix = next(m for m in flask_mods(base, 72) if m.affix == "prefix")
    suffix = next(m for m in flask_mods(base, 72) if m.affix == "suffix")
    raw = FlaskCandidate(base, prefix, suffix).raw(72).split("\n")
    # shape of tests/fixtures/tuadh_329 absolution_minions: "Scholar's Divine Life Flask of Sealing"
    assert raw[0] == "Rarity: MAGIC"
    assert raw[1] == f"{prefix.name} {base.name} {suffix.name}"
    assert raw[2:6] == ["Item Level: 72", "Quality: 0", f"LevelReq: {base.drop_level}", "Implicits: 0"]
    assert raw[6:] == [*prefix.lines, *suffix.lines]
    assert not any("(" in line and "-" in line.split("(")[1][:6] for line in raw[6:])
    assert FlaskCandidate(base, None, None).raw(72).split("\n")[1] == base.name


def test_not_for_sale_flasks_are_bases_but_iron_flask_is_not():
    """#589: `not_for_sale` on a flask means no vendor sells it; only `expedition_flask` (Iron Flask) is screened."""

    names = lambda n: {b.name for b in flask_bases(n)}  # noqa: E731
    for n in (1, 60, 65, 70, 100):
        assert "Iron Flask" not in names(n)
    for name in ("Divine Life Flask", "Divine Mana Flask", "Hallowed Hybrid Flask"):
        assert name in names(60) and name not in names(59)
    for name in ("Eternal Life Flask", "Eternal Mana Flask"):
        assert name in names(65) and name not in names(64)
