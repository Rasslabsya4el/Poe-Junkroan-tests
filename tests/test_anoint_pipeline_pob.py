"""What the pipeline's amulet trials measure when an anointed amulet is worn (#432 unit 5).

PoB's `CopyAnointsAndEldritchImplicits` (ItemsTab.lua:1817-1829) hands the worn amulet's single anoint to a new
amulet that carries none. The headless item trial calls it too (headless_runtime_worker.py, trial.item branch), so:
(a) a fast trial of a PLAIN amulet over a worn anointed one inherits the anoint, unlike a full equip after
emptying the slot; (b) a fast trial of anoint B over worn anoint A keeps B and equals the full equip of B.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.anoint_line import anoint_of, apply_anoint
from junkroan.pob.session import PobSession, decode_import_code

from test_anoint_pob import BUILD, DAY1_OILS, FIXTURES, NOTABLE, PROJECT_ROOT, _amulet_raw, needs_pob

KEYS = ("Life", "TotalEHP")


def _other_notable(tree_nodes: set[int]) -> str:
    records = json.loads((PROJECT_ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "passives.json").read_text(encoding="utf-8"))["records"]
    for r in sorted(records, key=lambda r: r["name"]):
        if r["is_notable"] and r["name"] != NOTABLE and r["recipe"] and set(r["recipe"]) <= DAY1_OILS and int(r["node_id"]) not in tree_nodes:
            return r["name"]
    raise AssertionError("no second anointable notable")


@needs_pob
@pytest.mark.pob
def test_fast_trial_over_a_worn_anoint_plain_inherits_it_and_another_anoint_replaces_it() -> None:
    xml = decode_import_code((FIXTURES / f"{BUILD}.pob.txt").read_text(encoding="utf-8").strip())
    plain = _amulet_raw(xml)
    assert anoint_of(plain) is None
    anointed_a = apply_anoint(plain, NOTABLE)

    with PobSession(run_id="test-anoint-pipeline-pob", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        pob.equip({"Amulet": plain})
        tree_nodes = set(pob.mutate_nodes()["allocated_node_ids"])
        other = _other_notable(tree_nodes)
        anointed_b = apply_anoint(plain, other)

        # the references: full equips with the slot emptied first
        pob.equip({"Amulet": None})
        pob.equip({"Amulet": plain})
        full_plain = pob.stats(KEYS)
        pob.equip({"Amulet": None})
        pob.equip({"Amulet": anointed_b})
        full_b = pob.stats(KEYS)
        pob.equip({"Amulet": None})
        pob.equip({"Amulet": anointed_a})
        full_a = pob.stats(KEYS)
        assert pob.granted_passives() != ()

        # worn: anoint A
        fast_plain = pob.trial_stats([{"item": {"slot": "Amulet", "raw": plain}}], KEYS, mode="fast")[0]
        fast_b = pob.trial_stats([{"item": {"slot": "Amulet", "raw": anointed_b}}], KEYS, mode="fast")[0]
        assert fast_plain["ok"] and fast_b["ok"], (fast_plain, fast_b)

    print(f"\nanoint A {NOTABLE}, B {other} on {BUILD}: full plain Life {full_plain['Life']} TotalEHP {full_plain['TotalEHP']}; "
          f"full A Life {full_a['Life']} TotalEHP {full_a['TotalEHP']}; full B Life {full_b['Life']} TotalEHP {full_b['TotalEHP']}; "
          f"fast plain-over-A Life {fast_plain['stats']['Life']} TotalEHP {fast_plain['stats']['TotalEHP']}; "
          f"fast B-over-A Life {fast_b['stats']['Life']} TotalEHP {fast_b['stats']['TotalEHP']}")
    # (a) the plain amulet over a worn anointed one inherits the anoint: it measures A, not the plain amulet
    assert fast_plain["stats"]["Life"] == pytest.approx(full_a["Life"], rel=0.001)
    assert fast_plain["stats"]["TotalEHP"] == pytest.approx(full_a["TotalEHP"], rel=0.001)
    assert full_a["Life"] != pytest.approx(full_plain["Life"], rel=0.001)
    # (b) anoint B over worn anoint A is B
    assert fast_b["stats"]["Life"] == pytest.approx(full_b["Life"], rel=0.001)
    assert fast_b["stats"]["TotalEHP"] == pytest.approx(full_b["TotalEHP"], rel=0.001)
