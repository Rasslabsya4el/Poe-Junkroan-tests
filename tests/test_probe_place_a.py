"""#916 unit 1: the pure parts of scripts/probe_place_a.py, through seams (no Win32)."""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import probe_place_a as pa  # noqa: E402

COLOUR = (0x43, 0x43, 0x47)


def _capture(w, h, fill=(0x20, 0x20, 0x20), rects=()):
    """A synthetic (w, h, rgb) capture with filled rects [(x, y, rw, rh, colour)]."""
    px = [fill] * (w * h)
    for x, y, rw, rh, col in rects:
        for yy in range(y, y + rh):
            for xx in range(x, x + rw):
                px[yy * w + xx] = col
    return w, h, b"".join(bytes(p) for p in px)


def test_block_8_by_19_found():
    plain = _capture(60, 50)
    hover = _capture(60, 50, rects=[(20, 10, 8, 19, COLOUR)])
    b = pa.measure_block(plain, hover)
    assert b is not None
    assert (b.x, b.y, b.w, b.h) == (20, 10, 8, 19)


def test_block_zero_when_captures_equal():
    plain = _capture(60, 50)
    assert pa.measure_block(plain, _capture(60, 50)) is None


def test_block_ignores_pixels_changed_in_both_plains_and_other_colours():
    plain = _capture(60, 50, rects=[(2, 2, 5, 5, COLOUR)])  # a #434347 patch already in the plain look
    hover = _capture(60, 50, rects=[(2, 2, 5, 5, COLOUR), (30, 20, 8, 19, (1, 2, 3))])
    assert pa.measure_block(plain, hover) is None


def test_block_region_limits_the_search():
    plain = _capture(80, 50)
    hover = _capture(80, 50, rects=[(60, 10, 8, 19, COLOUR)])
    assert pa.measure_block(plain, hover, region=(0, 0, 40, 50)) is None
    assert pa.measure_block(plain, hover, region=(50, 0, 80, 50)).w == 8


def test_block_size_mismatch_raises():
    with pytest.raises(ValueError):
        pa.measure_block(_capture(10, 10), _capture(11, 10))


def test_row_s_diff_names_changed_fields():
    a = {"processes": ((10, 111), (11, 112)), "window": (5, (0, 0, 9, 9), "Claude"),
         "foreground": (5, "Claude"), "moved_by_us": 0, "painted": True}
    assert pa.row_s_diff(a, dict(a)) == []
    b = dict(a, window=(5, (0, 0, 10, 9), "Claude"), moved_by_us=2)
    assert pa.row_s_diff(a, b) == ["window", "moved_by_us"]


def test_pointer_classification_ours_vs_his():
    # (x, y, last-input tick): a move with an unchanged input tick is ours; with a new tick it is his
    samples = [(5, 5, 100), (5, 5, 100), (9, 5, 100), (9, 5, 100), (12, 7, 160), (12, 7, 160)]
    assert pa.classify_pointer(samples) == (1, 1)
    assert pa.classify_pointer([(1, 1, 5)] * 4) == (0, 0)


def test_sampler_collects_with_injected_clock():
    pos = iter([(1, 1), (1, 1), (2, 2), (2, 2), (2, 2), (2, 2)])
    s = pa.PointerSampler(get_pos=lambda: next(pos), get_input_tick=lambda: 7, interval=0.0)
    s.sample_once()
    s.sample_once()
    s.sample_once()
    assert s.samples == [(1, 1, 7), (1, 1, 7), (2, 2, 7)]
    assert s.moved_by_us() == 1


def test_post_cap_raises_on_the_21st():
    sent = []
    budget = pa.PostBudget(20)
    for i in range(20):
        pa.post_move(budget, lambda h, m, w, l: sent.append((h, m, w, l)), 77, i, i)
    assert len(sent) == 20 and budget.used == 20
    with pytest.raises(pa.PostCapExceeded):
        pa.post_move(budget, lambda h, m, w, l: sent.append(1), 77, 0, 0)
    assert len(sent) == 20


def test_post_move_posts_only_wm_mousemove_with_client_lparam():
    sent = []
    pa.post_move(pa.PostBudget(5), lambda h, m, w, l: sent.append((h, m, w, l)), 9, 300, 200)
    assert sent == [(9, 0x0200, 0, (200 << 16) | 300)]
    sent.clear()
    pa.post_move(pa.PostBudget(5), lambda h, m, w, l: sent.append((h, m, w, l)), 9, -1, -1)
    assert sent[0][3] == 0xFFFFFFFF  # both words 0xFFFF: the client point (-1, -1)


