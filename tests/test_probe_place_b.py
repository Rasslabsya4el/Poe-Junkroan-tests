"""#916 unit 1 of 2 (way B): the pure parts and the orchestration of scripts/probe_place_b.py, through a faked seam
(no Win32, no second copy of the app is ever started here)."""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import probe_place_b as pb  # noqa: E402

HIS_PIDS = ((100, 133_800_000_000_000_000), (101, 133_800_000_000_000_001))  # (pid, start) of his running copy


class FakeProc:
    def __init__(self, pid, start):
        self.pid, self.start = pid, start


class FakeSampler:
    samples = []

    def start(self):
        pass

    def stop(self):
        pass

    def moved_by_us(self):
        return 0

    def moved_by_him(self):
        return 0


class FakeSeam:
    """Records every call in `calls`; the second copy is `ROOT` with two children, alive for `lives` seconds."""

    ROOT, ROOT_START = 5000, 7000

    def __init__(self, tmp_path, ram=8.0, lives=1e9, counter_file=None, exit_code=0, row_after=None,
                 default_windows_pid=None):
        self.calls, self.t, self.ram, self.lives = [], 0.0, ram, lives
        self.tmp, self.counter_file, self.code = tmp_path, counter_file, exit_code
        self.killed, self.dead, self.row_after = [], set(), row_after
        self.default_windows_pid = default_windows_pid
        self.counter_at_create = None
        self.requests = []

    # ---- time
    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    # ---- machine / row S
    def free_ram_gb(self):
        return self.ram

    def row_s_full(self, tag):
        self.calls.append("row_s_full:" + tag)
        row = {"processes": HIS_PIDS, "window": (9, (0, 0, 10, 10), "Claude"), "foreground": (9, "Claude"),
               "painted": True, "_look_bytes": 400_000, "_look_colours": 900}
        if tag == "after" and self.row_after:
            row.update(self.row_after)
        return row

    def row_s_light(self, mine):
        procs = tuple(p for p in HIS_PIDS)
        return {"processes": procs, "window": (9, (0, 0, 10, 10), "Claude"), "foreground": (9, "Claude")}

    def input_tick(self):
        return 1

    def pointer_sampler(self):
        return FakeSampler()

    # ---- desktop and process
    def create_desktop(self):
        self.calls.append("create_desktop")
        return 77, "junkroan-probe-test"

    def close_desktop(self, handle):
        self.calls.append("close_desktop")

    def create_process(self, req):
        self.calls.append("create_process")
        self.requests.append(req)
        if self.counter_file:
            self.counter_at_create = json.loads(Path(self.counter_file).read_text())
        return FakeProc(self.ROOT, self.ROOT_START)

    def _gone(self):
        return self.t >= self.lives

    def alive(self, proc):
        return not self._gone() and proc.pid not in self.dead

    def lived_for(self, proc):
        return min(self.lives, self.t)

    def place_listing(self, root):
        return []

    def exit_code(self, proc):
        return None if self.alive(proc) else self.code

    def process_table(self):
        tbl = [(1, 0), (100, 1), (101, 100), (6000, 1)]
        if not self._gone():
            tbl += [(self.ROOT, 1), (5001, self.ROOT), (5002, 5001)]
        return [(p, pp) for p, pp in tbl if p not in self.dead]

    def start_time(self, pid):
        return {5001: 7001, 5002: 7002, 6000: 9999}.get(pid, 1000 if pid in (100, 101) else self.ROOT_START)

    def is_running(self, pid, start):
        return pid in (5000, 5001, 5002) and pid not in self.dead and not self._gone()

    def kill(self, pid, start):
        self.calls.append("kill:%d" % pid)
        self.killed.append(pid)
        self.dead.add(pid)
        return True

    # ---- windows and inspection
    def default_windows(self):
        if self.default_windows_pid:
            return [{"hwnd": 1, "pid": self.default_windows_pid, "title": "x", "cls": "c", "visible": True}]
        return [{"hwnd": 9, "pid": 100, "title": "Claude", "cls": "Chrome_WidgetWin_1", "visible": True}]

    def desktop_windows(self, handle):
        return [("Chrome_WidgetWin_1", "Claude")]

    def inspect(self, pid):
        return {"cmdline": '"x" --user-data-dir="%s"' % (self.tmp / "var" / "monitor-place" / "userdata"),
                "files": [str(self.tmp / "var" / "monitor-place" / "userdata" / "a.log")]}

    def place_log_lines(self):
        return []

    def his_log_marker_lines(self, since):
        return []


