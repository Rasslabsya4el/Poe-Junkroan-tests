"""#1207 unit 2: a failure caused by a file the GitHub test copy omits is a skip, keyed on the cause.

The merge's `test (windows)` job runs the PC-only files in a copy that omits some files (`test_copy_exclude`), has no
`artifacts/`, `var/` and `vendor/pob`, and lacks the `test_copy_standins` stand-ins' sources. A test that reads one of
those fails there with a missing-file error that names the location. `omitted_locations` lists which locations are absent
under a root; `is_omitted_file_error` says whether one line of a failure names a missing file and one absent location.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from conftest import PROJECT_ROOT, is_omitted_file_error, omitted_locations

REPO = Path(__file__).resolve().parents[1]

ARTIFACTS_LINE = (
    r"FileNotFoundError: [Errno 2] No such file or directory: "
    r"'D:\a\Poe-Junkroan-tests\Poe-Junkroan-tests\artifacts\benchmark\x\results.json'"
)


def test_missing_file_line_under_an_omitted_location_is_omitted():
    assert is_omitted_file_error(ARTIFACTS_LINE, ["artifacts"]) is True


def test_same_missing_file_is_not_omitted_when_no_location_is_absent():
    assert is_omitted_file_error(ARTIFACTS_LINE, []) is False


def test_missing_file_outside_every_omitted_location_is_not_omitted():
    text = "FileNotFoundError: [Errno 2] No such file or directory: 'src/junkroan/foo.py'"
    assert is_omitted_file_error(text, ["artifacts"]) is False


def test_assertion_error_that_names_an_omitted_location_is_not_omitted():
    text = "AssertionError: artifacts/benchmark/x/results.json has 3 rows, expected 4"
    assert is_omitted_file_error(text, ["artifacts"]) is False


def test_no_fixture_message_names_an_excluded_file_by_its_basename_and_is_omitted():
    text = "FileNotFoundError: no fixture z326_elementalist_wave_of_conviction.pob.txt in ['tests\\fixtures\\tuadh_329']"
    locations = ["tests/fixtures/zizaran_326/early/elementalist_wave_of_conviction.pob.txt"]
    assert is_omitted_file_error(text, locations) is True


def test_omitted_locations_on_an_empty_root_lists_every_candidate(tmp_path):
    settings = {"test_copy_exclude": ["a/b.txt"], "test_copy_standins": {"x": "s/y.json"}}
    assert omitted_locations(tmp_path, settings) == ["artifacts", "var", "vendor/pob", "a/b.txt", "s/y.json"]


def test_omitted_locations_drops_what_exists_under_the_root(tmp_path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x", encoding="utf-8")
    settings = {"test_copy_exclude": ["a/b.txt"], "test_copy_standins": {"x": "s/y.json"}}
    assert omitted_locations(tmp_path, settings) == ["var", "vendor/pob", "s/y.json"]


def test_test_issue232_shard_passes_under_test_pc_only_in_a_child_pytest():
    """#1207 (c): the job's TEST_PC_ONLY must not leak into the tests' bodies. Before the autouse fixture the leak failed 14
    of test_issue232_shard's tests."""
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS" and not k.startswith("PYTEST_XDIST")}
    env["TEST_PC_ONLY"] = "1"
    env["PYTHONPATH"] = str(REPO / "src")
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_issue232_shard.py", "-q", "-p", "no:faulthandler"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=180,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def _hook_run(tmp_path, body):
    """A nested pytest whose conftest loads the real hooks with the repo root set to tmp_path (no artifacts/ there)."""
    import textwrap

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text(textwrap.dedent(body), encoding="utf-8")
    (tests / "conftest.py").write_text(textwrap.dedent(f"""
        import importlib.util
        from pathlib import Path

        _spec = importlib.util.spec_from_file_location("real_conftest_1207b", {str(PROJECT_ROOT / "tests" / "conftest.py")!r})
        _real = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_real)
        _real.PROJECT_ROOT = Path(__file__).resolve().parents[1]
        _real._SETTINGS = {{}}
        pytest_runtest_makereport = _real.pytest_runtest_makereport
        pytest_make_collect_report = _real.pytest_make_collect_report
    """), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS" and not k.startswith("PYTEST_XDIST")}
    env["PYTHONPATH"] = str(REPO / "src")
    return subprocess.run([sys.executable, "-m", "pytest", str(tests), "-q", "-rs", "-p", "no:cacheprovider"],
                          cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120)


def test_hooks_skip_a_missing_artifacts_file_in_setup_and_call_and_keep_other_errors(tmp_path):
    done = _hook_run(tmp_path, """
        import pytest
        from pathlib import Path

        ART = Path(__file__).resolve().parents[1] / "artifacts" / "benchmark" / "r" / "results.json"

        @pytest.fixture
        def needs_art():
            ART.read_text()

        def test_call_reads_artifacts():
            ART.read_text()

        def test_setup_reads_artifacts(needs_art):
            pass

        def test_other_missing_file_still_fails():
            (Path(__file__).resolve().parents[1] / "src" / "other.py").read_text()
    """)
    out = done.stdout + done.stderr
    assert "2 skipped" in out and "1 failed" in out, out
    assert "SKIPPED [2]" in out and "the copy omits artifacts (#1207)" in out, out
