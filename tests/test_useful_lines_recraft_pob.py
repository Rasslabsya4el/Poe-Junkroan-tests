"""#437 unit 4: removing an affix header from a loot rare is exact only when PoB re-renders the item text.

A rare rolled by `random_rares` carries every affix twice: the `Prefix:`/`Suffix:` header and its rendered text
after the implicit block (PoB takes the stats from the text). `useful_lines.without_lines` of a header drops the
header and every rendered text line, and PoB's own `Item:Craft()` re-renders what is left (`recraft`).

The measurement (every number read to the digit, no tolerance):

(a) for each header h of one rolled ring: the fast trial of `trial_item(slot, raw, [h])` (flag `recraft`) equals the
    fast trial of `craft_rare` of the remaining mods at the same ranges, on CombinedDPS, Life, the three resistances
    and Str / Dex / Int;
(b) `pob.recraft` of that raw, then a real `equip` + `stats`, equals the fast trial of (a);
(c) the cut that the issue replaces (header deleted, rendered text left) changes nothing in PoB: it equals the full item.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from junkroan.optimizer.useful_lines import item_lines, trial_item, without_lines
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

KEYS = ("CombinedDPS", "Life", "FireResist", "ColdResist", "LightningResist", "Str", "Dex", "Int")
BASE = "Iron Ring"
SLOT = "Ring 1"
HEADER = re.compile(r"^(Prefix|Suffix): \{range:([0-9.]+)\}(\S+)$")


@pytest.fixture(scope="module")
def pob():
    with PobSession(run_id="test-useful-lines-recraft", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()))
        yield session


def _headers(raw: str) -> list[tuple[str, float, str]]:
    return [(m.group(1), float(m.group(2)), m.group(3)) for line in raw.splitlines() if (m := HEADER.match(line))]


def _stats(pob: PobSession, item: dict) -> dict:
    out = pob.trial_stats([{"item": item}], KEYS, mode="fast")[0]
    assert out["ok"], out
    return out["stats"]


def test_recraft_trial_equals_a_craft_of_the_remaining_mods_and_equip(pob: PobSession) -> None:
    rolled = pob.random_rares(BASE, n=6, ilvl=84, quality=20, seed=11)
    raw = next(r["raw"] for r in rolled if len(_headers(r["raw"])) >= 5)
    headers = _headers(raw)
    lines = [ln for ln in item_lines(raw) if ln.kind in ("prefix", "suffix")]
    assert len(lines) == len(headers) >= 5
    assert "{prefix}" in raw or "{suffix}" in raw  # the raw carries rendered affix text

    full = _stats(pob, {"slot": SLOT, "raw": raw})
    print(f"RECRAFT full item: {full}")
    differing = 0
    for ln, (_kind, _rng, mod_id) in zip(lines, headers):
        assert ln.text == mod_id
        item = trial_item(SLOT, raw, [ln])
        assert item["recraft"] is True
        fast = _stats(pob, item)

        rest = [h for h in headers if h[2] != mod_id]
        crafted = pob.craft_rare(
            BASE,
            prefixes=[{"mod_id": m, "range": r} for k, r, m in rest if k == "Prefix"],
            suffixes=[{"mod_id": m, "range": r} for k, r, m in rest if k == "Suffix"],
            ilvl=84,
            quality=20,
        )
        assert crafted["problems"] == [], crafted
        reference = _stats(pob, {"slot": SLOT, "raw": crafted["raw"]})
        print(f"RECRAFT without {mod_id}: trial {fast}\nRECRAFT without {mod_id}: craft {reference}")
        assert fast == reference

        # (c) the old cut: the header goes, the rendered text stays -> PoB still sees the whole item
        header_only = "\n".join(piece for piece in raw.splitlines() if not piece.endswith(mod_id) or not HEADER.match(piece))
        assert _stats(pob, {"slot": SLOT, "raw": header_only}) == full
        differing += fast != full

        # (b) the delivered item: recraft once, then a real equip and a full stats read
        delivered = pob.recraft(without_lines(raw, [ln]))
        pob.equip({SLOT: delivered})
        assert pob.stats(KEYS) == fast
    assert differing >= 1  # at least one removed affix changes what PoB computes