@pytest.fixture
def place(tmp_path):
    root = tmp_path / "var" / "monitor-place"
    counter = tmp_path / "starts-counter.json"
    counter.write_text(json.dumps({"used": 0, "total_cap": 3}))
    return root, root / "userdata", root / "config", counter


def run(seam, place, counter_obj=None, **kw):
    root, ud, cfg, counter = place
    c = counter_obj or pb.StartCounter(counter)
    return pb.run_trial(seam, c, ud, cfg, root, live_s=kw.pop("live_s", 10), sample_s=2, tail_s=4,
                        forbidden=kw.pop("forbidden", ()), exe=kw.pop("exe", Path("C:/x/claude-desktop.exe")),
                        environ=kw.pop("environ", {"SystemRoot": "C:\\Windows"}), **kw)


# ---------------------------------------------------------------- the start counter

def test_counter_missing_file_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        pb.StartCounter(tmp_path / "nope.json")


def test_counter_written_before_the_start_and_one_per_run(place, tmp_path):
    root, ud, cfg, counter = place
    seam = FakeSeam(tmp_path, counter_file=counter)
    run(seam, place)
    assert seam.counter_at_create == {"used": 1, "total_cap": 3}  # already on disk when the process is created
    assert json.loads(counter.read_text()) == {"used": 1, "total_cap": 3}
    c2 = pb.StartCounter(counter)
    c2.spend()  # the 2nd start of the SAME script run is refused even though the file allows 3
    with pytest.raises(pb.StartCounterSpent):
        c2.spend()


def test_counter_spent_refuses_before_anything_starts(place, tmp_path):
    root, ud, cfg, counter = place
    counter.write_text(json.dumps({"used": 3, "total_cap": 3}))
    seam = FakeSeam(tmp_path)
    with pytest.raises(pb.StartCounterSpent):
        run(seam, place)
    assert seam.calls == []  # no row S read, no desktop, no process
    assert not ud.exists()


# ---------------------------------------------------------------- data folders

@pytest.mark.parametrize("which", ["userdata", "config"])
def test_data_folder_outside_place_is_refused(place, tmp_path, which):
    root, ud, cfg, counter = place
    seam = FakeSeam(tmp_path)
    bad = tmp_path / "elsewhere" / "userdata"
    args = dict(userdata=bad, config=cfg) if which == "userdata" else dict(userdata=ud, config=bad)
    with pytest.raises(pb.DataFolderOutside):
        pb.run_trial(seam, pb.StartCounter(counter), args["userdata"], args["config"], root, live_s=4, sample_s=2,
                     tail_s=2, forbidden=(), exe=Path("x.exe"), environ={})
    assert seam.calls == []
    assert json.loads(counter.read_text())["used"] == 0  # the counter is not spent by a refusal


def test_check_data_folders_rules(tmp_path):
    root = tmp_path / "var" / "monitor-place"
    pb.check_data_folders(root / "userdata", root / "config", root)
    for bad in (root, root / ".." / "x", tmp_path / "var" / "monitor-place-evil" / "u", Path("C:/Users/user/.claude")):
        with pytest.raises(pb.DataFolderOutside):
            pb.check_data_folders(bad, root / "config", root)
    # even inside the place, a folder that resolves under one of his folders is refused
    with pytest.raises(pb.DataFolderOutside):
        pb.check_data_folders(root / "userdata", root / "config", root, forbidden=(root,))


# ---------------------------------------------------------------- the start call

def test_start_request_arguments(tmp_path):
    root = tmp_path / "var" / "monitor-place"
    environ = {"SystemRoot": "C:\\Windows", "PATH": "p", "ANTHROPIC_API_KEY": "sk-secret", "CLAUDE_CODE_OAUTH_TOKEN": "t",
               "CLAUDECODE": "1", "GITHUB_TOKEN": "g", "APPDATA": "C:\\Users\\u\\AppData\\Roaming", "TEMP": "C:\\Users\\u\\T"}
    req = pb.build_start_request(Path("C:/a/claude-desktop.exe"), root / "userdata", root / "config",
                                 "junkroan-probe-abc", environ, root)
    assert req.desktop == "WinSta0\\junkroan-probe-abc"
    assert Path(req.cwd) == root
    assert req.env["CLAUDE_USER_DATA_DIR"] == str(root / "userdata")
    assert req.env["CLAUDE_CONFIG_DIR"] == str(root / "config")
    assert Path(req.env["TEMP"]) == root / "tmp" and Path(req.env["TMP"]) == root / "tmp"
    assert req.env["SystemRoot"] == "C:\\Windows" and req.env["PATH"] == "p"
    for secret in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDECODE", "GITHUB_TOKEN"):
        assert secret not in req.env
    assert req.command_line.startswith('"%s"' % Path("C:/a/claude-desktop.exe"))
    assert "--user-data-dir=" in req.command_line
    assert req.flags & pb.CREATE_UNICODE_ENVIRONMENT and req.flags & pb.CREATE_NO_WINDOW
    assert not req.flags & 0x8 and not req.flags & 0x10  # DETACHED_PROCESS, CREATE_NEW_CONSOLE


