import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sample_kinds_838", ROOT / "scripts" / "sample_kinds_838.py")
sk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sk)


def P(pid, ppid, name, cmd="", user="PC\\me", session=1, born=1.0, cpu=0.0):
    return {"pid": pid, "ppid": ppid, "name": name, "cmdline": cmd.split(), "username": user, "session": session,
            "cwd": None, "cpu_s": cpu, "born": born}


def kinds_of(rows, job_pids=None, self_pid=None):
    by = {r["pid"]: r for r in rows}
    return {r["pid"]: sk.classify(r, by, job_pids, self_pid) for r in rows}


def test_classifier_each_kind():
    rows = [
        P(1, 0, "explorer.exe"),
        P(2, 1, "claude.exe", "claude --bg"),
        P(3, 2, "python.exe", "python x.py"),
        P(4, 2, "python.exe", "python -m pytest tests/test_a.py"),
        P(5, 4, "python.exe", "python worker"),
        P(6, 2, "python.exe", "python -m tools.agentops merge 12"),
        P(7, 6, "python.exe", "python -m pytest tests -q"),
        P(8, 2, "python.exe", "python -m tools.agentops full-run"),
        P(9, 1, "python.exe", "python -m tools.agentops dispatch"),
        P(10, 9, "claude.exe", "claude --bg"),
        P(11, 1, "Claude.exe", "Claude"),
        P(12, 11, "node.exe", "node mod.js"),
        P(13, 1, "junkroan.exe", "junkroan job"),
        P(14, 13, "python.exe"),
        P(15, 1, "python.exe", "python job.py"),
        P(16, 1, "svchost.exe", user="NT AUTHORITY\\SYSTEM", session=0),
        P(17, 1, "notepad.exe"),
        P(18, 1, "python.exe", "python sample_kinds_838.py"),
        P(20, 1, "claude.exe", "C:/ProgramFiles/WindowsApps/Claude_2/app/claude.exe --type=renderer"),
        P(21, 1, "claude.exe", "C:/Users/u/AppData/Roaming/Claude/claude-code/2.1/x/claude.exe --bg"),
        P(22, 21, "node.exe", "node tool.js"),
        P(19, 1, "python.exe", "python scripts/runs.py daemon"),
    ]
    k = kinds_of(rows, {15: "counted"}, 18)
    assert k[3] == "orch_and_subagents" and k[4] == "workers_pytest" and k[5] == "workers_pytest"
    assert k[6] == "merge_suite" and k[7] == "merge_suite" and k[8] == "full_run"
    assert k[9] == "daemons" and k[10] == "daemons" and k[19] == "daemons"
    assert k[20] == "desktop_and_mods" and k[21] == "orch_and_subagents" and k[22] == "orch_and_subagents"
    assert k[11] == "desktop_and_mods" and k[12] == "desktop_and_mods"
    assert k[13] == "pob_jobs" and k[14] == "pob_jobs" and k[15] == "pob_jobs"
    assert k[16] == "system" and k[17] == "other" and k[18] == "sampler" and k[2] == "orch_and_subagents"


def test_delta_skips_reused_pid_and_new():
    prev = [P(1, 0, "claude.exe", cpu=1.0, born=1.0), P(2, 0, "x.exe", cpu=1.0, born=1.0)]
    cur = [P(1, 0, "claude.exe", cpu=3.0, born=1.0), P(2, 0, "x.exe", cpu=9.0, born=5.0), P(3, 0, "y.exe", cpu=4.0)]
    d = sk.kinds_delta(prev, cur, 2.0)
    assert d["orch_and_subagents"] == 1.0 and d["other"] == 0.0


def test_real_two_samples(tmp_path):
    out = tmp_path / "s.jsonl"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sample_kinds_838.py"), "--window", "5", "--count", "2",
                        "--ticket", "872", "--out", str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "own cost" in r.stderr
    lines = [json.loads(x) for x in out.read_text().splitlines()]
    owner, rows = lines[0]["owner"], lines[1:]
    assert owner["ticket"] == "872" and owner["pid"] and owner["end"]
    assert len(rows) == 2
    for row in rows:
        assert all(k in row for k in sk.KINDS)
        assert isinstance(row["total_busy_cores"], (int, float))
        assert abs(sum(row[k] for k in sk.KINDS) + row["short_lived_cores"] - row["total_busy_cores"]) < 0.01


