"""The pane's pointer elements: listed from the drawn tree, mapped onto the screenshot, hovered and pressed BY ELEMENT (#987).

  python mods/pob-slots/bin/pane_elements.py list [--overlay out.png] [--json out.json]
  python mods/pob-slots/bin/pane_elements.py hover <element> [--at centre|left|right] [--keep-raw] --out-dir <dir>
  python mods/pob-slots/bin/pane_elements.py press <element> [--at centre|left|right] [--tries 4] --out-dir <dir>
  python mods/pob-slots/bin/pane_elements.py go <element> <prefix> --out-dir <dir>     (choose an option of a switch unless chosen)
  python mods/pob-slots/bin/pane_elements.py switch <prefix> | toggle <element> --out-dir <dir>   (centre and both ends, and back)
  python mods/pob-slots/bin/pane_elements.py walk [--no-press] --out-dir <dir>   (the pass over the current state)
  python mods/pob-slots/bin/pane_elements.py tour --out-dir <dir> [--overlays <dir>]   (the pass over every tab; <dir>/STOP ends it)
  python mods/pob-slots/bin/pane_elements.py shoot <name> | shots --out-dir <dir>      (the whole tab in one picture / every tab and group)
  python mods/pob-slots/bin/pane_elements.py record <name> --out-dir <dir>       (the pane as it is now, kept for a test)
  python mods/pob-slots/bin/pane_elements.py report <log.jsonl> --out-dir <dir>  (the pass's three tables and totals)
  python mods/pob-slots/bin/pane_elements.py probe <x> <y> --out-dir <dir>       (a diagnostic: what lights at a raw point)

The rule (the owner, 2026-10-14): a target point comes from the element as drawn in the CURRENT picture, never from a
remembered or computed coordinate alone, and a look counts only when its after-picture shows the pointer on the element.
So every action here is: read the pane's own drawn tree (the state record), lay it out, CONFIRM the mapping on the
screenshot (each card of the tree lies on a card of the picture and is as high; a label the host draws is found by its
own glyphs and its rectangle taken from them; a blank label's drawn face must start where its rectangle does: else
MappingError), move the pointer, take the after-picture with the pointer drawn where the system says it is, and check
ON THAT PICTURE that the pointer is inside the element's rectangle (else Miss) and whether the host's light stands
under it. A press is made as a human makes one: no dwell, at the centre and near both ends of the face AS ITS LIGHT
SHOWED IT; a press that changes nothing is tried again and the tries are COUNTED, never hidden; a try with no light of
the element under the pointer is the tool's own miss (Miss), never the element's defect.

An element is named by its key in the drawn tree (`tab-pob`, `run-pick-<run>`, `tg-<N>`, `hv-<card><n>`; `list` prints
them), or by the unique beginning of it. What acts outside the pane (ACTS) is hovered and never pressed.
Exit codes: 0 done, 2 no such element, 4 MISS, 5 MAPPING. Every action is one line of <out-dir>/log.jsonl.

The raw pointer, the 120 s idle gate and the screenshot are scripts/pane_look.py's; nothing here bypasses them. A pass
is ended by the file <out-dir>/STOP, never by stopping the process: a stopped process leaves the pointer in the pane.
PIL + stdlib + ctypes; starts no process, opens no window.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import os
import re
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


def _repo_root() -> Path:
    env = os.environ.get("JUNKROAN_REPO")
    for base in ([Path(env)] if env else []) + list(Path(__file__).resolve().parents):
        if (base / "scripts" / "pane_look.py").is_file():
            return base
    raise SystemExit("pane_elements: scripts/pane_look.py not found above %s; set JUNKROAN_REPO" % __file__)


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "scripts"))
import pane_layout  # noqa: E402  (the px rules of the drawn tree)
import pane_look  # noqa: E402    (the owner's pointer and the screenshot)

DEFAULT_CACHE = Path.home() / ".claude" / "mods" / "pob-slots" / "bin" / ".cache"
POINTER = (255, 0, 255)      # the colour the pointer's outline is drawn in on an after-picture; nothing in the pane has it
CARD_BG = (38, 38, 40)       # a card's fill on the screen (tokens.ts card #262628)
PANE_BG = (26, 26, 25)       # the pane between its cards (the host's page)
LOADED_MEASURE = 10_000      # a pane that has its data draws more than this; a session that only mounted it draws ~3,900
# The host's own sizes, read off the real pane on 2026-10-14 (probe pictures var/brain/monitor-1014/t3/probe/):
CARD_INSET = 9.0             # a card's border + paddingX={1}: its content starts 9 px inside its edge
BTN_PAD = 4.0                # a plain Button's box (what the host lights) = its label and 4 px at each end
EM_PX = 13.3                 # an EM SPACE of a blank label (hooks/kit.tsx BLANK_PX)
NBSP_PX = 97 / 35            # a no-break space (hooks/kit.tsx NBSP_PX)
SELECT_PAD = 30.0            # a Select is its shown value and 30 px of the host's chrome
SELECT_H = 23.0              # and it is 23 px high: its row is 4 px higher than a text row
LABEL_FONT_PX = 13           # the host draws a Button's label in Segoe UI 13 px (POB 27, Билды 39, Тикеты 42, Расходы 50 px)
CARD_H_TOL = 3.0             # a card of the tree and its card on the picture differ by at most this (px rounding)
PAGE_TOP_IN, PAGE_BOTTOM_IN = 23, 14  # the page the pane's content is clipped to lies this far inside its background (a scrolled card is cut at 85 and 1376 of 62..1390)
HOST_CELL_PX = 950 / 120.0   # a cell of the host's grid: the cards of a 120-column pane are 950 px wide
PUT_BACK_REST_S = 0.2        # after the pointer is put back the host needs a frame to take its light off (a look taken at once still shows it)
EDGE_IN = 3                  # a press "near an edge" is this many px inside the face
# What a press does, by the element's key (hooks/register.tsx, hooks/addon.tsx): the ones that act OUTSIDE the pane are never pressed here.
ACTS = (("lk-", "opens the ticket in the browser"), ("tl-", "opens the ticket in the browser"),
        ("open-pob-", "opens Path of Building"), ("open-author-", "opens Path of Building"),
        ("res-go-", "reserves slots of the machine"), ("res-n-", "part of the reserve control"), ("res-m-", "part of the reserve control"))


class MappingError(RuntimeError):
    """The drawn tree does not lie on the picture (a stale tree, another tab, a covered pane)."""


class NoElement(LookupError):
    """No element, or more than one, answers to the name in this state."""


class Miss(RuntimeError):
    """An after-picture does not show the pointer on the element it was sent to."""


# ---------------------------------------------------------------------------------------------- the pictures

def to_image(shot) -> Image.Image:
    """A PIL RGB image from a path, an Image or a (w, h, rgb bytes) capture of pane_look.screen_rgb."""
    if isinstance(shot, Image.Image):
        return shot
    if isinstance(shot, (str, Path)):
        return Image.open(shot).convert("RGB")
    w, h, rgb = shot
    return Image.frombytes("RGB", (w, h), rgb)


# The pointer as drawn on an after-picture: the classic arrow, its tip (the hot spot) at the system's pointer position.
_ARROW = [(0, 0), (0, 16), (4, 12), (7, 18), (9, 17), (6, 11), (11, 11)]


def draw_pointer(im: Image.Image, x: int, y: int) -> Image.Image:
    """A copy of im with the pointer drawn at (x, y): a white arrow outlined in POINTER, its tip at the point."""
    out = im.copy()
    d = ImageDraw.Draw(out)
    d.polygon([(x + a, y + b) for a, b in _ARROW], fill=(255, 255, 255), outline=POINTER)
    d.point((x, y), fill=POINTER)
    return out


def find_pointer(shot):
    """(x, y) of the pointer drawn on an after-picture (the arrow's tip: the topmost, then leftmost POINTER pixel
    with the arrow's left edge under it), or None when the picture shows no pointer."""
    im = to_image(shot)
    r, g, b = im.split()
    mask = ImageChops.multiply(ImageChops.multiply(r.point(lambda v: 255 if v == 255 else 0),
                                                   g.point(lambda v: 255 if v == 0 else 0)),
                               b.point(lambda v: 255 if v == 255 else 0))
    box = mask.getbbox()
    if box is None:
        return None
    px = mask.load()
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            if px[x, y] and all(y + k < im.height and px[x, y + k] for k in range(1, 6)):
                return x, y
    return None


def inside(rect, x, y) -> bool:
    """True when (x, y) lies in rect = (left, top, right, bottom), all four inclusive."""
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def check_after(after_png, rect, origin=(0, 0)):
    """The pointer's screen position read OFF an after-picture; raises Miss when the picture shows no pointer or shows
    it outside rect (screen px, inclusive). `origin` = the screen position of the picture's top-left pixel (a crop)."""
    at = find_pointer(after_png)
    if at is None:
        raise Miss("the after-picture %s shows no pointer" % after_png)
    x, y = at[0] + origin[0], at[1] + origin[1]
    if not inside(rect, x, y):
        raise Miss("the after-picture %s shows the pointer at (%d, %d), outside the element's rectangle %s" % (after_png, x, y, tuple(rect)))
    return x, y


def _lightening(before, after, box):
    """An L image of box: how much lighter each pixel got (its lightest channel; a coloured glyph under a light loses in one channel only)."""
    cr, cg, cb = ImageChops.subtract(to_image(after).crop(box), to_image(before).crop(box)).split()
    return ImageChops.lighter(ImageChops.lighter(cr, cg), cb)


def lit_region(before, after, x: int, y: int, reach: int = 700, min_delta: int = 6):
    """What lit under the point (x, y) between two pictures: {rect: (l, t, r, b) inclusive, delta: its lightening}
    of the light shape that holds the point, or None when nothing lit at the point.
    The host lights an element with a translucent light rectangle: every pixel of it gets lighter by about the same
    amount, so the shape is the run of columns / rows around the point whose lightening is near the point's own.
    A wider, fainter shape (a row's own light under the element's) is not part of it."""
    a = to_image(before)
    w, h = a.size
    box = (max(0, x - reach), max(0, y - 40), min(w, x + reach + 1), min(h, y + 41))
    da = _lightening(a, after, box)
    px = da.load()
    bw, bh = da.size
    ox, oy = x - box[0], y - box[1]
    # the lightening at the point: the commonest one over a 21x17 block. The bare face of the shape gets one value; a
    # glyph under it changes less (a drawn face) or more (a dim host label that turns bright), and is the minority
    block = [px[i, j] for i in range(max(0, ox - 10), min(bw, ox + 11)) for j in range(max(0, oy - 8), min(bh, oy + 9))]
    lit = [v for v in block if v >= min_delta]
    if len(lit) < 0.35 * len(block):
        return None
    here = max(set(lit), key=lit.count)
    # an element's light lies ON its row's fainter light (measured 2026-10-14: a row 15, the number on it 30), so the
    # shape is cut where the lightening falls a step under the point's own, not at a share of it
    need = max(min_delta, here - max(2, here * 0.2))

    def share(cells):
        cells = list(cells)
        return sum(1 for v in cells if v >= need) / float(len(cells) or 1)

    i0, i1 = max(0, ox - 10), min(bw - 1, ox + 10)
    top = oy
    while top > 0 and share(px[i, top - 1] for i in range(i0, i1 + 1)) >= 0.4:
        top -= 1
    bottom = oy
    while bottom < bh - 1 and share(px[i, bottom + 1] for i in range(i0, i1 + 1)) >= 0.4:
        bottom += 1
    # a glyph never fills a whole column of the shape's height, a rounded corner leaves most of the edge column lit
    left = ox
    while left > 0 and share(px[left - 1, j] for j in range(top, bottom + 1)) >= 0.3:
        left -= 1
    right = ox
    while right < bw - 1 and share(px[right + 1, j] for j in range(top, bottom + 1)) >= 0.3:
        right += 1
    return {"rect": (left + box[0], top + box[1], right + box[0], bottom + box[1]), "delta": here}


def light_rect(before, after, rect, pad: int = 26, min_delta: int = 6):
    """The light the host laid on a button, measured round its laid-out rectangle (l, t, r, b inclusive):
    {rect, delta} or None when the rectangle did not light. Unlike lit_region it does not start from one point: a title's
    dense glyphs under the pointer hide the light there (2026-10-14: a run title's light was read as 3 px wide, its
    right end was then taken from the layout, 5 px past the real light, and four presses went beside the button).
    The level is the commonest lightening inside the rectangle; the shape is the rows and columns lit at that level
    (a glyph never fills a whole row or column of the shape)."""
    a = to_image(before)
    l, t, r, b = rect
    box = (max(0, l - pad), max(0, t - 10), min(a.width, r + pad + 1), min(a.height, b + 11))
    da = _lightening(a, after, box)
    bw, bh = da.size
    il, it, ir, ib = l - box[0] + 2, t - box[1] + 2, r - box[0] - 1, b - box[1] - 1
    if ir <= il or ib <= it:
        return None
    hist = da.crop((il, it, ir, ib)).histogram()
    total, lit = sum(hist), sum(hist[min_delta:])
    if not total or lit < 0.35 * total:
        return None
    here = max(range(min_delta, 256), key=lambda v: hist[v])
    need = max(min_delta, here - max(2, here * 0.2))
    px = da.load()

    def share(cells):
        cells = list(cells)
        return sum(1 for v in cells if v >= need) / float(len(cells) or 1)

    # a row through bright glyphs can fall under the level (they are near white already): the lit rows up to 8 apart are one shape
    rows = [j for j in range(bh) if share(px[i, j] for i in range(il, ir)) >= 0.3]
    mid = (it + ib) // 2
    band = [j for j in rows if abs(j - mid) <= 4]
    if not band:
        return None
    top, bottom = min(band), max(band)
    for j in sorted((j for j in rows if j < top), reverse=True):
        if top - j > 8:
            break
        top = j
    for j in sorted(j for j in rows if j > bottom):
        if j - bottom > 8:
            break
        bottom = j
    cx = (il + ir) // 2
    left = cx
    while left > 0 and share(px[left - 1, j] for j in range(top, bottom + 1)) >= 0.3:
        left -= 1
    right = cx
    while right < bw - 1 and share(px[right + 1, j] for j in range(top, bottom + 1)) >= 0.3:
        right += 1
    if share(px[cx, j] for j in range(top, bottom + 1)) < 0.3 and right - left < 4:
        return None
    return {"rect": (left + box[0], top + box[1], right + box[0], bottom + box[1]), "delta": here}


def light_band(before, after, rect, pad: int = 14, min_delta: int = 6):
    """The rows of the screen a ROW's own light covers, measured round its rectangle (l, t, r, b inclusive):
    (top, bottom), or None when no band lit there. A row is as wide as its card, so half of a long stretch of it
    lightening is its band (the words under the light are the smaller half); the band nearest the rectangle wins."""
    a = to_image(before)
    l, t, r, b = rect
    x0, x1 = l + 16, max(l + 40, min(r - 16, l + 640))
    box = (x0, max(0, t - pad), x1, min(a.height, b + pad + 1))
    da = _lightening(a, after, box)
    px = da.load()
    w, h = da.size
    xs = range(0, w, 3)
    lit = [sum(1 for i in xs if px[i, j] >= min_delta) >= 0.5 * len(xs) for j in range(h)]
    runs, j = [], 0
    while j < h:
        if lit[j]:
            s = j
            while j < h and lit[j]:
                j += 1
            if j - s >= 6:
                runs.append((s + box[1], j - 1 + box[1]))
        else:
            j += 1
    if not runs:
        return None
    mid = (t + b) / 2.0
    return min(runs, key=lambda run: abs((run[0] + run[1]) / 2.0 - mid))


def light_in(before, after, rect, min_delta: int = 6) -> int:
    """The commonest lightening of the pixels of rect (l, t, r, b inclusive) between two pictures; 0 when under 35 % of them got lighter."""
    a = to_image(before)
    box = (max(0, rect[0]), max(0, rect[1]), min(a.width, rect[2] + 1), min(a.height, rect[3] + 1))
    if box[2] <= box[0] or box[3] <= box[1]:
        return 0
    hist = _lightening(a, after, box).histogram()
    total = sum(hist)
    lit = sum(hist[min_delta:])
    if lit < 0.35 * total:
        return 0
    return max(range(min_delta, 256), key=lambda v: hist[v])


def changed_share(before, after, rect, skip=None) -> float:
    """The share of the pixels of rect (l, t, r, b inclusive) that differ between two pictures by more than 5 a channel;
    `skip` = a rectangle left out (the element under the pointer, whose own light is not a change of the pane)."""
    a, b = to_image(before), to_image(after)
    box = (max(0, rect[0]), max(0, rect[1]), min(a.width, rect[2] + 1), min(a.height, rect[3] + 1))
    if box[2] <= box[0] or box[3] <= box[1]:
        return 0.0
    d = ImageChops.difference(a.crop(box), b.crop(box)).convert("L").point(lambda v: 255 if v > 5 else 0)
    if skip is not None:
        ImageDraw.Draw(d).rectangle((skip[0] - box[0], skip[1] - box[1], skip[2] - box[0], skip[3] - box[1]), fill=0)
    return d.histogram()[255] / float((box[2] - box[0]) * (box[3] - box[1]))


def ink_runs(shot, rect, reach: int = 14, gap: int = 7) -> list:
    """The glyphs the picture draws under and beside a rectangle (l, t, r, b inclusive): [(first x, last x)] of every run
    of glyph columns in the strip `reach` px past both ends. A glyph column = a pixel 40 grey levels off the strip's own
    ground; columns up to `gap` px apart are one run (a space between two words)."""
    im = to_image(shot)
    l, t, r, b = rect
    box = (max(0, l - reach), min(t + 3, b), min(im.width, r + reach + 1), max(b - 2, t + 4))
    g = im.crop(box).convert("L")
    w, h = g.size
    if w < 1 or h < 1:
        return []
    hist = g.histogram()
    ground = max(range(256), key=lambda v: hist[v])
    px = g.load()
    ink = [any(abs(px[i, j] - ground) >= 40 for j in range(h)) for i in range(w)]
    runs, i = [], 0
    while i < w:
        if ink[i]:
            s, e = i, i
            while i < w and (ink[i] or any(ink[i + 1: i + 1 + gap])):
                if ink[i]:
                    e = i
                i += 1
            runs.append((s + box[0], e + box[0]))
        else:
            i += 1
    return runs


def ink_run(shot, rect, reach: int = 14, gap: int = 7):
    """The run of glyphs that lies most on a rectangle: (first x, last x), or None when the picture draws nothing on it."""
    l, t, r, b = rect
    on = lambda run: max(0, min(run[1], r) - max(run[0], l) + 1)
    runs = [run for run in ink_runs(shot, rect, reach, gap) if on(run) > 0]
    return max(runs, key=on) if runs else None


def face_on_picture(shot, el: dict):
    """Where the picture itself draws a button: its rectangle (l, t, r, b) FOUND there, or None when the picture draws no
    such thing at the laid-out place (the mapping is wrong: nothing is hovered or pressed). For a row, a non-clickable
    place and a Select there is no face to find: the laid-out rectangle is returned as it is.
    A label the host draws (a tab head, a pager word, a control) is found by its own glyphs: the run that starts nearest
    the laid-out start and is as wide as the label (the host's letters are a few % narrower than the laid-out ones, so a
    row of three controls drifts up to 9 px: the rectangle is taken from the glyphs, 4 px of pad each end). A blank label
    lies over a face the picture draws (a title, a number, a chevron): glyphs must start at its start."""
    rect = tuple(el["rect"])
    if el["kind"] != "button":
        return rect
    l, t, r, b = rect
    if el.get("blank") or r - l < 26:
        run = ink_run(shot, rect)
        if run is None:
            return None
        if r - l < 26 or l - 8 <= run[0] <= l + 14:
            return rect
        # a number right after a word of its own row («Билды #980», 5 px apart) is one run at a word's gap: read letter by letter
        fine = [w for w in ink_runs(shot, rect, gap=3) if w[1] >= l and w[0] <= r]
        return rect if any(l - 10 <= w[0] <= l + 12 for w in fine) else None
    want = (r - l + 1) - 2 * BTN_PAD
    fits = [run for run in ink_runs(shot, rect, reach=18) if abs((run[1] - run[0] + 1) - want) <= max(6.0, 0.08 * want)]
    if not fits:
        return None
    s, e = min(fits, key=lambda run: abs(run[0] - (l + BTN_PAD)))
    if abs(s - (l + BTN_PAD)) > 16:
        return None
    # its height too is read off the glyphs (the pager in a card's corner is drawn 8 px over where the layout puts it,
    # 2026-10-14): the host's box is one text line with the word in its middle
    im = to_image(shot)
    strip = im.crop((s, max(0, t - 10), e + 1, min(im.height, b + 11))).convert("L")
    hist = strip.histogram()
    ground = max(range(256), key=lambda v: hist[v])
    px = strip.load()
    sw, sh = strip.size
    counts = [sum(1 for i in range(sw) if abs(px[i, j] - ground) >= 40) for j in range(sh)]
    rows = [j for j, n in enumerate(counts) if 0 < n < 0.85 * sw]  # a row inked from end to end is a rule (the chosen tab's underline), not a glyph
    if rows:
        # the word's own band: the glyph rows round the one nearest the laid-out middle (the line over it is 19 px away)
        centre = (t + b) / 2.0 - max(0, t - 10)
        lo = hi = min(rows, key=lambda j: abs(j - centre))
        while any(lo - k in rows for k in (1, 2, 3)):
            lo = next(lo - k for k in (1, 2, 3) if lo - k in rows)
        while any(hi + k in rows for k in (1, 2, 3)):
            hi = next(hi + k for k in (1, 2, 3) if hi + k in rows)
        box = (0, lo, sw, hi + 1)
        mid = max(0, t - 10) + (box[1] + box[3] - 1) / 2.0
        top = int(round(mid - (b - t) / 2.0))
        if abs(top - t) <= 12:
            t, b = top, top + (b - t)
    return (int(s - BTN_PAD), t, int(e + BTN_PAD), b)


def page_shift(before, after, box, max_shift: int = 1300):
    """How far the page's content moved UP between two pictures, in px (negative = it moved down, 0 = it did not move),
    read off the pictures themselves: the shift at which the most rows of `after` are the same rows of `before`.
    `box` = the page (l, t, r, b; right and bottom exclusive). None when no shift explains the pictures (the content changed)."""
    a, b = to_image(before), to_image(after)
    l, t, r, bm = box
    xs = list(range(l + 8, r - 8, 12))

    def rows(im):
        px = im.load()
        out = []
        for y in range(t, bm):
            row = tuple(px[x, y] for x in xs)
            out.append(None if len(set(row)) == 1 else hash(row))  # a bare row says nothing about a shift
        return out
    ra, rb = rows(a), rows(b)
    n = len(ra)
    best_d, best_hit, best_tot = None, 0, 0
    for d in sorted(range(-max_shift, max_shift + 1), key=abs):  # the smallest shift wins a tie
        lo, hi = max(0, -d), min(n, n - d)
        if hi - lo < 30:
            continue
        hit = tot = 0
        for y in range(lo, hi, 2):
            if rb[y] is None:
                continue
            tot += 1
            hit += rb[y] == ra[y + d]
        if hit > best_hit:
            best_d, best_hit, best_tot = d, hit, tot
    if best_d is None or best_hit < 10 or best_hit < 0.6 * best_tot:
        return None
    return best_d


def _near(p, k, tol=2) -> bool:
    return all(abs(c - v) <= tol for c, v in zip(p, k))


def picture_cards(shot) -> dict:
    """The pane's cards as the picture shows them: {left, right: the cards' x (inclusive), cards: [(top, bottom)] top to
    bottom, viewport: (top, bottom) of the pane's own page}. Raises MappingError when the picture shows no card."""
    im = to_image(shot)
    r, g, b = im.split()
    bands = [ch.point(lambda v, k=k: 255 if abs(v - k) <= 2 else 0) for ch, k in zip((r, g, b), CARD_BG)]
    mask = ImageChops.multiply(ImageChops.multiply(bands[0], bands[1]), bands[2])
    share = list(mask.resize((im.width, 1), Image.Resampling.BOX).getdata())
    top_share = max(share, default=0)
    if top_share < 8:
        raise MappingError("the picture shows no card of the pane")
    # A card's rows are lighter tiles, so the share of card colour a column falls in its middle (2026-10-14: on the
    # readings tab the widest run of full columns was 583 px of the card's 950, and every tab head was laid 0.61 of its
    # way). The card's own edge rows are bare card colour over its whole width: the longest such run is the card.
    right = max(x for x, v in enumerate(share) if v >= 0.3 * top_share)
    px = im.load()
    left = right
    for y in range(0, im.height, 2):
        if not _near(px[right - 3, y], CARD_BG):
            continue
        x = right - 3
        while x > 0 and _near(px[x - 1, y], CARD_BG):
            x -= 1
        left = min(left, x)
    if right - left < 200:
        raise MappingError("the picture shows no card of the pane")
    # the pane's own page: the run of its background beside the cards
    gx, best, y = max(0, left - 4), (0, -1), 0
    while y < im.height:
        if _near(px[gx, y], PANE_BG):
            s = y
            while y < im.height and _near(px[gx, y], PANE_BG):
                y += 1
            if y - s > best[1] - best[0] + 1:
                best = (s, y - 1)
        else:
            y += 1
    vt, vb = best[0] + PAGE_TOP_IN, best[1] - PAGE_BOTTOM_IN
    cx, mid = left + 6, (left + right) // 2
    cards, y = [], vt
    while y <= vb:
        if _near(px[cx, y], CARD_BG):
            s = y
            while y <= vb and not _near(px[cx, y], PANE_BG):
                y += 1
            t, bt = s, y - 1
            while t > vt and not _near(px[mid, t - 1], PANE_BG):  # the rounded corner: the middle column reaches the true edge
                t -= 1
            while bt < vb and not _near(px[mid, bt + 1], PANE_BG):
                bt += 1
            if bt - t >= 20:
                cards.append((t, bt))
            y = bt + 1
        else:
            y += 1
    if not cards:
        raise MappingError("the picture shows no card of the pane")
    return {"left": left, "right": right, "cards": cards, "viewport": (vt, vb)}


# ---------------------------------------------------------------------------------------------- the state record

def read_lines(cache: Path) -> list:
    out = []
    for ln in (Path(cache) / "state.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def tree_tab(tree):
    """The tab a drawn tree shows: its `tab-<name>` Button that is not dim."""
    found = []

    def walk(n):
        if isinstance(n, dict):
            pr = n.get("props") or {}
            k = str(pr.get("key", ""))
            if n.get("type") == "Button" and k.startswith("tab-") and not pr.get("dimColor"):
                found.append(k[4:])
            for c in n.get("children") or []:
                walk(c)
    walk(tree)
    return found[0] if len(found) == 1 else None


def signature(line: dict) -> tuple:
    return (line.get("tab"), line.get("view") or "", line.get("picked"), line.get("open"))


def describe(a: tuple, b: tuple) -> str:
    """What differs between two state signatures, in the record's own words."""
    names = ("tab", "view", "picked", "open")
    short = lambda v: "-" if v in (None, "") else (str(v) if len(str(v)) <= 34 else "…" + str(v)[-30:])
    return "; ".join("%s %s -> %s" % (n, short(x), short(y)) for n, x, y in zip(names, a, b) if x != y) or "nothing"


def arrival_only(a: tuple, b: tuple) -> bool:
    """True when signature b is a with only `panel` / `squares` joined to the view: the rows of a thing opened earlier arrived."""
    if a[0] != b[0] or a[2:] != b[2:]:
        return False
    va, vb = set(a[1].split()), set(b[1].split())
    return va != vb and va <= vb and (vb - va) <= {"panel", "squares"}


def load_record(path) -> tuple:
    """A pane kept by `record`: (the screen's picture with the page at its place, the state {line, tree, count, session})."""
    path = Path(path)
    rec = json.loads(path.read_text(encoding="utf-8"))
    im = Image.new("RGB", tuple(rec["screen"]), (0, 0, 0))
    im.paste(Image.open(path.with_suffix(".png")).convert("RGB"), tuple(rec["origin"]))
    return im, dict(line=rec["line"], tree=rec["tree"], count=1, session=rec["line"].get("session"))


def read_state(cache: Path = DEFAULT_CACHE, session=None) -> dict:
    """The newest state of the pane the owner sees: {line, tree, count (lines of that session), session}.
    Every session that mounts the pane writes into the same record; the shown one is the newest that drew its data.
    Raises MappingError when the tree file is not the one the line wrote (the ring of 20 files is shared)."""
    lines = read_lines(cache)
    if session is None:
        loaded = [ln for ln in lines if ((ln.get("guard") or {}).get("measure") or 0) >= LOADED_MEASURE]
        if not loaded:
            raise MappingError("the state record holds no pane that drew its data")
        session = loaded[-1]["session"]
    mine = [ln for ln in lines if str(ln.get("session", "")).startswith(session)]
    if not mine:
        raise MappingError("the state record holds no line of session %s" % session)
    line = mine[-1]
    path = Path(cache) / "state" / str(line.get("tree"))
    try:
        text = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
        tree = json.loads(text)
    except (OSError, ValueError):
        raise MappingError("the tree file %s of the newest line is unreadable" % path.name)
    written = time.mktime(time.strptime(line["t"], "%Y-%m-%dT%H:%M:%S"))
    if abs(mtime - written) > 6 or tree_tab(tree) != line.get("tab"):
        raise MappingError("the tree file %s is not the one the line of %s wrote (another session overwrote the ring)" % (path.name, line["t"]))
    return {"line": line, "tree": tree, "count": len(mine), "session": line["session"]}


# ---------------------------------------------------------------------------------------------- the tree's elements, in pane px

_FONT = None


def _font():
    global _FONT
    if _FONT is None:
        try:
            _FONT = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", LABEL_FONT_PX)
        except OSError:
            _FONT = False
    return _FONT


def text_px(s: str) -> float:
    """The width the host draws a string at: blanks at their measured advances, words in the label font."""
    w, word = 0.0, []
    for ch in str(s) + "\0":
        if ch in ("\u2003", "\u00a0", " ", "\0"):  # the host's space is as wide as its no-break space
            if word:
                t = "".join(word)
                w += _font().getlength(t) if _font() else 7.0 * len(t)
                word = []
            w += EM_PX if ch == "\u2003" else NBSP_PX if ch in ("\u00a0", " ") else 0.0
        else:
            word.append(ch)
    return w


def acts(key: str):
    """Why a press of this element is never made here (it acts outside the pane), or None."""
    return next((why for pre, why in ACTS if str(key).startswith(pre)), None)


_GROUP = re.compile(r"<g transform=['\"]translate\(0 ([\d.]+)\)['\"]>")
_RECT = re.compile(r"<rect ([^>]*)>")
_ATTR = re.compile(r"([\w-]+)=['\"]([^'\"]*)['\"]")
_SVG_W = re.compile(r"<svg[^>]* width=['\"]([\d.]+)['\"]")


def _with_rows(tree):
    """A copy of the tree as the host draws it where pane_layout reads it otherwise: a Box that names no flexDirection is
    a row (pane_layout: a column), and marginTop={1} is half a line (pane_layout: a whole one). The second was measured
    2026-10-14 05:29: the runs card with a build open is 633 px high on the picture, 643 with a whole line, 633.5 with
    half; a card the page cuts cannot be checked by its height, and its lower rows had been laid 9 px low."""
    t = copy.deepcopy(tree)

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "Box":
                n.setdefault("props", {}).setdefault("flexDirection", "row")
                if n["props"].get("marginTop"):
                    n["props"]["marginTop"] = n["props"]["marginTop"] * 0.5
            for c in n.get("children") or []:
                walk(c)
    walk(t)
    return t


class _Lay(pane_layout.Layout):
    """pane_layout's px rules with the host's own widths (a label in its font, a blank at its advance, a Select's chrome),
    collecting what the pointer can meet: buttons, rows with a light of their own, pictures and texts."""

    def __init__(self, cell_w: float, root_w: float):
        super().__init__(1.0)
        self.col = cell_w
        self.slot = root_w  # the width a picture with no width of its own is fitted into
        self.border_x = CARD_INSET - cell_w
        self.buttons, self.rows, self.pics, self.texts, self.cards = [], [], [], [], []
        self.card = None

    def nat_w(self, n):
        if isinstance(n, str):
            return text_px(n)
        t = n.get("type")
        if t == "Button":
            return text_px(self.p(n).get("label", "")) + 2 * BTN_PAD
        if t == "Select":
            return text_px(self.select_text(n)) + SELECT_PAD
        if t == "Text":
            return sum(text_px(c) if isinstance(c, str) else self.nat_w(c) for c in n.get("children") or [])
        return super().nat_w(n)

    def nat_h(self, n):
        if isinstance(n, dict) and n.get("type") == "Select":
            return SELECT_H
        return super().nat_h(n)

    def margin_bottom(self, c) -> float:
        # the host draws marginBottom={1} as half a line under ANY Box (pane_layout halves it under a bordered one only):
        # the Tickets tab's legend stands 9.5 px over its first card, measured 2026-10-14
        return self.p(c).get("marginBottom", 0) * self.cell * 0.5

    def place(self, n, x, y, w, h=None):
        if not isinstance(n, dict):
            return super().place(n, x, y, w, h)
        t, pr = n.get("type"), self.p(n)
        if t in ("Button", "Select", "Link"):
            label = self.select_text(n) if t == "Select" else str(pr.get("label", ""))
            self.buttons.append(dict(kind="select" if t == "Select" else "button", key=str(pr.get("key", "")), label=label,
                                     x=x, y=y, w=self.nat_w(n), h=self.nat_h(n), card=self.card, dim=bool(pr.get("dimColor")),
                                     blank=label.strip(" \u2003\u00a0") == "", press=bool(n.get("press"))))
        elif t == "Text":
            s = self.text_of(n)
            if s.strip(" \u2003\u00a0"):
                self.texts.append(dict(x=x, y=y, w=self.nat_w(n), h=self.cell, text=s.strip(), card=self.card))
        elif t == "Svg":
            if pr.get("alt") != "row":
                sw, sh = self.svg_wh(n)
                src = str(pr.get("source", ""))
                fit = 1.0 if pr.get("width") is not None or not sw else min(1.0, self.slot / sw)
                self.pics.append(dict(x=x, y=y, w=sw * fit, h=sh, alt=str(pr.get("alt") or ""), source=src, fit=fit, card=self.card))
        elif t == "Box":
            key = pr.get("key")
            hh = h if h is not None else self.nat_h(n)
            outer = (self.card, self.slot)
            if isinstance(key, str) and key.startswith("card-"):
                self.card, self.slot = key, w - 2 * CARD_INSET
                self.cards.append(dict(key=key, x=x, y=y, w=w, h=hh))
            if pr.get("display") == "none":
                return  # a row's light, drawn only under the pointer: nothing of it is laid out
            light = next((c for c in n.get("children") or [] if isinstance(c, dict) and (c.get("hover") or {}).get("display")), None)
            if light is not None:
                self.rows.append(dict(kind="row", key=str(key or ""), label="", card=self.card, box=(x, y, w, hh), **self._pill(light, x, y, w, hh)))
            super().place(n, x, y, w, h)
            self.card, self.slot = outer
            return
        super().place(n, x, y, w, h)

    def _pill(self, light, x, y, w, hh) -> dict:
        """The drawn bounds of a row's light (the rounded shape its picture reveals under the pointer), in pane px."""
        svg = next((c for c in light.get("children") or [] if isinstance(c, dict) and c.get("type") == "Svg"), None)
        if svg is not None:
            src = str(self.p(svg).get("source", ""))
            m, r = _SVG_W.search(src), _RECT.search(src)
            if m and r:
                a = dict(_ATTR.findall(r.group(1)))
                fit = 1.0 if self.p(svg).get("width") is not None else min(1.0, w / float(m.group(1)))
                try:
                    return dict(x=x + float(a.get("x", 0)) * fit, y=y + float(a.get("y", 0)), w=float(a["width"]) * fit, h=float(a["height"]))
                except (KeyError, ValueError):
                    pass
        return dict(x=x, y=y, w=w, h=hh)


_TEXT = re.compile(r"<text ([^>]*)>(.*?)</text>", re.S)
_TSPAN = re.compile(r"<tspan ([^>]*)>([^<]*)</tspan>")
_TEXT_X = re.compile(r"<text [^>]*?x=['\"]([\d.]+)['\"]")


def _lines(p: dict) -> list:
    """The text lines of a picture: [(y, x, words)] in the picture's own px: one per row group of a card's rows, else one
    per line of <text> (a table's rows and head, a title, a gauge's words). y = a height inside the line's glyphs,
    x = where its first word starts (None when the markup does not say)."""
    src, out = p["source"], []
    starts = list(_GROUP.finditer(src))
    if starts:
        for i, m in enumerate(starts):
            body = src[m.end(): starts[i + 1].start() if i + 1 < len(starts) else len(src)]
            words = html.unescape(" ".join(w.strip() for w in re.findall(r">([^<>]+)<", body) if w.strip()))
            xs = [float(a) for a in _TEXT_X.findall(body)]
            if words:
                out.append((float(m.group(1)) + 5.0, min(xs) if xs else None, words))
        return out
    by = {}
    # a table's head is <text x y>, its cells are <tspan x y> inside one <text> a column
    for m in list(_TEXT.finditer(src)) + list(_TSPAN.finditer(src)):
        a = dict(_ATTR.findall(m.group(1)))
        words = html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)).strip())
        try:
            y, x = float(a["y"]) - 5.0, float(a.get("x", 0))
        except (KeyError, ValueError):
            continue
        if words:
            if a.get("text-anchor") == "end":
                x -= text_px(words)
            by.setdefault(y, []).append((x, words))
    return [(y, min(x for x, _ in ws), " ".join(w for _, w in sorted(ws))) for y, ws in sorted(by.items())]


