"""The visit driver of #837 (scripts/visit_837.py). Fakes only: 0 real pointer calls, 0 installs, 0 PoB."""
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pane_look as pl  # noqa: E402
import visit_837 as v  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "visit_837.py"
TABS = [("main", 100, 10), ("builds", 200, 10), ("tickets", 300, 10), ("cost", 400, 10), ("progress", 500, 10)]
HEADS = {name: (x, 95) for name, x, _y in TABS}


def tile_of(x, y):
    return (x - 8, y - 6, x + 40, y + 6)


class Fake:
    """Every seam of run_visit. The clock moves only by sleep() and by series_cost per hover-series call."""

    def __init__(self, rows=3, grey=(), install_rc=0, cp=(1.0,), back_times=None, dark=(), no_switch=(),
                 series_cost=0.0, placeholder=()):
        self.t = 1000.0
        self.presses, self.looks, self.series_calls, self.sleeps = [], [], [], []
        self.installs = 0
        self.put_backs = 0
        self.said = []
        self.rows, self.grey, self.install_rc = rows, grey, install_rc
        self.cp, self.cp_calls = list(cp), 0
        self.back_times = dict(back_times or {})
        self.dark, self.no_switch = set(dark), set(no_switch)
        self.placeholder = set(placeholder)
        self.series_cost = series_cost
        self.head = None
        self.spans = {}
        self.heads_asked = 0

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s

    def say(self, msg):
        self.said.append(msg)

    def find_tab_heads(self, picture):
        self.heads_asked += 1
        return dict(HEADS)

    def press(self, x, y):
        self.presses.append((x, y))
        if x not in self.no_switch:
            self.head = x
        return 0

    def look(self, path):
        self.looks.append(path)
        self.spans[path] = None if self.head is None else (self.head - 20, self.head + 20)
        return 0

    def size(self, path):
        return 100 if any(g in path for g in self.grey) else 300_000

    def underline(self, path):
        return self.spans.get(path)

    def crashpad(self):
        v_ = self.cp[min(self.cp_calls, len(self.cp) - 1)]
        self.cp_calls += 1
        return v_

    def install(self):
        self.installs += 1
        return self.install_rc

    def put_back(self):
        self.put_backs += 1
        return 0

    def find_points(self, path):
        items = []
        for r in range(self.rows):
            x, y = self.head + 10, 200 + 30 * r
            items.append({"x": x, "y": y, "card": "A" if r < 2 else "B", "row": r, "tile": tile_of(x, y),
                          "placeholder": (x, y) in self.placeholder, "text_found": True})
        return items

    def hover(self, points, out_dir):
        pts = tuple(points)
        self.series_calls.append(pts)
        self.t += self.series_cost
        if self.back_times.get(pts[0], 0) > 0:
            self.back_times[pts[0]] -= 1
            return 3
        return 0

    def diff(self, rest, hovered, tile):
        return 0 if tuple(tile) in self.dark else 9


def run(f, out_dir, tabs=TABS, with_heads=False):
    kw = dict(tabs=tabs, find_tab_heads=f.find_tab_heads) if with_heads else dict(tabs=tabs)
    return v.run_visit(out_dir=out_dir, press=f.press, look=f.look, hover_series=f.hover,
                       install=f.install, put_back=f.put_back, crashpad_mtime=f.crashpad,
                       find_points=f.find_points, diff_pixels=f.diff, picture_size=f.size,
                       underline_span=f.underline, now=f.now, sleep=f.sleep, say=f.say, **kw)


def test_happy_path_stays(tmp_path):
    f = Fake(rows=3)
    res = run(f, tmp_path)
    assert res["verdict"] == "stays"
    assert len(f.presses) == 10                      # 5 tab heads in step 1, 5 in step 4
    assert f.installs == 1
    assert f.put_backs == 0
    assert len(f.series_calls) == 5                  # one series per tab (3 rows each)
    assert f.sleeps == [60, 60, 60]                  # step 3: +60, +120, +180 s after the install
    assert sum(t["lit"] for t in res["tabs"]) == 15 and sum(t["failed"] for t in res["tabs"]) == 0
    assert (tmp_path / "visit_837_table.md").is_file()


