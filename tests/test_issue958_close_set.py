"""Issue #958 unit 4: the close_set rule over a fixed snapshot (rows 33-37e), no psutil kill."""

from dataclasses import replace

import psutil

from junkroan.runs import close_set as cs
from junkroan.runs.close_set import Proc, close_set

CONSOLE = 1
USER = "PC\\me"
ROOT = "C:\\Windows"
DAEMON = 1000
SELF = 9999
SESSION0_SYSTEM = "NT AUTHORITY\\SYSTEM"
NETWORK_SERVICE = "NT AUTHORITY\\NETWORK SERVICE"
CHROME_EXE = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
TELEGRAM_EXE = "C:\\Users\\user\\AppData\\Roaming\\Telegram Desktop\\Telegram.exe"
WMP_EXE = "C:\\Program Files\\Windows Media Player\\wmplayer.exe"
EXPLORER_EXE = "C:\\Windows\\explorer.exe"


def row33_chrome():
    return Proc(2001, 1, "chrome.exe", CHROME_EXE, CONSOLE, USER)


def row34_telegram():
    return Proc(2002, 1, "Telegram.exe", TELEGRAM_EXE, CONSOLE, USER)


def row35_wmplayer():
    return Proc(2003, 1, "wmplayer.exe", WMP_EXE, CONSOLE, USER)


def row36_explorer():
    return Proc(2004, 1, "explorer.exe", EXPLORER_EXE, CONSOLE, USER)


def row37a_sshd_tree():
    return [
        Proc(3001, 1, "sshd.exe", "C:\\Program Files\\OpenSSH\\sshd.exe", 0, SESSION0_SYSTEM),
        Proc(3002, 3001, "powershell.exe", "C:\\Program Files\\PowerShell\\7\\pwsh.exe", 0, USER),
    ]


def row37b_daemon_tree():
    return [
        Proc(DAEMON, 1, "python.exe", "C:\\Coding\\poe-junkroan-v2\\.venv\\Scripts\\python.exe", CONSOLE, USER),
        Proc(1001, DAEMON, "python.exe", "C:\\Coding\\poe-junkroan-v2\\.venv\\Scripts\\python.exe", CONSOLE, USER),
        Proc(1002, 1001, "luajit.exe", "C:\\PoB\\luajit.exe", CONSOLE, USER),
    ]


def row37c_svchost():
    return Proc(4001, 600, "svchost.exe", "C:\\Windows\\System32\\svchost.exe", 0, NETWORK_SERVICE)


def row37d_tailscale():
    return Proc(5001, 1, "tailscale-ipn.exe", "C:\\Program Files\\Tailscale\\tailscale-ipn.exe", CONSOLE, USER, (443,))


def row37e_foo():
    return Proc(6001, 1, "foo.exe", "C:\\Tools\\foo.exe", CONSOLE, USER)


def all_rows():
    return [
        row33_chrome(),
        row34_telegram(),
        row35_wmplayer(),
        row36_explorer(),
        *row37a_sshd_tree(),
        *row37b_daemon_tree(),
        row37c_svchost(),
        row37d_tailscale(),
        row37e_foo(),
    ]


def run(procs, *, protected=(DAEMON,), keep=("foo.exe",), self_pid=SELF):
    return close_set(
        procs,
        console_session=CONSOLE,
        user=USER,
        system_root=ROOT,
        protected_pids=set(protected),
        keep=list(keep),
        self_pid=self_pid,
    )


def reason_of(kept, pid):
    return next(r for p, r in kept if p.pid == pid)


def test_row33_chrome_closed():
    closed, kept = run([row33_chrome()])
    assert [p.name for p in closed] == ["chrome.exe"]
    assert kept == []


def test_row34_telegram_closed():
    closed, kept = run([row34_telegram()])
    assert [p.name for p in closed] == ["Telegram.exe"]
    assert kept == []


def test_row35_wmplayer_closed():
    closed, kept = run([row35_wmplayer()])
    assert [p.name for p in closed] == ["wmplayer.exe"]
    assert kept == []


def test_row36_explorer_kept_by_rule3():
    closed, kept = run([row36_explorer()])
    assert closed == []
    assert [(p.name, r) for p, r in kept] == [("explorer.exe", "rule 3: under %SystemRoot%")]


