"""Lay out a pane_dump.py tree in screen pixels (#843 unit 2).

  python scripts/pane_layout.py dump.json [--out prims.json] [--summary] [--zoom 1.0]

The engine model (read from the tree, not measured by a browser): a cell is 19 px high and COL_PX = 950/119 px wide (calibrated, see the constants);
`top` / `left` / `right` / `height` / `width` / margins / padding / gap are in cells (rows or columns); an Svg's `height`
and `width` are px; a borderStyle Box takes half a cell above and below and 9 px (border + paddingX) at the sides; an absolute Box is placed against its parent's inner
edge (inside the border, no padding) and takes no room in the flow. Output: a flat list of primitives in px:
  {kind: rect | hover_rect | press_rect | text | svg, x, y, w, h, ...}
A Box's `hover` backgroundColor is a hover_rect with the Box's own geometry; an absolute Box holding a Link / Button and
no fill is a press_rect (the place the press lies); its Button / Link label box is a label_hover (the host lights it, #926). An Svg carries `row_tops`: the px tops of its picture's rows (the
`<g transform='translate(0 Y)'>` groups, see row_top)).
Anything the model does not know goes to `unhandled` ({type, prop, count}), never silently dropped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CELL = 19.0
PX_PER_COL = 7.8  # the mod's own constant (kit.tsx:53): Svg widths are sized with it
# Engine constants measured on the real picture docs/research/pictures-613-837/after-install-main-11-35.png (#843 calibration):
COL_PX = 950 / 119  # a column of the engine in that picture: the card is 950 px = 119 cols (the mod's CW = round(119 * 7.8) + 4 = 932 = the Svg width)
BORDER_Y = CELL / 2  # a borderStyle Box takes half a cell above and below (card top to title text top 17 px = 9.5 + 7.5; last band to card bottom 18 = 9.5 + 8)
CARD_INSET_X = 9.0  # border + paddingX={1} of a card together: the Svg starts 9 px inside the card edge on both sides (card 950, Svg 932)
MARGIN_BOTTOM_BORDERED = CELL / 2  # a card's marginBottom={1} is drawn as 9.5 px (gap between cards 10 and 9 px)
TEXT_BASE = 14  # a table line is 19 px; its text baseline is 14 px under the line top
ROW_PADS = (9, 7, 16)  # a row group's translate Y = its band top + 9 (a pill row: (38 - 20 px PILL) / 2), 7 (a label / header row), 16 (a two-line row)


def row_top(y: float) -> float:
    """The band top of a row from its group's Y: the first pad of ROW_PADS that lands on the 19 px cell grid (the engine's
    rows are whole cells); when none does (a picture off the grid, e.g. before #837) Y - 9, so a drift stays visible."""
    for pad in ROW_PADS:
        t = y - pad
        if t >= 0 and abs(t / CELL - round(t / CELL)) < 1e-6:
            return t
    return max(0.0, y - ROW_PADS[0])

NOT_ROWS = ("hist-prev", "hist-next")  # the pager buttons of PoB runs sit on a label line, not on a row
KNOWN = {
    "Box": {"flexDirection", "position", "top", "left", "right", "height", "width", "alignItems", "key",
            "backgroundColor", "borderStyle", "borderColor", "paddingX", "paddingLeft", "marginTop", "marginBottom",
            "gap", "flexShrink", "flexGrow"},
    "Text": {"color", "bold", "wrap", "dimColor"},
    "Svg": {"source", "alt", "height", "width"},
    "Button": {"key", "label", "plain", "dimColor"},
    "Link": {"href", "label"},
    "Select": {"key", "options", "value"},
}


class Layout:
    def __init__(self, zoom: float = 1.0):
        self.cell = CELL * zoom
        self.col = COL_PX * zoom
        self.border_x = (CARD_INSET_X - COL_PX) * zoom  # one side of a border, so that border + paddingX={1} = CARD_INSET_X
        self.border_y = BORDER_Y * zoom
        self.zoom = zoom
        self.prims: list[dict] = []
        self.unhandled: dict[tuple, int] = {}
        self.label_ctx = False  # inside an absolute Box that holds a Link / Button and has no hover of its own
        self.scope_key = None  # the nearest keyed Box above the one being placed (index.d.ts:906-909: a keyed Box is a hover scope)

    # ---- measuring
    def p(self, n: dict) -> dict:
        return n.get("props") or {}

    def note(self, n: dict) -> None:
        t = n.get("type")
        known = KNOWN.get(t)
        for k in self.p(n):
            if known is None or k not in known:
                self.unhandled[(str(t), k)] = self.unhandled.get((str(t), k), 0) + 1
        if known is None:
            self.unhandled[(str(t), "<type>")] = self.unhandled.get((str(t), "<type>"), 0) + 1

    def text_of(self, n) -> str:
        if isinstance(n, str):
            return n
        t = n.get("type")
        if t == "Select":
            return self.select_text(n)
        if t in ("Button", "Link") and not any(isinstance(c, dict) for c in n.get("children") or []):
            return str(self.p(n).get("label", ""))
        return "".join(self.text_of(c) for c in n.get("children") or [])

    def select_text(self, n: dict) -> str:
        """A Select's drawn text: its label (index.d.ts SelectProps.label, "drawn before the current value") and the label of
        the selected option (SelectOption.label, the value when absent), as the tree gives them. The host's own decoration
        (arrow, brackets, a gap after label) is not in the tree and not counted; a label gets one space (guessed)."""
        pr = self.p(n)
        val = pr.get("value")
        opt = next((o for o in pr.get("options") or [] if o.get("value") == val), None)
        shown = "" if val is None else str((opt or {}).get("label", val))
        lab = pr.get("label")
        return f"{lab} {shown}" if lab else shown

    def svg_wh(self, n: dict) -> tuple[float, float]:
        pr = self.p(n)
        src = str(pr.get("source", ""))
        m = re.search(r"<svg[^>]* width=['\"]([\d.]+)['\"]", src)
        w = float(pr["width"]) if pr.get("width") is not None else (float(m.group(1)) if m else 0.0)
        h = float(pr["height"]) if pr.get("height") is not None else 0.0
        return w * self.zoom, h * self.zoom

    def is_abs(self, n) -> bool:
        return isinstance(n, dict) and n.get("type") == "Box" and self.p(n).get("position") == "absolute"

    def inflow(self, n) -> list:
        return [c for c in (n.get("children") or []) if not self.is_abs(c) and c != ""]

    def nat_w(self, n) -> float:
        if isinstance(n, str):
            return len(n) * self.col
        t, pr = n["type"], self.p(n)
        if t == "Svg":
            return self.svg_wh(n)[0]
        if t == "Box":
            if pr.get("width") is not None:
                return pr["width"] * self.col
            kids = self.inflow(n)
            pad = (pr.get("paddingX", 0) * 2 + pr.get("paddingLeft", 0)) * self.col + (2 * self.border_x if pr.get("borderStyle") else 0)
            if pr.get("flexDirection") == "row":
                return pad + sum(self.nat_w(c) for c in kids) + pr.get("gap", 0) * self.col * max(0, len(kids) - 1)
            return pad + max([self.nat_w(c) for c in kids] or [0.0])
        if t in ("Button", "Link", "Text"):
            kids = [c for c in n.get("children") or [] if isinstance(c, dict)]
            if kids:
                return sum(self.nat_w(c) for c in kids)
            return len(self.text_of(n)) * self.col
        return len(self.text_of(n)) * self.col

    def nat_h(self, n) -> float:
        if isinstance(n, str):
            return self.cell
        t, pr = n["type"], self.p(n)
        if t == "Svg":
            return self.svg_wh(n)[1]
        if t == "Box":
            if pr.get("height") is not None:
                return pr["height"] * self.cell
            kids = self.inflow(n)
            inner = [self.nat_h(c) + self.margin(c) for c in kids]
            if pr.get("flexDirection") == "row":
                h = max(inner or [0.0])
            else:
                h = sum(inner) + pr.get("gap", 0) * self.cell * max(0, len(kids) - 1)
            return h + (2 * self.border_y if pr.get("borderStyle") else 0)
        return self.cell

    def margin_bottom(self, c) -> float:
        pr = self.p(c)
        k = MARGIN_BOTTOM_BORDERED / CELL if pr.get("borderStyle") else 1.0
        return pr.get("marginBottom", 0) * self.cell * k

    def margin(self, c) -> float:
        if isinstance(c, dict) and c.get("type") == "Box":
            pr = self.p(c)
            return pr.get("marginTop", 0) * self.cell + self.margin_bottom(c)
        return 0.0

    # ---- placing
    def place(self, n, x: float, y: float, w: float, h: float | None = None) -> None:
        """n's border box at (x, y), width w, height h (None = natural)."""
        if isinstance(n, str):
            if n.strip():
                self.prims.append(dict(kind="text", x=x, y=y, w=len(n) * self.col, h=self.cell, text=n, color=None))
            return
        self.note(n)
        t, pr = n["type"], self.p(n)
        if t == "Svg":
            sw, sh = self.svg_wh(n)
            src = str(pr.get("source", ""))
            tops = [row_top(float(v)) * self.zoom + y
                    for v in re.findall(r"<g transform=['\"]translate\(0 ([\d.]+)\)['\"]>", src)]
            if not tops:  # a table picture (tableSvg): its rows are 19 px lines, a cell's first baseline sits 14 px below the line's top
                ys = sorted({float(v) - TEXT_BASE for v in re.findall(r"<tspan [^>]*? y=['\"]([\d.]+)['\"]", src)})
                tops = [v * self.zoom + y for v in ys if v >= 0]
            self.prims.append(dict(kind="svg", x=x, y=y, w=sw, h=sh, source=src, alt=pr.get("alt"), row_tops=tops,
                                   groups=self.groups(src, y)))
            return
        if t == "Box":
            hh = h if h is not None else self.nat_h(n)
            key = pr.get("key")
            hv = n.get("hover") or {}
            outer_scope = self.scope_key
            if isinstance(key, str) and key:
                self.scope_key = key
            if key or hv.get("scope"):  # a hover scope's own area (#926): the page lays a hit area on it
                self.prims.append(dict(kind="scope", x=x, y=y, w=w, h=hh, key=key, group=hv.get("scope")))
            if pr.get("backgroundColor"):
                self.prims.append(dict(kind="rect", x=x, y=y, w=w, h=hh, color=pr["backgroundColor"], key=key))
            if n.get("hover") and n["hover"].get("backgroundColor"):
                self.prims.append(dict(kind="hover_rect", x=x, y=y, w=w, h=hh, color=n["hover"]["backgroundColor"], key=key,
                                       scope=self.scope_key, group=hv.get("scope")))
            elif self.is_abs(n) and self.has_press(n):
                self.prims.append(dict(kind="press_rect", x=x, y=y, w=w, h=hh, key=key))
            outer_ctx = self.label_ctx
            self.label_ctx = self.is_abs(n) and self.has_press(n) and not (hv.get("backgroundColor"))
            b = 1 if pr.get("borderStyle") else 0
            ix, iy = x + b * self.border_x, y + b * self.border_y
            iw, ih = w - 2 * b * self.border_x, hh - 2 * b * self.border_y
            cx = ix + (pr.get("paddingX", 0) + pr.get("paddingLeft", 0)) * self.col
            cw = iw - (pr.get("paddingX", 0) * 2 + pr.get("paddingLeft", 0)) * self.col
            self.children(n, ix, iy, iw, ih, cx, iy, cw)
            self.scope_key = outer_scope
            self.label_ctx = outer_ctx
            return
        # Text / Button / Link / Select / unknown: leaf-ish
        kids = [c for c in n.get("children") or [] if isinstance(c, dict)]
        if t in ("Button", "Link") and self.label_ctx and self.nat_w(n) > 0:
            # the host lights the label box of a plain Button / Link in an absolute Box on hover (#926 row D, a guess about the closed host)
            self.prims.append(dict(kind="label_hover", x=x, y=y, w=self.nat_w(n), h=self.cell, key=pr.get("key"),
                                   text=self.text_of(n), of=t))
        if t in ("Button", "Link", "Select") and not kids:
            label = self.select_text(n) if t == "Select" else str(pr.get("label", pr.get("value", "")))
            if label:
                self.prims.append(dict(kind="text", x=x, y=y, w=len(label) * self.col, h=self.cell, text=label,
                                       color=None, of=t))
            return
        run = x
        for c in n.get("children") or []:
            if isinstance(c, str):
                if c:
                    self.prims.append(dict(kind="text", x=run, y=y, w=len(c) * self.col, h=self.cell, text=c,
                                           color=pr.get("color")))
                    run += len(c) * self.col
            else:
                self.note(c)
                s = self.text_of(c)
                col = self.p(c).get("color") or pr.get("color")
                if s:
                    self.prims.append(dict(kind="text", x=run, y=y, w=len(s) * self.col, h=self.cell, text=s, color=col))
                run += len(s) * self.col

    def groups(self, src: str, y: float) -> list[dict]:
        """Each row group of a picture: {y: its translate Y in px, band: (top, h) of the first wide rect drawn in it or None}.
        A picture whose rows are drawn as <use> of shared shapes has no band here (the pad rule of row_top then applies)."""
        out = []
        starts = list(re.finditer(r"<g transform=['\"]translate\(0 ([\d.]+)\)['\"]>", src))
        for i, m in enumerate(starts):
            body = src[m.end(): starts[i + 1].start() if i + 1 < len(starts) else len(src)]
            band = None
            for r in re.finditer(r"<rect ([^>]*)>", body):
                a = dict(re.findall(r"([\w-]+)=['\"]([^'\"]*)['\"]", r.group(1)))
                try:
                    if float(a.get("width", 0)) >= 100:
                        band = ((float(m.group(1)) + float(a.get("y", 0))) * self.zoom + y, float(a["height"]) * self.zoom)
                        break
                except (ValueError, KeyError):
                    continue
            out.append(dict(y=float(m.group(1)) * self.zoom + y, band=band))
        return out

    def has_press(self, n) -> bool:
        return any(isinstance(c, dict) and c.get("type") in ("Link", "Button") for c in n.get("children") or [])

    def children(self, n, ix, iy, iw, ih, cx, cy, cw) -> None:
        pr = self.p(n)
        row = pr.get("flexDirection") == "row"
        gap = pr.get("gap", 0) * (self.col if row else self.cell)
        kids = [c for c in (n.get("children") or []) if c != ""]
        flow = [c for c in kids if not self.is_abs(c)]
        grow_total = sum(self.p(c).get("flexGrow", 0) for c in flow if isinstance(c, dict))
        used = sum(self.nat_w(c) for c in flow) + gap * max(0, len(flow) - 1) if row else 0
        free = max(0.0, cw - used) if row else 0
        pos_x, pos_y = cx, cy
        center = pr.get("alignItems") == "center"
        for c in kids:
            if self.is_abs(c):
                self.place_abs(c, ix, iy, iw, ih)
                continue
            if isinstance(c, str):
                self.place(c, pos_x, pos_y, cw)
                if row:
                    pos_x += len(c) * self.col + gap
                else:
                    pos_y += self.cell + gap
                continue
            cp = self.p(c)
            mt = cp.get("marginTop", 0) * self.cell if c["type"] == "Box" else 0
            mb = self.margin_bottom(c) if c["type"] == "Box" else 0
            if row:
                w = self.nat_w(c) + (free * cp.get("flexGrow", 0) / grow_total if grow_total and cp.get("flexGrow") else 0)
                ch = self.nat_h(c)
                yy = pos_y + mt + ((ih - ch) / 2 if center and ih > ch else 0)
                self.place(c, pos_x, yy, w)
                pos_x += w + gap
            else:
                ch = self.nat_h(c)
                w = cw if c["type"] == "Box" and cp.get("width") is None else (cp["width"] * self.col if cp.get("width") is not None else self.nat_w(c))
                self.place(c, pos_x, pos_y + mt, w, ch if c["type"] == "Box" else None)
                pos_y += mt + ch + mb + gap

    def place_abs(self, c, ix, iy, iw, ih) -> None:
        cp = self.p(c)
        self.note(c)
        h = self.nat_h(c)
        if cp.get("width") is not None:
            w = cp["width"] * self.col
        elif cp.get("left") is not None and cp.get("right") is not None:
            w = iw - (cp["left"] + cp["right"]) * self.col
        elif c.get("children") and not (cp.get("flexDirection") == "column" and cp.get("right") is not None):
            w = self.nat_w(c)
        else:
            w = iw
        if cp.get("left") is not None:
            x = ix + cp["left"] * self.col
        elif cp.get("right") is not None:
            x = ix + iw - cp["right"] * self.col - w
        else:
            x = ix
        y = iy + (cp.get("top", 0)) * self.cell
        self.place(c, x, y, w, h if cp.get("height") is not None else None)


def layout(dump: dict, zoom: float = 1.0) -> dict:
    lay = Layout(zoom)
    root_w = dump["cols"] * COL_PX * zoom
    lay.place(dump["tree"], 0.0, 0.0, root_w)
    return dict(prims=lay.prims,
                unhandled=[dict(type=t, prop=p, count=c) for (t, p), c in sorted(lay.unhandled.items())],
                cols=dump["cols"], zoom=zoom)


def band_offsets(prims: list[dict], lo: float, hi: float) -> list[dict]:
    """For each hover_rect / press_rect with its top in [lo, hi): the offset of its top against the nearest row's ideal top.
    A row with a drawn band (a wide rect in its group): a box not taller than the band should start at the band's top,
    a taller one (a 2-cell slot round a pill row) is centred on it; a row without one: the cell-grid top of row_top()."""
    svgs = [p for p in prims if p["kind"] == "svg"]
    out = []
    for p in prims:
        if p["kind"] in ("hover_rect", "press_rect") and lo <= p["y"] < hi and svgs:
            tops = []
            for s in svgs:
                if s.get("groups"):
                    for g in s["groups"]:
                        if g["band"]:
                            bt, bh = g["band"]
                            tops.append(bt if p["h"] <= bh + 1 else bt + bh / 2 - p["h"] / 2)
                        else:
                            tops.append(row_top(g["y"] - s["y"]) + s["y"])
                else:
                    tops += s["row_tops"]
            if not tops:
                continue
            near = min(tops, key=lambda t: abs(t - p["y"]))
            out.append(dict(kind=p["kind"], key=p.get("key"), y=p["y"], row_top=near, offset=p["y"] - near, h=p["h"]))
    return out


def cards(prims: list[dict]) -> list[dict]:
    """A card = a key card-* rect; its title top, first / last row top and the worst hover / press offset."""
    out = []
    for r in prims:
        if r["kind"] != "rect" or not str(r.get("key", "")).startswith("card-"):
            continue
        lo, hi = r["y"], r["y"] + r["h"]
        inside = [p for p in prims if p is not r and lo <= p["y"] < hi and p["kind"] == "svg"]
        title = inside[0]["y"] if inside else None
        rows = sorted(t for p in inside[1:] for t in p["row_tops"])
        offs = band_offsets([p for p in prims if lo <= p["y"] < hi], lo, hi)
        offs = [o for o in offs if not any(k in str(o["key"]) for k in NOT_ROWS)]
        worst = max(offs, key=lambda o: abs(o["offset"])) if offs else None
        out.append(dict(card=r["key"], card_top=lo, card_h=r["h"], title_top=title, first_row=rows[0] if rows else None,
                        last_row=rows[-1] if rows else None, rows=len(rows), boxes=len(offs), worst=worst))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dump")
    ap.add_argument("--out")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--zoom", type=float, default=1.0)
    a = ap.parse_args(argv)
    res = layout(json.loads(Path(a.dump).read_text(encoding="utf-8")), a.zoom)
    if a.out:
        Path(a.out).write_text(json.dumps(res), encoding="utf-8")
    if a.summary or not a.out:
        print(f"primitives {len(res['prims'])}; unhandled {res['unhandled']}")
        for c in cards(res["prims"]):
            w = c["worst"]
            print(f"{c['card']}: top {c['card_top']:.0f}px h {c['card_h']:.0f}px title_top {c['title_top']} first_row {c['first_row']} "
                  f"last_row {c['last_row']} ({c['rows']} row tops, {c['boxes']} boxes); worst offset "
                  + (f"{w['offset']:+.1f}px ({w['kind']} {w['key']} at {w['y']:.1f}, row {w['row_top']:.1f})" if w else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