def test_env_block_is_double_nul_terminated():
    block = pb.env_block({"B": "2", "a": "1"})
    assert block == "a=1\0B=2\0\0"


def test_startupinfo_names_the_private_desktop():
    si = pb.make_startup_info("WinSta0\\junkroan-probe-abc")
    assert si.lpDesktop == "WinSta0\\junkroan-probe-abc"
    assert si.cb > 0


def test_trial_order_desktop_first_process_once_desktop_closed_last(place, tmp_path):
    seam = FakeSeam(tmp_path)
    res = run(seam, place)
    calls = seam.calls
    assert calls.count("create_process") == 1
    assert calls.index("row_s_full:before") < calls.index("create_desktop") < calls.index("create_process")
    assert calls[-1] == "close_desktop" or calls.index("close_desktop") > max(i for i, c in enumerate(calls) if c.startswith("kill"))
    assert seam.requests[0].desktop == "WinSta0\\junkroan-probe-test"
    assert res.default_windows_max == 0


def test_low_ram_refuses_before_anything(place, tmp_path):
    seam = FakeSeam(tmp_path, ram=1.5)
    with pytest.raises(pb.PlaceError):
        run(seam, place)
    assert seam.calls == []


# ---------------------------------------------------------------- stopping, row S

def test_only_started_pids_are_stopped_never_his(place, tmp_path):
    seam = FakeSeam(tmp_path)
    res = run(seam, place)
    assert sorted(seam.killed) == [5000, 5001, 5002]  # the root and its descendants, nothing else
    assert not set(seam.killed) & {100, 101, 6000}
    assert res.stopped == [5000, 5001, 5002] and res.still_running == []


def test_descendants_walk_checks_start_times():
    table = [(1, 0), (10, 1), (11, 10), (12, 11), (13, 10)]
    starts = {11: 50, 12: 60, 13: 5}  # 13 started BEFORE the root (pid reuse): not ours
    assert pb.descendants(table, 10, 40, starts.get) == [11, 12]


def test_row_s_compare_names_the_differences():
    a = {"processes": HIS_PIDS, "window": (9, (0, 0, 10, 10), "Claude"), "foreground": (9, "Claude"), "painted": True}
    assert pb.row_s_compare(a, dict(a)) == []
    b = dict(a, foreground=(77, "other"), processes=HIS_PIDS[:1])
    assert pb.row_s_compare(a, b) == ["processes", "foreground"]


def test_his_processes_exclude_ours():
    allp = ((100, 1), (5000, 7), (5001, 8))
    assert pb.his_processes(allp, {5000, 5001}) == ((100, 1),)


def test_trial_reports_a_row_s_change(place, tmp_path):
    seam = FakeSeam(tmp_path, row_after={"foreground": (55, "Claude")})
    res = run(seam, place)
    assert res.diff == ["foreground"]


def test_window_on_his_desktop_is_counted_and_ends_the_run_at_once(place, tmp_path):
    seam = FakeSeam(tmp_path, default_windows_pid=5001)
    res = run(seam, place, live_s=120)
    assert res.default_windows_max == 1
    assert seam.t < 10  # stopped at the first sample, not after the 2 minutes
    assert 5001 in seam.killed


# ---------------------------------------------------------------- verdicts

def test_lived_whole_time(place, tmp_path):
    seam = FakeSeam(tmp_path)
    res = run(seam, place, live_s=10)
    assert res.verdict == "lived" and res.alive_at_end
    assert res.inspect["files"] and res.inspect["cmdline"]


def test_forwarded_and_quit(place, tmp_path):
    seam = FakeSeam(tmp_path, lives=3, exit_code=0)
    res = run(seam, place)
    assert res.verdict == "forwarded-and-quit" and res.exit_code == 0 and not res.alive_at_end
    assert 3 <= res.lived_s < 5


