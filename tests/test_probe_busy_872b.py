"""#872 unit 2b: classification, top-10 table and named share of the short-lived read, on fixed fake records."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import probe_busy_872c as pb  # noqa: E402


def row(pid, ppid, name, *cmd):
    return {"pid": pid, "ppid": ppid, "name": name, "cmdline": tuple(cmd)}


def test_pytest_chain_is_test_suite():
    chain = [row(5, 4, "git.exe", "git", "status"), row(4, 3, "python.exe", "python", "-m", "pytest", "tests/x.py")]
    assert pb.kind_of(chain, False) == "test_suite"


def test_cli_claude_parent_is_orch_worker():
    cl = row(3, 1, "claude.exe", "C:/Users/u/.claude/claude-code/2.1/claude.exe", "--bg")
    chain = [row(9, 3, "git.exe", "git", "log"), cl]
    assert pb.kind_of(chain, False) == "orch_worker"


def test_pob_runtime_chain_is_pob_job():
    chain = [row(9, 8, "python.exe", "python", "x.py"), row(8, 2, "junkroan.exe", "junkroan.exe", "serve")]
    assert pb.kind_of(chain, False) == "pob_job"


def test_unnamed_is_other_or_unknown_when_parent_dead():
    chain = [row(9, 8, "conhost.exe", "conhost.exe")]
    assert pb.kind_of(chain, False) == "other"
    assert pb.kind_of(chain, True) == "unknown"


def test_summary_top10_and_named_share():
    recs = [{"name": "git.exe", "kind": "orch_worker", "cpu_s": 6.0},
            {"name": "git.exe", "kind": "other", "cpu_s": 1.0},
            {"name": "python.exe", "kind": "test_suite", "cpu_s": 3.0},
            {"name": "x.exe", "kind": "unknown", "cpu_s": 2.0}]
    recs += [{"name": f"e{i}.exe", "kind": "other", "cpu_s": 0.01} for i in range(12)]
    s = pb.summarize(recs, 10.0)
    assert [r["exe"] for r in s["top"][:3]] == ["git.exe", "python.exe", "x.exe"]
    assert len(s["top"]) == 10
    assert s["top"][0] == {"exe": "git.exe", "cores": 0.7, "n": 2, "main_kind": "orch_worker"}
    assert s["named_share"] == round(9.0 / 12.12, 3)
    assert s["n_processes"] == 16
    text = pb.format_table(s)
    assert "| 1 | git.exe | 0.700 | 2 | orch_worker |" in text and "named share" in text


def test_summary_empty():
    assert pb.summarize([], 10.0)["named_share"] is None


# --- #872 stable kinds: cache per (pid, create) ---
def snap(*procs):
    """procs: (pid, create, ppid, name) -> snapshot like read_all()."""
    return {(p, c): (1.0, 1.0, n, 1, pp) for p, c, pp, n in procs}


def reader_for(cmds):
    def rd(pid):
        if pid not in cmds or cmds[pid] is None:
            raise OSError("denied")
        return cmds[pid]
    return rd


PYTEST = ("python", "-m", "pytest", "tests/x.py")


def test_dead_parent_uses_cached_parent_kind():
    tr = pb.Tracker(reader_for({40: PYTEST, 5: ("git", "status")}))
    parent = (40, 10.0)
    assert tr.name(parent, snap((40, 10.0, 1, "python.exe")))[1] == "test_suite"
    child = (5, 11.0)
    assert tr.name(child, snap((5, 11.0, 40, "git.exe")))[1] == "test_suite"      # parent gone


def test_unreadable_cmdline_uses_cached_tree():
    tr = pb.Tracker(reader_for({40: PYTEST, 5: None}))
    tr.name((40, 10.0), snap((40, 10.0, 1, "python.exe")))
    cur = snap((40, 10.0, 1, "python.exe"), (5, 11.0, 40, "git.exe"))
    assert tr.name((5, 11.0), cur)[1] == "test_suite"


def test_same_exe_same_kind_in_both_orders():
    cmds = {40: PYTEST, 5: ("git", "status")}
    a = pb.Tracker(reader_for(cmds))
    a.name((40, 10.0), snap((40, 10.0, 1, "python.exe")))
    alive = a.name((5, 11.0), snap((40, 10.0, 1, "python.exe"), (5, 11.0, 40, "git.exe")))
    b = pb.Tracker(reader_for(cmds))
    b.name((40, 10.0), snap((40, 10.0, 1, "python.exe")))
    dead = b.name((5, 11.0), snap((5, 11.0, 40, "git.exe")))
    assert alive == dead == ("git.exe", "test_suite")


def test_nothing_resolvable_is_unresolved():
    tr = pb.Tracker(reader_for({5: ("conhost.exe",)}))
    assert tr.name((5, 11.0), snap((5, 11.0, 40, "conhost.exe")))[1] == "unresolved"
    s = pb.summarize([{"name": "conhost.exe", "kind": "unresolved", "cpu_s": 2.0}], 10.0)
    assert s["kind_cores"] == {"unresolved": 0.2}


# --- #872: an unresolved `claude.exe` (the desktop app's `Claude.exe` is the one the classifier leaves unnamed) is named by its exe; nothing else is ---
def test_unresolved_claude_exe_is_orch_worker_by_name():
    tr = pb.Tracker(reader_for({5: None}))
    assert tr.name((5, 11.0), snap((5, 11.0, 40, "Claude.exe"))) == ("Claude.exe", "orch_worker")   # dead parent, unreadable
    assert (5, 11.0) in tr.by_exe


def test_resolved_claude_exe_keeps_the_trees_kind():
    cmds = {40: PYTEST, 5: ("C:/Users/u/AppData/Local/Programs/WindowsApps/Claude/app/Claude.exe",)}
    tr = pb.Tracker(reader_for(cmds))
    tr.name((40, 10.0), snap((40, 10.0, 1, "python.exe")))
    cur = snap((40, 10.0, 1, "python.exe"), (5, 11.0, 40, "Claude.exe"))
    assert tr.name((5, 11.0), cur)[1] == "test_suite"          # the tree names it: not the fallback
    assert (5, 11.0) not in tr.by_exe


def test_unresolved_other_exes_stay_unresolved():
    for exe in ("gh.exe", "where.exe", "powershell.exe"):
        tr = pb.Tracker(reader_for({5: None}))
        assert tr.name((5, 11.0), snap((5, 11.0, 40, exe)))[1] == "unresolved"
        assert not tr.by_exe


def test_summary_counts_cores_named_by_exe():
    recs = [{"name": "claude.exe", "kind": "orch_worker", "cpu_s": 2.0, "by_exe": True},
            {"name": "git.exe", "kind": "orch_worker", "cpu_s": 3.0},
            {"name": "gh.exe", "kind": "unresolved", "cpu_s": 5.0}]
    s = pb.summarize(recs, 10.0)
    assert s["named_by_exe_cores"] == 0.2 and s["named_share"] == 0.5
    assert "named_by_exe_cores: 0.2" in pb.format_table(s)
