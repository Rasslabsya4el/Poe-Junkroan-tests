import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pane_look as pl  # noqa: E402

RECT = (100, 100, 500, 400)
IDLE = lambda: 999  # noqa: E731  owner away (#915)


@pytest.fixture(autouse=True)
def chain_env(tmp_path, monkeypatch):
    """No test writes the real var/ folder or reads the real last-input tick (#837)."""
    tick = [1_000_000]
    monkeypatch.setattr(pl, "CHAIN_PATH", tmp_path / "var" / "pane_look_chain.json")
    monkeypatch.setattr(pl, "last_input_tick", lambda: tick[0])
    return tick


def test_outside_refused_zero_presses():
    calls, out = [], []
    code = pl.do_press(600, 200, rect_fn=lambda: RECT, move=lambda x, y: calls.append((x, y)),
                       button=calls.append, sleep=lambda s: None, say=out.append, idle_seconds=IDLE, get_pos=lambda: (0, 0))
    assert code == 2 and calls == []
    assert out[0] == "refused: point (600, 200) outside the Claude window rect (100, 100, 500, 400)"


def test_inside_pressed_once():
    calls = []
    downs = []
    code = pl.do_press(150, 120, rect_fn=lambda: RECT, move=lambda x, y: calls.append((x, y)),
                       button=downs.append, sleep=lambda s: None, say=lambda s: None,
                       idle_seconds=IDLE, get_pos=lambda: (0, 0))
    assert code == 0 and calls[0] == (150, 120) and downs == [True, False]


def test_press_call_order():
    log = []
    code = pl.do_press(150, 120, rect_fn=lambda: RECT, say=lambda s: None, idle_seconds=IDLE, get_pos=lambda: (7, 9),
                       move=lambda x, y: log.append(("move", x, y)),
                       button=lambda down: log.append(("down" if down else "up",)),
                       sleep=lambda s: log.append(("sleep", s)))
    assert code == 0
    kinds = [e[0] for e in log]
    assert kinds == ["move", "sleep", "down", "sleep", "up", "move"]
    assert log[0] == ("move", 150, 120) and log[1][1] >= 0.3 and log[3][1] >= 0.05
    assert log[5] == ("move", 7, 9)


def test_refused_no_move_away():
    log = []
    code = pl.do_press(900, 900, rect_fn=lambda: RECT, say=lambda s: None,
                       move=lambda x, y: log.append("move"), button=lambda d: log.append("b"),
                       sleep=lambda s: log.append("s"), idle_seconds=IDLE)
    assert code == 2 and log == []


def test_no_window_refused():
    calls, out = [], []
    code = pl.do_press(1, 1, rect_fn=lambda: None, move=lambda x, y: calls.append(1), say=out.append, idle_seconds=IDLE)
    assert code == 2 and calls == [] and out == ["refused: no Claude window"]


def test_hover_call_order(tmp_path):
    log = []
    out = tmp_path / "h.png"

    def cap():
        log.append(("capture",))
        return 2, 1, bytes(6)

    code = pl.do_hover(150, 120, out, rect_fn=lambda: RECT, say=lambda s: None, capture=cap,
                       get_pos=lambda: (7, 9), move=lambda x, y: log.append(("move", x, y)),
                       sleep=lambda s: log.append(("sleep", s)), idle_seconds=IDLE)
    assert code == 0 and out.exists()
    assert [e[0] for e in log] == ["move", "sleep", "capture", "move"]
    assert log[0] == ("move", 150, 120) and log[1][1] >= 0.6 and log[3] == ("move", 7, 9)


def test_hover_no_button_events(tmp_path):
    seen = []
    pl.do_hover(150, 120, tmp_path / "h.png", rect_fn=lambda: RECT, say=lambda s: None,
                capture=lambda: (1, 1, bytes(3)), get_pos=lambda: (0, 0),
                move=lambda x, y: seen.append("move"), sleep=lambda s: None, idle_seconds=IDLE)
    assert seen == ["move", "move"]  # no button callable exists in the signature
    import inspect
    assert "button" not in inspect.signature(pl.do_hover).parameters


def test_hover_outside_refused_no_move(tmp_path):
    log = []
    code = pl.do_hover(900, 900, tmp_path / "h.png", rect_fn=lambda: RECT, say=lambda s: None,
                       capture=lambda: log.append("cap"), get_pos=lambda: log.append("pos") or (0, 0),
                       move=lambda x, y: log.append("move"), sleep=lambda s: log.append("s"), idle_seconds=IDLE)
    assert code == 2 and log == []