def split_of(prev, cur, win, intdpc, busy):
    kinds = sk.kinds_delta(prev, cur, win)
    return sk.sample_line(kinds, busy, win, born=sk.born_cores(prev, cur, win), intdpc=intdpc)


def test_residual_born_in_window():
    prev = [P(1, 0, "x.exe", cpu=1.0)]
    cur = [P(1, 0, "x.exe", cpu=2.0), P(2, 0, "y.exe", cpu=6.0, born=9.0), P(3, 0, "z.exe", cpu=2.0, born=7.0)]
    row = split_of(prev, cur, 2.0, 0.0, 5.0)  # kinds = 0.5; born = (6 + 2) / 2 = 4; busy 5 -> short_lived 4.5
    assert row["born_in_window_cores"] == 4.0 and row["short_lived_cores"] == 4.5
    assert row["died_or_unread_cores"] == 0.5 and row["interrupt_dpc_cores"] == 0.0


def test_residual_died_in_window_is_the_remainder():
    prev = [P(1, 0, "x.exe", cpu=1.0), P(2, 0, "gone.exe", cpu=1.0)]
    cur = [P(1, 0, "x.exe", cpu=3.0)]  # pid 2 died: its CPU is in busy, in no table
    row = split_of(prev, cur, 2.0, 0.0, 2.0)  # kinds 1.0, busy 2.0
    assert row["born_in_window_cores"] == 0.0 and row["died_or_unread_cores"] == 1.0


def test_residual_interrupt_dpc():
    prev = [P(1, 0, "x.exe", cpu=0.0)]
    cur = [P(1, 0, "x.exe", cpu=2.0)]
    row = split_of(prev, cur, 2.0, 0.4, 1.4)
    assert row["interrupt_dpc_cores"] == 0.4 and row["died_or_unread_cores"] == 0.0 and row["short_lived_cores"] == 0.4


def test_residual_died_seen_by_subread():
    t0 = [P(1, 0, "x.exe", cpu=1.0), P(2, 0, "gone.exe", cpu=1.0)]
    t1 = [P(1, 0, "x.exe", cpu=2.0), P(2, 0, "gone.exe", cpu=3.0)]  # pid 2 burns 2 s, then dies before the end
    t2 = [P(1, 0, "x.exe", cpu=3.0)]
    assert sk.died_seen_cores([t0, t1, t2], 4.0) == 0.5
    kinds = sk.kinds_delta(t0, t2, 4.0)
    row = sk.sample_line(kinds, 1.0, 4.0, born=0.0, intdpc=0.0, died_seen=0.5)
    assert row["died_seen_cores"] == 0.5 and row["died_or_unread_cores"] == 0.0


def test_short_lived_closes_the_sum_on_a_fixed_window():
    prev = [P(1, 0, "claude.exe", cpu=1.0), P(2, 0, "x.exe", cpu=0.0), P(9, 0, "gone.exe", cpu=5.0)]
    cur = [P(1, 0, "claude.exe", cpu=5.0), P(2, 0, "x.exe", cpu=2.0), P(3, 0, "new.exe", cpu=3.0, born=9.0)]
    kinds = sk.kinds_delta(prev, cur, 4.0)  # alive at both ends: 4/4 + 2/4 = 1.5 cores
    row = sk.sample_line(kinds, 3.0, 4.0)  # machine busy 3.0 cores
    alive = sum(row[k] for k in sk.KINDS)
    assert alive == 1.5 and row["short_lived_cores"] == 3.0 - alive == 1.5
    assert abs(alive + row["short_lived_cores"] - row["total_busy_cores"]) < 0.1
    assert "unattributed_cores" not in row


def test_sampler_is_a_reader():
    src = (ROOT / "scripts" / "sample_kinds_838.py").read_text(encoding="utf-8")
    assert "Popen" not in src and "subprocess" not in src and "os.nice" not in src
    assert src.count(".nice(") == 1  # only its own BELOW_NORMAL
