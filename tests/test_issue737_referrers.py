"""#737 rule C: a .py the map has no row for selects the tests of its referrers. Fixtures = the four real diffs of
2026-10-10 over the real map of 7e176f8 (var/agentops/test_map, built by the full run; read only here)."""
import os
import subprocess
import time
from pathlib import Path

import pytest

from tools.agentops import test_select as ts
from tests.test_issue690_select import Rig, commit, sh

ROOT = Path(__file__).resolve().parents[1]
MDIR = ts.map_dir(ROOT)
def _real_map_has_tests() -> bool:
    """The real map counts only when it holds tests: var/agentops/test_map with ``total`` 0 is no map (#74)."""
    meta = ts.read_meta(MDIR) or {}
    return (MDIR / "testmondata").is_file() and int(meta.get("total") or 0) > 0


needs_map = pytest.mark.skipif(not _real_map_has_tests(),
                               reason="real test map holds 0 tests (var/agentops/test_map): a full run must rebuild it")


def _head_with(path: str, base: str = "HEAD") -> str:
    """A commit over ``base`` that appends a line to ``path``, built with a scratch index (no ref, no worktree change)."""
    idx = ROOT / "var" / f"index737-{os.getpid()}"
    env = {**os.environ, "GIT_INDEX_FILE": str(idx)}
    g = lambda *a, inp=None: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True,  # noqa: E731
                                            env=env, input=inp, encoding="utf-8").stdout.strip()
    try:
        g("read-tree", base)
        blob = g("hash-object", "-w", "--stdin", inp=g("show", f"{base}:{path}") + "\n# 737\n")
        g("update-index", "--cacheinfo", f"100644,{blob},{path}")
        tree = g("write-tree")
        return g("-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", tree, "-p", base, "-m", "x")
    finally:
        idx.unlink(missing_ok=True)


def _sel(path: str, mdir=MDIR):
    base = sh(ROOT, "rev-parse", "HEAD")
    t = time.perf_counter()
    s = ts.select_for_diff(ROOT, base, _head_with(path), mdir)
    return s, time.perf_counter() - t


def _files(s):
    return {i.split("::", 1)[0] for i in s.ids}


@needs_map
def test_row1_modes_py_selects_its_referrers_not_the_suite():
    s, _ = _sel("src/junkroan/search/modes.py")
    assert not s.full and 0 < len(s.ids) < 200, (s.full, len(s.ids), s.line)


@needs_map
def test_row2_measure_724_selects_the_younger_test_file_whole():
    s, _ = _sel("scripts/measure_724.py")
    # rule B (#737) also adds every test file younger than the map
    assert not s.full and "tests/test_measure_724_table.py" in s.ids, (s.full, s.ids[:5])


def _young_test_files() -> set[str]:
    """Test files added or changed since the map's commit: rule B runs them whole, by design, whatever the map says."""
    mc = str((ts.read_meta(MDIR) or {}).get("map_commit") or "")
    out = sh(ROOT, "diff", "--name-status", "--no-renames", mc, "HEAD").splitlines()
    return {f for st, f in (ln.split("\t", 1) for ln in out) if st != "D" and ts.TEST_FILE.fullmatch(f)}


@needs_map
def test_row3_junkroan_py_ignores_the_conftest_docstring():
    s, _ = _sel("scripts/junkroan.py")
    assert not s.full, s.line
    # The bound reads the referrer part only. The young test files (170 at 6f5f9c50, a map 185 commits old) grow with
    # the map's age and are not the referrers' doing; the 542 of the 3e182359 run was the referrer alias bug (a src
    # package `junkroan` counted as a referrer of scripts/junkroan.py: 477 mapped test ids of runs tests), fixed in c4aaab34.
    own = [i for i in s.ids if i.split("::", 1)[0] not in _young_test_files()]
    assert all("::" not in i for i in own), (own[:5], s.line)  # junkroan.py has no source referrer: only whole test files
    assert len(own) < 50, (len(own), s.line)
    assert "tests/test_cli.py" in _files(s) or "tests/test_cli.py" in s.ids
    assert "tests/test_issue732_launcher_shadow.py" in s.ids
    assert "tests/conftest.py" not in s.ids and not any(i.startswith("tests/conftest.py") for i in s.ids)