def test_check_point_edges():
    assert pl.check_point(RECT, 100, 100)
    assert not pl.check_point(RECT, 500, 399)
    assert not pl.check_point(RECT, 99, 100)


def test_distinct_colours():
    buf = bytes([1, 2, 3, 1, 2, 3, 9, 9, 9, 0, 0, 0])
    assert pl.distinct_colours(buf) == 3


def test_png_roundtrip(tmp_path):
    buf = bytes(range(12))  # 2x2 RGB
    p = tmp_path / "t.png"
    pl.write_png(p, 2, 2, buf)
    data = p.read_bytes()
    assert data[:8] == pl.PNG_SIGNATURE
    assert struct.unpack(">II", data[16:24]) == (2, 2)


def test_look_with_fake_capture(tmp_path):
    out = []
    code = pl.do_look(tmp_path / "x.png", capture=lambda: (2, 1, bytes([1, 2, 3, 4, 5, 6])), say=out.append)
    assert code == 0 and out[0].startswith("size=2x1 distinct_colours=2 seconds=")


def test_scroll_down_sign_count_and_point():
    log = []
    code = pl.do_scroll(150, 120, -3, rect_fn=lambda: RECT, get_pos=lambda: (7, 9), say=lambda s: None,
                        move=lambda x, y: log.append(("move", x, y)),
                        wheel=lambda d: log.append(("wheel", d)),
                        sleep=lambda s: log.append(("sleep", s)), idle_seconds=IDLE)
    assert code == 0
    assert [e for e in log if e[0] == "wheel"] == [("wheel", -120)] * 3  # abs(notches) events, down
    assert [e[0] for e in log] == ["move", "sleep", "wheel", "sleep", "wheel", "sleep", "wheel", "sleep", "move"]
    assert log[0] == ("move", 150, 120)  # the wheel goes to the point
    assert log[1][1] == pl.SCROLL_SETTLE_S and log[3][1] == pl.SCROLL_NOTCH_GAP_S and log[7][1] == pl.SCROLL_REST_S
    assert log[-1] == ("move", 7, 9)     # the pointer is put back


def test_scroll_up_sign():
    wheels = []
    code = pl.do_scroll(150, 120, 2, rect_fn=lambda: RECT, get_pos=lambda: (7, 9), say=lambda s: None,
                        move=lambda x, y: None, wheel=wheels.append, sleep=lambda s: None, idle_seconds=IDLE)
    assert code == 0 and wheels == [120, 120]


def test_scroll_outside_refused_no_move():
    log, out = [], []
    code = pl.do_scroll(900, 900, -2, rect_fn=lambda: RECT, say=out.append,
                        move=lambda x, y: log.append("move"), wheel=lambda d: log.append("wheel"),
                        sleep=lambda s: log.append("sleep"), idle_seconds=IDLE)
    assert code == 2 and log == []
    assert out[0] == "refused: point (900, 900) outside the Claude window rect (100, 100, 500, 400)"


def test_scroll_zero_notches_refused():
    log, out = [], []
    code = pl.do_scroll(150, 120, 0, rect_fn=lambda: RECT, say=out.append,
                        move=lambda x, y: log.append("move"), wheel=lambda d: log.append("wheel"),
                        sleep=lambda s: log.append("sleep"), idle_seconds=IDLE)
    assert code == 2 and log == [] and out == ["refused: 0 notches"]


def test_scroll_look_only_with_out(tmp_path):
    looks = []

    def cap():
        looks.append(1)
        return 2, 1, bytes(6)

    kw = dict(rect_fn=lambda: RECT, get_pos=lambda: (0, 0), move=lambda x, y: None, wheel=lambda d: None,
              sleep=lambda s: None, say=lambda s: None, idle_seconds=IDLE, capture=cap)
    assert pl.do_scroll(150, 120, -1, **kw) == 0 and looks == []
    out = tmp_path / "s.png"
    assert pl.do_scroll(150, 120, -1, out=out, **kw) == 0 and looks == [1] and out.exists()


