"""PobSession.set_item_sockets: recolouring an item's sockets moves PoB's matching-socket quality (#435).

A gem whose colour equals the colour of the socket at its index on the group's item gets
`GemSocketQuality` +10 (SkillsTab.lua matchesSocket); a W socket never matches. Skipped without the runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

SLOT = "Body Armour"  # cold_dot: B-B-B-B rare, group Cold Snap (Int, blue) + supports


def _first_gem(pob: PobSession) -> dict:
    skills = pob.read_state()["skills_state"]
    active = next(s for s in skills["skill_sets"] if s["skill_set_id"] == skills["active_skill_set_id"])
    groups = active["socket_groups"]
    group = next(g for g in groups if g.get("slot") == SLOT)
    return group["gems"][0]


def test_socket_colour_moves_gem_socket_quality():
    xml = decode_import_code((FIXTURES / "cold_dot.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-socket-colour", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        assert pob.item_sockets(SLOT) == "B-B-B-B"
        pob.set_item_sockets(SLOT, "W-W-W-W")
        white = _first_gem(pob)
        assert pob.item_sockets(SLOT) == "W-W-W-W"
        pob.set_item_sockets(SLOT, "B-B-B-B")
        blue = _first_gem(pob)
        assert pob.item_sockets(SLOT) == "B-B-B-B"
        print("W:", white["quality"], white["socket_quality"], "B:", blue["quality"], blue["socket_quality"])
        assert white["socket_quality"] == 0 and not white["matches_socket"]
        assert blue["matches_socket"]
        assert blue["quality"] + blue["socket_quality"] == white["quality"] + white["socket_quality"] + 10
        pob.set_item_sockets(SLOT, "B-B R-W")
        assert pob.item_sockets(SLOT) == "B-B R-W"
