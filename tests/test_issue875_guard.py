"""#875 unit 2: a test that writes a made-up job id into the REAL queue.log fails the session, by name.

The real files are never touched: a subprocess pytest run uses a tmp project (its own conftest copy and a
`JUNKROAN_GUARD_REAL_ROOT` tmp tree standing in for the real checkout)."""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

WRONG_TEST = '''
import os
from pathlib import Path

def test_wrong_writer():
    log = Path(os.environ["JUNKROAN_GUARD_REAL_ROOT"]) / "artifacts" / "runs" / "queue.log"
    with log.open("a", encoding="utf-8") as f:
        f.write("2026-10-11 19:00:00 snapshot failed for job-zz: boom; running from the live checkout\\n")

def test_daemon_like_writer():
    # a line about a real run (its .out exists in the fake real tree): never trips the guard
    runs = Path(os.environ["JUNKROAN_GUARD_REAL_ROOT"]) / "artifacts" / "runs"
    with (runs / "queue.log").open("a", encoding="utf-8") as f:
        f.write("2026-10-11 19:00:01 end 20261011-1900-real: rc 0 -> x\\n")
'''


# a live daemon (another process) appends a line about a real laptop job: its id is not in the local jobs.jsonl
LIVE_DAEMON_TEST = '''
import os
import subprocess
import sys
from pathlib import Path

def test_live_daemon_appends_anomaly():
    anomalies = Path(os.environ["JUNKROAN_GUARD_REAL_ROOT"]) / "var" / "anomalies.json"
    code = ("import sys; open(sys.argv[1], 'a', encoding='utf-8')"
            ".write('  \\"laptop:job_stuck:j-20261011-1936-b223\\",\\\\n')")
    subprocess.run([sys.executable, "-c", code, str(anomalies)], check=True)
'''

# the test's own made-up id lands in the real anomalies.json
MADE_UP_ANOMALY_TEST = '''
import os
from pathlib import Path

def test_wrong_anomaly_writer():
    anomalies = Path(os.environ["JUNKROAN_GUARD_REAL_ROOT"]) / "var" / "anomalies.json"
    with anomalies.open("a", encoding="utf-8") as f:
        f.write('  "job_stuck:j-stuck",\\n')
'''


def _run(tmp: Path, with_guard: bool, test_src: str = WRONG_TEST) -> subprocess.CompletedProcess:
    real = tmp / "real"
    (real / "artifacts" / "runs").mkdir(parents=True)
    (real / "var").mkdir()
    (real / "artifacts" / "runs" / "queue.log").write_text("", encoding="utf-8")
    (real / "artifacts" / "runs" / "20261011-1900-real.out").write_text("", encoding="utf-8")
    proj = tmp / "proj"
    proj.mkdir()
    conf = (HERE / "conftest.py").read_text(encoding="utf-8")
    if not with_guard:
        conf = conf.replace("def pytest_sessionfinish(", "def _unused_sessionfinish(")
    (proj / "conftest.py").write_text(conf, encoding="utf-8")
    (proj / "test_wrong.py").write_text(test_src, encoding="utf-8")
    env = {**os.environ, "JUNKROAN_GUARD_REAL_ROOT": str(real),
           "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT)])}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(tmp / "bt"), str(proj)],
                          capture_output=True, text=True, env=env, cwd=str(proj), timeout=120)


def test_wrong_writer_fails_session_naming_test(tmp_path):
    res = _run(tmp_path, with_guard=True)
    out = res.stdout + res.stderr
    assert res.returncode != 0, out
    assert "test_wrong.py::test_wrong_writer" in out and "job-zz" in out, out
    assert "test_daemon_like_writer: queue.log" not in out, out


def test_without_guard_session_is_green(tmp_path):
    res = _run(tmp_path, with_guard=False)
    assert res.returncode == 0, res.stdout + res.stderr


def test_live_daemon_anomaly_line_with_real_shaped_id_is_not_blamed(tmp_path):
    res = _run(tmp_path, with_guard=True, test_src=LIVE_DAEMON_TEST)
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "1 passed" in out and "failed" not in out, out


def test_made_up_anomaly_id_fails_session_naming_test(tmp_path):
    res = _run(tmp_path, with_guard=True, test_src=MADE_UP_ANOMALY_TEST)
    out = res.stdout + res.stderr
    assert res.returncode != 0, out
    assert "test_wrong.py::test_wrong_anomaly_writer" in out and "j-stuck" in out, out
