"""issue #147 (half b), acceptance 4: the core's own duration helper renders the same
string as the product's `junkroan.report_format.human_duration` for the eleven seconds
values named in the spec. This test lives outside `tools/agentops/core_manifest.txt`
(it imports the product), unlike the module it tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from junkroan.report_format import human_duration as product_human_duration
from tools.agentops.core_format import human_duration as core_human_duration

SECONDS = [0.4, 42, 89, 90, 91, 600, 2856, 5399, 5400, 5401, 86400]


def test_core_format_matches_product_for_every_spec_second():
    results = [(s, core_human_duration(s), product_human_duration(s)) for s in SECONDS]
    mismatches = [(s, core, product) for s, core, product in results if core != product]
    assert mismatches == []
    assert len(results) == 11


def test_core_integral_floats_render_like_ints():
    assert core_human_duration(2.0) == "2 s"
    assert core_human_duration(2) == "2 s"
    assert core_human_duration(120.0) == "2 min"
    assert core_human_duration(5400.0) == "1 h 30 min"
    assert core_human_duration(13.8) == "14 s"


def test_core_agrees_with_product_on_integral_floats():
    for s in [2.0, 13.8, 90, 600.0, 5400.0, 7200]:
        assert core_human_duration(s) == product_human_duration(s), s
