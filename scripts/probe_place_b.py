"""#916 way B: ONE trial start of a second copy of the Claude desktop app on a private (CreateDesktopW) desktop.

  python scripts/probe_place_b.py plan                        # read only: what the start would be (no start, no counter)
  python scripts/probe_place_b.py start --out <file.out>      # the one start; row S before / every 2 s / after
  python scripts/probe_place_b.py start --visible --out <file.out>   # start 2 of 3: the copy's window on HIS desktop for his
                                                                     # one sign-in; waits for the signed-in state (<= 20 min)

Hard limits of the ticket (#916) kept here:
  * his running app is never closed, restarted, reloaded or written to; the only processes this script ever stops
    are the ones it started itself (the pid of its own CreateProcess and that pid's descendants, each checked by
    pid AND start time; never by image name);
  * the second copy gets its own data and config folders under `var/monitor-place/` (anything else is refused before
    anything starts) and an environment scrubbed down to a whitelist, so no credential of this session reaches it;
  * every process that can own a window starts with `STARTUPINFO.lpDesktop` = a private desktop; the windows of the
    second copy on `WinSta0\\Default` are counted at every sample (the run ends at once if there is one);
  * the real pointer is never used (the source scan in the test forbids every pointer and button call);
  * the start counter (`docs/research/pictures-916/starts-counter.json`) is written BEFORE the start; a missing file
    is an error; one start per script run; the file's total cap is 3 for the whole ticket.
ctypes + stdlib + psutil (command line and open files of its own children only).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "src"))
import probe_place_a as pa  # noqa: E402  (row S sampler, pointer sampler, window and process readers: reused, not copied)
import probe_console_windows as pcw  # noqa: E402  (CreateDesktopW, STARTUPINFOW, window count on a desktop)
from junkroan.report_format import human_duration  # noqa: E402

CREATE_UNICODE_ENVIRONMENT = pcw.CREATE_UNICODE_ENVIRONMENT
CREATE_NO_WINDOW = 0x08000000
PLACE_ROOT = REPO / "var" / "monitor-place"
COUNTER_FILE = REPO / "var" / "probe_place_b" / "starts-counter.json"
MIN_FREE_RAM_GB = 2.0
LIVE_S, SAMPLE_S, TAIL_S = 120, 2, 10
# start 2 of 3 (the visible start for the owner's one sign-in)
REAL_PLACE_ROOT = Path(r"C:\Coding\poe-junkroan-v2\var\monitor-place")  # the real path: no junction in it (the worktree's var is one)
DEFAULT_DESKTOP = "WinSta0\\Default"
SIGNIN_WAIT_S, SIGNIN_POLL_S, SETTLE_S, WINDOW_TICK_S = 20 * 60, 5, 60, 1
REPARSE_POINT = 0x400
WAIT_TIMEOUT, STILL_ACTIVE = 258, 259
ENV_WHITELIST = ("SystemRoot", "SystemDrive", "windir", "ComSpec", "PATH", "PATHEXT", "USERPROFILE", "USERNAME",
                 "USERDOMAIN", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "ProgramData", "ProgramFiles",
                 "ProgramFiles(x86)", "ProgramW6432", "CommonProgramFiles", "CommonProgramFiles(x86)",
                 "CommonProgramW6432", "PUBLIC", "ALLUSERSPROFILE", "COMPUTERNAME", "NUMBER_OF_PROCESSORS",
                 "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "OS",
                 "DriverData", "LANG")
LOG_MARKERS = ("Not main instance", "CLAUDE_USER_DATA_DIR", "second-instance", "second instance", "single instance")
SIGNIN_RE = re.compile(r"sign[ -]?in|log[ -]?in|not authenticated|unauthenticated|auth(?:entication)? required", re.I)
REDACT_RE = re.compile(r"(?i)\b(authorization|bearer|token|secret|cookie|api[-_ ]?key|password)\b.*")
# what the app's own logger writes when the account is signed in (read in app.asar: `claude.ai account active and logged in`
# is logged only when the account is not logged out; `[account] Login-state transition (loggedOut: true -> false, ...)` on the change)
SIGNED_IN_RE = re.compile(r"claude\.ai account active and logged in|Login-state transition \(loggedOut: \w+ → false")
LOG_TS_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
SK_RE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


class PlaceError(RuntimeError):
    pass


class DataFolderOutside(PlaceError):
    """A data or config folder is not strictly inside var/monitor-place/ (or resolves under one of his folders)."""


class StartCounterSpent(PlaceError):
    pass


# ---------------------------------------------------------------- pure parts (tested)

class StartCounter:
    """{"used": n, "total_cap": m} in a file, written BEFORE the start; one start per script run."""

    def __init__(self, path, limit: int = 1):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8"))  # FileNotFoundError when absent: never guessed
        self.total, self.total_cap = int(data["used"]), int(data["total_cap"])
        self.limit, self.used = limit, 0

    def remaining(self) -> int:
        return max(0, min(self.limit - self.used, self.total_cap - self.total))

    def spend(self) -> None:
        if self.remaining() <= 0:
            raise StartCounterSpent("start counter: %d of %d used in total, %d of %d in this run"
                                    % (self.total, self.total_cap, self.used, self.limit))
        self.used += 1
        self.total += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"used": self.total, "total_cap": self.total_cap}) + "\n", encoding="utf-8")


def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p))))


def inside_place(path, root) -> bool:
    """`path` is strictly inside `root`, judged on the text of the path (no `..`); the var junction is not followed."""
    if ".." in Path(str(path)).parts:
        return False
    n, r = _norm(path), _norm(root)
    try:
        return n != r and os.path.commonpath([n, r]) == r
    except ValueError:
        return False


def _under(path, folder) -> bool:
    n, f = os.path.normcase(os.path.realpath(str(path))), os.path.normcase(os.path.realpath(str(folder)))
    try:
        return os.path.commonpath([n, f]) == f
    except ValueError:
        return False


def check_data_folders(userdata, config, root, forbidden=()) -> None:
    for what, p in (("userdata", userdata), ("config", config)):
        if not inside_place(p, root):
            raise DataFolderOutside("%s folder %s is not inside %s" % (what, p, root))
        for f in forbidden:
            if _under(p, f):
                raise DataFolderOutside("%s folder %s resolves under his folder %s" % (what, p, f))


def assert_real_path(path) -> None:
    """No component of `path` that exists is a reparse point (junction or symlink): the app refuses a config folder
    below one (`PlantDetectedError`, start 1). A component that does not exist yet is fine."""
    p = Path(os.path.abspath(str(path)))
    if ".." in Path(str(path)).parts:
        raise DataFolderOutside("%s has a .. component" % path)
    for part in [*reversed(p.parents), p]:
        try:
            attrs = getattr(os.lstat(part), "st_file_attributes", 0)
        except FileNotFoundError:
            break
        if attrs & REPARSE_POINT:
            raise DataFolderOutside("%s: component %s is a reparse point (junction or symlink)" % (path, part))


def find_signed_in_line(lines, since_epoch):
    """The first line written at or after `since_epoch` (local time of the line's own prefix) that says signed in."""
    for line in lines:
        m = LOG_TS_RE.match(line)
        if not m or not SIGNED_IN_RE.search(line):
            continue
        if time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) >= since_epoch:
            return line
    return None


