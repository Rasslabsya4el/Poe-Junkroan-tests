"""The drawn pane as a web page, where a hover is a real hover (#926).

  python scripts/pane_web.py (--dump tree.json | --ref <commit|worktree> [--fixture live-fast|full|fallback]
      [--tab main] [--open-square] [--slots 1,3,7]) --out <dir> [--hover KEY] [--card KEY] [--check-hover] [--cols N]

pane_dump.dump (the drawn tree; a press is the plugin test kit's `ui.press` inside the dump, so the page is simply redrawn
from the new tree) -> pane_layout.layout (the one source of the px rules and constants) -> one self-contained HTML file
`pane.html` (absolutely positioned divs, Svg inline; a `hover` prop is a CSS `:hover` on the hit area of the nearest keyed Box,
index.d.ts:862-917) -> headless chromium through playwright, as pane_draw.py does: no window, no install, the page's own mouse
only. `--hover KEY` moves that page mouse onto the Box with that key and screenshots (`pane-hover.png`); `--card KEY` clips
the picture to that Box; `--check-hover` hovers every hover Box by key in turn and prints
  row 1: <lit> of <N> hover Boxes light when hovered by key   (the N named)
  row 2: other elements that changed colour while one was hovered: <total> (max <m> in one hover)
Every run prints `guessed:` (what the page decides alone, the host being closed) next to `unhandled:` (props pane_layout
does not know). The page is a place to work, not the judge of the final look.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pane_draw  # noqa: E402  (BG, TEXT, LINK: the same colours as the still picture)
import pane_layout  # noqa: E402

LABEL_HOVER = "rgba(255,255,255,0.12)"
FONT = "'Segoe UI', 'DejaVu Sans', sans-serif"
# Props the tree may carry that the page does not draw (pane_layout KNOWN covers them, no px geometry comes from them).
NOT_DRAWN = {"bold", "dimColor", "wrap", "borderStyle", "borderColor", "flexShrink", "plain", "href", "options"}
HOVER_DRAWN = {"backgroundColor", "scope"}
STATIC_GUESSED = [
    f"font {FONT} 12px, one text run per prim at its px x, no clipping, no wrap, no scrolling",
    f"text colour {pane_draw.TEXT}, Link {pane_draw.LINK} where the tree gives none; Button focus look not drawn",
    "hover: instant (no timing), the page mouse over the hit area of the nearest keyed Box (the Box's own px rect); "
    "where hit areas overlap the later (deeper) one takes the pointer",
    "hover backgroundColor replaces the Box's own backgroundColor while lit (the other Box props stay)",
    "a key used by two Boxes anywhere in the tree names no scope (host text: 'a key a sibling Box already took'; "
    "sibling vs anywhere is guessed)",
    "a hover Box with no keyed Box above it and no scope is inert",
    f"host hover of a plain Button / Link in an absolute Box (register.tsx:501-509 says the host fills the label box; its colour "
    f"is not in the repo): the label box as the tree gives it (text width x one cell) lights {LABEL_HOVER} (above the row picture, under the text) while the pointer is over it",
]


def _walk(n, f):
    if isinstance(n, dict):
        f(n)
        for c in n.get("children") or []:
            _walk(c, f)


def tree_facts(tree: dict) -> dict:
    """From the tree itself: the hover Boxes (key, colour), the keys, props the page does not draw, hover props it ignores."""
    hov, keys, ignored, hover_ignored = [], {}, {}, {}

    def f(n):
        pr = n.get("props") or {}
        k = pr.get("key")
        if isinstance(k, str):
            keys[k] = keys.get(k, 0) + 1
        for p in pr:
            if p in NOT_DRAWN:
                ignored[(n.get("type"), p)] = ignored.get((n.get("type"), p), 0) + 1
        h = n.get("hover")
        if h:
            if h.get("backgroundColor"):
                hov.append(dict(key=k, color=h["backgroundColor"]))
            for p in h:
                if p not in HOVER_DRAWN:
                    hover_ignored[p] = hover_ignored.get(p, 0) + 1
    _walk(tree, f)
    return dict(hover=hov, dup_keys=sorted(k for k, c in keys.items() if c > 1), ignored=ignored, hover_ignored=hover_ignored)


def guessed_list(facts: dict) -> list[str]:
    out = list(STATIC_GUESSED)
    for (t, p), c in sorted(facts["ignored"].items()):
        out.append(f"{t}.{p} x{c} is in the tree and not drawn by the page")
    for p, c in sorted(facts["hover_ignored"].items()):
        out.append(f"hover.{p} x{c} is in the tree and not applied by the page")
    if facts["dup_keys"]:
        out.append(f"duplicate keys (inert as scopes): {', '.join(facts['dup_keys'])}")
    return out


def _q(s: str) -> str:
    """A CSS attribute-selector string."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def isolate_svg(source: str, n: int) -> str:
    """One page holds every Svg: an id is defined once per document, so each Svg gets its own prefix on its ids and on every
    reference to them (url(#id), href / xlink:href="#id", a `#id` in a <style>); two Svg can then both own `b0`."""
    ids = set(re.findall(r"""\bid=["']([^"']+)["']""", source))
    if not ids:
        return source
    alt = "|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True))
    source = re.sub(r"""(\bid=["'])(%s)(["'])""" % alt, lambda m: f"{m[1]}s{n}-{m[2]}{m[3]}", source)
    return re.sub(r"#(%s)(?![\w-])" % alt, lambda m: f"#s{n}-{m[1]}", source)