def _map_without_row(tmp_path, filename: str) -> Path:
    """A copy of the real map with the testmon rows of ``filename`` deleted (machine_load.py had none before 220cf47)."""
    import shutil
    import sqlite3
    m = tmp_path / "map"
    shutil.copytree(MDIR, m)
    con = sqlite3.connect(m / "testmondata")
    con.execute("delete from test_execution_file_fp where fingerprint_id in (select id from file_fp where filename = ?)",
                (filename,))
    con.commit()
    con.close()
    return m


@needs_map
def test_row4_machine_load_py_is_not_the_suite(tmp_path):
    m = _map_without_row(tmp_path, "scripts/machine_load.py")
    assert "scripts/machine_load.py" not in ts.load_testmon(str(m / "testmondata"))[0]
    s, _ = _sel("scripts/machine_load.py", m)
    assert not s.full and len(s.ids) < 2000, (s.full, len(s.ids), s.line)


def _spin_seconds() -> float:
    t = time.perf_counter()
    n = 0
    for i in range(3_000_000):
        n += i
    return time.perf_counter() - t


@needs_map
def test_row9_selection_time_on_the_real_tree():
    _, dt = _sel("scripts/junkroan.py")
    # The bound is 5 s on a quiet machine and 60 x a fixed CPU spin timed here (0.13 s quiet, so 8 s) when the
    # machine is busy: a load that slows the spin slows the selection too (#823, 5.52 s beside a full run).
    assert dt < max(5, 60 * _spin_seconds()), f"{dt:.2f} s"


def test_row5_unreferenced_py_selects_nothing_and_says_why(tmp_path):
    r = Rig(tmp_path)
    c1 = commit(r.root, {"src/orphan.py": "x = 1\n"})
    c2 = commit(r.root, {"src/orphan.py": "x = 2\n"})
    s = ts.select_for_diff(r.root, c1, c2, r.mdir)
    assert not s.full and s.ids == [] and s.reason == "no test reaches src/orphan.py", (s.full, s.ids, s.reason)
    assert "no test reaches src/orphan.py" in s.line


def test_referrer_rules_import_string_docstring_comment(tmp_path):
    r = Rig(tmp_path)
    c1 = commit(r.root, {
        "src/lib.py": "x = 1\n",
        "src/impmod.py": "def f():\n    from . import lib\n",                       # function-level relative import
        "scripts/runner.py": 'CMD = ["python", "scripts/tool.py"]\n',          # file name in a string
        "scripts/tool.py": "y = 1\n",
        "tests/test_via_imp.py": "import impmod\n\ndef test_a(): pass\n",
        "tests/test_via_str.py": "from scripts import runner\n\ndef test_b(): pass\n",
        "tests/test_doc.py": '"""mentions lib.py and tool.py"""\n# lib.py tool.py\ndef test_c(): pass\n',
    })
    ts.write_meta(r.mdir, {**ts.read_meta(r.mdir), "map_commit": c1})  # map as young as c1: no rule B files
    c2 = commit(r.root, {"src/lib.py": "x = 2\n", "scripts/tool.py": "y = 2\n"})
    s = ts.select_for_diff(r.root, c1, c2, r.mdir)
    assert not s.full and "tests/test_via_imp.py" in s.ids and "tests/test_via_str.py" in s.ids
    assert "tests/test_doc.py" not in s.ids, s.ids


def test_row8_data_file_nobody_reads_is_still_full(tmp_path):
    r = Rig(tmp_path)
    c1 = commit(r.root, {"config/unread.json": "{}"})
    c2 = commit(r.root, {"config/unread.json": '{"a": 1}'})
    s = ts.select_for_diff(r.root, c1, c2, r.mdir)
    assert s.full and s.reason == "data change"  # core: config/ is a data-change prefix, full whether read or not