def scrub_env(environ, userdata, config, tmp) -> dict:
    """A whitelist of the system variables plus the two data variables; nothing else of this session passes."""
    keep = {n.lower() for n in ENV_WHITELIST}
    env = {k: v for k, v in environ.items() if k.lower() in keep}
    for k in [k for k in env if k.lower() in ("temp", "tmp")]:
        del env[k]
    env.update({"TEMP": str(tmp), "TMP": str(tmp), "CLAUDE_USER_DATA_DIR": str(userdata), "CLAUDE_CONFIG_DIR": str(config)})
    return env


def env_block(env: dict) -> str:
    return "".join("%s=%s\0" % (k, env[k]) for k in sorted(env, key=str.lower)) + "\0"


@dataclass
class StartRequest:
    exe: str
    command_line: str
    cwd: str
    desktop: str
    env: dict
    flags: int


def build_start_request(exe, userdata, config, desktop_name, environ, place_root, visible=False) -> StartRequest:
    env = scrub_env(environ, userdata, config, Path(place_root) / "tmp")
    return StartRequest(
        exe=str(exe),
        command_line='"%s" --user-data-dir="%s"' % (exe, userdata),
        cwd=str(place_root),
        desktop=DEFAULT_DESKTOP if visible else "WinSta0\\" + desktop_name,
        env=env,
        flags=CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW,
    )


def make_startup_info(desktop: str):
    si = pcw.STARTUPINFOW()
    si.cb = ctypes.sizeof(pcw.STARTUPINFOW)
    si.lpDesktop = desktop
    return si


def descendants(table, root_pid, root_start, start_of) -> list:
    """Pids below root_pid in the (pid, parent pid) table; each must have started at or after the root (pid reuse)."""
    found, frontier = [], [root_pid]
    while frontier:
        parent = frontier.pop(0)
        for pid, ppid in sorted(table):
            if ppid == parent and pid not in found and pid != root_pid:
                st = start_of(pid)
                if st and st >= root_start:
                    found.append(pid)
                    frontier.append(pid)
    return found


def his_processes(procs, mine) -> tuple:
    return tuple(p for p in procs if p[0] not in mine)


def row_s_compare(before: dict, after: dict) -> list:
    return pa.row_s_diff(pa.public(before), pa.public(after))


def classify_verdict(alive_at_end: bool, lived_s: float, exit_code, log_text: str, live_s: float) -> str:
    if alive_at_end:
        return "sign-in" if SIGNIN_RE.search(log_text or "") else "lived"
    return "forwarded-and-quit" if exit_code in (0, None) else "crashed"


def redact(line: str) -> str:
    return SK_RE.sub("[redacted]", REDACT_RE.sub(lambda m: m.group(1) + " [redacted]", line))


@dataclass
class TrialResult:
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    diff: list = field(default_factory=list)
    during_diffs: list = field(default_factory=list)
    samples_n: int = 0
    root_pid: int = 0
    pids: dict = field(default_factory=dict)
    lived_s: float = 0.0
    ran_s: float = 0.0
    alive_at_end: bool = False
    exit_code: object = None
    default_windows_max: int = 0
    private_windows: list = field(default_factory=list)
    inspect: dict = field(default_factory=dict)
    his_folder_hits: list = field(default_factory=list)
    ours: int = 0
    his: int = 0
    pointer_samples: int = 0
    stopped: list = field(default_factory=list)
    still_running: list = field(default_factory=list)
    own_log_lines: list = field(default_factory=list)
    his_log_lines: list = field(default_factory=list)
    place_files: list = field(default_factory=list)
    verdict: str = ""
    counter_total: int = 0
    counter_cap: int = 0
    start_error: str = ""
    aborted_for_window: bool = False


