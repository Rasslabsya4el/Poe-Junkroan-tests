"""Spec 2026-09-22 (fixture skeleton loads and obeys the rails): the six ziz-rules gaps
(`docs/readings/2026-09-22-ziz-rules-gaps.md`) never produced a counted build. Requirements 1-4
fix why: an unknown fixture config var reaching `set_config` (z325/z329 champion_explosive_arrow),
an ascendancy node id that means a different ascendancy at the pinned tree version
(z328_hierophant_kinetic_fusillade), and a unique our corpus does not know or that
`Rails.unique_allowed` rejects as drop-disabled (z328_hierophant_shock_nova_archmage,
z327_assassin_poison_spark). z325_berserker_ground_slam_autocry needs no skeleton change
(requirement 5: its ascendancy points are within the rail; the extra allocation the audit reports
is a tree-pathing artifact, not a skeleton problem) and is included here only to prove it still
loads exactly as before.

No PoB: this whole module is skipped.
"""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SLUGS = (
    "z325_champion_explosive_arrow",
    "z329_champion_explosive_arrow",
    "z328_hierophant_kinetic_fusillade",
    "z328_hierophant_shock_nova_archmage",
    "z325_berserker_ground_slam_autocry",
    "z327_assassin_poison_spark",
)


@pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")
@pytest.mark.pob
def test_the_six_ziz_rules_gap_references_build_a_skeleton_and_apply_it() -> None:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from benchmark import prepare_author
    from junkroan.pob.session import PobSession

    prepared_by_slug = {}
    logs_by_slug: dict[str, list[str]] = {}
    with PobSession(run_id="test_ziz_rules_gaps_author") as pob:
        for slug in SLUGS:
            logs: list[str] = []
            logs_by_slug[slug] = logs
            # requirement 1 (the two champion_explosive_arrow fixtures): must not raise
            # `PoBHeadlessHostContractError: ... references unknown PoB config var(s): enemyHit`.
            prepared_by_slug[slug] = prepare_author(pob, slug, log=logs.append)

    # every skeleton applies cleanly to a FRESH session (the one `set_tree` / `Skeleton.apply`
    # itself validates against): requirement 2 (an out-of-ascendancy node id), requirements 3-4
    # (a unique our corpus does not know / rejects as drop-disabled).
    with PobSession(run_id="test_ziz_rules_gaps_apply") as pob:
        for slug in SLUGS:
            prepared = prepared_by_slug[slug]
            prepared.skeleton.apply(
                pob,
                gem_level=prepared.rails.gems.level,
                gem_quality=prepared.rails.gems.quality,
                main_quality=prepared.rails.gems.main_quality,
            )

    assert any("fixture config var dropped: enemyHit" in l for l in logs_by_slug["z325_champion_explosive_arrow"])
    assert any("fixture config var dropped: enemyHit" in l for l in logs_by_slug["z329_champion_explosive_arrow"])
    assert any(l.startswith("fixture ascendancy node ") and l.endswith("-> dropped") for l in logs_by_slug["z328_hierophant_kinetic_fusillade"])
    assert any("fixture unique dropped from our skeleton: Ring 1: Foulborn Kikazaru" in l for l in logs_by_slug["z328_hierophant_shock_nova_archmage"])
    assert any("fixture unique dropped from our skeleton: Ring 1: Winterweave" in l for l in logs_by_slug["z327_assassin_poison_spark"])
    # requirement 5, closed 2026-09-23 (ascendancy nodes after conversion): the fixture allocates 8 within the
    # rail, but PoB's convert_tree drops 59920 Aspect of Carnage (its prerequisite is not allocated on the
    # current tree), so our skeleton drops exactly that node and nothing else -- the audit's "9 allocated" is gone.
    berserker = logs_by_slug["z325_berserker_ground_slam_autocry"]
    assert [l for l in berserker if "fixture ascendancy node" in l] == [
        "fixture ascendancy node 59920 'Aspect of Carnage' dropped: not allocated after tree conversion"
    ]
    assert not any("fixture unique dropped" in l for l in berserker)