def test_scroll_cli_passes_negative_notches(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(pl, "do_scroll", lambda *a, **kw: seen.append((a, kw)) or 0)
    png = str(tmp_path / "s.png")
    assert pl.main(["scroll", "150", "120", "-3", "--out", png]) == 0
    assert seen == [((150, 120, -3), {"out": png})]


# --- press: --no-dwell, --times N / --gap-ms G, --out (#837); no real pointer call, fake clock/pointer only ---

def _press(log, **kw):
    """do_press with a recording pointer, a recording sleep and a fixed owner-away idle; returns (code, out)."""
    out = []
    args = dict(rect_fn=lambda: RECT, get_pos=lambda: (7, 9), move=lambda x, y: log.append(("move", x, y)),
                button=lambda d: log.append(("down" if d else "up",)),
                sleep=lambda s: log.append(("sleep", s)), say=out.append, idle_seconds=IDLE)
    args.update(kw)
    return pl.do_press(150, 120, **args), out


def test_press_default_sequence_byte_equal():
    log = []
    code, _ = _press(log)
    assert code == 0
    assert log == [("move", 150, 120), ("sleep", 0.3), ("down",), ("sleep", 0.06), ("up",), ("move", 7, 9)]


def test_press_no_dwell_sleep_between_move_and_down_is_zero():
    log = []
    code, _ = _press(log, no_dwell=True)
    assert code == 0
    assert log == [("move", 150, 120), ("sleep", 0), ("down",), ("sleep", 0.06), ("up",), ("move", 7, 9)]


def test_press_times_3_gap_120_three_pairs_two_gaps():
    log = []
    code, _ = _press(log, times=3, gap_ms=120)
    assert code == 0
    assert [e for e in log if e[0] == "down"] == [("down",)] * 3
    assert [e for e in log if e[0] == "up"] == [("up",)] * 3
    assert [e[1] for e in log if e[0] == "sleep"] == [0.3, 0.06, 0.12, 0.06, 0.12, 0.06]
    assert [e[0] for e in log] == ["move", "sleep", "down", "sleep", "up", "sleep", "down", "sleep", "up",
                                   "sleep", "down", "sleep", "up", "move"]
    assert log[-1] == ("move", 7, 9)


def test_press_times_default_gap_is_120_ms():
    log = []
    _press(log, times=2)
    assert [e[1] for e in log if e[0] == "sleep"] == [0.3, 0.06, 0.12, 0.06]


def test_press_times_idle_read_once_put_back_once():
    log, idle_reads = [], []
    code, _ = _press(log, times=4, idle_seconds=lambda: idle_reads.append(1) or 300)
    assert code == 0 and idle_reads == [1]
    assert [e for e in log if e[0] == "move"] == [("move", 150, 120), ("move", 7, 9)]


@pytest.mark.parametrize("times", [0, 6, 9])
def test_press_times_out_of_range_refused_no_pointer(times):
    log = []
    code, out = _press(log, times=times)
    assert code == 2 and log == []
    assert out == ["refused: %d clicks, at most 5" % times]


def test_press_times_5_allowed():
    log = []
    code, _ = _press(log, times=5)
    assert code == 0 and [e for e in log if e[0] == "down"] == [("down",)] * 5


def test_press_negative_gap_refused_no_pointer():
    log = []
    code, out = _press(log, times=2, gap_ms=-1)
    assert code == 2 and log == [] and out == ["refused: gap -1 ms"]


def test_press_out_look_600_ms_after_last_click_before_put_back(tmp_path):
    log = []

    def cap():
        log.append(("capture",))
        return 2, 1, bytes(6)

    out_png = tmp_path / "p.png"
    code, _ = _press(log, times=2, out=out_png, capture=cap)
    assert code == 0 and out_png.exists()
    assert log[-3] == ("sleep", 0.6) and log[-2] == ("capture",) and log[-1] == ("move", 7, 9)
    assert log[-4] == ("up",)


def test_press_without_out_takes_no_look(tmp_path):
    log, looks = [], []
    code, _ = _press(log, capture=lambda: looks.append(1) or (1, 1, bytes(3)))
    assert code == 0 and looks == [] and ("sleep", 0.6) not in log


def test_press_cli_passes_new_flags(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(pl, "do_press", lambda *a, **kw: seen.append((a, kw)) or 0)
    png = str(tmp_path / "p.png")
    assert pl.main(["press", "150", "120", "--no-dwell", "--times", "3", "--gap-ms", "80", "--out", png]) == 0
    assert seen == [((150, 120), {"no_dwell": True, "times": 3, "gap_ms": 80, "out": png})]


def test_press_cli_defaults_are_one_plain_click(monkeypatch):
    seen = []
    monkeypatch.setattr(pl, "do_press", lambda *a, **kw: seen.append((a, kw)) or 0)
    assert pl.main(["press", "150", "120"]) == 0
    assert seen == [((150, 120), {"no_dwell": False, "times": 1, "gap_ms": 120, "out": None})]
