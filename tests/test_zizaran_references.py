"""The second reference set (`scripts/benchmark.py --set ziz`) as PoB reads it.

The Zizaran / Maxroll league starters are hand-written guide PoBs, and they break assumptions the
Tuadh day-1 snapshots never did: an author sockets a support before the active skill, leaves
`ascendClassName="None"` with the ascendancy allocated, and runs 20/20 gems where our build gets
the rails' 18/0. Each of those is a silent wrong number rather than an error, so it is checked
against PoB itself.

One session for the whole set (~80 s locally); skipped when the pinned runtime is not present.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import SETS, fixture_path, normalize_author_gems  # noqa: E402
from build_from_skeleton import skeleton_from_xml  # noqa: E402

from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402
from junkroan.search.hypothesis import active_gems, ascendancy  # noqa: E402

LOCK = json.loads((ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]


def _fixture_xml(reference: str) -> str:
    return decode_import_code(fixture_path(reference).read_text(encoding="utf-8").strip())


def _gem_levels(xml: str) -> set[tuple[str, str]]:
    return {(g.get("level"), g.get("quality")) for g in ET.fromstring(xml).iter("Gem") if (g.get("nameSpec") or "").strip()}


def test_the_rails_gems_replace_a_2020_authors_own_and_lower_their_number(tmp_path: Path) -> None:
    """D23: never compare a generated build with an author's on unequal gem levels. The readback is
    PoB's own export, so this is what PoB computes with, not what we wrote."""

    rails = Rails.load()
    xml = _fixture_xml("z328_hierophant_shock_nova_archmage")
    with PobSession(run_id="test-ziz-gems", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        before = pob.stats(("CombinedDPS", "Life"))
        author_gems = _gem_levels(pob.export_xml())
        assert ("20", "20") in author_gems and author_gems != {("18", "0")}, "the author runs 20/20 (a few utility gems lower)"

        normalized, report = normalize_author_gems(xml, rails)
        assert report["changed"] and report["before"] == {"level": 20.0, "quality": 20.0}
        pob.load_xml(normalized)
        after = pob.stats(("CombinedDPS", "Life"))

        assert _gem_levels(pob.export_xml()) == {(str(rails.gems.level), str(rails.gems.quality))}
        assert 0 < after["CombinedDPS"] < before["CombinedDPS"], (before, after)
        assert after["Life"] == before["Life"], "gem levels are damage here, not life: the floors do not move"


def test_every_zizaran_reference_derives_a_real_main_skill_and_ascendancy(tmp_path: Path) -> None:
    """The two things a guide PoB gets wrong for us, on the whole set and with PoB holding each
    build (so the derivation runs its PoB-backed drops as the benchmark runs them):

    * the head of the main link is an active gem -- `objective_for` reads it as the build's main
      skill and `Skeleton.apply_skills` sockets it at `main_active_skill_index` 1, so a support
      there scores the reference 0 (z327_necromancer_raise_spectre, z328_hierophant_shock_nova_archmage);
    * the ascendancy is a real one, and the one PoB itself reads back from the allocated nodes
      (z326_chieftain_righteous_fire exports `ascendClassName="None"`).

    Derived without the rest of the author preamble (no config lane, no unique normalization, no
    floors): those cost minutes, and none of them can change either answer."""

    actives = active_gems()
    with PobSession(run_id="test-ziz-skeletons", artifacts_root=tmp_path) as pob:
        for reference in SETS["ziz"]:
            xml = _fixture_xml(reference)
            pob.load_xml(xml)
            skeleton = skeleton_from_xml(xml, pob=pob)
            head = (skeleton.main_link or [""])[0]

            assert head.lower() in actives or head.lower().startswith("vaal "), (reference, skeleton.main_link)
            record = ascendancy(skeleton.ascendancy)
            assert record is not None, (reference, skeleton.ascendancy)
            assert (record.get("class_name") or "") == skeleton.class_name, (reference, skeleton.class_name, record.get("class_name"))
            # PoB's own verdict on the tree it is holding, which is where the "None" builds are caught
            readback = pob.read_state()["ascendancy_readback"]
            assert readback.get("ascendancy_id") == record["ascendancy_id"], (reference, readback.get("ascendancy_id"))
            assert readback.get("class_id") == skeleton.class_name, (reference, readback.get("class_id"))


def test_the_three_references_that_needed_the_fixes_read_the_way_pob_does(tmp_path: Path) -> None:
    """Named one by one, so a regression says which trap came back."""

    with PobSession(run_id="test-ziz-traps", artifacts_root=tmp_path) as pob:
        for reference, skill in (("z327_necromancer_raise_spectre", "Raise Spectre"),
                                 ("z328_hierophant_shock_nova_archmage", "Shock Nova"),
                                 ("z329_occultist_essence_drain", "Essence Drain")):
            xml = _fixture_xml(reference)
            pob.load_xml(xml)
            assert skeleton_from_xml(xml, pob=pob).main_link[0] == skill, reference

        xml = _fixture_xml("z326_chieftain_righteous_fire")
        pob.load_xml(xml)
        assert ET.fromstring(xml).find("Build").get("ascendClassName") == "None", "the fixture is the one with no ascendancy class"
        assert pob.read_state()["ascendancy_readback"]["ascendancy_id"] == "Chieftain", "PoB reads it from the nodes"
        assert skeleton_from_xml(xml, pob=pob).ascendancy == "Chieftain"