def run_trial(seam, counter, userdata, config, place_root, live_s=LIVE_S, sample_s=SAMPLE_S, tail_s=TAIL_S,
              forbidden=(), exe=None, environ=None) -> TrialResult:
    """Everything that can be refused is refused before the first read of row S; then desktop, counter, start."""
    check_data_folders(userdata, config, place_root, forbidden)
    if counter.remaining() <= 0:
        raise StartCounterSpent("start counter: %d of %d used in total; nothing started" % (counter.total, counter.total_cap))
    ram = seam.free_ram_gb()
    if ram < MIN_FREE_RAM_GB:
        raise PlaceError("free RAM %.1f GB < %.1f GB: not started" % (ram, MIN_FREE_RAM_GB))
    for d in (userdata, config, Path(place_root) / "tmp"):
        Path(d).mkdir(parents=True, exist_ok=True)

    res = TrialResult(counter_cap=counter.total_cap)
    res.before = seam.row_s_full("before")
    light_keys = ("processes", "window", "foreground")
    sampler = seam.pointer_sampler()
    sampler.start()
    handle = proc = None
    mine: dict = {}
    t0 = t_start = seam.now()
    try:
        handle, dname = seam.create_desktop()
        req = build_start_request(exe, userdata, config, dname, environ if environ is not None else {}, place_root)
        counter.spend()  # on disk before the process exists
        res.counter_total = counter.total
        t_start = seam.now()
        try:
            proc = seam.create_process(req)
        except OSError as e:
            res.start_error = str(e)
            proc = None
        if proc is not None:
            res.root_pid = proc.pid
            mine[proc.pid] = proc.start
            t0 = seam.now()
            died_at = None
            inspected = False
            last_tick = seam.input_tick()
            while True:
                elapsed = seam.now() - t0
                res.samples_n += 1
                for pid in descendants(seam.process_table(), proc.pid, proc.start, seam.start_time):
                    mine.setdefault(pid, seam.start_time(pid))
                light = seam.row_s_light(set(mine))
                names = [k for k in light_keys if res.before.get(k) != light.get(k)]
                tick = seam.input_tick()
                if names:
                    res.during_diffs.append((elapsed, names, tick != last_tick))
                last_tick = tick
                hits = [w for w in seam.default_windows() if w["pid"] in mine]
                res.default_windows_max = max(res.default_windows_max, len(hits))
                pw = seam.desktop_windows(handle)
                if pw:
                    res.private_windows = pw
                if hits:
                    res.aborted_for_window = True
                    break
                alive_pids = [p for p, s in mine.items() if seam.is_running(p, s)]
                if died_at is None and not seam.alive(proc):
                    died_at = elapsed
                if not inspected and alive_pids and elapsed >= min(20, live_s / 2):
                    res.inspect = inspect_all(seam, alive_pids)
                    inspected = True
                if not alive_pids and died_at is not None and elapsed - died_at >= tail_s:
                    break
                if elapsed >= live_s:
                    break
                seam.sleep(sample_s)
            res.ran_s = seam.now() - t0
            alive_pids = [p for p, s in mine.items() if seam.is_running(p, s)]
            res.alive_at_end = bool(alive_pids)
            if alive_pids:
                last = inspect_all(seam, alive_pids)
                res.inspect = _merge_inspect(res.inspect, last)
            res.exit_code = seam.exit_code(proc)
            res.lived_s = res.ran_s if res.alive_at_end else seam.lived_for(proc)
    finally:
        sampler.stop()
        res.stopped, res.still_running = stop_tree(seam, proc, mine)
        if handle is not None:
            seam.close_desktop(handle)
    res.pids = dict(mine)
    res.after = seam.row_s_full("after")
    res.diff = row_s_compare(res.before, res.after)
    res.ours, res.his, res.pointer_samples = sampler.moved_by_us(), sampler.moved_by_him(), len(sampler.samples)
    res.his_folder_hits = [f for f in res.inspect.get("files", []) if any(_under(f, x) for x in forbidden)]
    res.own_log_lines = seam.place_log_lines()
    res.his_log_lines = seam.his_log_marker_lines(t_start)
    res.place_files = seam.place_listing(place_root)
    log_text = "\n".join(res.own_log_lines)
    res.verdict = classify_verdict(res.alive_at_end, res.lived_s, res.exit_code, log_text, live_s) if proc else "not-started"
    return res


@dataclass
class VisibleResult:
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    diff: list = field(default_factory=list)
    during_diffs: list = field(default_factory=list)
    samples_n: int = 0
    root_pid: int = 0
    pids: dict = field(default_factory=dict)
    ran_s: float = 0.0
    settle_s: float = 0.0
    ended_by: str = ""  # "log" | "flag" | "timeout" | "exited"
    end_line: str = ""
    window_first_seen: object = None  # "HH:MM:SS" on the clock
    window_first_after_s: object = None
    copy_windows_max: int = 0
    copy_windows: list = field(default_factory=list)
    inspect: dict = field(default_factory=dict)
    his_folder_hits: list = field(default_factory=list)
    ours: int = 0
    his: int = 0
    pointer_samples: int = 0
    stopped: list = field(default_factory=list)
    still_running: list = field(default_factory=list)
    his_log_lines: list = field(default_factory=list)
    counter_total: int = 0
    counter_cap: int = 0
    start_error: str = ""


