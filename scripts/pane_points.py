"""Find the row points of the Junkroan pane in a look picture (#837).

  python scripts/pane_points.py <png> [--overlay <out.png>] [--json]

find_points(png_path) takes a full-screen PNG (scripts/pane_look.py look --out, primary screen, picture px =
screen px) and returns, for the tab shown, one dict per visible row tile:
  {"x": int, "y": int, "card": int, "row": int, "tile": (left, top, right, bottom),
   "text_found": bool, "placeholder": bool}
(x, y) is a screen point on the row's title: x = first glyph x + TEXT_X_INSET (a child row's coloured status dot
is skipped), y = tile vertical centre. No glyph found: x = tile left + FALLBACK_TEXT_INSET and text_found False.
placeholder is True for a dim-text row ("ничего" / "пусто"); its point is kept.
tile is inclusive pixel coordinates. Pure image scan: PIL only, no window, no pointer, no pane import.

The pane is found from its cards, not from the pane background colour: the (26,26,25) pane background also
occurs outside the pane (the Claude sidebar), so its bounding box is not the pane.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from PIL import Image, ImageChops, ImageDraw

PANE_BG = (26, 26, 25)                  # the pane background between and around the cards (live picture)
BG_TOL = 2                              # per-channel tolerance for a background pixel
CARD_BG = (38, 38, 40)                  # colour of a card panel on the pane (live picture)
CARD_TOL = 2                            # per-channel tolerance for a card pixel
CARD_COLUMN_SHARE = 0.1                 # a column is inside the cards when this share of the best column is card colour
TILE_LIGHTER_MIN = 3                    # a row tile is lighter than its card: brightest channel 3..30 above it
TILE_LIGHTER_MAX = 30                   # (text is far brighter than that; the pane background is darker)
TILE_SHARE = 0.25                       # on a tile row, this share of the band between the probes is tile colour
PROBE_IN_CARD = 30                      # x offset from the card's left edge: left of every tile, right of the card icon
PROBE_IN_RIGHT = 12                     # x offset from the card's right edge: inside every tile's right padding
MIN_TILE_H = 14
MAX_TILE_H = 34
TEXT_SCAN_FROM = 6                      # the title is searched from the tile's left edge + 6 px
TEXT_ROW_PAD = 2                        # rows above and below the text are left out of the search
SPREAD_MAX = 40                         # max-min channel spread: above it a pixel is coloured (status dot), not text
TITLE_LUM_MIN = 110                     # first glyph: a text pixel brighter than this (mean of channels)
TEXT_DOT_GAP = 2                        # the first glyph lies more than this many px right of the last coloured column
TEXT_X_INSET = 4                        # point x = first glyph x + this
FALLBACK_TEXT_INSET = 12                # point x when no glyph is found: tile left + this (text_found False)
PLACEHOLDER_DIM_MIN = 70                # a dim text pixel (placeholder kind) is brighter than this
PLACEHOLDER_PEAK_LUM = 130              # placeholder: dim text present and its peak below this (titles reach > 200)


def _is_card(p) -> bool:
    return all(abs(c - k) <= CARD_TOL for c, k in zip(p, CARD_BG))


def _is_tile(p) -> bool:
    d = [c - k for c, k in zip(p, CARD_BG)]
    return min(d) >= -1 and TILE_LIGHTER_MIN <= max(d) <= TILE_LIGHTER_MAX


def _card_columns(im) -> list[int]:
    """Per column, the share (0..255) of pixels that are card colour (outside the pane: about 1 px a column)."""
    r, g, b = im.split()
    bands = [ch.point(lambda v, k=k: 255 if abs(v - k) <= CARD_TOL else 0) for ch, k in zip((r, g, b), CARD_BG)]
    mask = ImageChops.multiply(ImageChops.multiply(bands[0], bands[1]), bands[2])
    return list(mask.resize((im.width, 1), Image.Resampling.BOX).getdata())


def _is_bg(p) -> bool:
    return all(abs(c - k) <= BG_TOL for c, k in zip(p, PANE_BG))


def _card_runs(px, x: int, height: int) -> list[tuple[int, int]]:
    """Vertical runs down column x that are not pane background and hold card colour: one run per card,
    top to bottom. Tile rows and their edges are not background, so a card stays one run."""
    runs, y = [], 0
    while y < height:
        if _is_bg(px[x, y]):
            y += 1
            continue
        start = y
        while y < height and not _is_bg(px[x, y]):
            y += 1
        if any(_is_card(px[x, k]) for k in range(start, y)):
            runs.append((start, y - 1))
    return runs


def _runs(ys: list[int]) -> list[tuple[int, int]]:
    runs: list[list[int]] = []
    for y in ys:
        if runs and y == runs[-1][1] + 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    return [(a, b) for a, b in runs]


def _spread(p) -> int:
    return max(p) - min(p)


def _lum(p) -> float:
    return (p[0] + p[1] + p[2]) / 3


def _title(px, t: int, b: int, tl: int, tr: int):
    """(first glyph x or None, peak text luminance, dim text present) of one tile's title.
    Coloured pixels (status dot, and its column run) are skipped; the glyph must be TEXT_DOT_GAP px clear of them."""
    top, bot = t + TEXT_ROW_PAD, b - TEXT_ROW_PAD
    first, last_coloured, peak, dim = None, None, 0.0, False
    for x in range(tl + TEXT_SCAN_FROM, tr):
        pix = [px[x, y] for y in range(top, bot + 1)]
        if any(_spread(p) > SPREAD_MAX for p in pix):
            last_coloured = x
            continue
        m = max(_lum(p) for p in pix)
        peak = max(peak, m)
        if m > PLACEHOLDER_DIM_MIN:
            dim = True
        if first is None and m > TITLE_LUM_MIN and (last_coloured is None or x - last_coloured > TEXT_DOT_GAP):
            first = x
    return first, peak, dim


def _card_tiles(px, c0: int, c1: int, right: int, probe_x: int, right_x: int):
    """(left, top, right, bottom) of every complete row tile inside the card rows c0..c1."""
    band = range(probe_x, right_x)
    tile_rows = []
    for y in range(c0, c1 + 1):
        if not _is_tile(px[right_x, y]):
            continue
        if sum(1 for x in band if _is_tile(px[x, y])) >= TILE_SHARE * len(band):
            tile_rows.append(y)
    out = []
    for t, b in _runs(tile_rows):
        if not MIN_TILE_H <= b - t + 1 <= MAX_TILE_H:
            continue
        if t - 1 < c0 or b + 1 > c1:  # cut by the pane's visible edge: no card colour above or below
            continue
        lefts, rights = [], []
        for y in range(t, b + 1):
            xl = next((x for x in range(probe_x, right_x + 1) if _is_tile(px[x, y])), None)
            xr = next((x for x in range(right, probe_x - 1, -1) if _is_tile(px[x, y])), None)
            if xl is not None:
                lefts.append(xl)
            if xr is not None:
                rights.append(xr)
        if lefts and rights:
            out.append((min(lefts), t, max(rights), b))
    return out


def _scan(png_path) -> tuple[list[dict], int]:
    im = Image.open(png_path).convert("RGB")
    share = _card_columns(im)
    top = max(share, default=0)
    if top == 0:
        return [], 0
    wide = [x for x, v in enumerate(share) if v >= CARD_COLUMN_SHARE * top]
    left, right = wide[0], wide[-1]
    px = im.load()
    probe_x = left + PROBE_IN_CARD
    right_x = right - PROBE_IN_RIGHT
    cards = _card_runs(px, probe_x, im.height)
    points = []
    for index, (c0, c1) in enumerate(cards):
        for row, (tl, t, tr, b) in enumerate(_card_tiles(px, c0, c1, right, probe_x, right_x)):
            first, peak, dim = _title(px, t, b, tl, tr)
            text_found = first is not None
            x = first + TEXT_X_INSET if text_found else tl + FALLBACK_TEXT_INSET
            points.append({"x": x, "y": (t + b) // 2, "card": index, "row": row, "tile": (tl, t, tr, b),
                           "text_found": text_found, "placeholder": dim and peak < PLACEHOLDER_PEAK_LUM})
    return points, len(cards)


def find_points(png_path) -> list[dict]:
    """One dict per visible row tile of the pane in the look picture at png_path (see module doc)."""
    return _scan(png_path)[0]


def write_overlay(png_path, points: list[dict], out_path) -> None:
    im = Image.open(png_path).convert("RGB")
    draw = ImageDraw.Draw(im)
    red = (255, 0, 0)
    for i, p in enumerate(points):
        x, y = p["x"], p["y"]
        draw.line([(x - 4, y), (x + 4, y)], fill=red)
        draw.line([(x, y - 4), (x, y + 4)], fill=red)
        draw.text((x + 7, y - 6), str(i), fill=red)
    im.save(out_path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Row points of the Junkroan pane in a look picture (#837).")
    ap.add_argument("png")
    ap.add_argument("--overlay", help="write a copy of the picture with a 9 px red cross and index on every point")
    ap.add_argument("--json", action="store_true", help="print the points as JSON")
    args = ap.parse_args(argv)
    points, cards = _scan(args.png)
    if args.overlay:
        write_overlay(args.png, points, args.overlay)
    if args.json:
        print(json.dumps(points))
        return 0
    per_card = Counter(p["card"] for p in points)
    print(f"points: {len(points)}")
    for index in range(cards):
        print(f"card {index}: {per_card.get(index, 0)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
