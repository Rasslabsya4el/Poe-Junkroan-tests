from junkroan.runs.load_groups import snapshot

MS = ".claude/worktrees/merge-suite"


def P(pid, ppid, name, cmd="", user="PC\\me", session=1, rss=10.0, cpu=0.0, cwd=None):
    return {"pid": pid, "ppid": ppid, "name": name, "cmdline": cmd.split(), "username": user,
            "session": session, "rss_mb": rss, "cpu_s": cpu, "cwd": cwd}


def table(cpu=0.0):
    return [
        P(1, 0, "explorer.exe"),
        P(10, 1, "claude.exe"),
        P(11, 10, "python.exe", "python -m pytest tests -q", rss=100, cpu=cpu),
        P(12, 11, "python.exe", "python worker.py", rss=50),
        P(13, 10, "node.exe"),
        P(14, 10, "python.exe", "python -m pytest tests/test_x.py", rss=20),
        P(20, 1, "junkroan.exe", "junkroan job"),
        P(21, 20, "python.exe", rss=200),
        P(22, 21, "luajit.exe", "headless_runtime_worker", rss=300, cpu=cpu),
        P(23, 21, "luajit.exe", "headless_runtime_worker", rss=300),
        P(30, 1, "filler.exe"),
        P(31, 30, "luajit.exe", rss=400),
        P(40, 1, "MsMpEng.exe", user="NT AUTHORITY\\SYSTEM", session=0, rss=500),
        P(0, 0, "System Idle Process", user=None, session=0),
        P(50, 1, "PathOfExile.exe", rss=3000),
        P(60, 1, "locked.exe", user=None, session=1),
        P(70, 1, "python.exe", "python -m pytest -q", cwd="C:/x/" + MS, rss=80),
    ]


JOBS = {20: "counted", 30: "filler"}


def test_groups_and_counts():
    s = snapshot(table(), JOBS)
    g = s["groups"]
    assert g["pob_counted"] == {"cpu_pct": 0.0, "rss_mb": 810.0, "count": 4}
    assert g["pob_filler"]["count"] == 2 and g["pob_filler"]["rss_mb"] == 410.0
    assert g["claude"]["count"] == 5 and g["claude"]["rss_mb"] == 190.0
    assert g["system"]["count"] == 2 and g["system"]["rss_mb"] == 510.0
    assert g["owner"]["count"] == 3  # explorer, PathOfExile, merge-suite pytest (not under claude)
    assert g["other"]["count"] == 1
    assert sum(x["count"] for x in g.values()) == len(table())
    assert s["whole_suite_pytest"] == 2  # claude's `pytest tests` and the merge-suite `pytest -q`
    assert s["merge_suite_pytest"] == 1
    assert "_cpu_s" in s and set(s) >= {"ts", "free_ram_mb", "total_ram_mb", "cpu_pct", "groups"}


def test_nested_pytest_not_counted_twice():
    t = table() + [P(15, 11, "python.exe", "python -m pytest tests -q")]
    assert snapshot(t, JOBS)["whole_suite_pytest"] == 2


def test_cpu_shares_from_two_snapshots():
    a = snapshot(table(0.0), JOBS, wall=100.0, ncpu=4)
    b = snapshot(table(8.0), JOBS, prev=a, wall=110.0, ncpu=4)
    # 8 cpu-seconds over 10 s on 4 cores = 20 % of the machine, in claude (pid 11) and in pob_counted (pid 22)
    assert b["groups"]["claude"]["cpu_pct"] == 20.0
    assert b["groups"]["pob_counted"]["cpu_pct"] == 20.0
    assert b["groups"]["owner"]["cpu_pct"] == 0.0


def test_pytest_under_a_pytest_through_cmd_is_not_top_level():
    # the merge suite's own test starts a pytest through cmd.exe: still one whole suite
    t = table() + [P(80, 70, "cmd.exe", "cmd /c x"), P(81, 80, "python.exe", "python -m pytest -q", cwd="C:/tmp/a")]
    s = snapshot(t, JOBS)
    assert s["whole_suite_pytest"] == 2
    assert s["merge_suite_pytest"] == 1
    assert sorted(r["pid"] for r in s["whole_suite_list"]) == [11, 70]
    assert [r["merge_suite"] for r in sorted(s["whole_suite_list"], key=lambda r: r["pid"])] == [False, True]


def test_pob_runtime_counted_per_group():
    t = table() + [P(90, 10, "luajit.exe", "luajit headless_runtime_worker", rss=300)]
    s = snapshot(t, JOBS)
    assert s["pob_runtime_by_group"]["pob_counted"] == 2
    assert s["pob_runtime_by_group"]["claude"] == 1
    assert sum(s["pob_runtime_by_group"].values()) == 3