def run_visible(seam, counter, userdata, config, place_root, flag_path, window_up_path, wait_s=SIGNIN_WAIT_S,
                poll_s=SIGNIN_POLL_S, settle_s=SETTLE_S, forbidden=(), exe=None, environ=None) -> VisibleResult:
    """Start 2 of 3: the second copy on HIS desktop (no private desktop object) so the owner can sign in once.
    Everything that can be refused is refused before row S is first read; nothing in the copy is ever touched."""
    check_data_folders(userdata, config, place_root, forbidden)
    for p in (place_root, userdata, config):
        assert_real_path(p)
    if counter.remaining() <= 0:
        raise StartCounterSpent("start counter: %d of %d used in total; nothing started" % (counter.total, counter.total_cap))
    if seam.path_exists(flag_path):
        raise PlaceError("%s exists before the start: it would end the wait at once; not started" % flag_path)
    ram = seam.free_ram_gb()
    if ram < MIN_FREE_RAM_GB:
        raise PlaceError("free RAM %.1f GB < %.1f GB: not started" % (ram, MIN_FREE_RAM_GB))
    for d in (userdata, config, Path(place_root) / "tmp"):
        Path(d).mkdir(parents=True, exist_ok=True)

    res = VisibleResult(counter_cap=counter.total_cap)
    res.before = seam.row_s_full("before")
    light_keys = ("processes", "window", "foreground")
    sampler = seam.pointer_sampler()
    sampler.start()
    proc = None
    mine: dict = {}
    t_start = seam.now()
    try:
        req = build_start_request(exe, userdata, config, None, environ if environ is not None else {}, place_root, visible=True)
        counter.spend()  # on disk before the process exists
        res.counter_total = counter.total
        since_epoch = seam.epoch_now() - 2
        t_start = seam.now()
        try:
            proc = seam.create_process(req)
        except OSError as e:
            res.start_error = str(e)
        if proc is not None:
            res.root_pid = proc.pid
            mine[proc.pid] = proc.start
            t0 = seam.now()
            last_tick, died_at = seam.input_tick(), None
            while True:
                elapsed = seam.now() - t0
                res.samples_n += 1
                for pid in descendants(seam.process_table(), proc.pid, proc.start, seam.start_time):
                    mine.setdefault(pid, seam.start_time(pid))
                light = seam.row_s_light(set(mine))
                names = [k for k in light_keys if res.before.get(k) != light.get(k)]
                tick = seam.input_tick()
                if names:
                    res.during_diffs.append((elapsed, names, tick != last_tick))
                last_tick = tick
                shown = [w for w in seam.default_windows() if w["pid"] in mine and w["visible"] and w["cls"] == "Chrome_WidgetWin_1"]
                if shown:
                    res.copy_windows_max = max(res.copy_windows_max, len(shown))
                    res.copy_windows = [(w["cls"], w["title"]) for w in shown]
                    if res.window_first_seen is None:
                        res.window_first_seen = seam.clock_hms()
                        res.window_first_after_s = elapsed
                        seam.write_text(window_up_path, "WINDOW UP %s\n" % res.window_first_seen)
                alive_pids = [p for p, s in mine.items() if seam.is_running(p, s)]
                if not alive_pids:
                    died_at = elapsed if died_at is None else died_at
                    if elapsed - died_at >= TAIL_S:
                        res.ended_by = "exited"
                        break
                line = seam.signin_line(userdata, since_epoch)
                if line:
                    res.ended_by, res.end_line = "log", line
                    break
                if seam.path_exists(flag_path):
                    res.ended_by = "flag"
                    break
                if elapsed >= wait_s:
                    res.ended_by = "timeout"
                    break
                seam.sleep(poll_s if res.window_first_seen else min(WINDOW_TICK_S, poll_s))
            res.ran_s = seam.now() - t0
            if res.ended_by in ("log", "flag") and settle_s > 0:
                seam.sleep(settle_s)  # the app writes its cookies to disk a little after the sign-in; stopping at once could lose it
                res.settle_s = settle_s
            alive_pids = [p for p, s in mine.items() if seam.is_running(p, s)]
            if alive_pids:
                res.inspect = inspect_all(seam, alive_pids)
    finally:
        sampler.stop()
        res.stopped, res.still_running = stop_tree(seam, proc, mine)
    res.pids = dict(mine)
    res.after = seam.row_s_full("after")
    res.diff = row_s_compare(res.before, res.after)
    res.ours, res.his, res.pointer_samples = sampler.moved_by_us(), sampler.moved_by_him(), len(sampler.samples)
    res.his_folder_hits = [f for f in res.inspect.get("files", []) if any(_under(f, x) for x in forbidden)]
    res.his_log_lines = seam.his_log_marker_lines(t_start)
    return res


def _ft(ft) -> str:
    try:
        return pa._filetime_text(ft)
    except (OSError, ValueError, OverflowError):
        return str(ft)


