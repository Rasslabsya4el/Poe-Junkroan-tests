"""#785: a skeleton built from a reference is evaluated with "kill all" whatever the author took; the author's own row is untouched."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark import fixture_path  # noqa: E402
from build_from_skeleton import skeleton_from_xml  # noqa: E402
from junkroan.pob.session import decode_import_code  # noqa: E402


def _xml(slug: str) -> str:
    return decode_import_code(fixture_path(slug).read_text(encoding="utf-8").strip())


def test_alira_reference_becomes_kill_all() -> None:
    xml = _xml("cold_dot")
    assert ET.fromstring(xml).find("Build").get("bandit") == "Alira"  # the author's own PoB keeps its bandit
    assert skeleton_from_xml(xml).bandit == "None"


def test_kraityn_and_oak_references_become_kill_all() -> None:
    for slug, author in (("z325_champion_explosive_arrow", "Kraityn"), ("z325_gladiator_lacerate", "Oak")):
        xml = _xml(slug)
        assert ET.fromstring(xml).find("Build").get("bandit") == author
        assert skeleton_from_xml(xml).bandit == "None"