def test_crashed_on_nonzero_exit():
    assert pb.classify_verdict(False, 2.0, 3221225477, "", 120) == "crashed"
    assert pb.classify_verdict(False, 2.0, 0, "Not main instance", 120) == "forwarded-and-quit"
    assert pb.classify_verdict(True, 120.0, None, "please sign in to continue", 120) == "sign-in"
    assert pb.classify_verdict(True, 120.0, None, "", 120) == "lived"


def test_log_lines_with_credentials_are_redacted():
    assert "secret" not in pb.redact("Authorization: Bearer secret-value-123")
    assert "sk-ant-abc" not in pb.redact("key sk-ant-abc123 loaded")
    assert pb.redact("Not main instance") == "Not main instance"


def test_report_uses_human_durations(place, tmp_path):
    seam = FakeSeam(tmp_path)
    res = run(seam, place, live_s=120)
    text = pb.format_report(res, live_s=120)
    assert "2 min" in text and "120 s" not in text
    assert "lived" in text


# ---------------------------------------------------------------- source scan

def test_source_has_no_pointer_button_or_kill_by_name_calls():
    src = (SCRIPTS / "probe_place_b.py").read_text(encoding="utf-8")
    for word in ("SetCursorPos", "mouse_event", "SendInput", "WM_LBUTTON", "PostMessage", "taskkill", "/IM",
                 "DETACHED_PROCESS", "CREATE_NEW_CONSOLE", "SetForegroundWindow", "ShowWindow"):
        assert word not in src, word
    # the one pointer-free sampler is reused from way A, not copied
    assert "import probe_place_a" in src


def test_the_row_s_sampler_is_the_way_a_one():
    import probe_place_a as pa
    assert pb.pa is pa


def test_during_sample_difference_is_recorded_with_his_input_flag(place, tmp_path):
    class Drifting(FakeSeam):
        def row_s_light(self, mine):
            row = super().row_s_light(mine)
            if self.t >= 2:
                row["foreground"] = (55, "Chrome")
            return row

    res = run(Drifting(tmp_path), place, live_s=6)
    assert res.during_diffs and res.during_diffs[0][1] == ["foreground"] and res.during_diffs[0][2] is False


# ================================================================ start 2 of 3: the visible start for the owner's sign-in

REAL_NAME = "monitor-place"