def _box(p: dict) -> str:
    return f"left:{p['x']:.2f}px;top:{p['y']:.2f}px;width:{p['w']:.2f}px;height:{p['h']:.2f}px"


def build_page(dump: dict) -> dict:
    """{html, guessed, unhandled, hover: [{id, key, scope, group, color, inert}], width, height}."""
    res = pane_layout.layout(dump)
    prims = res["prims"]
    facts = tree_facts(dump["tree"])
    scope_count: dict[str, int] = {}
    for p in prims:
        if p["kind"] == "scope" and p.get("key"):
            scope_count[p["key"]] = scope_count.get(p["key"], 0) + 1
    width = round(res["cols"] * pane_layout.COL_PX, 2)
    height = round(max([p["y"] + p["h"] for p in prims] or [0]), 2)
    body, rules, hov, scopes, lab = [], [], [], [], []
    for i, p in enumerate(prims):
        k = p["kind"]
        if k == "rect":
            key = f' data-key={_q(p["key"])}' if p.get("key") else ""
            body.append(f'<div class="r"{key} data-id="e{i}" style="{_box(p)};background:{html.escape(p["color"])}"></div>')
        elif k == "hover_rect":
            scope = p.get("scope")
            inert = (scope is None and not p.get("group")) or (scope is not None and scope_count.get(scope, 0) > 1 and not p.get("group"))
            hov.append(dict(id=f"e{i}", key=p.get("key"), scope=scope, group=p.get("group"), color=p["color"], inert=inert))
            attrs = f' data-key={_q(p["key"])}' if p.get("key") else ""
            attrs += f' data-scope={_q(scope)}' if scope else ""
            attrs += f' data-group={_q(p["group"])}' if p.get("group") else ""
            body.append(f'<div class="hv"{attrs} data-id="e{i}" style="{_box(p)};--hc:{html.escape(p["color"])}"></div>')
            if not inert:
                lit = ""
                if scope and scope_count.get(scope, 0) == 1:
                    lit = f'body:has(.sc[data-key={_q(scope)}]:hover) '
                if lit:
                    sel = f'.hv[data-id="e{i}"]'
                    rules.append(f'{lit}{sel}{{background:var(--hc)}}')
                    if p.get("key"):  # replace semantics: the Box's own fill gives way while lit
                        rules.append(f'{lit}.r[data-key={_q(p["key"])}]{{visibility:hidden}}')
                if p.get("group"):
                    rules.append(f'body:has(.sc[data-group={_q(p["group"])}]:hover) .hv[data-group={_q(p["group"])}]{{background:var(--hc)}}')
        elif k == "svg":
            body.append(f'<div class="s" style="{_box(p)}">{isolate_svg(p["source"], i)}</div>')
        elif k == "text":
            col = p.get("color") or (pane_draw.LINK if p.get("of") == "Link" else pane_draw.TEXT)
            body.append(f'<div class="t" style="left:{p["x"]:.2f}px;top:{p["y"]:.2f}px;height:{pane_layout.CELL}px;color:{html.escape(col)}">'
                        f'{html.escape(p["text"])}</div>')
        elif k == "scope":
            scopes.append(p)
        elif k == "label_hover":
            lid = f"l{i}"
            lab.append(dict(id=f"e{i}", lid=lid, key=p.get("key"), text=p["text"], x=p["x"], y=p["y"], w=p["w"], h=p["h"]))
            body.append(f'<div class="lh" data-id="e{i}" style="{_box(p)};--hc:{LABEL_HOVER}"></div>')
            rules.append(f'body:has(.lhit[data-lid="{lid}"]:hover) .lh[data-id="e{i}"]{{background:var(--hc)}}')
            scopes.append(dict(p, lid=lid, key=None))
    for p in scopes:  # last in the page: the hit areas lie above everything, transparent, a later one over an earlier one
        a = f' data-key={_q(p["key"])}' if p.get("key") else ""
        a += f' data-group={_q(p["group"])}' if p.get("group") else ""
        a += f' data-lid="{p["lid"]}"' if p.get("lid") else ""
        dup = " dup" if p.get("key") and scope_count.get(p["key"], 0) > 1 else ""
        body.append(f'<div class="sc{dup}{' lhit' if p.get('lid') else ''}"{a} style="{_box(p)}"></div>')
    css = (f"html,body{{margin:0;background:rgb{pane_draw.BG}}}#pane{{position:relative;width:{width}px;height:{height}px;overflow:hidden;"
           f"font:12px/{pane_layout.CELL}px {FONT}}}#pane>div{{position:absolute;box-sizing:border-box}}"
           ".t{white-space:pre;pointer-events:none;z-index:6}.lh{z-index:5}.s,.r,.hv,.lh{pointer-events:none}.s svg{display:block}.sc{z-index:10}"
           + "".join(rules))
    page = (f'<!doctype html><meta charset="utf-8"><title>pane {html.escape(str(dump.get("tab", "")))}</title>'
            f'<style>{css}</style><div id="pane">{"".join(body)}</div>')
    guessed = guessed_list(facts)
    return dict(html=page, guessed=guessed, unhandled=res["unhandled"], hover=hov, labels=lab, width=width, height=height,
                scopes=scopes, facts=facts)


