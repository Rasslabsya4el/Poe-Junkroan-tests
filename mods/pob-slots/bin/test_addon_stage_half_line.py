"""#992: the monitor's build card never shows half a word as a build's step.

A log whose last line has no trailing newline is still being written: `build_stage` ignores that line and names the last
full `step start:` line. Checked on the recorded `bleed_bow` seed 4 log (cut mid-line at `step start: confi`) and on the
payload fixture's running log (`logs/bleed_bow-s1.log`, read by `_fill_cell` only under its `.log` name).

    python -m pytest -q -p no:cacheprovider mods/pob-slots/bin/test_addon_stage_half_line.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()
FIX = Path(__file__).resolve().parent / "fixtures"
BLEED_S4 = FIX / "laptop_run" / "bench" / "20261013-2221-P2-core" / "logs" / "bleed_bow-s4.log"
PAYLOAD_RUN = FIX / "payload" / "bench" / "20261011-1000-snap-run"


def test_build_stage_on_the_cut_log_names_the_last_full_step():
    keep, addon.stage_shares = addon.stage_shares, lambda: None  # no weekly run: the bar is not under test here
    try:
        st = addon.build_stage(BLEED_S4, 0.0, 400.0)
        assert BLEED_S4.read_text(encoding="utf-8").endswith("step start: confi"), "the fixture is cut mid-line"
        assert st["step"] == "skeleton applied" and st["group"] == "construction", st
        assert st["stage"] == "construction: skeleton applied" and st["stage_index"] == 1, st
        assert "confi" not in st["stage"], st
    finally:
        addon.stage_shares = keep


def test_a_last_line_without_newline_is_not_a_step():
    keep, addon.stage_shares = addon.stage_shares, lambda: None
    try:
        with tempfile.TemporaryDirectory() as t:
            log = Path(t) / "x.log"
            head = "step start: skeleton applied\n  skeleton applied                 4.9 s  value        3,201\n"
            log.write_text(head + "step start: config (conservative lane)", encoding="utf-8")
            assert addon.build_stage(log, 0.0, 400.0)["step"] == "skeleton applied"
            log.write_text(head + "step start: config (conservative lane)\n", encoding="utf-8")  # the same line, complete
            assert addon.build_stage(log, 0.0, 400.0)["step"] == "config (conservative lane)"
    finally:
        addon.stage_shares = keep


def test_payload_running_log_is_read_by_fill_cell():
    keep, addon.stage_shares = addon.stage_shares, lambda: None
    try:
        assert (PAYLOAD_RUN / "logs" / "bleed_bow-s1.log").exists(), "the running log is named .log"
        assert not (PAYLOAD_RUN / "logs" / "bleed_bow-s1.log.txt").exists()
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "run"
            shutil.copytree(PAYLOAD_RUN, d)
            cell, took = {}, []
            addon._fill_cell(cell, d, "bleed_bow-s1", took)
            assert cell["state"] == "running" and cell["step"] == "gear" and cell["stage"] == "gear", cell
    finally:
        addon.stage_shares = keep


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