def _in(box, x, y, pad=0) -> bool:
    return box[0] - pad <= x <= box[0] + box[2] + pad and box[1] <= y < box[1] + box[3]


def _inert(lay: _Lay) -> list:
    """What the pointer must light NOTHING on: a picture's lines no row light covers (a label row, a table's head, a
    card's title, a gauge's words), three heights of a high picture with no rows (the gauges themselves), a plain text.
    Also names every row with the words its picture draws on it."""
    boxes = [r["box"] for r in lay.rows] + [(b["x"], b["y"], b["w"], b["h"]) for b in lay.buttons]
    out = []
    for p in lay.pics:
        for yl, xl, words in _lines(p):
            y = p["y"] + yl
            x = p["x"] + (xl * p["fit"] + 6 if xl is not None else p["w"] * 0.3)
            row = next((r for r in lay.rows if r["card"] == p["card"] and _in(r["box"], x, y, 10000)), None)
            if row is not None:
                row["label"] = (row["label"] + " " + words).strip()[:90]
            elif not any(_in(b, x, y, 6) for b in boxes):
                out.append(dict(kind="inert", label=words[:60], card=p["card"], x=x - 6, y=y - 6, w=12.0, h=12.0))
        whole = (p["x"], p["y"], p["w"], p["h"])
        if p["h"] > 90 and not any(r["card"] == p["card"] and _in(whole, r["x"] + 1, r["y"] + 1) for r in lay.rows):
            for j in range(3):  # a high picture with no rows (a machine's gauges) is met at three heights too
                out.append(dict(kind="inert", label="%s, picture /%d" % (p["alt"].split("\n")[0][:30], j + 1), card=p["card"],
                                x=p["x"] + p["w"] * 0.45, y=p["y"] + p["h"] * (0.2 + 0.3 * j), w=12.0, h=12.0))
    for t in lay.texts:
        if not any(_in(b, t["x"] + 8, t["y"] + 9, 2) for b in boxes):
            out.append(dict(kind="inert", label=t["text"][:60], card=t["card"], x=t["x"] + 4, y=t["y"] + 3, w=12.0, h=12.0))
    for r in lay.rows:
        r["label"] = r["label"] or r["key"] or "row"
    return out


