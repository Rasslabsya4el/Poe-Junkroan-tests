# Task 2026-09-25: how many lines do Zizaran's, Tuadh's and our template rares carry (CODE ONLY, ~30 min)

No PoB, no `machine_load`, no benchmarks, no whole suite. Read only the files named. No scratch files in the repo.

## Why

Our template gear (`--gear wishlist`) loses to Zizaran's hand-written day-1 gear by 38.8 points (25 references). Zizaran's
gear is also a "wishlist", so the question is what his items carry that ours do not. First: line counts and line kinds.

## Input (all PoB import codes; decode with `junkroan.pob.session.decode_import_code`)

- Zizaran authors: `tests/fixtures/zizaran_*/early/*.pob.txt`
- Tuadh authors: `tests/fixtures/tuadh_329/*.pob.txt` (only files that decode to a PoB XML)
- Our templates: `artifacts/benchmark/20260924-0231-ziz-tpl-main3-lap/*-s1.pob.txt` (seed 1 only)

In the XML, the ACTIVE item set is `<ItemSet id=...>` whose id equals `<Items activeItemSet=...>`; each `<Slot name=... itemId=...>`
names the worn item; `<Item id="N">` holds the item text. A rare item text has `Rarity: RARE`, then lines like
`Prefix: {range:0.5}IncreasedLife7` / `Suffix: ...` (one per explicit affix; `Prefix: None` means an empty affix -- skip it),
and crafted lines start with `{crafted}`. Worn slots to count: Weapon 1, Weapon 2, Helmet, Body Armour, Gloves, Boots, Belt,
Amulet, Ring 1, Ring 2 (rares only; skip uniques, magic, flasks, jewels).

## Steps

1. Write `scripts/item_lines_census.py` with a pure function `rare_lines(item_text) -> dict` returning
   `{"prefixes": [mod ids], "suffixes": [mod ids], "crafted": int}` and a main that walks the three inputs and prints:
   - Table A, per source (Zizaran / Tuadh / ours) and slot class (weapon, quiver+shield, body, helmet, gloves, boots,
     belt, amulet, ring): items counted, median explicit affixes (prefixes + suffixes, crafted counted once), median
     prefixes, median suffixes, share of items with a crafted line.
   - Table B, the 10 most frequent mod-id FAMILIES (the id without its trailing digits, e.g. `IncreasedLife`) per source.
   - Table C, for the references z329_champion_explosive_arrow, z329_elementalist_winter_orb,
     z325_gladiator_spectral_shield_throw: slot | Zizaran item affix ids | our template item affix ids (seed 1).
     (Our file names are `<slug>-s1.pob.txt`; the Zizaran fixture for `z329_elementalist_winter_orb` is
     `tests/fixtures/zizaran_329/early/elementalist_winter_orb.pob.txt`, and so on: `z<league>_<rest>` ->
     `zizaran_<league>/early/<rest>.pob.txt`.)
2. A test `tests/test_item_lines_census.py` for `rare_lines` on two hand-written item texts (one with `Prefix: None`,
   one with a `{crafted}` line). Run exactly:
   `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_item_lines_census.py`
3. Run the script once; `git add` the two files; commit.
4. Final message: `=== FINAL REPORT ===`, commit hash, the pytest line, and Tables A, B, C exactly as printed.
