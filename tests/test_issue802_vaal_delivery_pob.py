"""#802 unit 2b, the PoB half (1 PobSession, ~1 min): row 8 and the delivery swap on real fixtures.

Row 8: a hypothesis whose main skill is the Vaal twin of a core-set main skill is searched, and counted by PoB, as the plain
gem: the main skill name PoB reports is the plain skill and every main_output key equals the plain build's.
Row 5 on the fixtures: the delivery swap moves no PoB output; every gem with a Vaal version is written as it (N of N).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.vaal_delivery import deliver_vaal_twins
from junkroan.pob.session import PobSession, decode_import_code
from junkroan.search.skeleton import Skeleton
from junkroan.search.vaal_twin import vaal_twin

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")]

# core14 main skills with a Vaal version; Arc's Vaal skill is hidden by the flags (one active skill), the others list [Vaal X, X]
ROW8 = [("spark", "Spark"), ("arc_archmage", "Arc"), ("impale_cyclone", "Cyclone"), ("cold_dot", "Cold Snap")]
DELIVERY = ["spark", "arc_archmage", "hit_penance_brand"]


def _xml(name: str) -> str:
    return decode_import_code((FIXTURES / f"{name}.pob.txt").read_text(encoding="utf-8").strip())


def _outputs(pob) -> dict:
    return dict(pob.calc_raw()["baseline"].get("main_output") or {})


def _differ(a: dict, b: dict) -> dict:
    out = {}
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y)):
            continue
        if x != y:
            out[k] = (x, y)
    return out


def _main_name(pob) -> str:
    group = pob.read_state()["skills_state"]["socket_groups"][0]
    return group["active_skill_entries"][group["main_active_skill_index"] - 1]["name"]


@pytest.fixture(scope="module")
def pob():
    with PobSession(run_id="test-802-vaal-delivery", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        yield session


@pytest.mark.parametrize(("fixture", "plain"), ROW8)
def test_row8_a_vaal_main_skill_is_counted_as_the_plain_skill(pob, fixture: str, plain: str) -> None:
    twin = vaal_twin(plain)
    assert twin
    pob.load_xml(_xml(fixture))
    supports = ["Added Fire Damage Support"]
    Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=[plain, *supports]).apply(pob, gem_level=18, gem_quality=0, main_quality=0)
    plain_out, plain_name = _outputs(pob), _main_name(pob)
    hypothesis = Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=[twin, *supports])  # a hypothesis names the Vaal gem
    assert hypothesis.main_link[0] == plain
    hypothesis.apply(pob, gem_level=18, gem_quality=0, main_quality=0)
    assert _main_name(pob) == plain_name == plain and _differ(plain_out, _outputs(pob)) == {}

    # the same Vaal name written without the rule: the main skill PoB reports is the Vaal skill whenever it lists one
    raw = Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=[plain, *supports])
    raw.main_link = [twin, *supports]
    raw.apply(pob, gem_level=18, gem_quality=0, main_quality=0)
    print(f"{fixture}: without the rule the main skill is {_main_name(pob)!r}, {len(_differ(plain_out, _outputs(pob)))} outputs differ")


@pytest.mark.parametrize("fixture", DELIVERY)
def test_delivery_swap_moves_no_output_and_writes_n_of_n(pob, fixture: str) -> None:
    pob.load_xml(_xml(fixture))
    state = pob.read_state()["skills_state"]["socket_groups"]
    names = [g["gem_name"] for group in state for g in group["gems"]]
    expected = [n for n in names if vaal_twin(n)]
    assert expected, "the fixture must hold a gem with a Vaal version"
    before, main_before = _outputs(pob), _main_name(pob)
    pairs = deliver_vaal_twins(pob, Objective(maximize="CombinedDPS"), print, level_rail=18, quality_rail=0)
    assert [p for p, _ in pairs] == expected  # N of N
    after = pob.read_state()["skills_state"]["socket_groups"]
    written = [g for group in after for g in group["gems"] if g["gem_name"].startswith("Vaal ")]
    assert len(written) == len(expected)
    assert all((g["enable_global_1"], g["enable_global_2"]) == (False, True) for g in written)
    assert _main_name(pob) == main_before and _differ(before, _outputs(pob)) == {}
