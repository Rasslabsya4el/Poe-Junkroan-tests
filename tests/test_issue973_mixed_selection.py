"""#973: a selection holding tests/ ids and mods/<mod>/bin/ ids collects with 0 errors.

The bin folder's MONITOR_ROOT pin used to be a ``conftest.py``, which shadowed ``tests/conftest.py`` for
``from conftest import pc_only`` in a mixed run (32 collection errors on the merge of #962). The pin is now a
plugin (``mods/pob-slots/bin/pob_slots_pin.py``, loaded by the root ``pytest.ini``); its check is below.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "mods" / "pob-slots" / "bin"


def test_mixed_selection_collects_without_errors():
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_pane_dump.py", "mods/pob-slots/bin/test_cost_cut.py",
         "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    out = run.stdout + run.stderr
    assert run.returncode == 0, out[-3000:]
    assert "ERROR" not in out, out[-3000:]


def test_bin_plugin_pins_only_bin_files(monkeypatch):
    monkeypatch.delenv("MONITOR_ROOT", raising=False)
    sys.path.insert(0, str(BIN))
    try:
        plugin = importlib.import_module("pob_slots_pin")
        plugin.pytest_collect_file(file_path=ROOT / "tests" / "test_pane_dump.py", parent=None)
        assert "MONITOR_ROOT" not in os.environ
        plugin.pytest_collect_file(file_path=BIN / "test_cost_cut.py", parent=None)
        assert os.environ["MONITOR_ROOT"] == str(ROOT)
    finally:
        sys.path.remove(str(BIN))
        sys.modules.pop("pob_slots_pin", None)
