"""#707: a SELECTED merge suite that exits 5 (pytest: no test collected, all deselected by the suite's -m) is green;
a FULL suite exiting 5 and a selected suite exiting 1 stay red. Exit 5 is read from the return code."""

from __future__ import annotations

import re
import sys

from tests.test_issue690_merge_select import Rig, _line1
from tools.agentops import merge as merge_module

EXIT_STUB = """\
import sys
print("no tests ran in 0.1s" if {code} == 5 else "1 failed in 0.1s")
sys.exit({code})
"""


def _rig(tmp_path, monkeypatch, code: int, **kw) -> Rig:
    rig = Rig(tmp_path, monkeypatch, **kw)
    (tmp_path / "stub.py").write_text(EXIT_STUB.format(code=code), encoding="utf-8")
    return rig


def test_row1_selected_suite_exit5_is_green_with_a_zero_run_line(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch, 5)
    result = rig.land("feature-x", "src/a.py", "a = 2\n")
    assert result.ok and result.reason == "pushed", result.message
    assert result.failed_count in (0, None)
    text = open(result.suite_output_path, encoding="utf-8").read()
    assert re.search(r"selected 3 of 50; all 3 deselected by the suite's -m: 0 run", text)


def test_row2_full_suite_exit5_stays_red(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch, 5, with_map=False)
    result = rig.land("feature-y", "src/a.py", "a = 2\n")
    assert not result.ok and result.reason == "red-suite"
    assert _line1(result) == "full suite: no map"


def test_selected_suite_exit1_stays_red(tmp_path, monkeypatch):
    rig = _rig(tmp_path, monkeypatch, 1)
    result = rig.land("feature-z", "src/a.py", "a = 2\n")
    assert not result.ok and result.reason == "red-suite"
