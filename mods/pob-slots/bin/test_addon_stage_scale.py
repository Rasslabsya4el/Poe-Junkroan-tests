"""#985 c: the stage scale of a running build (`stage_index` / `stage_count`) comes only from real `step start:` lines.

The fixture is a real slice of a finished run's pipeline log (artifacts/runs/20261011-0930-diagnose_unspent_817.out,
lines 2-13), dedented to the raw form the benchmark writes (scripts/benchmark.py `_log_to`: `msg + "\\n"`, column 0).
Plain python: python test_addon_stage_scale.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stage_log_summon_raging_spirits.txt"


def _stage(text: str) -> dict:
    with tempfile.TemporaryDirectory() as t:
        log = Path(t) / "x.log"
        log.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")  # the writer ends every line (#992)
        return addon.build_stage(log, 0.0, 400.0)


def test_scale_present_for_real_step_lines():
    keep, addon.stage_shares = addon.stage_shares, lambda: None  # no weekly run: the bar is not under test here
    try:
        lines = FIXTURE.read_text(encoding="utf-8").splitlines()
        count = len(addon._catalog().STEPS)
        assert count == 27, count  # #1156: the `fill` step sits among the construction steps, before the loop
        # the step named by the last start line, cut at that line: its 1-based place in the catalog
        for name, want in (("gear pass 1 (empty tree)", 6), ("tree greedy", 11), ("gear pass 2 (with tree)", 12),
                           ("tree rebuilt on gear", 13)):
            k = lines.index(f"step start: {name}")
            st = _stage("\n".join(lines[:k + 1]))
            assert (st["stage_index"], st["stage_count"], st["step"]) == (want, count, name), st
        # the loop's marks: "loop opening" is the 22nd mark, "loop pass <N>" the 23rd, whatever N is (#1156 `fill` = 20th)
        loop = lines + ["step start: loop opening", "step start: loop pass 2", "loop pass 2 move refine"]
        st = _stage("\n".join(loop))
        assert (st["stage_index"], st["stage_count"], st["stage"]) == (23, count, "improvement loop, pass 2, refine"), st
        st = _stage("\n".join(lines + ["step start: loop opening"]))
        assert (st["stage_index"], st["stage_count"]) == (22, count), st
        # the whole real slice: the scale is the last named step's place, never the count of lines seen
        full = _stage(FIXTURE.read_text(encoding="utf-8"))
        assert (full["stage"], full["stage_index"], full["stage_count"]) == ("construction: tree rebuilt on gear", 13, count), full
    finally:
        addon.stage_shares = keep


def test_scale_absent_without_a_real_step():
    keep, addon.stage_shares = addon.stage_shares, lambda: None
    try:
        # no start line yet: no step is named, so no scale
        assert _stage("author raw 1 CombinedDPS\n") == {}
        # an older pipeline's log (ended stages only, no start lines): `after` is a fact, no scale
        old = _stage("  skeleton applied                 4.9 s  value        3,201\n"
                     "  gear pass 1 (empty tree)       2.7 min  value\n")
        assert old == {"after": "подбирает Items"}, old
        # a start line that no catalog step matches: the step is named as written, with no group and no scale
        st = _stage("step start: a step nobody wrote down\n")
        assert "stage_index" not in st and "stage_count" not in st and st["group"] is None, st
    finally:
        addon.stage_shares = keep


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