def test_row37a_sshd_and_child_kept_by_rules_1_and_4():
    closed, kept = run(row37a_sshd_tree(), protected=(3001,))
    assert closed == []
    assert reason_of(kept, 3001).startswith("rule 1")
    assert reason_of(kept, 3002).startswith("rule 1")
    # rule 4 on its own: the same two rows with the console session set to 0 (rule 1 no longer holds)
    same_owner = [replace(p, owner=USER) for p in row37a_sshd_tree()]
    _, kept0 = close_set(same_owner, console_session=0, user=USER, system_root=ROOT,
                         protected_pids={3001}, keep=[], self_pid=SELF)
    assert reason_of(kept0, 3001) == "rule 4: the runs daemon / sshd or a descendant"
    assert reason_of(kept0, 3002) == "rule 4: the runs daemon / sshd or a descendant"


def test_row37b_daemon_child_and_worker_kept_by_rule4():
    closed, kept = run(row37b_daemon_tree())
    assert closed == []
    assert reason_of(kept, 1001) == "rule 4: the runs daemon / sshd or a descendant"
    assert reason_of(kept, 1002) == "rule 4: the runs daemon / sshd or a descendant"


def test_row37c_svchost_kept_by_rules_1_and_2():
    closed, kept = run([row37c_svchost()])
    assert closed == []
    assert reason_of(kept, 4001) == "rule 1: not the console session"


def test_row37c_svchost_owner_alone_keeps_it():
    proc = Proc(4002, 600, "svchost.exe", "", CONSOLE, NETWORK_SERVICE)
    closed, kept = run([proc])
    assert closed == []
    assert reason_of(kept, 4002) == "rule 2: owner is not the user"


def test_row37d_port_owner_kept_by_rule5():
    closed, kept = run([row37d_tailscale()])
    assert closed == []
    assert reason_of(kept, 5001) == "rule 5: listens on a port"


def test_row37e_keep_list_name_kept_by_rule5():
    closed, kept = run([row37e_foo()])
    assert closed == []
    assert reason_of(kept, 6001) == "rule 5: in the keep list"


def test_keep_name_matches_with_or_without_exe_suffix():
    closed, kept = run([row37e_foo()], keep=("FOO",))
    assert closed == []
    assert reason_of(kept, 6001) == "rule 5: in the keep list"


def test_ppid_cycle_terminates_and_closes_nothing_protected():
    a = Proc(8001, 8002, "chrome.exe", CHROME_EXE, CONSOLE, USER)
    b = Proc(8002, 8001, "Telegram.exe", TELEGRAM_EXE, CONSOLE, USER)
    closed, kept = run([a, b])
    assert [p.pid for p in closed] == [8001, 8002]
    assert kept == []


def test_self_pid_and_its_parent_are_kept():
    parent = Proc(7000, 1, "junkroan.exe", "C:\\Coding\\junkroan.exe", CONSOLE, USER)
    me = Proc(SELF, 7000, "python.exe", "C:\\Coding\\python.exe", CONSOLE, USER)
    closed, kept = run([parent, me], self_pid=SELF)
    assert closed == []
    assert reason_of(kept, SELF) == "rule 4: the daemon itself"
    assert reason_of(kept, 7000) == "rule 4: the daemon itself"


def test_read_snapshot_none_when_process_iter_raises(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("snapshot read failed")

    monkeypatch.setattr(psutil, "process_iter", boom)
    assert cs.read_snapshot() is None


def test_read_snapshot_none_when_connections_denied(monkeypatch):
    def denied(*_a, **_k):
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "net_connections", denied)
    assert cs.read_snapshot() is None


def test_combined_snapshot_closes_exactly_the_three_programs_in_order():
    closed, kept = run(all_rows(), protected=(DAEMON, 3001))
    assert [p.name for p in closed] == ["chrome.exe", "Telegram.exe", "wmplayer.exe"]
    assert len(kept) == len(all_rows()) - 3


def test_protected_pids_collects_sshd_and_daemon():
    assert cs.protected_pids(all_rows(), daemon_pid=DAEMON) == {3001, DAEMON}
    assert cs.protected_pids([Proc(1, 0, "sshd", "", 0, "")]) == {1}