def tree_elements(tree, cell_w: float) -> dict:
    """Every thing of a drawn tree the pointer can meet, in pane px (the tree's own top-left = 0, 0):
    {elements: [{id, kind: button | select | row | inert, key, label, card, x, y, w, h, acts, ...}], cards: [...], cols}."""
    cols = tree_cols(tree)
    lay = _Lay(cell_w, cols * cell_w)
    lay.place(_with_rows(tree), 0.0, 0.0, cols * cell_w)
    inert = _inert(lay)  # names the rows too
    found, seen = [], {}
    for e in sorted(lay.buttons + lay.rows + inert, key=lambda e: (round(e["y"]), e["x"])):
        base = e.get("key") or "%s:%s" % (e["kind"], (e.get("card") or "pane").replace("card-", ""))
        seen[base] = seen.get(base, 0) + 1
        e["id"] = base if seen[base] == 1 and e.get("key") else "%s~%d" % (base, seen[base])
        e["acts"] = acts(e.get("key", "")) if e["kind"] in ("button", "select") else None
        e.pop("box", None)
        found.append(e)
    for e in found:
        e["name"] = _name_of(e, [r for r in found if r["kind"] == "row"])
    return {"elements": found, "cards": lay.cards, "cols": cols}


_TICKET = re.compile(r"(?:#|issue-[0-9]+-)([0-9]+)$")
_BLANKS = " " + chr(0x2003) + chr(0xA0)