def format_visible_report(r: VisibleResult, wait_s: float = SIGNIN_WAIT_S) -> str:
    def procs(row):
        return ", ".join("%d@%s" % (p, pa._filetime_text(s)) for p, s in row.get("processes", ())) or "none"

    how = {"log": "the copy's own main.log shows the signed-in state", "flag": "the file signed-in.flag exists",
           "timeout": "no sign-in in %s: the wait ran out" % human_duration(wait_s),
           "exited": "the copy quit by itself"}.get(r.ended_by, r.ended_by or "not started")
    end_line = re.sub(r"uuid:.*", "uuid: [account id omitted]", redact(r.end_line)) if r.end_line else ""
    lines = ["# #916 way B: start 2 of 3, the second copy on his desktop for the one sign-in (%s)" % time.strftime("%Y-%m-%d %H:%M"), "",
             "## How the wait ended: %s" % r.ended_by, "",
             "| # | wanted | number |", "|---|---|---|",
             "| W | WINDOW UP time (first window of the copy on WinSta0\\Default) | %s%s |"
             % (r.window_first_seen or "no window seen",
                " (%s after the start)" % human_duration(r.window_first_after_s) if r.window_first_after_s is not None else ""),
             "| W | windows of the copy on WinSta0\\Default (visible Chrome_WidgetWin_1, most at once) | %d: %s |"
             % (r.copy_windows_max, r.copy_windows or "none"),
             "| E | how the wait ended | %s; waited %s of at most %s; then %s kept before the stop |"
             % (how, human_duration(r.ran_s), human_duration(wait_s), human_duration(r.settle_s)),
             "| E | signed-in line quoted | %s |" % (end_line or "none"),
             "| S | row S before vs after | %s |" % ("equal" if not r.diff else "DIFFERENT: " + ", ".join(r.diff)),
             "| S | row S during (%d samples; the copy's own windows are left out of his) | %s |" % (
                 r.samples_n, "no change" if not r.during_diffs else "; ".join(
                     "%s: %s%s" % (human_duration(t), "/".join(n), " (his own input in that interval)" if his else "")
                     for t, n, his in r.during_diffs[:40])),
             "| S | pointer samples moved by us / by him | %d / %d (of %d) |" % (r.ours, r.his, r.pointer_samples),
             "| B2 | open files in his folders | %d of %d open files over %d processes |"
             % (len(r.his_folder_hits), len(r.inspect.get("files", [])), len(r.inspect.get("cmdline", {}))),
             "| - | start counter | %d of %d used in total |" % (r.counter_total, r.counter_cap),
             "| - | stopped (pids started by this script) | %s; still running: %s |"
             % (", ".join(str(p) for p in r.stopped) or "none", ", ".join(str(p) for p in r.still_running) or "none"),
             ""]
    if r.start_error:
        lines += ["CreateProcess failed: %s" % r.start_error, ""]
    lines += ["## Row S before / after", "", "| | processes (pid@start) | window hwnd / rect / title | foreground | look bytes (colours) | painted |",
              "|---|---|---|---|---|---|"]
    for tag, row in (("before", r.before), ("after", r.after)):
        w = row.get("window")
        lines.append("| %s | %s | %s | %s | %s (%s) | %s |" % (
            tag, procs(row), "%d / %s / %r" % w if w else "none", "%d %r" % row.get("foreground", (0, "")),
            row.get("_look_bytes"), row.get("_look_colours"), row.get("painted")))
    lines += ["", "Process pids of the copy: %s" % (", ".join("%d@%s" % (p, _ft(s)) for p, s in sorted(r.pids.items())) or "none")]
    lines += ["", "Command lines of its processes:"] + ["- %d: %s" % (p, c) for p, c in sorted(r.inspect.get("cmdline", {}).items())]
    lines += ["", "Marker lines in his app's log written since the start (read only, markers only): %s" % ("" if r.his_log_lines else "none")]
    lines += ["- %s" % x for x in r.his_log_lines[:20]]
    return "\n".join(lines) + "\n"


def inspect_all(seam, pids) -> dict:
    cmds, files = {}, set()
    for pid in pids:
        info = seam.inspect(pid)
        cmds[pid] = info.get("cmdline", "")
        files.update(info.get("files", []))
    return {"cmdline": cmds, "files": sorted(files)}


def _merge_inspect(a: dict, b: dict) -> dict:
    return {"cmdline": {**a.get("cmdline", {}), **b.get("cmdline", {})},
            "files": sorted(set(a.get("files", [])) | set(b.get("files", [])))}


def stop_tree(seam, proc, mine: dict):
    """Stops the root and what is below it, each checked by (pid, start): never anything else."""
    if proc is None:
        return [], []
    for pid in descendants(seam.process_table(), proc.pid, proc.start, seam.start_time):
        mine.setdefault(pid, seam.start_time(pid))
    stopped = []
    for _ in range(3):
        for pid, st in list(mine.items()):
            if seam.is_running(pid, st) and seam.kill(pid, st) and pid not in stopped:
                stopped.append(pid)
        seam.sleep(1)
        if not any(seam.is_running(p, s) for p, s in mine.items()):
            break
    return stopped, [p for p, s in mine.items() if seam.is_running(p, s)]


