"""#435 u5 witness: whitening + the colour step on the `cold_dot` fixture in a real PoB session."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from junkroan.optimizer.objective import Objective, better_score
from junkroan.optimizer.socket_step import (
    SOCKET_SLOTS,
    _sockets_line,
    colour_candidates,
    colour_step,
    slot_groups,
    whiten_equipped,
)
from junkroan.pob.session import PobSession, decode_import_code, raw_with_sockets
from junkroan.search.sockets import coloured_max, gem_colour, whiten

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]


def test_cold_dot_whiten_then_colour_at_most_two():
    xml = decode_import_code((FIXTURES / "cold_dot.pob.txt").read_text(encoding="utf-8").strip())
    objective = Objective(maximize="CombinedDPS")
    keys = objective.stat_keys
    with PobSession(run_id="test-435-colour-step", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        entry = objective.score(pob.stats(keys))
        groups = slot_groups(pob)
        raws = dict(pob.equipped_item_raws())
        print("sockets at entry:", {s: _sockets_line(r) for s, r in raws.items() if s in SOCKET_SLOTS})
        changed = whiten_equipped(pob, raws, groups)
        raws.update(changed)
        whitened = objective.score(pob.stats(keys))
        print(f"entry {entry.value:,.1f} -> whitened {whitened.value:,.1f}; whitened slots {sorted(changed)}")

        candidates = colour_candidates(raws, groups)
        single = {}
        for cand in candidates:
            touched = raw_with_sockets(raws[cand.slot], whiten(_sockets_line(raws[cand.slot]), {cand.position: cand.colour}))
            pob.equip({cand.slot: touched})
            single[cand] = objective.score(pob.stats(keys)).value
            pob.equip({cand.slot: raws[cand.slot]})
            print(f"  candidate {cand.slot}[{cand.position}] {cand.gem} {cand.colour}: {single[cand]:,.2f} (white {whitened.value:,.2f})")
        assert objective.score(pob.stats(keys)).value == pytest.approx(whitened.value)

        logs: list[str] = []
        started = time.perf_counter()
        result = colour_step(pob, objective, lambda new, cur: better_score(new, cur), logs.append)
        seconds = time.perf_counter() - started
        print(logs, f"the step took {seconds:.1f} s over {result.trials} trials")

        after = objective.score(pob.stats(keys))
        assert after.value >= whitened.value - 1e-6 and result.score_after.value == pytest.approx(after.value)
        assert len(result.picks) <= (coloured_max("day1") or 2)

        # at most two R/G/B sockets over all items, each holding a gem of its colour that PoB sees as matching
        final = pob.equipped_item_raws()
        coloured = [(slot, i, c) for slot, raw in final.items() if slot in SOCKET_SLOTS
                    for i, c in enumerate(ch for ch in (_sockets_line(raw) or "") if ch.isalpha()) if c in "RGB"]
        assert len(coloured) <= 2
        state_groups = (pob.read_state()["skills_state"])["socket_groups"]
        matching = {}
        offsets: dict[str, int] = {}
        for g in state_groups:
            slot = g.get("slot")
            if not slot:
                continue
            for i, gem in enumerate(g["gems"]):
                matching[(slot, offsets.get(slot, 0) + i)] = (gem["gem_name"], gem["matches_socket"])
            offsets[slot] = offsets.get(slot, 0) + len(g["gems"])
        for slot, i, c in coloured:
            name, matches = matching[(slot, i)]
            assert gem_colour(name.removesuffix(" Support")) == c and matches, (slot, i, c, name)
        assert {(p.slot, p.position) for p in result.picks} == {(s, i) for s, i, _ in coloured}

        main = groups.get("Body Armour", [("", True)])[0][0]
        main_cands = [c for c in candidates if c.gem == main]
        if main_cands and max(single[c] for c in main_cands) > whitened.value:
            assert any(p.gem == main for p in result.picks) or len(result.picks) == (coloured_max("day1") or 2)