def test_failed_row_puts_back_and_names_tab_card_row(tmp_path):
    f = Fake(rows=3, dark={tile_of(410, 260)})       # cost tab, row 2 (card B) does not light
    res = run(f, tmp_path)
    assert res["verdict"] == "put back"
    assert f.put_backs == 1
    assert res["failed"] == [("cost", "B", 2)]
    assert any(p.endswith("step5_after_put_back.png") for p in f.looks)
    assert f.sleeps[-1] == 60


def test_placeholder_row_not_lit_is_not_a_failure(tmp_path):
    f = Fake(rows=3, dark={tile_of(110, 200)}, placeholder={(110, 200)})   # main tab row 0: a dim empty row
    res = run(f, tmp_path)
    assert res["verdict"] == "stays"
    assert f.put_backs == 0
    assert res["failed"] == []
    main = [t for t in res["tabs"] if t["tab"] == "main"][0]
    assert main["placeholder_not_lit"] == 1 and main["failed"] == 0 and main["lit"] == 2
    table = (tmp_path / "visit_837_table.md").read_text(encoding="utf-8")
    assert "placeholder not lit" in table and "| main | 3 | 2 | 0 | 1 |" in table


def test_grey_pane_in_step_1_no_install(tmp_path):
    f = Fake(grey=("step1_pane",))
    res = run(f, tmp_path)
    assert res["verdict"] == "stopped" and "grey" in res["reason"]
    assert f.installs == 0 and f.presses == []


def test_press_that_does_not_switch_stops_before_install(tmp_path):
    f = Fake(no_switch={300})                        # the tickets head press does not move the underline
    res = run(f, tmp_path)
    assert res["verdict"] == "stopped" and "did not switch" in res["reason"]
    assert f.installs == 0
    assert f.presses == [(100, 10), (200, 10), (300, 10)]


def test_install_refused_no_put_back_no_step_3(tmp_path):
    f = Fake(install_rc=1)
    res = run(f, tmp_path)
    assert res["verdict"] == "stopped" and res["reason"].startswith("refused")
    assert f.put_backs == 0
    assert not any("step3" in p for p in f.looks)
    assert len(f.presses) == 5                       # step 1 only


def test_moved_crashpad_time_in_step_3_no_press_after_no_put_back(tmp_path):
    f = Fake(cp=(1.0, 2.0))                          # the listing before the install says 1.0, then 2.0
    res = run(f, tmp_path)
    assert res["verdict"] == "not finished"
    assert "only the owner reloads" in res["reason"]
    assert len(f.presses) == 5                       # nothing pressed after step 3 started
    assert f.series_calls == []
    assert f.put_backs == 0


@pytest.mark.parametrize("grey_look", ["step3_look_60s", "step3_look_120s"])
def test_grey_look_in_step_3_stops_not_finished(tmp_path, grey_look):
    f = Fake(grey=(grey_look,))
    res = run(f, tmp_path)
    assert res["verdict"] == "not finished"
    assert len(f.presses) == 5 and f.series_calls == [] and f.put_backs == 0


def test_second_owner_back_on_one_series_is_not_finished(tmp_path):
    f = Fake(back_times={(110, 200): 2})             # the first series of the main tab, stopped twice
    res = run(f, tmp_path)
    assert res["verdict"] == "not finished"
    assert len(f.series_calls) == 2                  # the series, once more, then the verdict


def test_one_owner_back_is_repeated_once_and_the_visit_goes_on(tmp_path):
    f = Fake(back_times={(110, 200): 1})
    res = run(f, tmp_path)
    assert res["verdict"] == "stays"
    assert len(f.series_calls) == 6                  # 5 series, one of them repeated