def _name_of(e: dict, rows: list) -> str:
    """What a human calls the element: a drawn label's own words; for a blank label over a drawn face the ticket number its
    key names, a branch's chevron, or the words of the row it stands on."""
    label = e["label"].strip(_BLANKS)
    if e["kind"] not in ("button", "select") or label:
        return label or e["id"]
    key = e.get("key", "")
    m = _TICKET.search(key)
    if key.startswith(("lk-", "tl-")) and m:
        return "#%s (the ticket's number)" % m.group(1)
    if key.startswith("tg-"):
        return "the chevron of #%s" % key[3:]
    cy = e["y"] + e["h"] / 2
    row = next((r for r in rows if r.get("card") == e.get("card") and r["y"] - 4 <= cy <= r["y"] + r["h"] + 4), None)
    return ("the title: " + row["label"]) if row else "a drawn face"


def tree_cols(tree) -> int:
    """The pane's width in cells: the first picture is drawn W = round(cols x 7.8) + 4 px wide (hooks/register.tsx CW)."""
    found = []

    def walk(n):
        if isinstance(n, dict) and not found:
            if n.get("type") == "Svg":
                m = _SVG_W.search(str((n.get("props") or {}).get("source", "")))
                if m:
                    found.append(float(m.group(1)))
            for c in n.get("children") or []:
                walk(c)
    walk(tree)
    if not found:
        raise MappingError("the tree draws no picture: the pane has no data yet")
    return int(round((found[0] - 4) / 7.8))


# ---------------------------------------------------------------------------------------------- the tree laid on the picture

def align_cards(tree_cards: list, pic: dict, hint=None) -> list:
    """Which card of the picture each card of the tree is: [{key, dy, state: ok | stale | cut | hidden}] in the tree's order.
    The picture's cards are consecutive cards of the tree (a scrolled pane shows a middle stretch); a card is `ok` when it is
    as high on the picture as in the tree (its dy = picture top - tree top), `cut` when the page's edge cuts it (placed by
    its whole edge), `stale` when its height differs (its rows changed since the tree was written), `hidden` when not shown."""
    shown, (vt, vb) = pic["cards"], pic["viewport"]
    n, m = len(tree_cards), len(shown)
    if m > n:
        raise MappingError("the picture shows %d cards, the tree draws %d: not this state's tree" % (m, n))
    best = None
    for s in range(n - m + 1):
        row, score = [], 0
        for j, (pt, pb) in enumerate(shown):
            c = tree_cards[s + j]
            cut_top, cut_bot = pt <= vt + 2, pb >= vb - 2
            if cut_top and cut_bot:
                row.append(dict(dy=None, state="cut"))
            elif cut_top:
                row.append(dict(dy=pb + 1 - (c["y"] + c["h"]), state="cut"))
            elif cut_bot:
                row.append(dict(dy=pt - c["y"], state="cut"))
            else:
                same = abs((pb - pt + 1) - c["h"]) <= CARD_H_TOL
                score += 2 if same else 0  # a stale card keeps its dy: its TOP is where the picture shows it
                row.append(dict(dy=pt - c["y"], state="ok" if same else "stale"))
        dys = [r["dy"] for r in row if r["dy"] is not None and r["state"] != "stale"]
        spread = (max(dys) - min(dys)) if dys else 0.0
        near = -abs((dys[0] if dys else 0.0) - hint) if hint is not None else -s
        cand = ((score - (1 if spread > 3 else 0), near), s, row)
        if best is None or cand[0] > best[0]:
            best = cand
    _, s, row = best
    out = []
    for i, c in enumerate(tree_cards):
        r = row[i - s] if s <= i < s + m else dict(dy=None, state="hidden")
        out.append(dict(key=c["key"], dy=r["dy"], state=r["state"]))
    return out