class VisSeam(FakeSeam):
    """The second copy shows a window on his desktop at `window_at`; the log shows the signed-in line at `signin_at`;
    the flag file exists from `flag_at`. Every time is seconds of the fake clock."""

    def __init__(self, tmp_path, window_at=3, signin_at=None, flag_at=None, **kw):
        super().__init__(tmp_path, **kw)
        self.window_at, self.signin_at, self.flag_at = window_at, signin_at, flag_at
        self.written, self.flag_checked, self.log_polls = [], 0, 0

    def default_windows(self):
        out = [{"hwnd": 9, "pid": 100, "title": "Claude", "cls": "Chrome_WidgetWin_1", "visible": True}]
        if self.window_at is not None and self.t >= self.window_at and not self._gone():
            out.append({"hwnd": 2, "pid": 5001, "title": "Claude", "cls": "Chrome_WidgetWin_1", "visible": True})
            out.append({"hwnd": 3, "pid": 5002, "title": "", "cls": "Chrome_WidgetWin_0", "visible": False})
        return out

    def epoch_now(self):
        return 1000.0

    def clock_hms(self):
        return "15:%02d:%02d" % (40 + int(self.t) // 60, int(self.t) % 60)

    def write_text(self, path, text):
        self.calls.append("write:" + Path(path).name)
        self.written.append((self.t, str(path), text))

    def path_exists(self, path):
        self.flag_checked += 1
        return self.flag_at is not None and self.t >= self.flag_at

    def signin_line(self, userdata, since_epoch):
        self.log_polls += 1
        if self.signin_at is not None and self.t >= self.signin_at:
            return "2026-10-12 15:44:10 [info] claude.ai account active and logged in"
        return None


def run_vis(seam, place, counter_obj=None, **kw):
    root, ud, cfg, counter = place
    c = counter_obj or pb.StartCounter(counter)
    return pb.run_visible(seam, c, ud, cfg, root, flag_path=root / "signed-in.flag", window_up_path=root / "window-up.txt",
                          wait_s=kw.pop("wait_s", 1200), poll_s=kw.pop("poll_s", 5), settle_s=kw.pop("settle_s", 60),
                          forbidden=kw.pop("forbidden", ()), exe=kw.pop("exe", Path("C:/x/claude-desktop.exe")),
                          environ=kw.pop("environ", {"SystemRoot": "C:\\Windows"}), **kw)


def test_visible_request_is_on_his_desktop_not_a_private_one(tmp_path):
    root = tmp_path / "var" / REAL_NAME
    req = pb.build_start_request(Path("C:/a/claude-desktop.exe"), root / "userdata", root / "config", None,
                                 {"SystemRoot": "C:\\Windows", "ANTHROPIC_API_KEY": "sk-x"}, root, visible=True)
    assert req.desktop == "WinSta0\\Default"
    assert req.env["CLAUDE_USER_DATA_DIR"] == str(root / "userdata")
    assert req.env["CLAUDE_CONFIG_DIR"] == str(root / "config")
    assert '--user-data-dir="%s"' % (root / "userdata") in req.command_line
    assert "ANTHROPIC_API_KEY" not in req.env
    assert not req.flags & 0x8 and not req.flags & 0x10


def test_visible_run_creates_no_private_desktop(place, tmp_path):
    seam = VisSeam(tmp_path, flag_at=20)
    run_vis(seam, place)
    assert "create_desktop" not in seam.calls and "close_desktop" not in seam.calls
    assert seam.requests[0].desktop == "WinSta0\\Default"
    assert seam.calls.count("create_process") == 1


def test_real_path_assert_refuses_a_junction(tmp_path):
    import _winapi
    real, jn = tmp_path / "real", tmp_path / "jn"
    real.mkdir()
    _winapi.CreateJunction(str(real), str(jn))
    pb.assert_real_path(real / "monitor-place" / "config")  # a plain path passes (and need not exist yet)
    for bad in (jn, jn / "monitor-place" / "config"):
        with pytest.raises(pb.DataFolderOutside):
            pb.assert_real_path(bad)


def test_visible_run_refuses_a_path_through_a_junction_before_anything(tmp_path):
    import _winapi
    real, jn = tmp_path / "real", tmp_path / "jn"
    (real / "var" / REAL_NAME).mkdir(parents=True)
    _winapi.CreateJunction(str(real / "var"), str(jn))
    root = jn / REAL_NAME
    counter = tmp_path / "starts-counter.json"
    counter.write_text(json.dumps({"used": 1, "total_cap": 3}))
    seam = VisSeam(tmp_path)
    with pytest.raises(pb.DataFolderOutside):
        pb.run_visible(seam, pb.StartCounter(counter), root / "userdata", root / "config", root,
                       flag_path=root / "signed-in.flag", window_up_path=root / "window-up.txt", exe=Path("x.exe"), environ={})
    assert seam.calls == [] and json.loads(counter.read_text())["used"] == 1


def test_counter_goes_1_to_2_before_the_start_and_the_4th_is_refused(place, tmp_path):
    root, ud, cfg, counter = place
    counter.write_text(json.dumps({"used": 1, "total_cap": 3}))
    seam = VisSeam(tmp_path, counter_file=counter, flag_at=10)
    res = run_vis(seam, place)
    assert seam.counter_at_create == {"used": 2, "total_cap": 3}
    assert res.counter_total == 2
    counter.write_text(json.dumps({"used": 3, "total_cap": 3}))
    seam2 = VisSeam(tmp_path)
    with pytest.raises(pb.StartCounterSpent):
        run_vis(seam2, place)
    assert seam2.calls == []
    assert json.loads(counter.read_text()) == {"used": 3, "total_cap": 3}


def test_wait_is_bounded_at_20_minutes(place, tmp_path):
    seam = VisSeam(tmp_path)  # never signs in, no flag
    res = run_vis(seam, place)
    assert res.ended_by == "timeout"
    assert 1200 <= res.ran_s < 1230
    assert sorted(seam.killed) == [5000, 5001, 5002] and res.still_running == []
    # polled the log about every 5 s once the window was up, never more than the bound allows
    assert 200 <= seam.log_polls <= 1210


def test_the_flag_ends_the_wait(place, tmp_path):
    seam = VisSeam(tmp_path, flag_at=47)
    res = run_vis(seam, place)
    assert res.ended_by == "flag"
    assert 47 <= res.ran_s < 60
    assert sorted(seam.killed) == [5000, 5001, 5002]


def test_the_signed_in_log_line_ends_the_wait_and_is_quoted(place, tmp_path):
    seam = VisSeam(tmp_path, signin_at=33)
    res = run_vis(seam, place)
    assert res.ended_by == "log"
    assert "account active and logged in" in res.end_line
    assert 33 <= res.ran_s < 45


def test_a_grace_is_kept_after_the_sign_in_before_the_copy_is_stopped(place, tmp_path):
    seam = VisSeam(tmp_path, flag_at=30)
    stop_at = []
    orig = seam.kill
    seam.kill = lambda pid, st: (stop_at.append(seam.t), orig(pid, st))[1]
    run_vis(seam, place, settle_s=60)
    assert min(stop_at) >= 30 + 60


def test_window_up_line_written_once_when_the_copy_window_first_exists(place, tmp_path):
    seam = VisSeam(tmp_path, window_at=7, flag_at=40)
    res = run_vis(seam, place)
    ups = [w for w in seam.written if w[1].endswith("window-up.txt")]
    assert len(ups) == 1
    t, path, text = ups[0]
    assert 7 <= t <= 8  # at once, not after the next 5 s poll
    assert text.strip() == "WINDOW UP 15:40:%02d" % int(t)
    assert res.window_first_seen == "15:40:%02d" % int(t)
    assert res.copy_windows_max == 1  # the invisible helper window is not counted
    assert not [w for w in seam.written if w[0] < 7]


def test_no_window_up_line_when_no_window_appears(place, tmp_path):
    seam = VisSeam(tmp_path, window_at=None, flag_at=30)
    res = run_vis(seam, place)
    assert not seam.written and res.window_first_seen is None


def test_stale_flag_is_refused_before_anything_starts(place, tmp_path):
    seam = VisSeam(tmp_path, flag_at=0)
    with pytest.raises(pb.PlaceError):
        run_vis(seam, place)
    assert seam.calls == []


def test_the_copy_quitting_ends_the_wait(place, tmp_path):
    seam = VisSeam(tmp_path, lives=20)
    res = run_vis(seam, place)
    assert res.ended_by == "exited" and res.ran_s < 60


def test_his_row_s_is_compared_after_a_visible_run(place, tmp_path):
    seam = VisSeam(tmp_path, flag_at=10, row_after={"foreground": (55, "other")})
    res = run_vis(seam, place)
    assert res.diff == ["foreground"]
    assert ("row_s_full:before" in seam.calls) and ("row_s_full:after" in seam.calls)
    assert not set(seam.killed) & {100, 101, 6000}


def test_signed_in_line_reading_is_pure():
    base = ["2026-10-12 15:07:37 [info] [account] User is logged out, skipping account ID wait"]
    since = pb.time.mktime(pb.time.strptime("2026-10-12 15:30:00", "%Y-%m-%d %H:%M:%S"))
    assert pb.find_signed_in_line(base, 0) is None
    on = "2026-10-12 15:44:10 [info] claude.ai account active and logged in"
    assert pb.find_signed_in_line(base + [on], since) == on
    assert pb.find_signed_in_line(base + [on], since + 3600) is None  # an older line of an earlier start does not count
    tr = "2026-10-12 15:44:09 [info] [account] Login-state transition (loggedOut: true \u2192 false, uuid: <none> \u2192 abc)"
    assert pb.find_signed_in_line([tr], since) == tr
    off = "2026-10-12 15:44:09 [info] [account] Login-state transition (loggedOut: null \u2192 true, uuid: <none> \u2192 <none>)"
    assert pb.find_signed_in_line([off], since) is None


def test_visible_report_has_the_rows_and_human_durations(place, tmp_path):
    seam = VisSeam(tmp_path, window_at=7, signin_at=33)
    res = run_vis(seam, place)
    text = pb.format_visible_report(res, wait_s=1200)
    for needle in ("WINDOW UP", "15:40:", "20 min", "account active and logged in", "5000", "start counter"):
        assert needle in text
    assert "1200 s" not in text and "120 s" not in text


def test_source_scan_for_the_visible_mode():
    src = (SCRIPTS / "probe_place_b.py").read_text(encoding="utf-8")
    for word in ("SetCursorPos", "mouse_event", "SendInput", "keybd_event", "WM_KEY", "WM_CHAR", "WM_LBUTTON", "WM_CLOSE",
                 "BlockInput", "taskkill", "/IM", "SetForegroundWindow", "ShowWindow", "PostMessage", "SendMessage",
                 "DETACHED_PROCESS", "CREATE_NEW_CONSOLE", "SetFocus", "BringWindowToTop", "click"):
        assert word not in src, word
