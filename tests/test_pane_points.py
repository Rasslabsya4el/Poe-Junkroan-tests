import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pane_points as pp  # noqa: E402

BG = (26, 26, 25)
CARD = (38, 38, 40)
TILE = (46, 46, 48)
TEXT = (200, 200, 200)
W, H = 500, 360


def _picture(path, ox=60, oy=0):
    """Two cards at (20+ox..379+ox). Card 0: 3 tiles. Card 1: heading text, 3 tiles, one tile cut by the
    picture bottom (16 px visible, nothing below it)."""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([20 + ox, 20 + oy, 379 + ox, 179 + oy], fill=CARD)
    for y0 in (40, 66, 92):
        d.rectangle([55 + ox, y0 + oy, 369 + ox, y0 + oy + 19], fill=TILE)
    d.rectangle([20 + ox, 200 + oy, 379 + ox, H - 1], fill=CARD)
    d.rectangle([120 + ox, 212 + oy, 200 + ox, 221 + oy], fill=TEXT)
    for y0 in (232, 258, 284):
        d.rectangle([55 + ox, y0 + oy, 369 + ox, y0 + oy + 19], fill=TILE)
    d.rectangle([55 + ox, H - 16, 369 + ox, H - 1], fill=TILE)
    im.save(path)


def _key(points):
    return [(p["card"], p["row"], p["x"], p["y"]) for p in points]


# (card, row, x, y) for _picture(ox=60, oy=0): x = 55 + 60 + TEXT_INSET; y = tile centre
EXPECTED = [(0, 0, 127, 49), (0, 1, 127, 75), (0, 2, 127, 101), (1, 0, 127, 241), (1, 1, 127, 267), (1, 2, 127, 293)]


def test_six_points_at_known_coordinates(tmp_path):
    png = tmp_path / "p.png"
    _picture(png)
    pts = pp.find_points(png)
    assert len(pts) == 6
    for got, exp in zip(_key(pts), EXPECTED):
        assert got[:2] == exp[:2]
        assert abs(got[2] - exp[2]) <= 1 and abs(got[3] - exp[3]) <= 1
    assert pts[0]["tile"] == (115, 40, 429, 59)


def test_shift_moves_points_by_the_same_amount(tmp_path):
    base, shifted = tmp_path / "a.png", tmp_path / "b.png"
    _picture(base, ox=60, oy=0)
    _picture(shifted, ox=23, oy=11)
    a = _key(pp.find_points(base))
    b = _key(pp.find_points(shifted))
    assert len(a) == len(b) == 6
    for (ca, ra, xa, ya), (cb, rb, xb, yb) in zip(a, b):
        assert (ca, ra) == (cb, rb)
        assert (xb - xa, yb - ya) == (-37, 11)


def test_no_pane_returns_empty(tmp_path):
    png = tmp_path / "none.png"
    Image.new("RGB", (W, H), BG).save(png)
    assert pp.find_points(png) == []


DOT = (150, 80, 220)     # coloured status dot (spread 140)
BRIGHT = (210, 210, 210)  # normal title text
DIM = (100, 100, 105)     # placeholder text ("ничего" kind)


def _rich_picture(path):
    """One card, tiles at y 40, 66, 92 (tile left 55): a top-level title, a child row whose title follows a
    purple dot, and a dim placeholder title."""
    im = Image.new("RGB", (W, 300), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 379, 299], fill=CARD)
    y0s = (40, 66, 92)
    for y0 in y0s:
        d.rectangle([55, y0, 369, y0 + 19], fill=TILE)
    d.rectangle([67, 46, 200, 53], fill=BRIGHT)                 # tile 0: title at tile left + 12
    d.rectangle([64, 73, 72, 81], fill=DOT)                     # tile 1: dot at tile left + 9
    d.rectangle([85, 72, 220, 79], fill=BRIGHT)                 # tile 1: title at tile left + 30
    d.rectangle([67, 98, 120, 105], fill=DIM)                   # tile 2: dim text at tile left + 12
    im.save(path)


def test_title_point_skips_status_dot_and_flags_placeholder(tmp_path):
    png = tmp_path / "rich.png"
    _rich_picture(png)
    pts = pp.find_points(png)
    assert [(p["card"], p["row"]) for p in pts] == [(0, 0), (0, 1), (0, 2)]
    top, child, dim = pts
    assert top["text_found"] and top["x"] == 67 + pp.TEXT_X_INSET and not top["placeholder"]
    assert child["text_found"] and child["x"] == 85 + pp.TEXT_X_INSET   # on the title, not the dot at 64..72
    assert not child["placeholder"]
    assert dim["placeholder"] is True and dim["text_found"] is False      # kept, fallback x
    assert dim["x"] == 55 + pp.FALLBACK_TEXT_INSET
    assert all(isinstance(p["placeholder"], bool) and isinstance(p["text_found"], bool) for p in pts)