def test_deadline_14_minutes_with_rows_unhovered_puts_back(tmp_path):
    f = Fake(rows=3, series_cost=400.0)              # each series takes 400 s on the fake clock
    res = run(f, tmp_path)
    assert res["verdict"] == "put back"
    assert "14 minutes" in res["reason"]
    assert f.put_backs == 1
    assert len(f.series_calls) == 2                  # the third tab starts after the 14 minutes


def test_tab_heads_from_the_seam_when_no_override(tmp_path):
    f = Fake(rows=2)
    res = run(f, tmp_path, tabs=None, with_heads=True)
    assert res["verdict"] == "stays" and f.heads_asked == 1
    assert res["tab_names"] == list(v.TAB_ORDER)
    assert f.presses[:5] == [(HEADS[n][0], HEADS[n][1]) for n in v.TAB_ORDER]


def test_tab_heads_seam_missing_a_label_stops_before_install(tmp_path):
    f = Fake()
    f.find_tab_heads = lambda picture: {n: HEADS[n] for n in v.TAB_ORDER[:4]}
    res = run(f, tmp_path, tabs=None, with_heads=True)
    assert res["verdict"] == "stopped" and "progress" in res["reason"]
    assert f.installs == 0


def test_plan_default_over_14_and_fewer_presses_arithmetic():
    assert v.PRESS_RESETS_IDLE is True              # the plan charges one gate per press
    default = v.plan_minutes()
    assert default["presses"] == 10
    assert default["total_s"] == pytest.approx(1476.0)
    assert default["fits_14_min"] is False
    fewer = v.plan_minutes(presses_step1=0, presses_step4=4)
    assert fewer["presses"] == 4
    step4 = fewer["steps"]["step 4 tabs and rows"]
    assert step4 == pytest.approx(4 * v.PRESS_GATE_S + 4 * v.PRESS_S + 5 * v.LOOK_S
                                  + 60 * (v.HOVER_REST_S + v.LOOK_S))
    assert fewer["total_s"] == pytest.approx(751.1)
    assert fewer["fits_14_min"] is True


def test_plan_command_prints_both_orders_in_pane_tab_order(capsys):
    assert v.main(["--plan"]) == 0
    out = capsys.readouterr().out
    assert "fits_14_min: False" in out and "fits_14_min: True" in out
    assert "fewer presses" in out
    assert "main 12, builds 12, tickets 12, cost 12, progress 12" in out


def test_run_dry_run_calls_no_seam(tmp_path, monkeypatch, capsys):
    def boom(**kw):
        raise AssertionError("run_visit must not run with --dry-run")
    monkeypatch.setattr(v, "run_visit", boom)
    assert v.main(["--run", "--dry-run", "--out-dir", str(tmp_path)]) == 0
    assert "step 2: crashpad listing; ONE install" in capsys.readouterr().out