class Snap:
    """One look at the pane with its tree laid on it: every element has its rectangle ON THIS PICTURE."""

    def __init__(self, im, state: dict, hint=None):
        self.im = to_image(im)
        self.line, self.session, self.count = state["line"], state["session"], state["count"]
        self.sig = signature(self.line)
        self.pic = picture_cards(self.im)
        self.left, self.right = self.pic["left"], self.pic["right"]
        self.viewport = self.pic["viewport"]
        cols = tree_cols(state["tree"])
        self.cell = (self.right - self.left + 1) / float(cols)
        if abs(self.cell - HOST_CELL_PX) > 0.2:
            raise MappingError("the cards are %d px wide on the picture, the tree draws %d columns: %.2f px a column, the host's is %.2f (the cards' edges were not found)"
                               % (self.right - self.left + 1, cols, self.cell, HOST_CELL_PX))
        got = tree_elements(state["tree"], self.cell)
        if not got["cards"]:
            raise MappingError("the tree draws no card")
        self.cards = align_cards(got["cards"], self.pic, hint)
        # A stale card still shows where its TOP is: what stands above it (the tab heads over a tab's only card) keeps its
        # place, so the tab can be left and entered again for a fresh tree (04:41: the runs card grew a row, nothing of the
        # tree lay on the picture any more, and the pass could not even press a tab head to recover).
        placed = [c for c in self.cards if c["dy"] is not None]
        if not placed:
            raise MappingError("no card of the tree lies on the picture (tab %s): the pane is covered or scrolled off its cards; cards %s"
                               % (self.line.get("tab"), [(c["key"], c["state"]) for c in self.cards]))
        self.dy = next((c["dy"] for c in placed if c["state"] != "stale"), placed[0]["dy"])
        by = {c["key"]: c for c in self.cards}
        order = [c["key"] for c in self.cards]
        tops = {c["key"]: c["y"] for c in got["cards"]}
        self.elements = []
        for e in got["elements"]:
            card = by.get(e.get("card"))
            if card is None:  # between the cards: it stands on the TOP of the next card under it (a card above may have grown)
                under = [k for k in order if tops[k] >= e["y"]]
                card = by[under[0]] if under else by[order[-1]]
                if card["dy"] is None or (not under and card["state"] == "stale"):
                    card = None
                state_of = "ok" if card else "hidden"
            else:
                state_of = card["state"]
            el = dict(e)
            if card is None or card["dy"] is None or (state_of == "stale" and e.get("card")):
                guess = self.dy if self.dy is not None else 0.0
                el["rect"] = self._rect(e, guess)
                el["state"] = "stale" if state_of == "stale" else "hidden"
            else:
                el["rect"] = self._rect(e, card["dy"])
                l, t, r, b = el["rect"]
                el["state"] = "ok" if t >= self.viewport[0] and b <= self.viewport[1] else "hidden"
                if el["state"] == "ok" and el["kind"] == "button":
                    found = face_on_picture(self.im, el)
                    el["drawn"] = found is not None
                    if found is not None:
                        el["laid"], el["rect"] = el["rect"], found
            self.elements.append(el)

    def _rect(self, e, dy):
        return (int(round(self.left + e["x"])), int(round(e["y"] + dy)),
                int(round(self.left + e["x"] + e["w"])) - 1, int(round(e["y"] + dy + e["h"])) - 1)

    def get(self, ident: str) -> dict:
        hit = [e for e in self.elements if e["id"] == ident] or [e for e in self.elements if e["id"].startswith(ident)]
        if len(hit) != 1:
            raise NoElement("%d elements match %r in this state (tab %s)" % (len(hit), ident, self.line.get("tab")))
        return hit[0]

    def point(self, el: dict, at: str = "centre", face=None):
        """A screen point of an element: its centre, or EDGE_IN px inside its left / right end. `face` = the light's own
        rectangle read off a hover picture of this element (it wins over the laid-out one)."""
        l, t, r, b = face or el["rect"]
        y = (t + b) // 2
        if at == "left":
            return l + EDGE_IN, y
        if at == "right":
            return r - EDGE_IN, y
        x = (l + r) // 2
        if el["kind"] == "row":  # not on a button that stands on the row
            others = [o["rect"] for o in self.elements if o["kind"] in ("button", "select") and o is not el]
            for share in (0.5, 0.3, 0.7, 0.15, 0.85, 0.05):
                x = int(l + (r - l) * share)
                if not any(inside((o[0] - 6, o[1] - 2, o[2] + 6, o[3] + 2), x, y) for o in others):
                    break
        return x, y

    def overlay(self, out) -> None:
        """The picture with every element's rectangle drawn over it (a button blue, one never pressed orange, a row green,
        an inert place a yellow cross), cut to the pane."""
        im = self.im.copy()
        d = ImageDraw.Draw(im)
        for n, e in enumerate(self.elements):
            if e["state"] != "ok":
                continue
            l, t, r, b = e["rect"]
            if e["kind"] == "inert":
                x, y = self.point(e)
                d.line([(x - 5, y), (x + 5, y)], fill=(255, 220, 0))
                d.line([(x, y - 5), (x, y + 5)], fill=(255, 220, 0))
            elif e["kind"] == "row":
                d.rectangle((l, t, r, b), outline=(60, 200, 90))
            else:
                colour = (255, 40, 40) if e.get("drawn") is False else (255, 150, 0) if e["acts"] else (80, 170, 255)
                d.rectangle((l, t, r, b), outline=colour)
                d.text((l + 1, t - 11), str(n), fill=colour)
        im.crop((max(0, self.left - 12), max(0, self.viewport[0] - 4), min(im.width, self.right + 13), min(im.height, self.viewport[1] + 5))).save(out)


# ---------------------------------------------------------------------------------------------- the pointer (pane_look's)

class Shots:
    """The capture seam handed to pane_look: keeps the raw picture and the system's pointer position at that moment,
    and gives pane_look the picture to write: the pointer drawn on it, cut to `box` (l, t, r, b exclusive) when given."""

    def __init__(self, box=None):
        self.raw, self.pos, self.box = None, None, box

    def __call__(self):
        w, h, rgb = pane_look.screen_rgb()
        self.pos = pane_look.mouse_pos()
        self.raw = Image.frombytes("RGB", (w, h), rgb)
        marked = draw_pointer(self.raw, *self.pos)
        if self.box is not None:
            marked = marked.crop(self.box)
        return marked.width, marked.height, marked.tobytes()


def look() -> Image.Image:
    """The screen now, no pointer moved."""
    return to_image(pane_look.screen_rgb())


def _run(fn, *args, **kw):
    said = []
    if not pane_look.wait_for_pause(say=said.append):
        raise SystemExit("owner active: no pause in 10 minutes; nothing moved")
    code = fn(*args, say=said.append, **kw)
    if code:
        raise SystemExit("pane_look refused (%d): %s" % (code, "; ".join(map(str, said))))
    time.sleep(PUT_BACK_REST_S)


def raw_hover(x: int, y: int, out, box=None):
    """pane_look's hover at a point; returns (raw after-picture, pointer position at the look). The png at `out` has the pointer drawn."""
    shots = Shots(box)
    _run(pane_look.do_hover, int(x), int(y), str(out), capture=shots)
    return shots.raw, shots.pos


def raw_press(x: int, y: int, out, box=None):
    """pane_look's press at a point, as a human presses: no dwell, one click; the look 600 ms later, the pointer still there."""
    shots = Shots(box)
    _run(pane_look.do_press, int(x), int(y), no_dwell=True, times=1, out=str(out), capture=shots)
    return shots.raw, shots.pos


def raw_scroll(x: int, y: int, notches: int) -> None:
    _run(pane_look.do_scroll, int(x), int(y), int(notches))