def test_screen_to_client_from_the_window_rect():
    assert pa.screen_to_client((2399, 914), (1590, 40, 2560, 1400)) == (809, 874)


def test_source_has_no_pointer_or_button_calls():
    src = (SCRIPTS / "probe_place_a.py").read_text(encoding="utf-8")
    for word in ("SetCursorPos", "mouse_event", "SendInput", "WM_LBUTTON"):
        assert word not in src, word


def test_template_found_at_exact_place_only():
    word = _capture(6, 3, rects=[(1, 1, 3, 1, (250, 250, 250))])
    scene = _capture(40, 20, rects=[(12, 8, 3, 1, (250, 250, 250))])  # the word's bright run at (12, 8)
    assert pa.find_template(scene, word) == (11, 7)
    assert pa.find_template(_capture(40, 20), word) is None
    assert pa.find_template(scene, word, region=(0, 0, 20, 5)) is None


def test_pointer_tick_one_sample_late_is_still_his():
    # the position moved at sample 2, the input tick only shows at sample 3: his
    samples = [(5, 5, 100), (5, 5, 100), (9, 5, 100), (9, 5, 130), (9, 5, 130)]
    assert pa.classify_pointer(samples) == (0, 1)


# ---------------------------------------------------------------- #916 unit 1b: counter, gate, stop (all seams)

import json  # noqa: E402


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t
        self.sleeps = 0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        self.sleeps += 1


def _counter(tmp_path, used=34, limit=10, cap=44):
    p = tmp_path / "posts-counter.json"
    p.write_text(json.dumps({"used": used, "total_cap": cap}), encoding="utf-8")
    return pa.PostCounter(p, limit=limit), p


def _total(p):
    return json.loads(p.read_text(encoding="utf-8"))["used"]


def test_counter_refuses_the_11th_post_and_persists_every_post(tmp_path):
    c, p = _counter(tmp_path)
    sent = []
    for i in range(10):
        pa.post_move(c, lambda h, m, w, l: sent.append(m), 7, i, i)
        assert _total(p) == 34 + i + 1  # written before the next post, survives a crash
    assert len(sent) == 10 and _total(p) == 44
    with pytest.raises(pa.PostCapExceeded):
        pa.post_move(c, lambda h, m, w, l: sent.append(m), 7, 0, 0)
    assert len(sent) == 10 and _total(p) == 44
    assert set(sent) == {0x0200}


def test_counter_survives_script_runs_and_refuses_the_first_at_44(tmp_path):
    c1, p = _counter(tmp_path, used=40)
    sent = []
    for _ in range(4):
        pa.post_move(c1, lambda h, m, w, l: sent.append(1), 7, 1, 1)
    with pytest.raises(pa.PostCapExceeded):  # the run limit 10 is not reached: the total cap 44 stops it
        pa.post_move(c1, lambda h, m, w, l: sent.append(1), 7, 1, 1)
    c2 = pa.PostCounter(p, limit=10)  # a new script run reads the file
    assert c2.total == 44 and c2.remaining() == 0
    with pytest.raises(pa.PostCapExceeded):
        pa.post_move(c2, lambda h, m, w, l: sent.append(1), 7, 1, 1)
    assert len(sent) == 4


def test_counter_missing_file_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        pa.PostCounter(tmp_path / "none.json")


def _gate(state):
    """check(point) over a mutable state dict: idle seconds, covered flag, template found flag."""
    def find_point():
        return (2399, 941) if state.get("found", True) else None

    def in_app(pt):
        return not state["covered"]

    def idle():
        return state["idle"]

    return lambda point=None: pa.gate_check(find_point, in_app, idle, point)


def test_gate_needs_template_uncovered_and_120_s_idle():
    st = {"idle": 200.0, "covered": False}
    assert _gate(st)()[:2] == (True, None)
    assert _gate(st)()[2] == (2399, 941)
    assert _gate(dict(st, idle=119.9))()[0] is False
    assert _gate(dict(st, covered=True))()[0] is False
    ok, why, pt = _gate(dict(st, found=False))()
    assert not ok and "pager" in why and pt is None
    # inside a run the point is given: no new capture is asked for
    assert _gate(dict(st, found=False))((1, 1))[0] is True


