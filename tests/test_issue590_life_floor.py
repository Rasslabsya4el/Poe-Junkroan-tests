"""#590: builds from a request hold Life 4,500; a reference rebuilt against its author keeps the author's Life. PoB-free."""

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import SETS, author_floors, author_memo_path, read_author_memo  # noqa: E402

from junkroan.optimizer.audit import audit_stats  # noqa: E402
from junkroan.optimizer.objective_select import objective_for  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402

MEMO_DIR = ROOT / "tests" / "fixtures" / "author_memos"  # author_raw + author_lane of the 2026-10-05 weekly run, trimmed


def test_default_rails_and_objective_carry_life_4500() -> None:
    rails = Rails.load()
    assert rails.life_floor == 4500
    assert rails.objective().floors["Life"] == 4500


def test_the_objective_a_request_build_searches_under_has_life_4500() -> None:
    """`junkroan build --dry-run` echoes the request's plan (search.py:179, request.expand) and carries no floors line
    unless the request overrides them, so the dry-run echo cannot show the rails' Life. The rails the search runs under
    are `objective_for(rails, skill)` (search.py:57 and the pipeline); that is what is tested here, and the dry-run
    echo is checked to run PoB-free and to say nothing that contradicts it."""

    from junkroan.search.request import BuildRequest, expand

    rails = Rails.load()
    assert objective_for(rails, "Fireball").floors["Life"] == 4500
    exp = expand(BuildRequest.from_dict({"skill": "Fireball", "ascendancy": "auto"}), rails)
    assert "floors overridden" not in exp.echo  # the request left the floors alone: the rails' own apply
    print("dry-run echo carries no floors line; objective_for(rails, 'Fireball').floors['Life'] =", objective_for(rails, "Fireball").floors["Life"])


def test_a_request_build_with_life_4250_gets_exactly_one_life_error() -> None:
    objective = Rails.load().objective()
    stats: dict = {stat: floor * 1.2 for stat, floor in objective.floors.items()}
    stats.update({"Life": 4250.0, "FireResist": 75, "ColdResist": 75, "LightningResist": 75, "FireResistMax": 75, "ColdResistMax": 75, "LightningResistMax": 75,
                  "Str": 100, "Dex": 100, "Int": 100, "ReqStr": 0, "ReqDex": 0, "ReqInt": 0})
    findings = audit_stats(stats, objective)
    errors = [f for f in findings if f.severity == "error"]
    print("row 2 findings:", [(f.severity, f.detail) for f in findings])
    assert len(errors) == 1 and errors[0].detail == "Life = 4250.0 < 4500", errors


def _stats_by_slug(monkeypatch) -> dict:
    import benchmark

    monkeypatch.setattr(benchmark, "AUTHOR_REGIME", "flasks-active")  # the memos of the 2026-10-05 weekly run carry (#575 renamed it since)
    out = {}
    for slug in SETS["core14"]:
        memo = read_author_memo(author_memo_path(str(MEMO_DIR), slug, None))
        if memo is None:
            print(f"SKIP {slug}: no author memo in {MEMO_DIR}")
            continue
        out[slug] = memo
    return out


def test_the_14_core_references_keep_the_authors_life_under_3700_and_4500(monkeypatch) -> None:
    memos = _stats_by_slug(monkeypatch)
    if not memos:
        pytest.skip("no author memos on this machine")
    rails = Rails.load()
    new = rails.objective()
    old = dataclasses.replace(new, floors={**new.floors, "Life": 3700})
    checked = 0
    print(f"{'slug':32} {'author Life':>12} {'floor@3700':>11} {'floor@4500':>11}")
    for slug, memo in memos.items():
        raw, lane = memo["author_raw"], memo["author_lane"]
        f_new = author_floors(new, raw, lane, rails)
        f_old = author_floors(old, raw, lane, rails)
        print(f"{slug:32} {raw['Life']:>12} {f_old['Life']:>11} {f_new['Life']:>11}")
        assert f_new["Life"] == raw["Life"] == f_old["Life"], slug
        checked += 1
    print(f"checked {checked} of {len(SETS['core14'])}")
    assert checked >= 1