def _name(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z_#.-]+", "_", str(s))[:60].strip("_") or "el"


class Pane:
    """The live pane: its elements now, and the actions on them."""

    def __init__(self, out_dir, cache: Path = DEFAULT_CACHE, session=None):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.cache, self.session = Path(cache), session
        self.hint = None
        self.n = len(list(self.out.glob("*.png")))
        self.notch_px = 100.0
        self.adj = {}
        self.line_wait = 2.5     # how long a press waits for the pane's next state line before it counts as a try that did nothing
        self.keep_raw = False    # a hover also writes the look before it and the look under the pointer without the drawn pointer (a test's fixture)

    def snap(self) -> Snap:
        if (self.out / "STOP").exists():  # the way to end a pass: between two actions, the pointer put back
            raise SystemExit("stopped: %s exists" % (self.out / "STOP"))
        state = read_state(self.cache, self.session)
        self.session = state["session"]
        s = Snap(look(), state, self.hint)
        self.hint = s.dy
        return s

    def _file(self, *parts) -> Path:
        self.n += 1
        return self.out / ("%04d-%s.png" % (self.n, "-".join(_name(p) for p in parts)))

    def _pane_box(self, s: Snap, rect=None, pad=70):
        """The part of the screen a look is written as: the pane's width, the whole page or `pad` px round a rectangle."""
        l, r = max(0, s.left - 12), min(s.im.width, s.right + 13)
        if rect is None:
            return (l, max(0, s.viewport[0] - 30), r, min(s.im.height, s.viewport[1] + 5))
        return (l, max(0, rect[1] - pad), r, min(s.im.height, rect[3] + pad + 1))

    def bring(self, ident: str):
        """Scroll until the element lies whole on the page; returns (snap, element). Raises MappingError when it cannot be shown."""
        for _ in range(14):
            s = self.snap()
            el = s.get(ident)
            if el["state"] == "ok":
                if el.get("drawn") is False:
                    raise MappingError("the picture does not draw %s (%s) under its rectangle %s: glyphs found %s"
                                       % (ident, el["label"].strip() or "a drawn face", el["rect"], ink_run(s.im, el["rect"])))
                return s, el
            if el["state"] == "stale":
                raise MappingError("the card of %s changed since the tree was written (its height differs on the picture): re-enter the state" % ident)
            vt, vb = s.viewport
            mid = (vt + vb) // 2
            off = (el["rect"][1] + el["rect"][3]) / 2 - mid
            notches = int(max(1, min(12, round(abs(off) / self.notch_px))))
            raw_scroll((s.left + s.right) // 2, mid, -notches if off > 0 else notches)
            moved = page_shift(s.im, look(), (s.left, vt, s.right + 1, vb + 1))
            if moved == 0:
                raise MappingError("the pane does not scroll further and %s is still off the page" % ident)
            if moved:
                self.notch_px = max(20.0, abs(moved) / float(notches))
        raise MappingError("%s could not be brought onto the page" % ident)

    def note(self, rec: dict) -> dict:
        """Every action is written down as it is made: one JSON line in <out>/log.jsonl."""
        rec.setdefault("t", time.strftime("%H:%M:%S"))
        with open(self.out / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def _face(self, el: dict):
        """The element's rectangle on this picture, set right by what its own hover picture showed (the light's edges
        against the laid-out ones); never a remembered place: the offsets ride on the rectangle mapped now."""
        adj = self.adj.get((el["id"], el["label"]))
        return tuple(v + d for v, d in zip(el["rect"], adj)) if adj else tuple(el["rect"])

    def hover(self, ident: str, at: str = "centre", _again: bool = False) -> dict:
        """Hover an element; the record says where the after-picture shows the pointer and what lit. Raises Miss when the
        picture does not show the pointer inside the element's rectangle."""
        s, el = self.bring(ident)
        face = self._face(el)
        x, y = s.point(el, at, face)
        box = self._pane_box(s, el["rect"])
        out = self._file(s.line.get("tab"), el["id"], "hover", at)
        after, pos = raw_hover(x, y, out, box)
        if self.keep_raw:
            s.im.crop(box).save(out.with_name(out.stem + ".base.png"))
            after.crop(box).save(out.with_name(out.stem + ".raw.png"))
        rec = dict(action="hover", id=el["id"], kind=el["kind"], label=el["label"], name=el.get("name"), at=at, rect=list(face), sent=[x, y], screen=list(s.im.size),
                   pic=out.name, origin=[box[0], box[1]], tab=s.line.get("tab"), view=s.line.get("view") or "",
                   picked=s.line.get("picked"), open=s.line.get("open"), acts=el.get("acts"))
        try:
            rec["pointer"] = list(check_after(out, face, (box[0], box[1])))
        except Miss as e:
            self.note(dict(rec, miss=str(e)))
            raise
        rec.update(self._light(s.im, el, face, after, pos))
        if el["kind"] == "button" and not rec["lights"]:
            # "it lights nothing" is said of a button only after a second look with a fresh look before it (04:41: one
            # look of a pager word read no light although its picture shows one; five looks after it all read it)
            before = look()
            again_png = self._file(s.line.get("tab"), el["id"], "hover", at, "again")
            again, pos2 = raw_hover(x, y, again_png, box)
            second = self._light(before, el, face, again, pos2)
            rec["first_look_lit"] = False
            rec["pic_again"] = again_png.name
            rec.update(second)
        if el["kind"] == "row" and rec["lights"]:
            # the row that lit must be THIS row: its band lies on the rectangle. A band beside it (the layout drifted down
            # a high card the page cuts) is the neighbour's light or this row's edge: the tool's miss, set right and redone
            band = light_band(s.im, after, face)
            rec["band"] = list(band) if band else None
            if band and (abs(band[0] - face[1]) > 4 or abs(band[1] - face[3]) > 4):
                rec["drift"] = [band[0] - face[1], band[1] - face[3]]
                if not _again:
                    self.note(dict(rec, miss="the row's light stands %+d / %+d px off its rectangle %s: the pointer was at its edge or on its neighbour"
                                             % (rec["drift"][0], rec["drift"][1], list(face))))
                    old = self.adj.get((el["id"], el["label"]), (0, 0, 0, 0))
                    self.adj[(el["id"], el["label"])] = (old[0], old[1] + rec["drift"][0], old[2], old[3] + rec["drift"][1])
                    return self.hover(ident, at, _again=True)
        if el["kind"] == "button":
            run = ink_run(s.im, el["rect"])
            rec["glyphs"] = list(run) if run else None  # where the picture draws the face, beside where its light stands
            if rec["lights"] and at == "centre" and rec["lit"]:
                self.adj[(el["id"], el["label"])] = tuple(a - b for a, b in zip(rec["lit"], el["rect"]))
                rec["off"] = [a - b for a, b in zip(rec["lit"], el["rect"])]
        return self.note(rec)

    def _light(self, base, el: dict, face, after, pos) -> dict:
        """What lit under the pointer, read off the look before and the look with the pointer on the element."""
        l, t, r, b = face
        beside = max(light_in(base, after, (l - 16, t + 2, l - 6, b - 2)), light_in(base, after, (r + 6, t + 2, r + 16, b - 2)))
        if el["kind"] in ("button", "select"):
            lit = light_rect(base, after, face)
            # the element's own light: under the pointer, and lighter than the row beside it
            own = bool(lit) and inside((lit["rect"][0] - 1, lit["rect"][1] - 1, lit["rect"][2] + 1, lit["rect"][3] + 1), *pos) \
                and lit["delta"] >= beside + 3
            return dict(lit=list(lit["rect"]) if lit else None, delta=lit["delta"] if lit else 0, light_beside=beside, lights=own)
        lit = lit_region(base, after, *pos)
        here = light_in(base, after, (pos[0] - 20, pos[1] - 6, pos[0] + 20, pos[1] + 6))
        return dict(lit=list(lit["rect"]) if lit else None, delta=lit["delta"] if lit else here, light_beside=beside,
                    lights=bool(lit) or here > 0)

    def press(self, ident: str, at: str = "centre", tries: int = 4) -> dict:
        """Press an element as a human does (no dwell) until the pane's state changes, at most `tries` times; the record
        counts the tries. Each try maps the element afresh. A try that changed nothing counts against the ELEMENT only when
        a picture shows its light under the pointer at that very point; else it is the tool's miss (Miss)."""
        s0 = self.snap()
        el0 = s0.get(ident)
        why = el0.get("acts")
        if why:
            raise SystemExit("refused: %s is never pressed here: %s" % (ident, why))
        if at != "centre" and el0["kind"] == "button" and (el0["id"], el0["label"]) not in self.adj:
            self.hover(ident)  # an end of the face is an end of its LIGHT: measured on a picture first
        rec = dict(action="press", id=el0["id"], kind=el0["kind"], label=el0["label"], name=el0.get("name"), at=at, tab=s0.line.get("tab"),
                   view=s0.line.get("view") or "", picked=s0.line.get("picked"), open=s0.line.get("open"),
                   tries=0, pressed=False, change="nothing", pics=[], on_light=[])
        prev = None
        for k in range(1, tries + 1):
            if prev is not None:
                late = self._new_line(prev, 0)
                if late is not None:  # the try before did press: the record only came after the wait
                    rec["pressed"], rec["change"] = True, describe(prev.sig, signature(late)) + " (the record came late)"
                    rec["after_sig"] = list(signature(late))
                    return self.note(rec)
            s, el = self.bring(ident)
            face = self._face(el)
            measured = (el["id"], el["label"]) in self.adj
            x, y = s.point(el, at, face)
            if at != "centre" and not measured:  # no light was read for it: stay well inside the laid-out end
                inset = max(8, int(0.12 * (face[2] - face[0])))
                x = face[0] + inset if at == "left" else face[2] - inset
            rec["face"] = "its light on a hover picture" if measured else "the layout"
            box = self._pane_box(s)
            out = self._file(s.line.get("tab"), el["id"], "press", at, "try%d" % k)
            after, pos = raw_press(x, y, out, box)
            rec["tries"] = k
            rec["pics"].append(out.name)
            rec["rect"], rec["sent"], rec["origin"] = list(face), [x, y], [box[0], box[1]]
            try:
                rec["pointer"] = list(check_after(out, face, (box[0], box[1])))
            except Miss as e:
                self.note(dict(rec, miss=str(e)))
                raise
            line = self._new_line(s, self.line_wait)
            if line is not None:
                rec["pressed"], rec["change"] = True, describe(s.sig, signature(line))
                rec["after_sig"] = list(signature(line))
                return self.note(rec)
            if el["kind"] == "select":  # a Select opens the host's own menu: the picture changes, the state record does not
                pane = (s.left, s.viewport[0], s.right, s.viewport[1])
                l, t, r, b = face
                moved = changed_share(s.im, after, pane, skip=(l - 30, t - 12, r + 30, b + 12))
                rec["picture_changed"] = round(moved, 4)
                if moved > 0.002:
                    rec["pressed"], rec["change"] = True, "the picture changed (%.2f %% of the page), the state record did not" % (moved * 100)
                    return self.note(rec)
            # nothing changed: was the pointer on the element at all? Its own light under the pointer says so
            # (the look is taken 600 ms after the click, the pointer still there)
            on = self._light(s.im, el, face, after, pos)["lights"]
            if not on and el["kind"] == "button":
                shown = self._file(s.line.get("tab"), el["id"], "press", at, "try%d-check" % k)
                look_before = look()  # a fresh look: the pointer is put back, the pane is as the failed press left it
                again, pos2 = raw_hover(x, y, shown, box)
                on = self._light(look_before, el, face, again, pos2)["lights"]
                rec["pics"].append(shown.name)
                if not on:
                    msg = "try %d at (%d, %d) changed nothing and no light of %s stands under the pointer there: the press was beside the element" % (k, x, y, ident)
                    self.note(dict(rec, miss=msg))
                    raise Miss(msg)
            rec["on_light"].append(bool(on))
            prev = s
        return self.note(rec)

    def record(self, name: str) -> Path:
        """The pane as it is now, kept for a test: <name>.png (the page, cut out of the screen) and <name>.json (where the cut
        lies, the state line and the drawn tree). `load_record` gives back the picture and the state a Snap is made of."""
        s = self.settle()
        box = self._pane_box(s)
        s.im.crop(box).save(self.out / ("%s.png" % name))
        path = self.out / ("%s.json" % name)
        state = read_state(self.cache, self.session)
        path.write_text(json.dumps(dict(origin=[box[0], box[1]], screen=list(s.im.size), line=state["line"], tree=state["tree"]),
                                   ensure_ascii=False), encoding="utf-8")
        return path

    def refresh(self) -> None:
        """Have the pane write its tree again (it writes one only when its state changes): leave the tab and come back."""
        s = self.snap()
        tab = str(s.line.get("tab"))
        away = "tab-progress" if tab != "progress" else "tab-tickets"
        a = self.press(away)
        b = self.press("tab-%s" % tab)
        if not (a["pressed"] and b["pressed"]):
            raise MappingError("the tree could not be written again: the tab heads did not press (%s, %s)" % (a["tries"], b["tries"]))

    def _new_line(self, s: Snap, wait_s: float):
        """The line the shown session wrote after snap `s` that says the STATE changed, waiting up to wait_s for it; None
        when it wrote none. A line that only says an opened thing's own rows arrived (`panel`, `squares` joined the view:
        the answer to an earlier press) is not this press's change."""
        end = time.monotonic() + wait_s
        while True:
            mine = [ln for ln in read_lines(self.cache) if ln.get("session") == s.session]
            if len(mine) > s.count or (mine and mine[-1].get("t") != s.line.get("t")):
                if not arrival_only(s.sig, signature(mine[-1])):
                    time.sleep(0.25)  # the tree file is written before the line; the picture follows within a frame
                    return mine[-1]
            if time.monotonic() >= end:
                return None
            time.sleep(0.1)

    def settle(self, wait_s: float = 8.0) -> Snap:
        """Wait until the picture shows what the newest tree draws (an opened block's rows arrive a moment after the
        press: the pane writes a second line then); returns that snap, or raises MappingError after wait_s."""
        end, last = time.monotonic() + wait_s, None
        while True:
            try:
                s = self.snap()
                if not any(c["state"] == "stale" for c in s.cards):
                    return s
                last = MappingError("cards %s differ from the tree" % [c["key"] for c in s.cards if c["state"] == "stale"])
            except MappingError as e:
                last = e
            if time.monotonic() >= end:
                raise last
            time.sleep(0.4)

    def shoot(self, name: str) -> Path:
        """The whole tab in one picture: the page from its top, scrolled a page at a time and stitched by how far the
        pictures themselves say the content moved (never by a count of notches). Leaves the pane scrolled back to its top."""
        pic = self._top()
        l, r, (vt, vb) = pic["left"], pic["right"], pic["viewport"]
        page = (l, vt, r + 1, vb + 1)
        cut_box = (max(0, l - 12), vt, r + 13, vb + 1)
        im = look()
        parts, at = [(0, im.crop(cut_box))], 0
        for _ in range(40):
            raw_scroll((l + r) // 2, (vt + vb) // 2, -6)
            nxt = look()
            moved = page_shift(im, nxt, page)
            if not moved or moved < 0:
                break
            at += moved
            parts.append((at, nxt.crop(cut_box)))
            im = nxt
        self._top()
        sheet = Image.new("RGB", (parts[0][1].width, parts[-1][0] + parts[-1][1].height), PANE_BG)
        for off, part in parts:
            sheet.paste(part, (0, off))
        out = self.out / ("%s-whole.png" % _name(name))
        sheet.save(out)
        return out

    def _top(self) -> dict:
        """Scroll the page to its top (until a scroll moves nothing); returns the picture's cards there."""
        for _ in range(12):
            im = look()
            pic = picture_cards(im)
            l, r, (vt, vb) = pic["left"], pic["right"], pic["viewport"]
            raw_scroll((l + r) // 2, (vt + vb) // 2, 12)
            if page_shift(im, look(), (l, vt, r + 1, vb + 1)) == 0:
                return picture_cards(look())
        raise MappingError("the page does not come to its top")


# ---------------------------------------------------------------------------------------------- the pass over a state

PLACEHOLDER_WORDS = ("ничего", "пусто")   # a row that says its list is empty
TAB_ORDER = ("main", "pob", "builds", "tickets", "cost", "progress")
COST_PERIODS, COST_GROUPS = ("day", "week", "month"), ("roles", "spawn", "days")
AT = ("centre", "left", "right")


def is_placeholder(el: dict) -> bool:
    return el["kind"] == "row" and el["label"].strip().lower() in PLACEHOLDER_WORDS


def attempt(pane: "Pane", ident: str, fn):
    """One action of the pass; a miss or a stale card is written down and never stops the pass. A stale card is met once
    by having the pane write its tree again."""
    for n in (1, 2):
        try:
            return fn()
        except MappingError as e:
            pane.note(dict(action="note", id=ident, problem="mapping: %s" % e))
            if n == 2:
                return None
            try:
                pane.refresh()
                pane.settle()
            except (MappingError, Miss, NoElement) as e2:
                pane.note(dict(action="note", id=ident, problem="could not re-enter the state: %s" % e2))
                return None
        except Miss as e:
            return None  # written down by the action itself
        except NoElement as e:
            pane.note(dict(action="note", id=ident, problem="gone: %s" % e))
            return None


def selected(snap: Snap, prefix: str):
    """The chosen option of a switch (a tab head, a period, a group): the one Button of the prefix that is not dim."""
    on = [e["id"] for e in snap.elements if e["kind"] == "button" and e["id"].startswith(prefix) and not e["dim"]]
    return on[0] if len(on) == 1 else None


def calm(pane: "Pane"):
    """Wait for the picture to show the newest tree; a block that never arrives is written down, the pass goes on."""
    try:
        return pane.settle()
    except MappingError as e:
        pane.note(dict(action="note", id="-", problem="the picture did not come to the tree in 8 s: %s" % e))
        try:
            pane.refresh()
            return pane.settle()
        except (MappingError, Miss, NoElement) as e2:
            pane.note(dict(action="note", id="-", problem="could not re-enter the state: %s" % e2))
            return None


def goto(pane: "Pane", ident: str, prefix: str) -> None:
    """Choose an option of a switch unless it is chosen already (a press on the chosen one changes nothing)."""
    calm(pane)
    if selected(pane.snap(), prefix) != ident:
        attempt(pane, ident, lambda: pane.press(ident))
        calm(pane)


def walk_hover(pane: "Pane", kinds=("button", "select", "row", "inert"), skip=()) -> int:
    """One hover on every element of the current state, top to bottom (the pane is scrolled to each)."""
    calm(pane)
    ids = [e["id"] for e in pane.snap().elements if e["kind"] in kinds and not e["id"].startswith(tuple(skip) or ("\0",))]
    for ident in ids:
        attempt(pane, ident, lambda: pane.hover(ident))
    return len(ids)


def press_switch(pane: "Pane", prefix: str) -> None:
    """Every option of a switch pressed at the centre and near both ends, the chosen one too: away and back."""
    s = pane.snap()
    opts = [e["id"] for e in s.elements if e["kind"] == "button" and e["id"].startswith(prefix)]
    home = selected(s, prefix)
    if home is None:
        pane.note(dict(action="note", id=prefix, problem="the switch shows no single chosen option"))
        return
    for other in [o for o in opts if o != home]:
        for at in AT:
            attempt(pane, other, lambda: pane.press(other, at))
            calm(pane)
            attempt(pane, home, lambda: pane.press(home, at))
            calm(pane)
    goto(pane, home, prefix)


def press_pager(pane: "Pane", older: str = "hist-next", newer: str = "hist-prev") -> None:
    """A pager's two words pressed at the centre and near both ends: a page on and back."""
    for at in AT:
        attempt(pane, older, lambda: pane.press(older, at))
        calm(pane)
        attempt(pane, newer, lambda: pane.press(newer, at))
        calm(pane)


def press_toggle(pane: "Pane", ident: str, first_of=None) -> None:
    """An element that opens and closes (a run's title, a build, a reading, a branch): pressed at the centre and near both
    ends, then once more when that leaves it open. `first_of` = another run's title: the first running run is what the
    card shows when nothing is picked, so its own press changes nothing then; the other one is picked first."""
    calm(pane)
    home = pane.snap().sig
    for at in AT:
        if first_of and pane.snap().line.get("picked") is None:
            attempt(pane, first_of, lambda: pane.press(first_of))
            calm(pane)
        attempt(pane, ident, lambda: pane.press(ident, at))
        calm(pane)
    if pane.snap().sig != home:  # the third press left it open: closed by one more
        attempt(pane, ident, lambda: pane.press(ident))
        calm(pane)
    s = pane.snap()
    if s.sig != home:
        pane.note(dict(action="note", id=ident, problem="left in another state: %s" % describe(home, s.sig)))


def shots(pane: "Pane") -> list:
    """The whole of every tab and of every group x period of the cost tab, one picture each; ends where it began."""
    start = pane.snap()
    home_tab = "tab-%s" % start.line.get("tab")
    made = []
    for n, tab in enumerate(TAB_ORDER, 1):
        goto(pane, "tab-%s" % tab, "tab-")
        if tab != "cost":
            made.append(pane.shoot("before-%02d-%s" % (n, tab)))
            continue
        s = pane.snap()
        home_p, home_g = selected(s, "cost-"), selected(s, "costg-")
        for p in COST_PERIODS:
            goto(pane, "cost-%s" % p, "cost-")
            for g in COST_GROUPS:
                goto(pane, "costg-%s" % g, "costg-")
                made.append(pane.shoot("before-%02d-cost-%s-%s" % (n, p, g)))
        if home_p:
            goto(pane, home_p, "cost-")
        if home_g:
            goto(pane, home_g, "costg-")
    goto(pane, home_tab, "tab-")
    return made


def walk(pane: "Pane", press: bool = True) -> None:
    """The pass over the CURRENT state: one hover on every element; then every element that opens, switches or pages
    inside the pane pressed at its centre and near both ends, each state it opens closed again. What acts outside the
    pane is hovered only. The tab heads are pressed by `tabs`, once, from the first tab."""
    walk_hover(pane)
    if not press:
        return
    s = pane.snap()
    ids = [e["id"] for e in s.elements if e["kind"] == "button" and not e["acts"]]
    for prefix in ("cost-", "costg-"):
        if any(i.startswith(prefix) for i in ids):
            press_switch(pane, prefix)
    pagers = [i[:-5] for i in ids if i.endswith("-next") and i[:-5] + "-prev" in ids]  # hist- (finished runs), rd- (readings)
    for stem in pagers:
        press_pager(pane, stem + "-next", stem + "-prev")
    runs = [i for i in ids if i.startswith(("run-pick-", "run-hist-"))]
    for i in ids:
        if i.startswith(("tab-", "cost-", "costg-")) or i.endswith(("-next", "-prev")):
            continue
        first = next((r for r in runs if r != i), None) if runs and i == runs[0] and i.startswith("run-pick-") else None
        press_toggle(pane, i, first)


def tour(pane: "Pane", overlays=None) -> None:
    """The whole pass in ONE process (a file <out>/STOP ends it between two actions): every tab, the tab heads pressed
    from the first one, and every group x period of the cost tab (its switches pressed in one of them); the pane is
    left on the tab and the cost view it was found on."""
    start = pane.snap()
    home_tab = "tab-%s" % start.line.get("tab")
    for tab in TAB_ORDER:
        goto(pane, "tab-%s" % tab, "tab-")
        if overlays:
            try:
                calm(pane)
                pane.snap().overlay(Path(overlays) / ("overlay-%s.png" % tab))
            except MappingError as e:
                pane.note(dict(action="note", id="tab-%s" % tab, problem="no overlay: %s" % e))
        if tab != "cost":
            walk(pane)
            if tab == TAB_ORDER[0]:
                press_switch(pane, "tab-")
            continue
        s = pane.snap()
        home_p, home_g = selected(s, "cost-"), selected(s, "costg-")
        walk(pane)  # the two switches are pressed here
        for p in COST_PERIODS:
            for g in COST_GROUPS:
                if ("cost-%s" % p, "costg-%s" % g) == (home_p, home_g):
                    continue
                goto(pane, "cost-%s" % p, "cost-")
                goto(pane, "costg-%s" % g, "costg-")
                walk(pane, press=False)
        if home_p:
            goto(pane, home_p, "cost-")
        if home_g:
            goto(pane, home_g, "costg-")
    goto(pane, home_tab, "tab-")


# ---------------------------------------------------------------------------------------------- the tables of a pass

def _md(s) -> str:
    return str(s).replace("|", "/").replace("\n", " ")


def report(log_path, out_dir) -> dict:
    """The pass's log as three tables (markdown files in out_dir) and its totals."""
    recs = [json.loads(ln) for ln in Path(log_path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    def where(r):
        """A row's own place: the tab, and on the cost tab its period and group. What is open or picked at the moment is
        the pane's, not the row's: a press of an opener is made half in the closed state and half in the open one."""
        tab = r.get("tab") or ""
        view = r.get("view") or ""
        return (tab, next((w for w in view.split() if "/" in w), "") if tab == "cost" else "")

    def state(r):
        tab, view = where(r)
        opened = str(r.get("open") or "")
        extra = [w for w in (r.get("view") or "").split() if w not in ("panel", "squares") and "/" not in w]
        if tab == "pob" and r.get("picked"):
            extra.append("a run picked")
        if tab == "pob" and opened and not opened.startswith("rd|"):
            extra.append("a build open")
        if tab == "builds" and opened.startswith("rd|"):
            extra.append("a reading open")
        return " ".join(x for x in (tab, view) if x) + (" (%s)" % ", ".join(extra) if extra else "")

    def named(i, r):
        """The element's name: the one its record carries; for an older log a blank label takes its ticket number from
        its key, or the words of the row hovered right beside it (after or before) at the same height."""
        if r.get("name"):
            return r["name"]
        label = (r.get("label") or "").strip("   ")
        if label:
            return label
        m = _TICKET.search(r["id"])
        if r["id"].startswith(("lk-", "tl-")) and m:
            return "#%s (the ticket's number)" % m.group(1)
        if r["id"].startswith("tg-"):
            return "the chevron of #%s" % r["id"][3:]
        if r.get("rect"):
            for nxt in recs[i + 1: i + 4] + recs[max(0, i - 3): i][::-1]:
                if nxt.get("kind") == "row" and nxt.get("rect") and nxt.get("tab") == r.get("tab") and abs(nxt["rect"][1] - r["rect"][1]) <= 6:
                    return "the title: " + (nxt.get("label") or "")
        return ""

    rows, order = {}, []
    for i, r in enumerate(recs):
        if r.get("action") not in ("hover", "press"):
            continue
        k = (where(r), r["id"])
        if k not in rows:
            rows[k] = dict(state=state(r), tab=r.get("tab"), id=r["id"], kind=r["kind"], label=r.get("label") or "", acts=r.get("acts"),
                           name="", hovers=0, landed=0, lights=None, off=None, presses=[], misses=0, pics=[])
            order.append(k)
        row = rows[k]
        row["name"] = row["name"] or named(i, r)
        if r.get("miss"):
            row["misses"] += 1
            continue
        if r["action"] == "hover":
            row["hovers"] += 1
            row["landed"] += 1
            row["lights"] = bool(r.get("lights")) if row["lights"] is None else (row["lights"] and bool(r.get("lights")))
            row["off"] = r.get("off") or row["off"]
            row["pics"].append(r.get("pic"))
            row["acts"] = r.get("acts") or row["acts"]
        else:
            row["presses"].append(r)
    for row in rows.values():
        row["name"] = row["name"] or "a drawn face"
    kind_word = lambda row: ("placeholder" if row["kind"] == "row" and row["label"].strip().lower() in PLACEHOLDER_WORDS
                             else "non-clickable" if row["kind"] == "inert" else row["kind"])
    t3 = ["| tab and state | element | kind | hover: pointer on it | what lit | presses: tries at centre / left / right (+ more) | what changed |", "|---|---|---|---|---|---|---|"]
    t4 = ["| tab and state | element | where pressed | tries | pressed | what changed | pictures |", "|---|---|---|---|---|---|---|"]
    t5 = ["| tab and state | element | kind | hover: pointer on it | lights nothing | picture |", "|---|---|---|---|---|---|"]
    tot = dict(elements=0, per_tab={}, hovers=0, misses=0, presses=0, press_tries=0, slow=[], never=[], not_pressed_acts=0, inert=0, inert_lit=[], placeholders=0, placeholders_lit=[], no_light=[])
    for k in order:
        row = rows[k]
        ident = row["id"] if len(row["id"]) <= 46 else "…" + row["id"][-44:]
        name = "%s `%s`" % (_md(row["name"][:60]), ident)
        kw = kind_word(row)
        tot["elements"] += 1
        tot["per_tab"][row["tab"]] = tot["per_tab"].get(row["tab"], 0) + 1
        tot["hovers"] += row["hovers"]
        tot["misses"] += row["misses"]
        landed = "yes" if row["landed"] and not row["misses"] else "MISS x%d" % row["misses"] if row["misses"] else "-"
        if kw in ("placeholder", "non-clickable"):
            lit = "nothing" if row["lights"] is False else "LIGHTS" if row["lights"] else "-"
            t5.append("| %s | %s | %s | %s | %s | %s |" % (row["state"], name, kw, landed, "yes" if row["lights"] is False else "NO: it lights", (row["pics"] or ["-"])[0]))
            if kw == "placeholder":
                tot["placeholders"] += 1
                if row["lights"]:
                    tot["placeholders_lit"].append("%s: %s" % (row["state"], row["id"]))
            else:
                tot["inert"] += 1
                if row["lights"]:
                    tot["inert_lit"].append("%s: %s (%s)" % (row["state"], row["id"], row["label"][:30]))
        else:
            lit = "-" if not row["hovers"] else ("its own light" if row["lights"] else "NOTHING") if row["kind"] in ("button", "select") else ("its row" if row["lights"] else "NOTHING")
            if row["hovers"] and not row["lights"]:
                tot["no_light"].append("%s: %s" % (row["state"], row["id"]))
        by_at = {}
        for p in row["presses"]:
            by_at.setdefault(p["at"], []).append(p)
        cells, changes = [], []
        for at in AT:
            ps = by_at.get(at, [])
            cells.append(", ".join(("%d" % p["tries"]) if p["pressed"] else "never (%d)" % p["tries"] for p in ps) or "-")
        for p in row["presses"]:
            tot["presses"] += 1
            tot["press_tries"] += p["tries"]
            if p["change"] not in changes:
                changes.append(p["change"])
            if not p["pressed"] or p["tries"] > 1:
                (tot["never"] if not p["pressed"] else tot["slow"]).append("%s: %s at %s, %d tries" % (row["state"], name, p["at"], p["tries"]))
                t4.append("| %s | %s | %s | %d | %s | %s | %s |" % (row["state"], name, p["at"], p["tries"], "yes" if p["pressed"] else "NEVER", _md(p["change"]), " ".join(p.get("pics") or [])))
        if row["acts"] and not row["presses"]:
            press_cell, change = "hover only, press skipped: acts (%s)" % row["acts"], "-"
            tot["not_pressed_acts"] += 1
        elif row["presses"]:
            press_cell, change = " / ".join(cells), "; ".join(changes)
        else:
            press_cell, change = "-", "-"
        t3.append("| %s | %s | %s | %s | %s | %s | %s |" % (row["state"], name, kw, landed, lit, press_cell, _md(change)))
    notes = [r for r in recs if r.get("action") == "note"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "table-rows3-elements.md").write_text("\n".join(t3) + "\n", encoding="utf-8")
    (out / "table-row4-presses-over-one-try.md").write_text("\n".join(t4) + "\n", encoding="utf-8")
    (out / "table-row5-placeholders-and-cells.md").write_text("\n".join(t5) + "\n", encoding="utf-8")
    (out / "notes.md").write_text("\n".join("- %s `%s`: %s" % (n.get("t"), n.get("id"), n.get("problem")) for n in notes) + "\n", encoding="utf-8")
    tot["notes"] = len(notes)
    return tot


# ---------------------------------------------------------------------------------------------- the command line

def _list(s: Snap) -> str:
    rows = ["%-3s %-7s %-7s %-5s %-44s %-22s %s" % ("n", "kind", "state", "drawn", "element", "rect l,t,r,b", "label")]
    for n, e in enumerate(s.elements):
        lab = "(blank over a drawn face)" if e.get("blank") else e["label"]
        drawn = {True: "yes", False: "NO", None: "-"}[e.get("drawn")]
        rows.append("%-3d %-7s %-7s %-5s %-44s %-22s %s%s" % (n, e["kind"], e["state"], drawn, e["id"][:44], ",".join(map(str, e["rect"])), lab[:50],
                                                            "  [never pressed: %s]" % e["acts"] if e.get("acts") else ""))
    shown = [e for e in s.elements if e["state"] == "ok" and e["kind"] == "button"]
    rows.append("buttons on the page %d: the picture draws %d of them under their rectangles, %d not" % (
        len(shown), sum(1 for e in shown if e.get("drawn")), sum(1 for e in shown if e.get("drawn") is False)))
    rows.append("tab %s view %r; cards %s; cell %.3f px; page y %d..%d" % (s.line.get("tab"), s.line.get("view") or "",
                [(c["key"], c["state"]) for c in s.cards], s.cell, s.viewport[0], s.viewport[1]))
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--session", default=None, help="the session whose pane is shown (default: the newest that drew its data)")
    sub = ap.add_subparsers(dest="action", required=True)
    ls = sub.add_parser("list", help="every pointer element of the current state with its rectangle on the screenshot")
    ls.add_argument("--overlay", help="write the look with every rectangle drawn over it")
    ls.add_argument("--json", help="write the elements as JSON")
    for name in ("hover", "press"):
        sp = sub.add_parser(name)
        sp.add_argument("element", help="an element's id (or its unique beginning) from `list`")
        sp.add_argument("--at", choices=("centre", "left", "right"), default="centre")
        sp.add_argument("--out-dir", required=True)
        sp.add_argument("--keep-raw", action="store_true", help="hover: also write the look before and the look under the pointer without the drawn pointer")
        if name == "press":
            sp.add_argument("--tries", type=int, default=4)
    sh = sub.add_parser("shoot", help="the whole tab in one picture")
    sh.add_argument("name")
    sh.add_argument("--out-dir", required=True)
    ss = sub.add_parser("shots", help="the whole of every tab and of every group x period of the cost tab")
    ss.add_argument("--out-dir", required=True)
    wk = sub.add_parser("walk", help="the pass over the current state: a hover on every element, every opener pressed at the centre and both ends")
    wk.add_argument("--out-dir", required=True)
    wk.add_argument("--no-press", action="store_true")
    tb = sub.add_parser("switch", help="every option of one switch pressed at the centre and both ends (tab-, cost-, costg-)")
    tb.add_argument("prefix")
    tb.add_argument("--out-dir", required=True)
    go = sub.add_parser("go", help="choose an option of a switch unless it is chosen already: go tab-cost tab- / go cost-day cost- / go costg-days costg-")
    go.add_argument("element")
    go.add_argument("prefix")
    go.add_argument("--out-dir", required=True)
    tg = sub.add_parser("toggle", help="one opener pressed at the centre and both ends, and closed again")
    tg.add_argument("element")
    tg.add_argument("--out-dir", required=True)
    rc = sub.add_parser("record", help="keep the pane as it is now for a test: <name>.png + <name>.json")
    rc.add_argument("name")
    rc.add_argument("--out-dir", required=True)
    tr = sub.add_parser("tour", help="the whole pass in one process: every tab and every group x period of the cost tab (a file <out-dir>/STOP ends it between two actions)")
    tr.add_argument("--out-dir", required=True)
    tr.add_argument("--overlays", help="a folder for one overlay picture a tab")
    rp = sub.add_parser("report", help="the tables of a pass from its log")
    rp.add_argument("log")
    rp.add_argument("--out-dir", required=True)
    pb = sub.add_parser("probe", help="a diagnostic: hover a raw point and say what lit under it")
    pb.add_argument("x", type=int)
    pb.add_argument("y", type=int)
    pb.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        if a.action == "probe":
            os.makedirs(a.out_dir, exist_ok=True)
            base = look()
            after, pos = raw_hover(a.x, a.y, Path(a.out_dir) / ("probe-%d-%d.png" % (a.x, a.y)))
            print("pointer at the look: %s; lit: %s" % (pos, lit_region(base, after, a.x, a.y)))
            return 0
        if a.action == "list":
            s = Snap(look(), read_state(Path(a.cache), a.session))
            print(_list(s))
            if a.overlay:
                s.overlay(a.overlay)
            if a.json:
                Path(a.json).write_text(json.dumps([{k: v for k, v in e.items() if k != "source"} for e in s.elements], ensure_ascii=False, indent=1), encoding="utf-8")
            return 0
        if a.action == "report":
            print(json.dumps(report(a.log, a.out_dir), ensure_ascii=False, indent=1))
            return 0
        pane = Pane(a.out_dir, Path(a.cache), a.session)
        if a.action == "shoot":
            print(pane.shoot(a.name))
            return 0
        if a.action == "record":
            print(pane.record(a.name))
            return 0
        if a.action == "tour":
            tour(pane, a.overlays)
            return 0
        if a.action == "shots":
            for f in shots(pane):
                print(f)
            return 0
        if a.action == "walk":
            walk(pane, press=not a.no_press)
            return 0
        if a.action == "switch":
            press_switch(pane, a.prefix)
            return 0
        if a.action == "go":
            goto(pane, a.element, a.prefix)
            print("%s %s" % signature(pane.snap().line)[:2])
            return 0
        if a.action == "toggle":
            press_toggle(pane, pane.snap().get(a.element)["id"])
            return 0
        pane.keep_raw = bool(getattr(a, "keep_raw", False))
        rec = pane.hover(a.element, a.at) if a.action == "hover" else pane.press(a.element, a.at, a.tries)
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    except Miss as e:
        print("MISS: %s" % e)
        return 4
    except MappingError as e:
        print("MAPPING: %s" % e)
        return 5
    except NoElement as e:
        print("NO ELEMENT: %s" % e)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
