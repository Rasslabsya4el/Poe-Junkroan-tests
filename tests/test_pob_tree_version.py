"""The passive tree a loaded build sits on, and PoB's own conversion to the latest tree
(`PobSession.tree_version` / `latest_tree_version` / `convert_tree`).

36 of the 37 reference fixtures declare an older tree (3_25-3_28) and PoB keeps it: `TreeTab:Load`
builds the spec at the version the XML names and never converts by itself (`ConvertToVersion` is
behind a UI button). Node ids are additive 3_25 -> 3_29, so converting loses no allocation; only
the node stats become the current ones (the 3.29 cost rework and friends).

Skipped when the pinned runtime is not present locally.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]


def test_a_fixture_keeps_its_own_tree_until_convert_tree_moves_it(tmp_path: Path) -> None:
    xml = decode_import_code((FIXTURES / "arc_archmage.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-tree-version", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        latest = pob.latest_tree_version()
        assert latest != "3_25", "the fixture set would need another build if 3_25 became the latest tree"
        assert pob.tree_version() == "3_25", "the version arc_archmage's <Spec> declares"
        assert pob.read_state()["tree_state"]["tree_version"] == "3_25"
        allocated = list(pob.tree_light()["user_allocated_node_ids"])

        result = pob.convert_tree()
        assert result["from"] == "3_25" and result["to"] == latest and result["converted"] is True
        assert result["nodes_before"] == len(allocated) > 100
        assert result["nodes_after"] == result["nodes_before"], "the ids are additive: the allocation survives whole"
        assert result["lost_node_ids"] == []
        assert list(pob.tree_light()["user_allocated_node_ids"]) == allocated
        assert pob.tree_version() == latest
        assert pob.read_state()["tree_state"]["tree_version"] == latest

        # already on the target: nothing to convert, and the build is left exactly as it is
        assert pob.convert_tree() == {"from": latest, "to": latest, "converted": False,
                                      "nodes_before": result["nodes_after"], "nodes_after": result["nodes_after"],
                                      "lost_node_ids": []}
        assert pob.convert_tree(latest)["converted"] is False

        # a plain load stays faithful to the build it was handed: conversion is the caller's decision
        pob.load_xml(xml)
        assert pob.tree_version() == "3_25"