SNAP_JS = """() => { const o = {}; for (const e of document.querySelectorAll('.r,.hv,.lh'))
  o[e.dataset.id] = getComputedStyle(e).backgroundColor + '|' + getComputedStyle(e).visibility; return o; }"""
EXPECT_JS = """(c) => { const d = document.createElement('div'); d.style.background = c; document.body.appendChild(d);
  const v = getComputedStyle(d).backgroundColor; d.remove(); return v; }"""
POINTS_JS = """(sel) => { const el = document.querySelector(sel); if (!el) return [];
  const b = el.getBoundingClientRect(), out = [];
  for (const fy of [.5, .25, .75, .1, .9]) for (const fx of [.5, .25, .75, .1, .9]) {
    const x = b.left + b.width * fx, y = b.top + b.height * fy;
    const top = document.elementsFromPoint(x, y).find(e => e.classList.contains('sc'));
    if (top === el) out.push([x, y]); }
  return out; }"""


def free_points(pg, key: str | None = None, group: str | None = None, lid: str | None = None) -> list:
    """Points inside the hit area of the Box with this key (or of the first Box of this group) where no later hit area lies on top."""
    sel = f'.sc[data-lid="{lid}"]' if lid else f".sc[data-key={_q(key)}]" if key else f".sc[data-group={_q(group)}]"
    return pg.evaluate(POINTS_JS, sel)


def check_hover(pg, info: dict) -> dict:
    """Hover every hover Box by its key: row 1 (lit by key) and row 2 (others changing colour). The page mouse only."""
    pg.mouse.move(info["width"] + 1, info["height"] + 1)  # off every Box, wherever a --hover left the page mouse
    base = pg.evaluate(SNAP_JS)
    lit_n, rows, others_total, others_max, unlit = 0, [], 0, 0, []
    for h in info["hover"]:
        name = h["key"] or f"(scope {h['scope'] or h['group']})"
        pts = [] if h["inert"] else free_points(pg, key=h["scope"]) if h["scope"] else free_points(pg, group=h["group"])
        if not pts:
            unlit.append(f"{name}: {'inert' if h['inert'] else 'no free point of its scope ' + str(h['scope'] or h['group'])}")
            continue
        pg.mouse.move(*pts[0])
        snap = pg.evaluate(SNAP_JS)
        want = pg.evaluate(EXPECT_JS, h["color"])
        ok = snap[h["id"]].split("|")[0] == want
        mine = {x["id"] for x in info["hover"] if x["scope"] == h["scope"] or (h["group"] and x["group"] == h["group"])}
        # the Boxes own fill that gives way while lit counts as the lit Box, not as a neighbour
        own = set(pg.evaluate("(k) => Array.from(document.querySelectorAll('.r[data-key=' + JSON.stringify(k) + ']')).map(e => e.dataset.id)", h["key"])) if h["key"] else set()
        others = {i for i in snap if snap[i] != base.get(i)} - mine - own
        others_total += len(others)
        others_max = max(others_max, len(others))
        if ok:
            lit_n += 1
        else:
            unlit.append(f"{name}: background {snap[h['id']]} not {want}")
        rows.append(dict(key=name, lit=ok, others=len(others)))
        pg.mouse.move(info["width"] + 1, info["height"] + 1)  # the 2 px margin of the viewport: over no Box
    lab_n, lab_lit, lab_others, lab_unlit = len(info["labels"]), 0, 0, []
    for lb in info["labels"]:
        pts = free_points(pg, lid=lb["lid"])
        if not pts:
            lab_unlit.append(f"{lb['text']!r}: no free point")
            continue
        pg.mouse.move(*pts[0])
        snap = pg.evaluate(SNAP_JS)
        if snap[lb["id"]] != base[lb["id"]]:
            lab_lit += 1
        else:
            lab_unlit.append(f"{lb['text']!r}: not lit")
        lab_others += len({i for i in snap if snap[i] != base.get(i)} - {lb["id"]})
        pg.mouse.move(info["width"] + 1, info["height"] + 1)
    return dict(labels=lab_n, labels_lit=lab_lit, labels_others=lab_others, labels_unlit=lab_unlit,
                n=len(info["hover"]), lit=lit_n, names=[r["key"] for r in rows], others_total=others_total,
                others_max=others_max, unlit=unlit)


