"""#772 unit 1: failed ids come only from pytest's last "short test summary info"; a re-check drops a
not-found id and keeps every id only when it produced no output (stub suites, no PoB)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.test_agentops_line_check import Rig, _drive, _final, _protect  # noqa: F401  (autouse fixture)
from tools.agentops import full_run, merge as m

DATA = Path(__file__).parent / "data" / "full_run_26cf3ef4_trimmed.out"
REAL = "tests/test_agentops_merge_line_check.py::test_row2_a_flaky_failure_stays_in_the_line_and_is_batched"
FAKE = "tests/t.py::bad"


def _text() -> str:
    return DATA.read_text(encoding="utf-8")


def test_row1_stored_output_gives_the_one_real_test():
    assert FAKE in _text()  # the captured stdout line is in the data
    assert m._failed_ids(_text()) == [REAL]
    assert m._parse_pytest_failures(_text()) == (1, [REAL])


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    yield r
    for c in r.checks:
        c.stop()


def test_row2_each_callers_path_gets_one_id(tmp_path, rig):
    # full run, merge suite (:2006) and single-branch merge (:2465) all read through _parse_pytest_failures
    assert full_run._merge._parse_pytest_failures is m._parse_pytest_failures
    assert m._parse_pytest_failures(_text())[1] == [REAL]
    assert m._failed_ids(_text()) == [REAL]  # merge suite's red_ids (:1932)
    # the waiting-branch check: a suite that prints the stored output and fails, passes the re-check
    stub = tmp_path / "s.py"
    stub.write_text(
        "import sys, pathlib\n"
        f"p = pathlib.Path(r'{rig.dir}') / 'calls.txt'\n"
        "ids = sys.argv[1:]\n"
        "p.open('a').write(('RE ' + ' '.join(ids) if ids else 'FULL') + chr(10))\n"
        f"print(open(r'{DATA}', encoding='utf-8').read()) if not ids else print('1 passed')\n"
        "sys.exit(0 if ids else 1)\n", encoding="utf-8")
    c = rig.check(1, f'"{sys.executable}" "{stub}"')
    _drive([c], lambda: _final(c))
    assert rig.calls() == ["FULL", f"RE {REAL}"]


RECHECK_STUB = """\
import sys
ids = sys.argv[1:]
if "tests/t.py::gone" in ids:
    print("ERROR: file or directory not found: tests/t.py::gone"); sys.exit(4)
if ids and "{mode}" == "silent":
    sys.exit(1)
print("1 passed"); sys.exit(0)
"""


def _recheck(tmp_path, mode, ids):
    stub = tmp_path / "rc.py"
    stub.write_text(RECHECK_STUB.replace("{mode}", mode), encoding="utf-8")
    out = tmp_path / "rc.out"
    return m._recheck_failed(f'"{sys.executable}" "{stub}"', ids, tmp_path, None, out), out


def test_row3_not_found_id_is_dropped_and_named(tmp_path):
    (still, output), out = _recheck(tmp_path, "pass", ["tests/t.py::gone", "tests/t.py::ok"])
    assert still == []
    assert "could not find tests/t.py::gone" in output
    assert "could not find tests/t.py::gone" in out.read_text(encoding="utf-8")


def test_row4_a_recheck_with_no_output_keeps_every_id(tmp_path):
    (still, output), _ = _recheck(tmp_path, "silent", ["tests/t.py::a", "tests/t.py::b"])
    assert still == ["tests/t.py::a", "tests/t.py::b"]
    assert not output.strip()
