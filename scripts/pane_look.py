"""Look at the primary screen and press one point inside the Claude window (#790).

  python scripts/pane_look.py look --out <png>
  python scripts/pane_look.py press <x> <y>
  python scripts/pane_look.py press <x> <y> --no-dwell --times N --gap-ms G --out <png>   (#837)
      move, rest 300 ms (0 with --no-dwell), click (button down 60 ms, up); --times N = 1..5 clicks at the same
      point, G ms apart (default 120; one action: one idle check, one put-back); --out = look 600 ms after the
      last click, before the pointer is put back; 6 or more clicks refused (exit 2)
  python scripts/pane_look.py hover <x> <y> --out <png>   (move, rest 600 ms, look, move back; no click)
  python scripts/pane_look.py hover-series <x,y> ... --out-dir <dir>   (<= 20 looks)
  python scripts/pane_look.py scroll <x> <y> <notches> [--out <png>]   (move, rest 300 ms, wheel <notches>
      notches one by one 40 ms apart (negative = down, content moves up; one notch = WHEEL_DELTA 120), rest
      600 ms, look if --out, move back; no click; 0 notches refused)

press / hover / hover-series / scroll refuse (exit 3) unless the owner had no input for 120 s (#915);
--wait-for-pause polls for it up to 10 minutes. The pointer is put back after every one.
Idle chain (#837): after a completed action var/pane_look_chain.json keeps the last-input tick read after the put-back;
the next action passes without the 120 s while that tick is unchanged and the record is under 10 minutes old.

ctypes + stdlib only; no console window is created, no child process is started.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import zlib
from pathlib import Path

PNG_SIGNATURE = bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A])


def check_point(rect, x, y) -> bool:
    """True when (x, y) lies inside rect = (left, top, right, bottom)."""
    left, top, right, bottom = rect
    return left <= x < right and top <= y < bottom


def distinct_colours(rgb: bytes) -> int:
    """Count distinct RGB triples in a packed 3-bytes-per-pixel buffer."""
    return len({rgb[i:i + 3] for i in range(0, len(rgb) - len(rgb) % 3, 3)})


def write_png(path, width: int, height: int, rgb: bytes) -> None:
    """Write a packed RGB buffer (width*height*3 bytes) as an 8-bit RGB PNG."""
    if len(rgb) != width * height * 3:
        raise ValueError("buffer size does not match width x height")
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[r * stride:(r + 1) * stride] for r in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (PNG_SIGNATURE
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def _dpi_aware() -> None:
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def claude_window_rect():
    """Rect (l, t, r, b) of the largest visible top-level window titled *Claude*, or None."""
    import ctypes
    from ctypes import wintypes
    _dpi_aware()
    user32 = ctypes.windll.user32
    found = []
    proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if "Claude" in buf.value:
                    r = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(r))
                    found.append((r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumWindows(proc_t(cb), 0)
    found = [r for r in found if r[2] > r[0] and r[3] > r[1]]
    if not found:
        return None
    return max(found, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))


def screen_rgb():
    """Capture the primary screen with GDI; returns (width, height, packed RGB bytes)."""
    import ctypes
    from ctypes import wintypes
    _dpi_aware()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]

    sdc = user32.GetDC(None)
    if not sdc:
        raise OSError("GetDC(NULL) failed")
    mdc = gdi32.CreateCompatibleDC(sdc)
    bmp = gdi32.CreateCompatibleBitmap(sdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        if not gdi32.BitBlt(mdc, 0, 0, w, h, sdc, 0, 0, 0x00CC0020 | 0x40000000):  # SRCCOPY | CAPTUREBLT
            raise OSError("BitBlt failed (error %d)" % ctypes.GetLastError())
        bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0) != h:
            raise OSError("GetDIBits failed")
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, sdc)
    bgra = buf.raw
    rgb = bytearray(w * h * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    return w, h, bytes(rgb)


PRESS_SETTLE_S = 0.3   # pointer rests on the target before the button goes down
PRESS_HOLD_S = 0.06    # button held down
PRESS_GAP_MS = 120     # default gap between two clicks of one --times action
PRESS_TIMES_MAX = 5    # at most this many clicks in one action
PRESS_LOOK_REST_S = 0.6  # after the last click, before the --out look (pointer still on the point)
IDLE_NEED_S = 120      # the owner must have had no input for this long; nothing lowers it (#915)
CHAIN_MAX_AGE_S = 600  # the idle chain record counts only while younger than this (#837)
CHAIN_SLACK_MS = 50    # the tick may be this far after the recorded one and still count as unchanged (#837)
CHAIN_PATH = Path(__file__).resolve().parents[1] / "var" / "pane_look_chain.json"
WAIT_MAX_S = 600       # --wait-for-pause: at most 10 minutes per look
WAIT_POLL_S = 5
SERIES_MAX = 20
POINTER_TOLERANCE_PX = 3


def idle_from_ticks(tick: int, last: int) -> float:
    """Seconds between two 32-bit millisecond tick counts (survives the 49-day wrap)."""
    return ((tick - last) & 0xFFFFFFFF) / 1000.0


def last_input_tick() -> int:
    """The system's last keyboard or mouse input tick (GetLastInputInfo dwTime, milliseconds, 32 bit)."""
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError("GetLastInputInfo failed")
    return info.dwTime


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input of the user (GetLastInputInfo)."""
    import ctypes
    last = last_input_tick()
    ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint32
    return idle_from_ticks(ctypes.windll.kernel32.GetTickCount(), last)


def read_chain():
    """The idle chain record {own_last_input_tick, chain_started_idle, recorded_at}; None when missing or corrupt."""
    try:
        with open(CHAIN_PATH, encoding="utf-8") as f:
            rec = json.load(f)
        tick, started, at = rec["own_last_input_tick"], rec["chain_started_idle"], rec["recorded_at"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if type(tick) is not int or not 0 <= tick <= 0xFFFFFFFF or started is not True or type(at) not in (int, float):
        return None
    return rec


def chain_passes() -> bool:
    """True when the idle chain holds: the record is under 10 minutes old and nothing but the tool's own
    event has moved the last-input tick since it was written (#837)."""
    rec = read_chain()
    if rec is None:
        return False
    age = time.time() - rec["recorded_at"]
    if not 0 <= age < CHAIN_MAX_AGE_S:
        return False
    ms_since = (last_input_tick() - rec["own_last_input_tick"]) & 0xFFFFFFFF
    return ms_since <= CHAIN_SLACK_MS


def forget_chain() -> None:
    try:
        os.remove(CHAIN_PATH)
    except OSError:
        pass


def record_chain() -> None:
    """Called after a completed action, after the pointer put-back: keep the last-input tick read now (#837).
    A write or read failure removes the record, so the next action falls back to the plain 120 s rule."""
    try:
        rec = {"own_last_input_tick": last_input_tick(), "chain_started_idle": True, "recorded_at": time.time()}
        CHAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CHAIN_PATH.with_name(CHAIN_PATH.name + ".tmp")
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        os.replace(tmp, CHAIN_PATH)
    except OSError:
        forget_chain()


def idle_gate(idle_fn, say):
    """None when the owner has been idle long enough or the idle chain holds, else the exit code 3 (after saying so)."""
    n = idle_fn()
    if n < IDLE_NEED_S and not chain_passes():
        say("owner active: last input %d s ago, need %d s; nothing moved" % (n, IDLE_NEED_S))
        return 3
    return None


def wait_for_pause(idle_fn=None, sleep=time.sleep, say=print) -> bool:
    """Poll the idle seam every 5 s up to 10 minutes; True when a pause of IDLE_NEED_S or the idle chain shows."""
    idle_fn = idle_fn or idle_seconds
    waited = 0
    while True:
        if idle_fn() >= IDLE_NEED_S or chain_passes():
            return True
        if waited >= WAIT_MAX_S:
            say("no pause")
            return False
        sleep(WAIT_POLL_S)
        waited += WAIT_POLL_S


def mouse_move(x: int, y: int) -> None:
    import ctypes
    _dpi_aware()
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def mouse_button(down: bool) -> None:
    import ctypes
    _dpi_aware()
    ctypes.windll.user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)  # LEFTDOWN / LEFTUP


