"""#1207: a test module that reads `vendor/pob` at import is skipped, not errored, in a copy without `vendor/pob`.

The GitHub Windows job copies the repo without `vendor/pob` (gitignored, a junction on the PC). Three test modules
open `vendor/pob/source/.../amulet.lua` at import; collection then fails and the whole job falls back to the PC.
`pytest_make_collect_report` in `tests/conftest.py` turns exactly that collect error into a skip.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from conftest import GITHUB_ONLY_SKIPS, github_only_skip_reason, is_missing_pob_collect_error

REPO = Path(__file__).resolve().parents[1]
REAL_CONFTEST = REPO / "tests" / "conftest.py"

MISSING_POB_TEXT = (
    "FileNotFoundError: [Errno 2] No such file or directory: "
    "'C:\\\\a\\\\repo\\\\vendor\\\\pob\\\\source\\\\src\\\\Data\\\\Bases\\\\amulet.lua'"
)


def test_missing_vendor_pob_file_error_is_skipped_when_vendor_pob_is_absent():
    assert is_missing_pob_collect_error(MISSING_POB_TEXT, pob_source_present=False) is True


def test_same_error_is_not_skipped_when_vendor_pob_is_present():
    assert is_missing_pob_collect_error(MISSING_POB_TEXT, pob_source_present=True) is False


def test_module_not_found_error_is_not_skipped():
    text = "ModuleNotFoundError: No module named 'vendor_pob_helper'"
    assert is_missing_pob_collect_error(text, pob_source_present=False) is False


def test_file_not_found_for_another_file_is_not_skipped():
    text = "FileNotFoundError: [Errno 2] No such file or directory: 'var/cache/other.json'"
    assert is_missing_pob_collect_error(text, pob_source_present=False) is False


def test_syntax_error_that_mentions_vendor_and_pob_is_not_skipped():
    text = "SyntaxError: invalid syntax in vendor/pob/source/src/Data/Bases/amulet.lua"
    assert is_missing_pob_collect_error(text, pob_source_present=False) is False


def test_unrelated_missing_file_in_a_traceback_that_mentions_vendor_and_pob_elsewhere_is_not_skipped():
    text = (
        "src/junkroan/pob/session.py:10: in start\n    open(cfg)\n"
        "E   FileNotFoundError: [Errno 2] No such file or directory: 'var/vendor_list.json'"
    )
    assert is_missing_pob_collect_error(text, pob_source_present=False) is False


def test_end_to_end_collect_of_a_module_reading_missing_pob_is_a_skip_not_an_error(tmp_path):
    """A temp tests dir whose module opens `vendor/pob/x.lua` at import, with the real hook loaded through its conftest."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_reads_pob.py").write_text(textwrap.dedent("""
        from pathlib import Path

        open(Path(__file__).resolve().parents[1] / "vendor" / "pob" / "x.lua", encoding="utf-8")

        def test_never_runs():
            pass
    """), encoding="utf-8")
    (tests / "conftest.py").write_text(textwrap.dedent(f"""
        import importlib.util
        from pathlib import Path

        _spec = importlib.util.spec_from_file_location("real_conftest_1207", {str(REAL_CONFTEST)!r})
        _real = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_real)
        _real.POB_SOURCE_DIR = Path(__file__).resolve().parents[1] / "vendor" / "pob" / "source"
        pytest_make_collect_report = _real.pytest_make_collect_report
    """), encoding="utf-8")
    # the merge suite puts `-p <plugin>` into PYTEST_ADDOPTS (merge.py:2834/2844): a nested pytest in tmp_path cannot import it
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS" and not k.startswith("PYTEST_XDIST")}
    env["PYTHONPATH"] = str(REPO / "src")
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests), "-q", "-rs", "-p", "no:cacheprovider"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120,
    )
    out = done.stdout + done.stderr
    assert "error" not in out.lower(), out
    assert "SKIPPED [1]" in out and "vendor/pob is not in this copy (#1207)" in out, out
    assert done.returncode == 5, out  # nothing collected, nothing errored


def _nested_run(tmp_path, body, hook_names):
    """A temp tests dir with one module and a conftest that loads the real hooks; returns the nested pytest's output."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_reads_pob.py").write_text(textwrap.dedent(body), encoding="utf-8")
    (tests / "conftest.py").write_text(textwrap.dedent(f"""
        import importlib.util
        from pathlib import Path

        _spec = importlib.util.spec_from_file_location("real_conftest_1207", {str(REAL_CONFTEST)!r})
        _real = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_real)
        _real.POB_SOURCE_DIR = Path(__file__).resolve().parents[1] / "vendor" / "pob" / "source"
    """) + "".join(f"{n} = _real.{n}\n" for n in hook_names), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS" and not k.startswith("PYTEST_XDIST")}
    env["PYTHONPATH"] = str(REPO / "src")
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests), "-q", "-rs", "-p", "no:cacheprovider"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120,
    )
    return done


def test_a_test_that_opens_missing_pob_at_run_time_is_a_skip_in_a_copy_without_pob(tmp_path):
    done = _nested_run(tmp_path, """
        from pathlib import Path

        def test_reads_pob_while_running():
            (Path(__file__).resolve().parents[1] / "vendor" / "pob" / "source" / "x.lua").read_text()
    """, ["pytest_runtest_makereport"])
    out = done.stdout + done.stderr
    assert "failed" not in out.lower(), out
    assert "vendor/pob is not in this copy (#1207)" in out, out
    assert done.returncode == 5 or "1 skipped" in out, out


def test_a_run_time_error_that_is_not_a_missing_pob_file_still_fails(tmp_path):
    done = _nested_run(tmp_path, """
        def test_other_error():
            open("var/other_missing.json")
    """, ["pytest_runtest_makereport"])
    assert done.returncode == 1, done.stdout + done.stderr
    assert "1 failed" in done.stdout, done.stdout


def test_github_only_skips_apply_on_github_for_every_listed_test():
    for nodeid in GITHUB_ONLY_SKIPS:
        assert "#1207" in github_only_skip_reason(nodeid, {"GITHUB_ACTIONS": "true"})


def test_github_only_skips_never_apply_on_the_pc_or_to_other_tests():
    nodeid = next(iter(GITHUB_ONLY_SKIPS))
    assert github_only_skip_reason(nodeid, {}) is None
    assert github_only_skip_reason(nodeid, {"GITHUB_ACTIONS": "false"}) is None
    assert github_only_skip_reason("tests/test_other.py::test_x", {"GITHUB_ACTIONS": "true"}) is None
