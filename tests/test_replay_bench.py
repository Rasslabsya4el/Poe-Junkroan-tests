"""Replay-bench aggregation is pure Python; the live PoB runs are measurements."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import LEGAL_MOVES, paired_summary, render_report, source_info, structural_lines, validate_move, weapon_base_lines  # noqa: E402


def test_paired_report_uses_build_level_bootstrap_and_expected_wins() -> None:
    ours = [
        {"ok": True, "source": "a", "gain_percent": 1.0, "seconds": 10.0},
        {"ok": True, "source": "b", "gain_percent": 2.0, "seconds": 20.0},
        {"ok": True, "source": "c", "gain_percent": 3.0, "seconds": 30.0},
    ]
    against = [
        {"ok": True, "source": "a", "gain_percent": 2.0, "seconds": 5.0},
        {"ok": True, "source": "b", "gain_percent": 2.0, "seconds": 10.0},
        {"ok": True, "source": "c", "gain_percent": 5.0, "seconds": 15.0},
    ]

    summary = paired_summary(ours, against)

    assert summary["builds"] == 3
    assert summary["median_gain_difference"] == 1.0
    assert summary["wins"] == 2
    assert summary["ties"] == 1
    assert summary["losses"] == 0
    assert summary["seconds_ratio"] == 2.0
    assert summary["bootstrap_90"] is not None


def test_unknown_move_names_all_legal_moves() -> None:
    with pytest.raises(ValueError, match="legal moves: " + ", ".join(LEGAL_MOVES)):
        validate_move("not-a-loop-move")


def test_source_info_keeps_the_producing_builds_tree_churn(tmp_path: Path) -> None:
    build = tmp_path / "stormbrand-s1.pob.txt"
    build.touch()
    (tmp_path / "results.json").write_text(
        '[{"ok": true, "slug": "stormbrand", "seed": 1, "tree_churn": {"all": 0.25}}]',
        encoding="utf-8",
    )

    info = source_info(build)

    assert info["result_row"]["tree_churn"] == {"all": 0.25}


def _row(reference: str, *, recorded: float, replayed: float, gain: float, violated: list[str]) -> dict:
    return {
        "ok": True, "reference": reference, "source": reference, "move": "loop", "seed": 1,
        "stat": "CombinedDPS", "value_before": replayed, "value_after": replayed * (1 + gain / 100.0),
        "gain_percent": gain, "recorded_value": recorded, "replayed_value": replayed,
        "replayed_over_recorded": replayed / recorded, "start_infeasible": bool(violated),
        "start_violated": violated, "seconds": 10.0, "kept": 1, "not_kept": 13,
        "judged_and_reverted": 4, "violation_before": 0.0034 if violated else 0.0,
        "violation_after": 0.0034 if violated else 0.0, "audit_errors": 0,
    }


def test_report_shows_recorded_against_replayed_and_pairs_feasible_starts_apart() -> None:
    rows = [
        _row("impale_ballista", recorded=963_133.0, replayed=674_530.0, gain=5.69, violated=["EffectiveMovementSpeedMod"]),
        _row("stormbrand", recorded=2_115_491.0, replayed=2_115_491.0, gain=2.47, violated=[]),
        _row("bleed_bow", recorded=969_206.0, replayed=969_206.0, gain=0.0, violated=[]),
    ]
    against = [dict(row, gain_percent=row["gain_percent"] + 1.0) for row in rows]

    report = render_report(rows, stamp="t", move="loop", passes=1, workers=1, seconds=30.0,
                           against=(Path("other/results.json"), against))

    assert "Start broken: impale_ballista: violation 0.0034, floors: EffectiveMovementSpeedMod" in report  # #816: no 0.700x note
    assert "starts infeasible: EffectiveMovementSpeedMod" in report
    assert "stormbrand" not in report.split("Builds the replay does not reproduce as delivered:")[1].split("## Paired")[0]
    assert "**over all builds** (2 builds)" in report
    assert "**over builds that start feasible (1 dropped)** (2 builds)" in report
    assert "1 / 4 / 13" in report  # kept / judged+reverted / not kept
    assert "gain per minute" in report


def test_report_uses_human_time_without_a_seconds_column() -> None:
    report = render_report(
        [_row("stormbrand", recorded=1.0, replayed=1.0, gain=1.0, violated=[])],
        stamp="t",
        move="loop",
        passes=1,
        workers=1,
        seconds=2856.0,
    )

    assert "| reference | source | recorded | replayed | replayed / recorded | after | gain | time |" in report
    assert "48 min on 1 workers" in report
    assert not re.search(r"\d{3,} ?s\b", report)
    assert "| seconds |" not in report


def test_the_trunk_moves_report_their_structural_counts() -> None:
    """Plan B is accepted on counts as well as on gain (D84), so the bench sums them per run."""

    rows = [
        dict(_row("stormbrand", recorded=1.0, replayed=1.0, gain=1.0, violated=[]), tree_counts={
            "corridors": 22, "corridors_with_bypass": 3, "corridors_no_bypass": 19, "corridor_candidates": 3,
            "corridor_applied": 1, "corridor_kept": 1, "corridor_unpriceable": 0, "regions": 0,
            "region_candidates": 0, "regions_challenged": 0, "regions_kept": 0, "honest_removals": 0,
            "trunk_nodes": 22, "trunk_considered": 7, "allocated": 109, "restore_failures": 0,
            "region_bucket_kept": {"4-6": 2}, "region_policy_kept": {"target-first": 1, "greedy": 1}}),
        dict(_row("bleed_bow", recorded=1.0, replayed=1.0, gain=0.0, violated=[]), tree_counts={
            "corridors": 10, "corridors_with_bypass": 1, "trunk_nodes": 18, "trunk_considered": 2,
            "allocated": 100, "restore_failures": 0, "region_bucket_kept": {"13-20": 1}}),
    ]

    text = "\n".join(structural_lines(rows))

    assert "TRUNK nodes (removal drops 13+) 40, inside at least one evaluated candidate 9 (22.5%)" in text
    assert "Corridors found / with a bypass / no bypass: 32 / 4 / 19" in text
    assert "Regions kept by bucket: {'4-6': 2, '13-20': 1}" in text
    assert "RESTORE FAILED: 0" in text
    assert structural_lines([{"ok": False}]) == []


def test_weapon_base_report_lists_kept_swaps_and_illegal_candidates() -> None:
    rows = [dict(_row("crit_attack", recorded=1.0, replayed=1.0, gain=1.0, violated=[]), moves=[{
        "move": "weapon base", "kept": True, "slot": "Weapon 1", "base_before": "Low Sword", "base_after": "High Sword",
        "base_numbers_before": {"Critical Strike Chance": "5.00%", "Attacks per Second": "1.20"},
        "base_numbers_after": {"Critical Strike Chance": "7.50%", "Attacks per Second": "1.20"},
        "implicit_before": "", "implicit_after": "20% increased Global Accuracy Rating",
    }], weapon_base_skipped={"One Handed Sword": 3})]

    text = "\n".join(weapon_base_lines(rows))

    assert "Low Sword | High Sword" in text
    assert "Critical Strike Chance 5.00% -> 7.50%" in text
    assert "implicit - -> 20% increased Global Accuracy Rating" in text
    assert "Illegal candidate bases skipped by item class: One Handed Sword 3." in text


def test_report_splits_weapon_base_results_by_damage_kind() -> None:
    rows = [
        dict(_row("attack", recorded=1.0, replayed=1.0, gain=1.0, violated=[]), damage_kind="attack"),
        dict(_row("spell", recorded=1.0, replayed=1.0, gain=0.0, violated=[]), damage_kind="spell"),
        dict(_row("minion", recorded=1.0, replayed=1.0, gain=0.0, violated=[]), damage_kind="minion"),
    ]

    report = render_report(rows, stamp="t", move="weapon-base", passes=1, workers=1, seconds=30.0)

    assert "**attack builds** (1 builds)" in report
    assert "**spell builds** (1 builds)" in report
    assert "**minion builds** (1 builds)" in report