def test_gate_not_met_means_zero_posts_exit_4_and_the_line(tmp_path):
    c, p = _counter(tmp_path)
    clk, said, posts = FakeClock(), [], []
    st = {"idle": 10.0, "covered": False}

    def steps(guard):
        pa.post_move(c, lambda *a: posts.append(a), 7, 1, 1)

    rc = pa.gated_run(c, _gate(st), steps, clk.sleep, clk.now, said.append)
    assert rc == pa.EXIT_NOT_MET == 4
    assert posts == [] and _total(p) == 34
    assert any(s.startswith("not met at ") and len(s.split("not met at ")[1][:5]) == 5 for s in said)
    waited = clk.t - 1_000_000.0
    assert 1800 <= waited <= 1805 and clk.sleeps == 360  # 30 min, polled every 5 s


def test_gate_not_met_when_covered_even_if_idle(tmp_path):
    c, p = _counter(tmp_path)
    clk, said = FakeClock(), []
    rc = pa.gated_run(c, _gate({"idle": 900.0, "covered": True}), lambda g: pytest.fail("posted"),
                      clk.sleep, clk.now, said.append)
    assert rc == pa.EXIT_NOT_MET and _total(p) == 34


def test_gate_opens_after_a_while_and_the_steps_run(tmp_path):
    c, p = _counter(tmp_path)
    clk, said, posts = FakeClock(), [], []
    st = {"idle": 10.0, "covered": False}
    real_sleep = clk.sleep

    def sleep(s):
        real_sleep(s)
        if clk.sleeps == 7:
            st["idle"] = 500.0

    def steps(guard):
        for i in range(3):
            pa.post_move(c, lambda *a: posts.append(a), 7, i, i, guard=guard, point=(2399, 941))

    rc = pa.gated_run(c, _gate(st), steps, sleep, clk.now, said.append)
    assert rc == 0 and len(posts) == 3 and _total(p) == 37
    assert not any("not met" in s for s in said)


def test_stop_on_his_input_ends_the_run_and_counts_the_posts_so_far(tmp_path):
    c, p = _counter(tmp_path)
    clk, said, posts = FakeClock(), [], []
    st = {"idle": 500.0, "covered": False}

    def post_fn(*a):
        posts.append(a)
        if len(posts) == 2:
            st["idle"] = 30.0  # he touched the keyboard

    def steps(guard):
        for i in range(10):
            pa.post_move(c, post_fn, 7, i, i, guard=guard, point=(2399, 941))

    rc = pa.gated_run(c, _gate(st), steps, clk.sleep, clk.now, said.append)
    assert rc == pa.EXIT_STOPPED == 5
    assert len(posts) == 2 and _total(p) == 36 and c.used == 2
    assert any("stopped" in s and "input" in s for s in said)


def test_stop_on_cover_ends_the_run_and_counts_the_posts_so_far(tmp_path):
    c, p = _counter(tmp_path)
    clk, said, posts = FakeClock(), [], []
    st = {"idle": 500.0, "covered": False}

    def post_fn(*a):
        posts.append(a)
        if len(posts) == 3:
            st["covered"] = True  # another window came over the point

    def steps(guard):
        for i in range(10):
            pa.post_move(c, post_fn, 7, i, i, guard=guard, point=(2399, 941))

    rc = pa.gated_run(c, _gate(st), steps, clk.sleep, clk.now, said.append)
    assert rc == pa.EXIT_STOPPED
    assert len(posts) == 3 and _total(p) == 37
    assert any("stopped" in s and "covered" in s for s in said)


def test_counter_at_44_exits_before_waiting_or_posting(tmp_path):
    c, p = _counter(tmp_path, used=44)
    clk, said = FakeClock(), []

    def check(point=None):
        pytest.fail("the gate must not be read when no post is left")

    rc = pa.gated_run(c, check, lambda g: pytest.fail("posted"), clk.sleep, clk.now, said.append)
    assert rc == pa.EXIT_COUNTER == 6
    assert clk.sleeps == 0 and _total(p) == 44


def test_idle_seam_is_the_one_of_pane_look():
    import pane_look
    assert pa.idle_seconds is pane_look.idle_seconds and pa.IDLE_NEED_S == pane_look.IDLE_NEED_S == 120