def format_report(r: TrialResult, live_s: float = LIVE_S) -> str:
    def procs(row):
        return ", ".join("%d@%s" % (p, pa._filetime_text(s)) for p, s in row.get("processes", ())) or "none"

    b, a = r.before, r.after
    lines = ["# #916 way B: one trial start of a second copy on a private desktop (%s)" % time.strftime("%Y-%m-%d %H:%M"), "",
             "## Verdict: %s" % r.verdict, "",
             "| # | wanted | number |", "|---|---|---|",
             "| B1 | a second copy runs for %s next to his | root pid %d; its tree: %s; lived %s of %s (alive at the end: %s); exit code %s |"
             % (human_duration(live_s), r.root_pid, ", ".join(str(p) for p in r.pids) or "none", human_duration(r.lived_s),
                human_duration(live_s), "yes" if r.alive_at_end else "no", r.exit_code),
             "| B2 | it names only var/monitor-place paths | %d open files over %d processes; in his folders: %d |"
             % (len(r.inspect.get("files", [])), len(r.inspect.get("cmdline", {})), len(r.his_folder_hits)),
             "| S | row S before vs after | %s |" % ("equal" if not r.diff else "DIFFERENT: " + ", ".join(r.diff)),
             "| S | row S during (%d samples, every %s) | %s |" % (
                 r.samples_n, human_duration(SAMPLE_S),
                 "no change" if not r.during_diffs else "; ".join("%s: %s%s" % (human_duration(t), "/".join(n), " (his own input in that interval)" if his else "")
                                                     for t, n, his in r.during_diffs)),
             "| S | pointer samples moved by us / by him | %d / %d (of %d) |" % (r.ours, r.his, r.pointer_samples),
             "| S | windows of ours on WinSta0\\Default | %d |" % r.default_windows_max,
             "| - | start counter | %d of %d used in total |" % (r.counter_total, r.counter_cap),
             "| - | stopped (pids started by this script) | %s; still running: %s |"
             % (", ".join(str(p) for p in r.stopped) or "none", ", ".join(str(p) for p in r.still_running) or "none"),
             ""]
    if r.start_error:
        lines += ["CreateProcess failed: %s" % r.start_error, ""]
    if r.aborted_for_window:
        lines += ["The run ended at the first sample: a window of ours was on WinSta0\\Default (limit 3).", ""]
    lines += ["## Row S before / after", "", "| | processes (pid@start) | window hwnd / rect / title | foreground | look bytes (colours) | painted |",
              "|---|---|---|---|---|---|"]
    for tag, row in (("before", b), ("after", a)):
        w = row.get("window")
        lines.append("| %s | %s | %s | %s | %s (%s) | %s |" % (
            tag, procs(row), "%d / %s / %r" % w if w else "none", "%d %r" % row.get("foreground", (0, "")),
            row.get("_look_bytes"), row.get("_look_colours"), row.get("painted")))
    lines += ["", "## What the second copy did", "",
              "Windows it made on its private desktop (class, title): %s" % (r.private_windows or "none"), ""]
    lines += ["Command lines of its processes:"] + ["- %d: %s" % (p, c) for p, c in sorted(r.inspect.get("cmdline", {}).items())]
    lines += ["", "Open files (B2):"] + ["- %s" % f for f in r.inspect.get("files", [])] + [""]
    lines += ["Marker lines in its own logs under var/monitor-place/ (credential words redacted): %s" % ("" if r.own_log_lines else "none")]
    lines += ["- %s" % x for x in r.own_log_lines[:80]]
    lines += ["", "Marker lines in his app's log written since the start (read only, markers only): %s" % ("" if r.his_log_lines else "none")]
    lines += ["- %s" % x for x in r.his_log_lines[:20]]
    lines += ["", "Files under var/monitor-place/ after the run (%d):" % len(r.place_files)]
    lines += ["- %s (%d B)" % (n, s) for n, s in r.place_files[:60]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- Win32 (not unit tested; read as little as possible)

class _Proc:
    def __init__(self, pid, start, handle):
        self.pid, self.start, self.handle = pid, start, handle


class RealSeam:
    def __init__(self, place_root: Path, looks: Path, his_dirs):
        self.root, self.looks, self.his_dirs = Path(place_root), Path(looks), tuple(his_dirs)
        self.looks.mkdir(parents=True, exist_ok=True)
        k = self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        H, DW = wintypes.HANDLE, wintypes.DWORD
        k.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, DW,
                                     ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(pcw.STARTUPINFOW),
                                     ctypes.POINTER(pcw.PROCESS_INFORMATION)]
        k.CloseHandle.argtypes = [H]
        k.GetExitCodeProcess.argtypes = [H, ctypes.POINTER(DW)]
        k.WaitForSingleObject.argtypes = [H, DW]
        k.OpenProcess.argtypes = [DW, wintypes.BOOL, DW]
        k.OpenProcess.restype = H
        k.TerminateProcess.argtypes = [H, wintypes.UINT]
        k.GetProcessTimes.argtypes = [H] + [ctypes.POINTER(wintypes.FILETIME)] * 4

    def now(self):
        return time.time()

    def sleep(self, s):
        time.sleep(s)

    def free_ram_gb(self):
        class MEM(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
                                                                          ("tp", "ap", "tpf", "apf", "tv", "av", "aev")]
        m = MEM()
        m.l = ctypes.sizeof(MEM)
        self.k.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ap / 2 ** 30

    def row_s_full(self, tag):
        return pa.snapshot_row_s(self.looks / (tag + ".png"))

    def row_s_light(self, mine):
        wins = [w for w in pa.top_windows() if w["pid"] not in mine]  # the copy's own window is never taken for his
        main = pa.find_app_window(wins)
        u = pa._api()[0]
        fg = u.GetForegroundWindow()
        return {"processes": his_processes(pa.app_processes(main["pid"]), mine) if main else (),
                "window": (main["hwnd"], main["rect"], main["title"]) if main else None,
                "foreground": (int(fg or 0), pa._text(u, fg) if fg else "")}

    def input_tick(self):
        return pa.last_input_tick()

    def epoch_now(self):
        return time.time()

    def clock_hms(self):
        return time.strftime("%H:%M:%S")

    def write_text(self, path, text):
        Path(path).write_text(text, encoding="utf-8")
        print("%s: %s" % (Path(path).name, text.strip()), flush=True)

    def path_exists(self, path):
        return Path(path).exists()

    def signin_line(self, userdata, since_epoch):
        """The copy's own main.log (read only): the first line since the start that says signed in, or None."""
        log = Path(userdata) / "logs" / "main.log"
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-6000:]
        except OSError:
            return None
        return find_signed_in_line(lines, since_epoch)

    def pointer_sampler(self):
        return pa.PointerSampler(pa.cursor_pos, pa.last_input_tick)

    def create_desktop(self):
        return pcw.create_isolated_desktop()

    def close_desktop(self, handle):
        pcw.close_desktop(handle)

    def create_process(self, req: StartRequest):
        block = env_block(req.env)
        env_buf = (ctypes.c_wchar * len(block))(*block)
        cmd = ctypes.create_unicode_buffer(req.command_line)
        si = make_startup_info(req.desktop)
        pi = pcw.PROCESS_INFORMATION()
        ok = self.k.CreateProcessW(None, cmd, None, None, False, req.flags, ctypes.cast(env_buf, ctypes.c_void_p),
                                   req.cwd, ctypes.byref(si), ctypes.byref(pi))
        if not ok:
            raise OSError("CreateProcessW failed (error %d)" % ctypes.get_last_error())
        self.k.CloseHandle(pi.hThread)
        return _Proc(pi.dwProcessId, self._times(pi.hProcess)[0], pi.hProcess)

    def _times(self, h):
        c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
        self.k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut))
        return (c.dwHighDateTime << 32) | c.dwLowDateTime, (e.dwHighDateTime << 32) | e.dwLowDateTime

    def alive(self, proc):
        return self.k.WaitForSingleObject(proc.handle, 0) == WAIT_TIMEOUT

    def exit_code(self, proc):
        if self.alive(proc):
            return None
        code = wintypes.DWORD()
        self.k.GetExitCodeProcess(proc.handle, ctypes.byref(code))
        return code.value

    def lived_for(self, proc):
        c, e = self._times(proc.handle)
        return max(0.0, (e - c) / 1e7)

    def process_table(self):
        k = self.k
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(pa.PROCESSENTRY32W)]
        k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(pa.PROCESSENTRY32W)]
        snap, out = k.CreateToolhelp32Snapshot(0x2, 0), []
        try:
            e = pa.PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(e)
            ok = k.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                out.append((e.th32ProcessID, e.th32ParentProcessID))
                ok = k.Process32NextW(snap, ctypes.byref(e))
        finally:
            k.CloseHandle(snap)
        return out

    def start_time(self, pid):
        return pa.process_info(pid)[1]

    def is_running(self, pid, start):
        h = self.k.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            self.k.GetExitCodeProcess(h, ctypes.byref(code))
            return code.value == STILL_ACTIVE and self._times(h)[0] == start
        finally:
            self.k.CloseHandle(h)

    def kill(self, pid, start):
        h = self.k.OpenProcess(0x0001 | 0x1000, False, pid)  # PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            return self._times(h)[0] == start and bool(self.k.TerminateProcess(h, 1))
        finally:
            self.k.CloseHandle(h)

    def default_windows(self):
        return pa.top_windows()

    def desktop_windows(self, handle):
        return pcw.count_windows_on_desktop(handle)

    def inspect(self, pid):
        import psutil
        try:
            p = psutil.Process(pid)
            cmd = " ".join(p.cmdline())
        except psutil.Error as e:
            return {"cmdline": "unreadable: %s" % type(e).__name__, "files": []}
        try:
            files = [f.path for f in p.open_files()]
        except psutil.Error:
            files = []
        return {"cmdline": cmd, "files": files}

    def _marker_lines(self, folder: Path, since_epoch: float, markers, limit_files=12):
        out = []
        files = [f for d in (folder,) if d.exists() for f in d.rglob("*.log")]
        for f in sorted(files, key=lambda f: -f.stat().st_mtime)[:limit_files]:
            if since_epoch and f.stat().st_mtime < since_epoch:
                continue
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]:
                if not markers or any(m.lower() in line.lower() for m in markers):
                    out.append("%s: %s" % (f.name, redact(line.strip())[:300]))
        return out

    def place_log_lines(self):
        lines = self._marker_lines(self.root, 0, ())
        return lines[-150:]

    def his_log_marker_lines(self, since):
        out = []
        for d in self.his_dirs:
            try:
                out += self._marker_lines(d, since - 5, LOG_MARKERS)
            except OSError as e:
                out.append("%s: unreadable (%s)" % (d.name, type(e).__name__))
        return out[-20:]

    def place_listing(self, root):
        out = []
        for f in sorted(Path(root).rglob("*")):
            if f.is_file() and len(out) < 400 and "looks" not in f.parts:
                out.append((str(f.relative_to(root)), f.stat().st_size))
        return out