def do_look(out, capture=screen_rgb, say=print) -> int:
    t0 = time.monotonic()
    w, h, rgb = capture()
    n = distinct_colours(rgb)
    write_png(out, w, h, rgb)
    say("size=%dx%d distinct_colours=%d seconds=%.2f" % (w, h, n, time.monotonic() - t0))
    return 0


def do_press(x, y, rect_fn=claude_window_rect, get_pos=None, move=mouse_move, button=mouse_button,
             sleep=time.sleep, say=print, idle_seconds=idle_seconds, no_dwell=False, times=1,
             gap_ms=PRESS_GAP_MS, out=None, capture=screen_rgb) -> int:
    """One action: `times` clicks at (x, y), gap_ms apart; no_dwell drops the rest before the first button down;
    out takes a look PRESS_LOOK_REST_S after the last click, before the put-back (#837)."""
    if not 1 <= times <= PRESS_TIMES_MAX:
        say("refused: %d clicks, at most %d" % (times, PRESS_TIMES_MAX))
        return 2
    if gap_ms < 0:
        say("refused: gap %d ms" % gap_ms)
        return 2
    code = idle_gate(idle_seconds, say)
    if code:
        return code
    rect = rect_fn()
    if rect is None:
        say("refused: no Claude window")
        return 2
    if not check_point(rect, x, y):
        say("refused: point (%d, %d) outside the Claude window rect (%d, %d, %d, %d)" % ((x, y) + tuple(rect)))
        return 2
    back = (get_pos or mouse_pos)()
    try:
        move(x, y)
        sleep(0 if no_dwell else PRESS_SETTLE_S)
        for i in range(times):
            if i:
                sleep(gap_ms / 1000.0)
            button(True)
            sleep(PRESS_HOLD_S)
            button(False)
        if out is not None:
            sleep(PRESS_LOOK_REST_S)
            do_look(out, capture=capture, say=say)
    finally:
        move(*back)
    record_chain()
    count = " x%d" % times if times > 1 else ""
    say("pressed (%d, %d)%s, pointer moved back to (%d, %d)" % ((x, y, count) + tuple(back)))
    return 0


