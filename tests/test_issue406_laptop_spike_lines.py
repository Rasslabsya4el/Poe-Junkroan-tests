"""#406: the laptop's own spike lines. Without a `spike` block its ladder is off (Lines.from_config -> None)."""
import json
from pathlib import Path

from junkroan.runs import spike

HOSTS = Path(__file__).resolve().parents[1] / "config" / "hosts.json"
LAPTOP_RAM_MB = 8076  # Win32_ComputerSystem TotalPhysicalMemory 8,468,402,176 B read over ssh on 2026-10-15


def _cfg():
    return json.loads(HOSTS.read_text(encoding="utf-8"))


def test_the_laptop_has_spike_lines_so_its_ladder_is_on():
    lines = spike.Lines.from_config(_cfg()["laptop"].get("spike"))
    assert lines is not None
    assert (lines.cpu_pct_soft, lines.window_s) == (95.0, 300.0)


def test_the_laptop_ram_line_is_a_quarter_of_its_ram_like_the_pcs():
    lines = spike.Lines.from_config(_cfg()["laptop"]["spike"])
    assert abs(lines.ram_free_mb_hard - LAPTOP_RAM_MB * 0.25) < 1.0
    assert _cfg()["pc"]["spike"]["ram_free_mb_hard"] == 32768 * 0.25
