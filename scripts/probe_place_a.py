"""#916 way A: does a posted WM_MOUSEMOVE make the owner's Claude window draw the hover block?

  python scripts/probe_place_a.py list                 # read only: his windows, children, processes, row S
  python scripts/probe_place_a.py run --out <dir>      # 5 runs x 2 posted moves, A1-A4 table

Hard limits of the ticket: reading his app only (EnumWindows / EnumChildWindows / GetWindowRect /
GetForegroundWindow / process lookup); nothing written under his folders; the real pointer is never moved and
no button message is posted: the only message this script sends is WM_MOUSEMOVE. Unit 1b (autopilot's rules):
the posts are counted in a file that survives runs (at most 10 per run, 44 in total, PostCounter raises on the
next); nothing is posted before BOTH hold: the "novee" point belongs to his app's window (WindowFromPoint) and his
last input is 120 s or more ago (pane_look.idle_seconds); the wait for that is at most 30 min, else 0 posts and
exit 4 with "not met at HH:MM"; the run stops by itself when either fails again. ctypes + stdlib only; no console
window, no child process.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pane_look  # noqa: E402  (write_png, distinct_colours, screen_rgb, _dpi_aware, idle seam: reused, not copied)
from pane_look import IDLE_NEED_S, idle_seconds  # noqa: E402

WM_MOUSEMOVE = 0x0200
PW_RENDERFULLCONTENT = 2
MAX_POSTS = 10                 # per script run
TOTAL_POST_CAP = 44            # across script runs: 34 used before unit 1b + 10
COUNTER_FILE = Path(__file__).resolve().parents[1] / "docs" / "research" / "pictures-916" / "posts-counter.json"
GATE_MAX_S = 30 * 60
GATE_POLL_S = 5
EXIT_NO_WINDOW, EXIT_NOT_MET, EXIT_STOPPED, EXIT_COUNTER = 2, 4, 5, 6
HOVER_COLOUR = (0x43, 0x43, 0x47)
H2_POINT = (2399, 914)  # screen point of the pager word "новее", #837 H2 (orch44cb-h2/table.md); it moves with the rows
TEMPLATE = Path(__file__).resolve().parents[1] / "docs" / "research" / "pictures-916" / "template-novee.png"
H2_BLOCK = (8, 19)  # width x height H2 measured through the real pointer
REST = 0.6
LOOK_MIN_BYTES = 330_000


# ---------------------------------------------------------------- pure parts (tested)

class PostCapExceeded(RuntimeError):
    pass


class StopRun(RuntimeError):
    """The gate closed inside the run (his input arrived, or the point got covered)."""


class PostBudget:
    """Counts posted messages; the (limit+1)-th raises."""

    def __init__(self, limit: int = MAX_POSTS):
        self.limit = limit
        self.used = 0

    def spend(self) -> None:
        if self.used >= self.limit:
            raise PostCapExceeded("posted-move cap %d reached" % self.limit)
        self.used += 1


class PostCounter(PostBudget):
    """PostBudget whose total lives in a JSON file {"used": n, "total_cap": m}, written before every post.

    `used` counts this script run (at most `limit`), `total` all runs (at most the file's total_cap).
    """

    def __init__(self, path, limit: int = MAX_POSTS):
        super().__init__(limit)
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8"))  # FileNotFoundError when absent: never guessed
        self.total = int(data["used"])
        self.total_cap = int(data["total_cap"])

    def remaining(self) -> int:
        return max(0, min(self.limit - self.used, self.total_cap - self.total))

    def spend(self) -> None:
        if self.total >= self.total_cap:
            raise PostCapExceeded("posts total cap %d reached (file %s)" % (self.total_cap, self.path.name))
        super().spend()
        self.total += 1
        self.path.write_text(json.dumps({"used": self.total, "total_cap": self.total_cap}) + "\n", encoding="utf-8")


def make_lparam(x: int, y: int) -> int:
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def post_move(budget: PostBudget, post_fn, hwnd, x: int, y: int, guard=None, point=None) -> None:
    """The one send of this script: WM_MOUSEMOVE at client point (x, y) of hwnd, counted.

    With a `guard` (point -> reason or None) the gate is read first; a reason raises StopRun and nothing is sent.
    """
    if guard is not None:
        why = guard(point)
        if why:
            raise StopRun(why)
    budget.spend()
    post_fn(hwnd, WM_MOUSEMOVE, 0, make_lparam(x, y))


def gate_check(find_point, in_app, idle_fn, point=None):
    """(ok, why, point). find_point() -> screen point of the template in a fresh capture, or None (read only);
    in_app(point) -> the window at that point belongs to his app (not covered); idle_fn() -> seconds since his input.
    With `point` given (inside a run) no new capture is asked for."""
    if point is None:
        point = find_point()
        if point is None:
            return False, "pager word not on screen", None
    if not in_app(point):
        return False, "point covered by another window", point
    n = idle_fn()
    if n < IDLE_NEED_S:
        return False, "his input %d s ago, need %d s (input)" % (n, IDLE_NEED_S), point
    return True, None, point


def wait_for_gate(check, sleep, clock, say, max_wait: float = GATE_MAX_S, poll: float = GATE_POLL_S):
    """Polls `check` every `poll` s for at most `max_wait` s: (True, point) or (False, last reason)."""
    start, last = clock(), None
    while True:
        ok, why, point = check(None)
        if ok:
            return True, point
        if why != last:
            say("waiting (%s): %s" % (time.strftime("%H:%M:%S", time.localtime(clock())), why))
            last = why
        if clock() - start >= max_wait:
            return False, why
        sleep(poll)


def gated_run(counter, check, steps, sleep, clock, say, max_wait: float = GATE_MAX_S) -> int:
    """Counter left? -> wait for the gate (30 min) -> steps(guard); the exit code says which way it ended."""
    if counter.remaining() <= 0:
        say("no post left: %d of %d used in total; nothing posted" % (counter.total, counter.total_cap))
        return EXIT_COUNTER

    def guard(point):
        ok, why, _ = check(point)
        return None if ok else why

    ok, info = wait_for_gate(check, sleep, clock, say, max_wait)
    if not ok:
        say("not met at %s (%s); 0 posts" % (time.strftime("%H:%M", time.localtime(clock())), info))
        return EXIT_NOT_MET
    try:
        steps(guard)
    except StopRun as e:
        say("stopped inside the run: %s; posts so far %d (total %d of %d)" % (e, counter.used, counter.total, counter.total_cap))
        return EXIT_STOPPED
    return 0


def screen_to_client(point, rect):
    """Client coordinates of a screen point for a window whose rect is (left, top, right, bottom)."""
    return point[0] - rect[0], point[1] - rect[1]


@dataclass
class Block:
    x: int
    y: int
    w: int
    h: int
    pixels: int


def measure_block(plain, hover, region=None, base2=None, colour=HOVER_COLOUR):
    """Bounding box of the pixels that are `colour` in `hover` and differ from `plain`.

    Captures are (w, h, packed RGB). When `base2` (the second plain look) is given, only pixels equal in both
    plain looks count. `region` = (left, top, right, bottom) limits the search. None when nothing matches.
    """
    w, h, a = plain
    if hover[0] != w or hover[1] != h or (base2 is not None and (base2[0] != w or base2[1] != h)):
        raise ValueError("captures differ in size")
    b = hover[2]
    c = base2[2] if base2 is not None else None
    left, top, right, bottom = region if region else (0, 0, w, h)
    left, top, right, bottom = max(0, left), max(0, top), min(w, right), min(h, bottom)
    target = bytes(colour)
    xs, ys, n = [], [], 0
    for y in range(top, bottom):
        lo, hi = (y * w + left) * 3, (y * w + right) * 3
        if a[lo:hi] == b[lo:hi]:
            continue
        for x in range(left, right):
            i = (y * w + x) * 3
            if b[i:i + 3] == target and a[i:i + 3] != target and (c is None or c[i:i + 3] == a[i:i + 3]):
                xs.append(x)
                ys.append(y)
                n += 1
    if not n:
        return None
    return Block(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, n)


def row_s_diff(before: dict, after: dict) -> list:
    """Names of the row-S fields that differ, in the order of `before`."""
    return [k for k in before if before[k] != after.get(k)]


def find_template(capture, tmpl, region=None):
    """Top-left (x, y) of the first exact match of `tmpl` (w, h, rgb) inside `capture`, or None."""
    w, h, rgb = capture
    tw, th, trgb = tmpl
    left, top, right, bottom = region if region else (0, 0, w, h)
    left, top, right, bottom = max(0, left), max(0, top), min(w, right), min(h, bottom)
    first = trgb[:tw * 3]
    for y in range(top, bottom - th + 1):
        row = rgb[(y * w + left) * 3:(y * w + right) * 3]
        at = row.find(first)
        while at != -1:
            if at % 3 == 0:
                x = left + at // 3
                if all(rgb[((y + j) * w + x) * 3:((y + j) * w + x + tw) * 3] == trgb[j * tw * 3:(j + 1) * tw * 3]
                       for j in range(th)):
                    return x, y
            at = row.find(first, at + 1)
    return None


def classify_pointer(samples):
    """samples = [(x, y, last_input_tick)] -> (moved by us, moved by him).

    A position change between two samples while the system's last-input tick also changed (in that sample or the
    next one: the tick is read after the position) is his own input;
    a position change with an unchanged tick is ours (it must stay 0).
    """
    ours = his = 0
    for i in range(1, len(samples)):
        prev, cur = samples[i - 1], samples[i]
        if prev[:2] != cur[:2]:
            # the tick may be updated just after the position was read: look one sample ahead too
            ahead = samples[i + 1][2] if i + 1 < len(samples) else cur[2]
            if prev[2] != cur[2] or cur[2] != ahead:
                his += 1
            else:
                ours += 1
    return ours, his


class PointerSampler:
    """Samples the pointer position every `interval` seconds in a background thread."""

    def __init__(self, get_pos, get_input_tick, interval: float = 0.05):
        self.get_pos, self.get_input_tick, self.interval = get_pos, get_input_tick, interval
        self.samples = []
        self._stop = threading.Event()
        self._thread = None

    def sample_once(self) -> None:
        x, y = self.get_pos()
        self.samples.append((x, y, self.get_input_tick()))

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample_once()
            self._stop.wait(self.interval)

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.sample_once()

    def moved_by_us(self) -> int:
        return classify_pointer(self.samples)[0]

    def moved_by_him(self) -> int:
        return classify_pointer(self.samples)[1]


# ---------------------------------------------------------------- Win32, read only (not unit tested)

def _api():
    u, k, g = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.gdi32
    pane_look._dpi_aware()
    H, P = wintypes.HWND, ctypes.c_void_p
    u.GetWindowRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
    u.IsWindowVisible.argtypes = [H]
    u.IsIconic.argtypes = [H]
    u.GetClassNameW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowTextW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowTextLengthW.argtypes = [H]
    u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowDC.argtypes = [H]
    u.GetWindowDC.restype = wintypes.HDC
    u.ReleaseDC.argtypes = [H, wintypes.HDC]
    u.PrintWindow.argtypes = [H, wintypes.HDC, wintypes.UINT]
    u.PostMessageW.argtypes = [H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    u.WindowFromPoint.argtypes = [wintypes.POINT]
    u.WindowFromPoint.restype = wintypes.HWND
    u.GetAncestor.argtypes = [H, wintypes.UINT]
    u.GetAncestor.restype = wintypes.HWND
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.SelectObject.restype = wintypes.HGDIOBJ
    g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, P, P, wintypes.UINT]
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g.DeleteDC.argtypes = [wintypes.HDC]
    return u, k, g


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def cursor_pos():
    u, _, _ = _api()
    p = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def last_input_tick() -> int:
    u = ctypes.windll.user32
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    u.GetLastInputInfo(ctypes.byref(li))
    return li.dwTime


def _text(u, hwnd):
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(u, hwnd):
    buf = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _rect(u, hwnd):
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def _pid(u, hwnd) -> int:
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def process_info(pid: int):
    """(image path, start time as FILETIME int) of a process, read only; ('', 0) when it cannot be opened."""
    _, k, _ = _api()
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return "", 0
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        path = buf.value if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
        c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
        start = 0
        if k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
            start = (c.dwHighDateTime << 32) | c.dwLowDateTime
        return path, start
    finally:
        k.CloseHandle(h)


def _filetime_text(ft: int) -> str:
    if not ft:
        return "?"
    unix = ft / 1e7 - 11644473600
    return time.strftime("%H:%M:%S", time.localtime(unix))


def top_windows():
    """All top-level windows in z-order (top first): dicts hwnd, title, cls, pid, visible, iconic, rect."""
    u, _, _ = _api()
    out = []
    proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        out.append({"hwnd": int(hwnd or 0), "title": _text(u, hwnd), "cls": _class(u, hwnd), "pid": _pid(u, hwnd),
                    "visible": bool(u.IsWindowVisible(hwnd)), "iconic": bool(u.IsIconic(hwnd)),
                    "rect": _rect(u, hwnd)})
        return True

    u.EnumWindows(proc_t(cb), 0)
    return out


def child_windows(hwnd: int):
    """Every descendant window of hwnd (read only): dicts hwnd, cls, title, visible, rect."""
    u, _, _ = _api()
    out = []
    proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        out.append({"hwnd": int(h or 0), "cls": _class(u, h), "title": _text(u, h),
                    "visible": bool(u.IsWindowVisible(h)), "rect": _rect(u, h)})
        return True

    u.EnumChildWindows(hwnd, proc_t(cb), 0)
    return out


def find_app_window(windows):
    """His main window: the largest visible top-level Chrome_WidgetWin_1 window titled *Claude*."""
    c = [w for w in windows if w["visible"] and not w["iconic"] and w["cls"] == "Chrome_WidgetWin_1"
         and "Claude" in w["title"] and w["rect"][2] > w["rect"][0]]
    if not c:
        return None
    return max(c, key=lambda w: (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1]))


def app_processes(main_pid: int):
    """((pid, start FILETIME), ...) of every process running the same image as the main window's process."""
    path, _ = process_info(main_pid)
    if not path:
        return ()
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    found = []
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        name = os.path.basename(path).lower()
        while ok:
            if e.szExeFile.lower() == name:
                p, st = process_info(e.th32ProcessID)
                if p.lower() == path.lower():
                    found.append((e.th32ProcessID, st))
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return tuple(sorted(found))