def run_page(info: dict, out: Path, hover: str | None = None, card: str | None = None, check: bool = False) -> dict:
    """Write pane.html, open it in headless chromium, take the pictures. Returns what was measured."""
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    (out / "pane.html").write_text(info["html"], encoding="utf-8")
    got: dict = dict(pictures=[])
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": max(200, int(info["width"]) + 2), "height": max(200, int(info["height"]) + 2)})
            pg.set_content(info["html"])
            clip = None
            if card:
                sc = next((s for s in info["scopes"] if s.get("key") == card), None)
                if sc is None:
                    raise SystemExit(f"--card {card}: no keyed Box with that key")
                clip = dict(x=sc["x"], y=sc["y"], width=sc["w"], height=sc["h"])
            if hover:
                pts = free_points(pg, key=hover)
                sc = next((s for s in info["scopes"] if s.get("key") == hover), None)
                inside = [lb for lb in info["labels"] if sc and sc["x"] <= lb["x"] and lb["x"] + lb["w"] <= sc["x"] + sc["w"]
                          and sc["y"] <= lb["y"] and lb["y"] + lb["h"] <= sc["y"] + sc["h"]]
                for lb in inside:  # a row holding a Button / Link: the pointer goes onto its label box (that is what the host lights)
                    lp = free_points(pg, lid=lb["lid"])
                    if lp:
                        pts = lp
                        break
                if not pts:
                    raise SystemExit(f"--hover {hover}: no keyed Box with that key has a free point under the pointer")
                pg.mouse.move(*pts[0])
                path = out / "pane-hover.png"
            else:
                path = out / "pane.png"
            pg.screenshot(path=str(path), clip=clip, full_page=clip is None)
            got["pictures"].append(str(path))
            if check:
                got["check"] = check_hover(pg, info)
        finally:
            b.close()
    return got


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dump", help="a pane_dump.py JSON file instead of dumping a ref")
    ap.add_argument("--ref")
    ap.add_argument("--fixture", default="live-fast", choices=["live-fast", "full", "fallback"])
    ap.add_argument("--tab", default="main")
    ap.add_argument("--open-square", action="store_true")
    ap.add_argument("--slots")
    ap.add_argument("--cols", type=int, default=119)
    ap.add_argument("--hover")
    ap.add_argument("--card")
    ap.add_argument("--check-hover", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if not a.dump and not a.ref:
        ap.error("--dump or --ref is required")
    t0 = time.time()
    if a.dump:
        d = json.loads(Path(a.dump).read_text(encoding="utf-8"))
    else:
        import pane_dump
        d = pane_dump.dump(a.ref, a.fixture, a.tab, a.open_square, a.cols,
                           slots=[int(x) for x in a.slots.split(",")] if a.slots else None)
    t_dump = time.time() - t0
    info = build_page(d)
    got = run_page(info, Path(a.out), a.hover, a.card, a.check_hover)
    from junkroan.report_format import human_duration
    for pth in got["pictures"]:
        print(pth)
    print(f"page {Path(a.out) / 'pane.html'} ({len(info['html']) // 1024} KB); hover Boxes in the tree {len(info['hover'])}, label boxes {len(info['labels'])}")
    c = got.get("check")
    if c:
        print(f"row 1: {c['lit']} of {c['n']} hover Boxes light when hovered by key: {', '.join(c['names'])}")
        print(f"row 2: other elements that changed colour while one was hovered: {c['others_total']} (max {c['others_max']} in one hover)")
        print(f"row 1b (label boxes of plain Button / Link in an absolute Box, a guess about the host): {c['labels_lit']} of {c['labels']} light when hovered, "
              f"{c['labels_others']} neighbours changed")
        for u in c["unlit"] + c["labels_unlit"]:
            print(f"  not lit: {u}")
    print("unhandled: " + ("; ".join(f"{u['type']}.{u['prop']} x{u['count']}" for u in info["unhandled"]) or "none"))
    print("guessed:")
    for g in info["guessed"]:
        print(f"  - {g}")
    print(f"{human_duration(time.time() - t0)} (dump {human_duration(t_dump)}); windows 0 installs 0 pointer moves of the real mouse 0")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    raise SystemExit(main())