HOVER_REST_S = 0.6   # pointer rests on the target, no button event, before the look


def mouse_pos():
    import ctypes
    from ctypes import wintypes
    _dpi_aware()
    pt = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        raise OSError("GetCursorPos failed")
    return pt.x, pt.y


def _check_target(rect_fn, x, y, say):
    rect = rect_fn()
    if rect is None:
        say("refused: no Claude window")
        return 2
    if not check_point(rect, x, y):
        say("refused: point (%d, %d) outside the Claude window rect (%d, %d, %d, %d)" % ((x, y) + tuple(rect)))
        return 2
    return None


def do_hover(x, y, out, rect_fn=claude_window_rect, get_pos=mouse_pos, move=mouse_move,
             capture=screen_rgb, sleep=time.sleep, say=print, idle_seconds=idle_seconds) -> int:
    code = idle_gate(idle_seconds, say)
    if code:
        return code
    code = _check_target(rect_fn, x, y, say)
    if code:
        return code
    back = get_pos()
    move(x, y)
    try:
        sleep(HOVER_REST_S)
        do_look(out, capture=capture, say=say)
    finally:
        move(*back)
    record_chain()
    say("hovered (%d, %d), pointer moved back to (%d, %d)" % ((x, y) + tuple(back)))
    return 0


def _near(a, b) -> bool:
    return abs(a[0] - b[0]) <= POINTER_TOLERANCE_PX and abs(a[1] - b[1]) <= POINTER_TOLERANCE_PX


def do_hover_series(points, out_template, rect_fn=claude_window_rect, get_pos=mouse_pos, move=mouse_move,
                    capture=screen_rgb, sleep=time.sleep, say=print, idle_seconds=idle_seconds) -> int:
    """Hover looks at several points (<= 20). Idle is read once; after each own move the pointer must be
    where it was left, else the owner is back and the series stops (exit 3). out_template has {k} (1-based)."""
    n = len(points)
    if n > SERIES_MAX:
        say("refused: %d points, at most %d" % (n, SERIES_MAX))
        return 2
    code = idle_gate(idle_seconds, say)
    if code:
        return code
    for x, y in points:
        code = _check_target(rect_fn, x, y, say)
        if code:
            return code
    back = get_pos()
    for k, (x, y) in enumerate(points, 1):
        move(x, y)
        if not _near(get_pos(), (x, y)):
            move(*back)
            say("owner back: series stopped after %d of %d" % (k - 1, n))
            return 3
        try:
            sleep(HOVER_REST_S)
            do_look(out_template.format(k=k), capture=capture, say=say)
        finally:
            move(*back)
        if not _near(get_pos(), back):
            say("owner back: series stopped after %d of %d" % (k, n))
            return 3
    record_chain()
    return 0


SCROLL_SETTLE_S = 0.3       # pointer rests on the point before the first notch
SCROLL_NOTCH_GAP_S = 0.04   # between two notches
SCROLL_REST_S = 0.6         # after the last notch, before the look
WHEEL_DELTA = 120           # one wheel notch