def covering_windows(main, windows):
    """Windows above `main` in z-order that are visible, not minimised and overlap its rect: (title, cls, share)."""
    ml, mt, mr, mb = main["rect"]
    area = max(1, (mr - ml) * (mb - mt))
    out = []
    for w in windows:
        if w["hwnd"] == main["hwnd"]:
            break
        if not w["visible"] or w["iconic"]:
            continue
        l, t, r, b = w["rect"]
        iw, ih = min(mr, r) - max(ml, l), min(mb, b) - max(mt, t)
        if iw > 0 and ih > 0:
            out.append((w["title"], w["cls"], iw * ih / area))
    return out


def print_window_rgb(hwnd: int):
    """PrintWindow(hwnd, PW_RENDERFULLCONTENT) of the window itself, not the screen: (w, h, rgb, ok)."""
    u, _, g = _api()

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    l, t, r, b = _rect(u, hwnd)
    w, h = r - l, b - t
    wdc = u.GetWindowDC(hwnd)
    mdc = g.CreateCompatibleDC(wdc)
    bmp = g.CreateCompatibleBitmap(wdc, w, h)
    old = g.SelectObject(mdc, bmp)
    try:
        ok = bool(u.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT))
        bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0) != h:
            raise OSError("GetDIBits failed")
    finally:
        g.SelectObject(mdc, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(hwnd, wdc)
    bgra = buf.raw
    rgb = bytearray(w * h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    return w, h, bytes(rgb), ok


def client_origin(hwnd: int):
    """Screen position of the (0, 0) client point of hwnd (ClientToScreen, read only)."""
    u, _, _ = _api()
    u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    p = wintypes.POINT(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


def real_post(hwnd, msg, wparam, lparam) -> None:
    u, _, _ = _api()
    if not u.PostMessageW(hwnd, msg, wparam, lparam):
        raise OSError("PostMessageW failed (error %d)" % ctypes.GetLastError())


# ---------------------------------------------------------------- row S

def load_template(path):
    """(w, h, rgb) of a PNG cut from his window (Pillow, only to read this file)."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    return im.width, im.height, im.tobytes()


def human_ms(seconds: float) -> str:
    return "%.1f s" % seconds


def snapshot_row_s(look_png: Path):
    """One row S: processes, main window, foreground, one look of the screen (painted = LOOK_MIN_BYTES+)."""
    u, _, _ = _api()
    wins = top_windows()
    main = find_app_window(wins)
    fg = u.GetForegroundWindow()
    fg_title = _text(u, fg) if fg else ""
    w, h, rgb = pane_look.screen_rgb()
    colours = pane_look.distinct_colours(rgb)
    pane_look.write_png(look_png, w, h, rgb)
    size = look_png.stat().st_size
    return {
        "processes": app_processes(main["pid"]) if main else (),
        "window": (main["hwnd"], main["rect"], main["title"]) if main else None,
        "foreground": (int(fg or 0), fg_title),
        "painted": size >= LOOK_MIN_BYTES,
        "_look_bytes": size,
        "_look_colours": colours,
    }


def public(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ---------------------------------------------------------------- the run

def pick_render(children):
    for c in children:
        if c["cls"] == "Chrome_RenderWidgetHostHWND" and c["visible"]:
            return c
    return None


def region_around(point_in_capture, dx=40, dy=30):
    x, y = point_in_capture
    return (x - dx, y - dy, x + dx, y + dy)


def run_step(name, app_hwnd, app_rect, post_hwnd, post_rect, cap_hwnd, budget, scratch, tmpl, outside, save_dir=None,
             guard=None):
    """One step: row S before, capture, hover post, capture, outside post, capture, row S after."""
    sampler = PointerSampler(cursor_pos, last_input_tick)
    sampler.start()
    try:
        return _run_step(sampler, name, post_hwnd, cap_hwnd, budget, scratch, tmpl, outside, save_dir, guard)
    finally:
        sampler.stop()


def _run_step(sampler, name, post_hwnd, cap_hwnd, budget, scratch, tmpl, outside, save_dir, guard):
    before = snapshot_row_s(scratch / (name + "-look-before.png"))
    cap0 = print_window_rgb(cap_hwnd)
    cap_origin = _rect(_api()[0], cap_hwnd)[:2]
    at = find_template(cap0[:3], tmpl)
    if at is None:
        after = snapshot_row_s(scratch / (name + "-look-after.png"))
        sampler.stop()
        return {"name": name, "before": before, "after": after, "block": None, "skipped": "pager word not on screen",
                "caps_ok": (cap0[3],), "ours": sampler.moved_by_us(), "his": sampler.moved_by_him(),
                "samples": len(sampler.samples), "colours": (pane_look.distinct_colours(cap0[2]),) * 3,
                "diff": row_s_diff(public(before), public(after)), "pt_in_cap": None, "gone": None,
                "cap_size": cap0[:2], "point": None}
    pt = (at[0] + tmpl[0] // 2, at[1] + tmpl[1] // 2)
    point = (pt[0] + cap_origin[0], pt[1] + cap_origin[1])
    hx, hy = screen_to_client(point, client_origin(post_hwnd))
    post_move(budget, real_post, post_hwnd, hx, hy, guard=guard, point=point)
    time.sleep(REST)
    cap1 = print_window_rgb(cap_hwnd)
    ox, oy = outside
    post_move(budget, real_post, post_hwnd, ox, oy, guard=guard, point=point)
    time.sleep(REST)
    cap2 = print_window_rgb(cap_hwnd)
    after = snapshot_row_s(scratch / (name + "-look-after.png"))
    sampler.stop()
    c0, c1, c2 = cap0[:3], cap1[:3], cap2[:3]
    block = measure_block(c0, c1, region=region_around(pt), base2=c2) if c0[:2] == c1[:2] == c2[:2] else None
    gone = None
    if block:
        gone = measure_block(c2, c1, region=region_around(pt)) is not None  # still shows the block vs outside look
    if save_dir is not None:
        pane_look.write_png(save_dir / (name + "-before.png"), *c0)
        pane_look.write_png(save_dir / (name + "-hover.png"), *c1)
        pane_look.write_png(save_dir / (name + "-outside.png"), *c2)
    return {
        "name": name, "before": before, "after": after, "block": block, "caps_ok": (cap0[3], cap1[3], cap2[3]),
        "ours": sampler.moved_by_us(), "his": sampler.moved_by_him(), "samples": len(sampler.samples),
        "colours": tuple(pane_look.distinct_colours(c[:3][2]) for c in (cap0, cap1, cap2)),
        "diff": row_s_diff(public(before), public(after)), "pt_in_cap": pt, "gone": gone, "cap_size": c0[:2], "point": point,
    }


def cmd_list() -> int:
    wins = top_windows()
    main = find_app_window(wins)
    cands = [w for w in wins if "Claude" in w["title"]]
    print("windows with 'Claude' in the title:")
    for w in cands:
        path, _ = process_info(w["pid"])
        print("  hwnd=%d cls=%s pid=%d visible=%s iconic=%s rect=%s title=%r image=%s"
              % (w["hwnd"], w["cls"], w["pid"], w["visible"], w["iconic"], w["rect"], w["title"], path))
    if not main:
        print("no main window found")
        return 2
    print("main: hwnd=%d rect=%s title=%r" % (main["hwnd"], main["rect"], main["title"]))
    kids = child_windows(main["hwnd"])
    print("children of main (%d):" % len(kids))
    for c in kids:
        print("  hwnd=%d cls=%s visible=%s rect=%s title=%r" % (c["hwnd"], c["cls"], c["visible"], c["rect"], c["title"]))
    procs = app_processes(main["pid"])
    print("processes of the same image (%d): %s" % (len(procs), ", ".join("%d@%s" % (p, _filetime_text(s)) for p, s in procs)))
    cov = covering_windows(main, wins)
    print("windows above main in z-order overlapping it: %s" % ([(t, c, round(s, 2)) for t, c, s in cov] or "none"))
    return 0


def app_target():
    """Read only: his main window, its children, the render child (if any), and the window to capture."""
    wins = top_windows()
    main = find_app_window(wins)
    if not main:
        return None
    kids = child_windows(main["hwnd"])
    render = pick_render(kids)
    cap_hwnd = main["hwnd"]
    probe = print_window_rgb(cap_hwnd)
    if pane_look.distinct_colours(probe[2]) < 50 and render:
        cap_hwnd = render["hwnd"]
    return {"wins": wins, "main": main, "kids": kids, "render": render, "post": render or main, "cap_hwnd": cap_hwnd}


def find_point_now(tmpl):
    """Screen point of the "novee" template in a fresh capture of his window (PrintWindow, read only), or None."""
    t = app_target()
    if not t:
        return None
    u = _api()[0]
    cap = print_window_rgb(t["cap_hwnd"])
    at = find_template(cap[:3], tmpl)
    if at is None:
        return None
    ox, oy = _rect(u, t["cap_hwnd"])[:2]
    return at[0] + tmpl[0] // 2 + ox, at[1] + tmpl[1] // 2 + oy


def point_in_app(point) -> bool:
    """WindowFromPoint at the screen point: its top-level root is his Claude window (read only)."""
    u = _api()[0]
    main = find_app_window(top_windows())
    if not main:
        return False
    hit = u.WindowFromPoint(wintypes.POINT(int(point[0]), int(point[1])))
    return bool(hit) and int(u.GetAncestor(hit, 2) or 0) == int(u.GetAncestor(main["hwnd"], 2) or main["hwnd"])


def cmd_run(out: Path, repeats: int, outside_arg, counter_path=COUNTER_FILE) -> int:
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / "scratch"
    scratch.mkdir(exist_ok=True)
    counter = PostCounter(counter_path, MAX_POSTS)
    tmpl = load_template(TEMPLATE)
    results, state = [], {}

    def check(point=None):
        try:
            return gate_check(lambda: find_point_now(tmpl), point_in_app, idle_seconds, point)
        except OSError as e:
            return False, "read failed: %s" % e, None

    def steps(guard):
        t = app_target()
        if not t:
            raise StopRun("main window gone")
        main, post, kids = t["main"], t["post"], t["kids"]
        state.update(t)
        state["cov"] = covering_windows(main, t["wins"])
        print("main hwnd=%d cls=%s rect=%s; children: %s" % (main["hwnd"], main["cls"], main["rect"],
              "; ".join("%d/%s/%s" % (c["hwnd"], c["cls"], c["rect"]) for c in kids) or "none"), flush=True)
        print("post target: hwnd=%d cls=%s rect=%s; capture target hwnd=%d"
              % (post["hwnd"], post["cls"], post["rect"], t["cap_hwnd"]), flush=True)
        pr = post["rect"]
        outside = outside_arg or ((pr[2] - pr[0]) // 8, (pr[3] - pr[1]) // 2)
        for i in range(1, repeats + 1):
            r = run_step("run%d" % i, main["hwnd"], main["rect"], post["hwnd"], post["rect"], t["cap_hwnd"], counter,
                         scratch, tmpl, outside, save_dir=out if i == 1 else None, guard=guard)
            results.append(r)
            b = r["block"]
            print("run %d: block=%s ours=%d his=%d samples=%d rowS_diff=%s posts=%d (total %d of %d)"
                  % (i, "%dx%d@(%d,%d) px=%d" % (b.w, b.h, b.x, b.y, b.pixels) if b else "none", r["ours"], r["his"],
                     r["samples"], r["diff"] or "equal", counter.used, counter.total, counter.total_cap), flush=True)

    rc = gated_run(counter, check, steps, time.sleep, time.time, lambda m: print(m, flush=True))
    if state and rc in (0, EXIT_STOPPED):
        stopped = None if rc == 0 else "stopped inside the run after %d of %d steps" % (len(results), repeats)
        write_table(out, state["main"], state["post"], state["kids"], state["cov"], results, [], counter, stopped)
    return rc


def write_table(out, main, post, kids, cov, results, alt, budget, stopped=None):
    n = len(results)
    if not n:
        (out / "table.md").write_text("# #916 way A: stopped before the first step (%s); posts this run %d, total %d of %d\n"
                                    % (stopped, budget.used, budget.total, budget.total_cap), encoding="utf-8")
        print("stopped before the first step; posts %d" % budget.used)
        return
    blocks = [r["block"] for r in results]
    sizes = [(b.w, b.h, b.x, b.y, b.pixels) if b else None for b in blocks]
    equal = sum(1 for s in sizes if s == sizes[0])
    found = sum(1 for b in blocks if b)
    b0 = blocks[0]
    ours = sum(r["ours"] for r in results)
    his = sum(r["his"] for r in results)
    unchanged = sum(1 for r in results if not r["diff"])
    skipped = sum(1 for r in results if r.get("skipped"))
    big = [(t, c, round(s, 2)) for t, c, s in cov if s >= 0.05]
    if big:
        black = [pane_look is not None and r["colours"][0] < 50 for r in results]
        a3 = "covered by %s; capture %s" % (big[:3], "black" if all(black) else "painted (colours %s)" % (results[0]["colours"],))
    else:
        a3 = "not seen (his window is not covered by another window)"
    lines = ["# #916 way A: posted WM_MOUSEMOVE on his window (%s)" % time.strftime("%Y-%m-%d %H:%M"), "",
             "Main window hwnd=%d rect=%s title=%r. Post target hwnd=%d class=%s rect=%s. Posts this run: %d of %d; counter total: %d of %d.%s"
             % (main["hwnd"], main["rect"], main["title"], post["hwnd"], post["cls"], post["rect"], budget.used, budget.limit,
                budget.total, budget.total_cap, (" Run " + stopped + ".") if stopped else ""),
             "Children read (hwnd / class / visible / rect): "
             + "; ".join("%d / %s / %s / %s" % (c["hwnd"], c["cls"], c["visible"], c["rect"]) for c in kids), "",
             "| # | wanted | number |", "|---|---|---|",
             "| A1 | block #434347 near the word, H2 measured %dx%d through the pointer | %s (found in %d of %d runs) |"
             % (H2_BLOCK[0], H2_BLOCK[1], "%d x %d at (%d, %d), %d px" % (b0.w, b0.h, b0.x, b0.y, b0.pixels) if b0 else "no block under posted moves" + (" (%d runs skipped: pager word not on screen)" % skipped if skipped else ""), found, n),
             "| A2 | row S unchanged; pointer samples moved by us | steps with row S equal: %d of %d; moved by us: %d (moved by him: %d) |" % (unchanged, n, ours, his),
             "| A3 | PrintWindow painted with the window covered | %s |" % a3,
             "| A4 | %d runs in a row equal | %d of %d |" % (n, equal, n), "",
             "## Row S before / after every step", "",
             "| step | processes (pid@start) | window hwnd / rect / title | foreground | look bytes (colours) | painted | samples | ours | his | diff |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        for tag in ("before", "after"):
            s = r[tag]
            w = s["window"]
            lines.append("| %s %s | %s | %s | %s | %d (%d) | %s | %s | %s | %s | %s |" % (
                r["name"], tag, ", ".join("%d@%s" % (p, _filetime_text(t)) for p, t in s["processes"]),
                "%d / %s / %r" % w if w else "none", "%d %r" % s["foreground"], s["_look_bytes"], s["_look_colours"],
                s["painted"], r["samples"] if tag == "after" else "", r["ours"] if tag == "after" else "",
                r["his"] if tag == "after" else "", (r["diff"] or "equal") if tag == "after" else ""))
    lines += ["", "## Per run", "", "| run | capture size | capture colours (plain / hover / outside) | PrintWindow ok | block | block gone after outside move |", "|---|---|---|---|---|---|"]
    for r in results:
        b = r["block"]
        lines.append("| %s | %dx%d | %s | %s | %s | %s |" % (r["name"], r["cap_size"][0], r["cap_size"][1], r["colours"], r["caps_ok"],
                     "%dx%d at (%d,%d) %d px" % (b.w, b.h, b.x, b.y, b.pixels) if b else "none", "n/a" if b is None else "see run1 pictures"))
    if alt:
        lines += ["", "## Other windows tried once each", "", "| hwnd | class | block |", "|---|---|---|"]
        for h, c, blk in alt:
            lines.append("| %d | %s | %s |" % (h, c, "%dx%d at (%d,%d)" % (blk.w, blk.h, blk.x, blk.y) if blk else "none"))
    (out / "table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    rn = sub.add_parser("run")
    rn.add_argument("--out", required=True)
    rn.add_argument("--repeats", type=int, default=5)
    rn.add_argument("--outside", type=int, nargs=2, default=None, help="client point of the post target, off the pane")
    a = ap.parse_args(argv)
    if a.action == "list":
        return cmd_list()
    return cmd_run(Path(a.out), a.repeats, tuple(a.outside) if a.outside else None)


if __name__ == "__main__":
    sys.exit(main())