def test_import_references_real_seams_and_calls_none(monkeypatch):
    def trap(*a, **k):
        raise AssertionError("a real seam was called at import time")
    for name in ("do_look", "do_press", "do_hover_series", "wait_for_pause", "screen_rgb"):
        monkeypatch.setattr(pl, name, trap)
    monkeypatch.setattr(v.os, "walk", trap)
    spec = importlib.util.spec_from_file_location("visit_837_fresh", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    kw = mod.run_visit.__kwdefaults__
    assert kw["press"] is mod.real_press and kw["install"] is mod.real_install
    assert kw["put_back"] is mod.real_put_back and kw["crashpad_mtime"] is mod.real_crashpad_mtime
    assert kw["find_tab_heads"] is mod.real_find_tab_heads and kw["tabs"] is None


def test_item_forms_pane_points_dict_and_old_tuples():
    d = v._norm({"x": 50, "y": 60, "card": "C", "row": 4, "tile": (40, 55, 70, 65), "placeholder": True,
                 "text_found": False})
    assert d == {"card": "C", "row": 4, "x": 50, "y": 60, "tile": (40, 55, 70, 65), "placeholder": True}
    assert v._norm((50, 60))["tile"] == (45, 55, 54, 64)
    t = v._norm(("A", 1, 50, 60))
    assert (t["card"], t["row"], t["placeholder"]) == ("A", 1, False)


def _png(path, w, h, pixels):
    buf = bytearray(w * h * 3)
    for (x, y), rgb in pixels.items():
        off = (y * w + x) * 3
        buf[off:off + 3] = bytes(rgb)
    pl.write_png(str(path), w, h, bytes(buf))
    return str(path)


def test_png_diff_counts_inside_the_tile_grown_by_3(tmp_path):
    rest = _png(tmp_path / "rest.png", 60, 60, {})
    hov = _png(tmp_path / "hov.png", 60, 60, {(30, 30): (1, 2, 3)})
    assert v.real_diff_pixels(rest, hov, (30, 30, 30, 30)) == 1      # 27..33 holds (30,30)
    assert v.real_diff_pixels(rest, hov, (34, 34, 36, 36)) == 0      # 31..39 does not
    assert v.real_diff_pixels(rest, hov, (5, 5, 9, 9)) == 0


def test_real_underline_span_finds_the_colour(tmp_path):
    pic = _png(tmp_path / "pane.png", 2010, 120, {(x, 110): v.UNDERLINE_RGB for x in range(1600, 1701)})
    assert v.real_underline_span(pic) == (1600, 1700)


def test_real_tab_heads_five_runs_to_five_points(tmp_path):
    # five light label runs in the strip y 88..102; one run has a 7 px inner gap (one label), gaps 59 px between
    runs = [(1580, 1600), (1608, 1620), (1680, 1720), (1780, 1820), (1880, 1920), (1960, 1990)]
    pixels = {}
    for a, b in runs:
        for x in range(a, b + 1):
            for y in range(90, 101):
                pixels[(x, y)] = (200, 200, 200)
    # five labels: runs 1 (1580..1620 with the gap), 2, 3, 4, 5 (1960..1990 is the fifth)
    pic = _png(tmp_path / "strip.png", 2010, 120, pixels)
    assert v.real_find_tab_heads(pic) == {
        "main": (1600, 95), "builds": (1700, 95), "tickets": (1800, 95), "cost": (1900, 95),
        "progress": (1975, 95)}


def test_real_tab_heads_four_labels_raise(tmp_path):
    pixels = {(x, y): (200, 200, 200) for x in list(range(1580, 1600)) + list(range(1700, 1720))
              + list(range(1800, 1820)) + list(range(1900, 1920)) for y in range(90, 101)}
    pic = _png(tmp_path / "four.png", 2010, 120, pixels)
    with pytest.raises(ValueError, match="4 labels"):
        v.real_find_tab_heads(pic)


def test_shown_tab_first_presses_only_four_heads_and_cap_is_given():
    """The owner's go 20: step 1 = one look, no press; step 4 presses the 4 other heads only."""
    import visit_837 as v
    presses = []
    res = v.run_visit(out_dir=str(__import__("tempfile").mkdtemp()), tabs=[(n, 10 * i, 5) for i, n in enumerate(v.TAB_ORDER)],
                      press=lambda x, y: presses.append((x, y)) or 0, look=lambda p: open(p, "wb").write(b"x" * 300000) and 0,
                      hover_series=lambda pts, d: (__import__("os").makedirs(d, exist_ok=True), 0)[1],
                      install=lambda: 0, put_back=lambda: 0, crashpad_mtime=lambda: 1.0,
                      find_points=lambda p: [], diff_pixels=lambda a, b, t: 1, underline_span=lambda p: (0, 100),
                      sleep=lambda s: None, say=lambda *_: None, shown_tab_first=True, deadline_s=20 * 60)
    assert presses == [(10, 5), (20, 5), (30, 5), (40, 5)]
    assert res["verdict"] == "stays"


def test_run_without_repo_is_refused(capsys):
    import visit_837 as v
    assert v.main(["--run", "--out-dir", "x"]) == 2
    assert "--repo" in capsys.readouterr().out
