"""scripts/pane_draw.py: one card, one table; the PNG's size, row tops and hover rectangle read back from the pixels
equal the layout's values (#843 unit 3). 0 PoB; headless chromium renders the Svg (a browser, no window)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PIL")  # not installed on the laptop

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pane_draw as pd  # noqa: E402
import pane_layout as pl  # noqa: E402
import pane_dump as _pd  # noqa: E402
import pytest  # noqa: E402

ROW = (255, 0, 0)
HOV = (47, 47, 51)


def svg(h, body, w=700):
    return {"type": "Svg", "props": {"source": f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>{body}</svg>",
                                     "alt": "t", "height": h}}


def box(props, children=None, hover=None):
    n = {"type": "Box", "props": props, "children": children or []}
    if hover:
        n["hover"] = hover
    return n


def small():
    body = "<rect width='700' height='20' fill='#ff0000'/>"
    rows = svg(114, "".join(f"<g transform='translate(0 {y})'>{body}</g>" for y in (9, 47, 85)))
    hov = {"backgroundColor": "#2f2f33"}
    presses = box({"position": "absolute", "top": 0, "left": 30, "right": 0, "flexDirection": "column"},
                  [box({"position": "absolute", "top": 2 * i, "left": 0, "height": 2, "key": f"hv-row-{i}"}, [], hov) for i in range(3)])
    card = box({"flexDirection": "column", "key": "card-x", "backgroundColor": "#262628"}, [svg(30, "<rect width='700' height='3' fill='#58a6ff'/>"), box({"flexDirection": "column"}, [rows, presses])])
    return {"cols": 100, "tree": box({"flexDirection": "column"}, [card])}


def bbox(img, rgb, x0=0, x1=None):
    a = np.asarray(img)[:, x0:x1, :3]
    ys, xs = np.where((a == rgb).all(axis=2))
    return (xs.min() + x0, ys.min(), xs.max() + 1 + x0, ys.max() + 1)


def test_size_rows_and_hover_read_back_from_pixels():
    res = pl.layout(small())
    assert res["unhandled"] == []
    img = pd.draw(res, scale=1.0, hover="hv-row-1", label="t")
    bottom = max(p["y"] + p["h"] for p in res["prims"])
    assert img.size == (round(100 * pl.COL_PX), round(bottom) + pd.FOOT_H)  # 798 x (150 + 22)
    tops = [p for p in res["prims"] if p["kind"] == "svg"][1]["row_tops"]
    assert tops == [30, 68, 106]
    a = np.asarray(img)[:, 0:30, :3]  # a column left of the hover rects: the three red rows
    red = np.where((a == ROW).all(axis=2).any(axis=1))[0]
    starts = [int(y) for i, y in enumerate(red) if i == 0 or red[i - 1] != y - 1]
    assert starts == [t + 9 for t in tops]  # each group is translated 9 px under its row top
    hov = [p for p in res["prims"] if p["kind"] == "hover_rect"][1]
    x0, y0, x1, y1 = bbox(img, HOV, x0=int(30 * pl.COL_PX))
    assert (y0, y1) == (hov["y"], hov["y"] + hov["h"]) == (68, 106)
    assert x0 == round(hov["x"]) and y0 == tops[1]  # the hover rect starts on its row top: no drift
    # without --hover nothing of the hover colour is drawn over the rows
    plain = pd.draw(pl.layout(small()), scale=1.0, label="t")
    assert not (np.asarray(plain)[:, int(30 * pl.COL_PX):, :3] == HOV).all(axis=2).any()


def test_scale_and_save_limit(tmp_path):
    img = pd.draw(pl.layout(small()), scale=1.25, label="t")
    assert img.width == round(100 * pl.COL_PX * 1.25) == 998
    p = tmp_path / "x.png"
    n = pd.save_small(pd.pair_image(img, img, "a", "b"), p)
    assert n == p.stat().st_size < pd.MAX_BYTES


# ---- calibration against the real picture (#843, row 1) ----
# REAL = measured (px, card top = 0) on docs/research/pictures-613-837/after-install-main-11-35.png (2560x1440, the pane
# installed at ref fc46b270, 119 cols, cards at x 1579..2528); the PNG itself is not needed here. The data of the two
# pictures differs (14 Agents rows real, 19 in the fixture), so only offsets from a card edge are compared.
REF = "fc46b270"
BG = np.array([38, 38, 40.0])
TOL = 2.0
REAL = {
    "card-agents": dict(title_text_top=16.0, first_band=64.0, last_band_to_bottom=18.0),
    "card-merge": dict(title_text_top=16.0, first_band=87.0, last_band_to_bottom=13.9, height=288.0),
    "card-runs": dict(title_text_top=16.0, first_band=89.0),  # the real card is cut by the viewport: no bottom
}
REAL_GAP_ABOVE = {"card-merge": 10.0, "card-runs": 9.0}  # px between a card and the one above
REAL_CARD_W, REAL_BAND_X0, REAL_BAND_X1 = 950.0, 38.0, 940.0  # card width; the first Agents band, from the card left edge


def measure(img, left=0, probe=800):
    """The same reading as on the real picture: cards by their colour in a column left of the content, bands in a column
    near the right end of the card (runs of non-card pixels >= 17 px high), the title text by its bright pixels."""
    im = np.asarray(img.convert("RGB")).astype(float)
    on = np.abs(im[:, left + 10] - BG).sum(axis=1) <= 4
    ys = np.where(on)[0]
    segs, s, p = [], ys[0], ys[0]
    for y in ys[1:]:
        if y != p + 1:
            segs.append((s, p))
            s = y
        p = y
    segs.append((s, p))
    segs = [x for x in segs if x[1] - x[0] > 60][:3]
    out, prev_bottom = [], None
    for key, (a, b) in zip(("card-agents", "card-merge", "card-runs"), segs):
        reg = im[a:a + 60, left + 28:left + 80].sum(axis=2)
        rows = np.where((reg > 450).any(axis=1))[0]
        col = im[:, left + probe]
        nb = np.abs(col - BG).sum(axis=1) > 6
        runs, y = [], a + 50
        while y < b:
            if nb[y]:
                y0 = y
                while y < b and nb[y]:
                    y += 1
                if y - y0 >= 17:
                    runs.append((y0, y))
            y += 1
        full = lambda i: np.abs(col[i] - BG).sum()
        first = runs[0][0] - min(1.0, np.abs(col[runs[0][0] - 1] - BG).sum() / full(runs[0][0] + 2))
        last = runs[-1][1] + min(1.0, np.abs(col[runs[-1][1]] - BG).sum() / full(runs[-1][1] - 3))
        row = np.where(np.abs(im[a + 25] - BG).sum(axis=1) <= 4)[0]
        out.append((key, dict(card_top=a, title_text_top=float(a + rows.min() - a), first_band=first - a,
                              last_band_to_bottom=b + 1 - last, height=b + 1 - a, gap_above=None if prev_bottom is None else a - prev_bottom,
                              card_w=float(row[row >= left].max() + 1 - row[row >= left].min()))))
        prev_bottom = b + 1
    return dict(out)


def band_x(img, left=0, probe=600):
    """x extent (from the card's left edge) of the first Agents band, read on a row of its green."""
    im = np.asarray(img.convert("RGB")).astype(int)
    ys = np.where(np.abs(im[:, left + 5 + probe] - np.array([38, 58, 43])).sum(axis=1) <= 3)[0]
    xs = np.where(np.abs(im[ys.min() + 1] - np.array([38, 58, 43])).sum(axis=1) <= 3)[0]
    xs = xs[xs >= left]
    return float(xs.min() - left), float(xs.max() + 1 - left)


@pytest.mark.skipif(_pd.claude_exe() is None,
                    reason="no claude.exe on this machine (CLAUDE_EXE, the app package, PATH)")
def test_calibration_against_the_real_main_tab():
    import pane_dump
    d = pane_dump.dump(REF, "live-fast", "main", False, 119)
    img = pd.draw(pl.layout(d), scale=1.0, label="cal")
    m = measure(img)
    bad = []
    for card, real in REAL.items():
        for k, v in real.items():
            if abs(m[card][k] - v) > TOL:
                bad.append(f"{card} {k}: tool {m[card][k]:.1f} real {v}")
    for card, v in REAL_GAP_ABOVE.items():
        if abs(m[card]["gap_above"] - v) > TOL:
            bad.append(f"{card} gap_above: tool {m[card]['gap_above']} real {v}")
    for card in REAL:
        if abs(m[card]["card_w"] - REAL_CARD_W) > TOL:
            bad.append(f"{card} width: tool {m[card]['card_w']} real {REAL_CARD_W}")
    x0, x1 = band_x(img)
    if abs(x0 - REAL_BAND_X0) > TOL or abs(x1 - REAL_BAND_X1) > TOL:
        bad.append(f"first band x: tool {x0}..{x1} real {REAL_BAND_X0}..{REAL_BAND_X1}")
    assert not bad, bad
    # no cropped right edge: the right-aligned header "длительность" of the Agents card is whole, ending 12..45 px left of the card edge
    top = m["card-agents"]["card_top"]
    hdr = np.asarray(img.convert("L"))[top + 45: top + 62, :int(REAL_CARD_W)]
    bright = np.where((hdr > 100).any(axis=0))[0]
    assert 905 < bright.max() < 941, bright.max()


@pytest.mark.skipif(_pd.claude_exe() is None,
                    reason="no claude.exe on this machine (CLAUDE_EXE, the app package, PATH)")
def test_dump_rig_survives_a_slow_machine(monkeypatch):
    """#857: the plugin test runner's default 5000 ms cut the rig off in a loaded full run (14:36, 5196 ms). A rig that
    takes 5.5 s of wall time must still hand its tree over."""
    slow = "  const clock = mock.clock(on)\n"
    assert slow in _pd.RIG
    monkeypatch.setattr(_pd, "RIG", _pd.RIG.replace(slow, "  const t0 = Date.now(); while (Date.now() - t0 < 5500) {}\n" + slow))
    assert _pd.dump(REF, "live-fast", "main", False, 119)["tree"]