def mouse_wheel(delta: int) -> None:
    import ctypes
    from ctypes import wintypes
    _dpi_aware()
    ctypes.windll.user32.mouse_event(0x0800, 0, 0, wintypes.DWORD(delta & 0xFFFFFFFF), 0)  # MOUSEEVENTF_WHEEL


def do_scroll(x, y, notches, out=None, rect_fn=claude_window_rect, get_pos=mouse_pos, move=mouse_move,
              wheel=mouse_wheel, capture=screen_rgb, sleep=time.sleep, say=print, idle_seconds=idle_seconds) -> int:
    """Wheel <notches> notches at (x, y): negative = down. Look when out is given; pointer put back (#837)."""
    if notches == 0:
        say("refused: 0 notches")
        return 2
    code = idle_gate(idle_seconds, say)
    if code:
        return code
    code = _check_target(rect_fn, x, y, say)
    if code:
        return code
    back = get_pos()
    step = WHEEL_DELTA if notches > 0 else -WHEEL_DELTA
    move(x, y)
    try:
        sleep(SCROLL_SETTLE_S)
        for i in range(abs(notches)):
            if i:
                sleep(SCROLL_NOTCH_GAP_S)
            wheel(step)
        sleep(SCROLL_REST_S)
        if out is not None:
            do_look(out, capture=capture, say=say)
    finally:
        move(*back)
    record_chain()
    say("scrolled %d notches at (%d, %d), pointer moved back to (%d, %d)" % ((notches, x, y) + tuple(back)))
    return 0


def _gated(fn, wait, *args, **kw):
    if wait and not wait_for_pause():
        return 3
    return fn(*args, **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    lk = sub.add_parser("look")
    lk.add_argument("--out", required=True)
    pr = sub.add_parser("press")
    pr.add_argument("x", type=int)
    pr.add_argument("y", type=int)
    pr.add_argument("--no-dwell", action="store_true", help="no rest between the move and the button down")
    pr.add_argument("--dwell-ms", type=int, default=None, help="#972: the rest between the move and the button down, ms (a human's ~80; default 300; 0 = --no-dwell)")
    pr.add_argument("--times", type=int, default=1, help="clicks in a row at the point, 1..5 (default 1)")
    pr.add_argument("--gap-ms", type=int, default=PRESS_GAP_MS, help="gap between two clicks (default 120)")
    pr.add_argument("--out", default=None, help="look 600 ms after the last click (png); none = no look")
    hv = sub.add_parser("hover")
    hv.add_argument("x", type=int)
    hv.add_argument("y", type=int)
    hv.add_argument("--out", required=True)
    hs = sub.add_parser("hover-series")
    hs.add_argument("points", nargs="+", help="x,y pairs (at most 20)")
    hs.add_argument("--out-dir", required=True)
    sc = sub.add_parser("scroll")
    sc.add_argument("x", type=int)
    sc.add_argument("y", type=int)
    sc.add_argument("notches", type=int, help="negative = down; one notch = WHEEL_DELTA 120; 0 refused")
    sc.add_argument("--out", default=None, help="look after the wheel (png); none = no look")
    for sp in (pr, hv, hs, sc):
        sp.add_argument("--wait-for-pause", action="store_true",
                        help="poll for 120 s idle or the idle chain (#837), up to 10 min")
    a = ap.parse_args(argv)
    try:
        if a.action == "look":
            return do_look(a.out)
        if a.action == "hover":
            return _gated(do_hover, a.wait_for_pause, a.x, a.y, a.out)
        if a.action == "hover-series":
            import os
            pts = [tuple(int(v) for v in p.split(",")) for p in a.points]
            os.makedirs(a.out_dir, exist_ok=True)
            return _gated(do_hover_series, a.wait_for_pause, pts, os.path.join(a.out_dir, "hover_{k}.png"))
        if a.action == "scroll":
            return _gated(do_scroll, a.wait_for_pause, a.x, a.y, a.notches, out=a.out)
        if a.dwell_ms is not None:  # #972: a human-like rest (~80 ms) between the move and the click; 0 = no rest
            global PRESS_SETTLE_S
            PRESS_SETTLE_S = a.dwell_ms / 1000.0
        return _gated(do_press, a.wait_for_pause, a.x, a.y, no_dwell=a.no_dwell or a.dwell_ms == 0, times=a.times,
                      gap_ms=a.gap_ms, out=a.out)
    except OSError as e:
        print("error: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
