"""7.1d: an active gem in the main link after the main skill is an enabler (Snipe, Spellslinger,
General's Cry), kept in place by every support re-pick and re-judge, never treated as a slot."""

from pathlib import Path

from junkroan.search.skeleton import Skeleton

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _skeleton(link):
    return Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=list(link))


def test_active_gems_after_the_main_skill_are_enablers() -> None:
    assert _skeleton(["Burning Arrow", "Snipe", "Added Lightning Damage", "Burning Damage"]).enablers() == ["Snipe"]
    assert _skeleton(["Volatile Dead", "Spellslinger", "Immolate", "Spell Cascade"]).enablers() == ["Spellslinger"]
    assert _skeleton(["Sunder", "General's Cry", "Pulverise"]).enablers() == ["General's Cry"]
    assert _skeleton(["Spark", "Faster Projectiles", "Efficacy", "Spell Echo"]).enablers() == []


def test_fixture_skeletons_keep_their_enablers() -> None:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml
    from junkroan.pob.session import decode_import_code

    for slug, enabler in (("burning_arrow_snipe", "Snipe"), ("vd_spellslinger", "Spellslinger")):
        sk = skeleton_from_xml(decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / f"{slug}.pob.txt").read_text(encoding="utf-8").strip()))
        assert sk.enablers() == [enabler], slug