def his_folders():
    local, roam, home = os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", ""), Path.home()
    return tuple(p for p in (Path(local) / "Packages" / "Claude_pzs8sxrjxfjjc", Path(roam) / "Claude", home / ".claude")
                 if str(p) and local)


def his_log_dirs():
    local = os.environ.get("LOCALAPPDATA", "")
    return (Path(local) / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude" / "logs",)


def alias_exe() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WindowsApps" / "claude-desktop.exe"


def cmd_plan() -> int:
    exe = alias_exe()
    print("exe: %s (alias present: %s)" % (exe, os.path.lexists(exe)))
    userdata, config = PLACE_ROOT / "userdata", PLACE_ROOT / "config"
    check_data_folders(userdata, config, PLACE_ROOT, his_folders())
    req = build_start_request(exe, userdata, config, "<private desktop>", dict(os.environ), PLACE_ROOT)
    print("command line: %s\ncwd: %s\ndesktop: %s\nflags: 0x%x" % (req.command_line, req.cwd, req.desktop, req.flags))
    print("env passed: %s" % ", ".join("%s=%s" % (k, v) for k, v in sorted(req.env.items()) if k.startswith("CLAUDE") or k in ("TEMP", "TMP")))
    print("env names passed: %s" % ", ".join(sorted(req.env)))
    c = StartCounter(COUNTER_FILE)
    print("start counter: %d of %d used in total; this run may spend %d" % (c.total, c.total_cap, c.remaining()))
    print("his folders (must never appear): %s" % ", ".join(map(str, his_folders())))
    print("free RAM: %.1f GB" % RealSeam(PLACE_ROOT, PLACE_ROOT / "looks", ()).free_ram_gb())
    return 0


def cmd_start(out: Path, live_s: float) -> int:
    counter = StartCounter(COUNTER_FILE)
    seam = RealSeam(PLACE_ROOT, PLACE_ROOT / "looks", his_log_dirs())
    res = run_trial(seam, counter, PLACE_ROOT / "userdata", PLACE_ROOT / "config", PLACE_ROOT, live_s=live_s,
                    forbidden=his_folders(), exe=alias_exe(), environ=dict(os.environ))
    text = format_report(res, live_s)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


def visible_paths():
    root = REAL_PLACE_ROOT
    return root, root / "userdata", root / "config", root / "signed-in.flag", root / "window-up.txt"


def cmd_plan_visible() -> int:
    root, userdata, config, flag, up = visible_paths()
    exe = alias_exe()
    check_data_folders(userdata, config, root, his_folders())
    for p in (root, userdata, config):
        assert_real_path(p)
    req = build_start_request(exe, userdata, config, None, dict(os.environ), root, visible=True)
    print("exe: %s (alias present: %s)" % (exe, os.path.lexists(exe)))
    print("command line: %s" % req.command_line)
    print("cwd: %s\ndesktop: %s\nflags: 0x%x" % (req.cwd, req.desktop, req.flags))
    print("env passed: %s" % ", ".join("%s=%s" % (k, v) for k, v in sorted(req.env.items()) if k.startswith("CLAUDE") or k in ("TEMP", "TMP")))
    c = StartCounter(COUNTER_FILE)
    print("start counter: %d of %d used in total; this run may spend %d" % (c.total, c.total_cap, c.remaining()))
    print("flag file (ends the wait when it exists): %s (exists now: %s)" % (flag, flag.exists()))
    print("window-up file: %s (exists now: %s)" % (up, up.exists()))
    print("real path check: no reparse point in %s, %s, %s" % (root, userdata, config))
    return 0


def cmd_start_visible(out: Path, wait_s: float) -> int:
    root, userdata, config, flag, up = visible_paths()
    seam = RealSeam(root, root / "looks", his_log_dirs())
    res = run_visible(seam, StartCounter(COUNTER_FILE), userdata, config, root, flag, up, wait_s=wait_s,
                      forbidden=his_folders(), exe=alias_exe(), environ=dict(os.environ))
    text = format_visible_report(res, wait_s)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--visible", action="store_true")
    st = sub.add_parser("start")
    st.add_argument("--out", required=True)
    st.add_argument("--live", type=float, default=LIVE_S)
    st.add_argument("--visible", action="store_true", help="start 2 of 3: the copy on his desktop for his one sign-in")
    st.add_argument("--wait", type=float, default=SIGNIN_WAIT_S, help="visible mode: at most this many seconds (default 20 min)")
    a = ap.parse_args(argv)
    if a.action == "plan":
        return cmd_plan_visible() if a.visible else cmd_plan()
    if a.visible:
        return cmd_start_visible(Path(a.out), min(a.wait, SIGNIN_WAIT_S))
    return cmd_start(Path(a.out), a.live)


if __name__ == "__main__":
    sys.exit(main())
