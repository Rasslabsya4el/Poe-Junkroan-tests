"""scripts/pane_web.py (#926): the drawn tree as a web page, hover by key. 0 PoB, no window, no install (rows 1, 2, 5)."""
from __future__ import annotations

import ctypes
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pane_layout as pl  # noqa: E402
import pane_web as pw  # noqa: E402

pytest.importorskip("playwright")


def box(props, children=None, hover=None):
    n = {"type": "Box", "props": props, "children": children or []}
    if hover:
        n["hover"] = hover
    return n


def tree():
    """A keyed row with a hover, a hover Box with no key of its own (scope = the keyed card above), two Boxes of one
    group, two Boxes sharing a key (inert), and a hover Box with no keyed Box above it (inert)."""
    row = lambda k, y, hov: box({"key": k, "position": "absolute", "top": y, "left": 0, "right": 0, "height": 1}, [], hov)
    card = box({"key": "card-a", "flexDirection": "column", "height": 6, "backgroundColor": "#101010"}, [
        row("row-1", 0, {"backgroundColor": "#2f2f33"}),
        row("row-2", 2, {"backgroundColor": "#58a6ff2e"}),
        box({"position": "absolute", "top": 4, "left": 0, "width": 10, "height": 1}, [], {"backgroundColor": "#aa0000"}),
    ])
    grp = box({"flexDirection": "row", "height": 1}, [
        box({"width": 10, "height": 1}, ["g1"], {"scope": "g", "backgroundColor": "#00aa00"}),
        box({"width": 10, "height": 1}, ["g2"], {"scope": "g", "backgroundColor": "#00aa00"}),
    ])
    dup = box({"flexDirection": "row", "height": 1}, [
        box({"key": "same", "width": 10, "height": 1}, [], {"backgroundColor": "#0000aa"}),
        box({"key": "same", "width": 10, "height": 1}, [], {"backgroundColor": "#0000aa"}),
    ])
    lone = box({"height": 1}, ["x"], {"backgroundColor": "#bbbb00"})
    return {"cols": 40, "tab": "t", "tree": box({"flexDirection": "column"}, [card, grp, dup, lone])}


@pytest.fixture()
def page():
    from playwright.sync_api import sync_playwright
    info = pw.build_page(tree())
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:  # no chromium here
            pytest.skip(f"no headless chromium: {e}")
        pg = b.new_page(viewport={"width": int(info["width"]) + 2, "height": int(info["height"]) + 2})
        pg.set_content(info["html"])
        yield info, pg
        b.close()


def away(info, pg):
    pg.mouse.move(info["width"] + 1, info["height"] + 1)
    return pg.evaluate(pw.SNAP_JS)


def hover_by_key(pg, key):
    pts = pw.free_points(pg, key=key)
    assert pts, key
    pg.mouse.move(*pts[0])
    return pg.evaluate(pw.SNAP_JS)


def test_layout_gives_scopes_and_nearest_keyed_scope():
    r = pl.layout(tree())
    hv = {p.get("key"): p for p in r["prims"] if p["kind"] == "hover_rect" and p.get("key")}
    assert hv["row-1"]["scope"] == "row-1"  # a keyed hover Box is its own scope
    assert [p["scope"] for p in r["prims"] if p["kind"] == "hover_rect" and p["color"] == "#aa0000"] == ["card-a"]
    assert {p["key"] for p in r["prims"] if p["kind"] == "scope"} >= {"card-a", "row-1", "row-2", "same"}


def label_tree():
    btn = lambda k, t: {"type": "Button", "props": {"key": k, "label": t, "plain": True}, "children": []}
    absb = lambda c, top: box({"position": "absolute", "top": top, "left": 2}, [c])
    return {"cols": 40, "tab": "t", "tree": box({"flexDirection": "column", "height": 5}, [
        absb(btn("b1", "Open"), 0), absb(btn("b2", "Stop"), 2)])}


def test_host_hover_label_box_lights_and_no_neighbour_changes():
    """#926 row D: the label box of a plain Button in an absolute Box lights while the pointer is over it; named in guessed."""
    from playwright.sync_api import sync_playwright
    info = pw.build_page(label_tree())
    assert len(info["labels"]) == 2 and any("host hover" in g for g in info["guessed"])
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip(f"no headless chromium: {e}")
        pg = b.new_page(viewport={"width": int(info["width"]) + 2, "height": int(info["height"]) + 2})
        pg.set_content(info["html"])
        got = pw.check_hover(pg, info)
        b.close()
    assert (got["labels"], got["labels_lit"], got["labels_others"]) == (2, 2, 0), got["labels_unlit"]


def test_row1_every_hover_box_lights_when_hovered_by_key(page):
    info, pg = page
    got = pw.check_hover(pg, info)
    live = [h for h in info["hover"] if not h["inert"]]
    assert got["n"] == len(info["hover"]) == 8
    assert got["lit"] == len(live) == 5  # row-1, row-2, the card's unkeyed one, g1, g2; inert: the two "same" and the lone one
    assert not got["unlit"] or all("inert" in u for u in got["unlit"])
    assert got["others_total"] == 0  # row 2


def test_row2_only_the_hovered_scope_changes_colour(page):
    info, pg = page
    base = away(info, pg)
    snap = hover_by_key(pg, "row-1")
    ids = {h["key"]: h["id"] for h in info["hover"] if h["key"]}
    changed = {i for i in snap if snap[i] != base[i]}
    assert changed == {ids["row-1"]}


def test_card_scope_lights_the_unkeyed_hover_box(page):
    info, pg = page
    base = away(info, pg)
    pts = pw.free_points(pg, key="card-a")
    assert pts
    card_hv = [h["id"] for h in info["hover"] if h["scope"] == "card-a"]
    assert len(card_hv) == 1
    pg.mouse.move(*pts[0])
    snap = pg.evaluate(pw.SNAP_JS)
    assert snap[card_hv[0]] != base[card_hv[0]]


def test_inert_hover_boxes_do_not_light(page):
    info, pg = page
    base = away(info, pg)
    inert = [h for h in info["hover"] if h["inert"]]
    assert {h["key"] for h in inert} == {"same", None}
    pg.mouse.move(5, info["height"] - 5)  # over the lone Box
    snap = pg.evaluate(pw.SNAP_JS)
    assert snap == base


def test_guessed_and_unhandled_are_listed():
    t = tree()
    t["tree"]["children"][0]["props"]["borderStyle"] = "round"
    t["tree"]["children"][0]["hover"] = {"borderColor": "red"}
    t["tree"]["children"].append({"type": "Marquee", "props": {}, "children": []})
    info = pw.build_page(t)
    g = "\n".join(info["guessed"])
    assert "Box.borderStyle x1" in g and "hover.borderColor x1" in g and "duplicate keys" in g and "same" in g
    assert any(u["type"] == "Marquee" for u in info["unhandled"])


def test_hover_picture_and_card_clip(tmp_path):
    info = pw.build_page(tree())
    got = pw.run_page(info, tmp_path, hover="row-1", card="card-a")
    from PIL import Image
    im = Image.open(got["pictures"][0]).convert("RGB")
    assert abs(im.size[0] - 40 * pl.COL_PX) <= 1 and abs(im.size[1] - 6 * pl.CELL) <= 1
    assert im.getpixel((5, 5)) == (0x2f, 0x2f, 0x33)  # row-1 lit
    assert im.getpixel((5, 2 * 19 + 5)) == (0x10, 0x10, 0x10)  # row-2 not
    assert (tmp_path / "pane.html").read_text(encoding="utf-8").startswith("<!doctype html>")


def _windows():
    if sys.platform != "win32":
        return None
    u = ctypes.windll.user32
    seen = []
    cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(lambda h, p: (seen.append(h) if u.IsWindowVisible(h) else None) or True)
    u.EnumWindows(cb, 0)
    return sorted(seen)


def _cursor():
    if sys.platform != "win32":
        return None
    import ctypes.wintypes as wt
    pt = wt.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def _last_input_tick():
    """GetLastInputInfo: the tick of the owner's last real input (as scripts/pane_look.py's gate reads it)."""
    if sys.platform != "win32":
        return None

    class LII(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    i = LII(ctypes.sizeof(LII), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(i))
    return i.dwTime


def test_row5_no_window_no_install_no_real_pointer(tmp_path):
    mods = Path.home() / ".claude" / "mods"
    listing = lambda: sorted(p.name for p in mods.iterdir()) if mods.is_dir() else []
    before = (_windows(), _cursor(), listing())
    tick0 = _last_input_tick()
    info = pw.build_page(tree())
    got = pw.run_page(info, tmp_path, hover="row-1", check=True)
    after = (_windows(), _cursor(), listing())
    owner_moved = _last_input_tick() != tick0  # his own mouse / keys: the pointer difference then says nothing about the page
    assert got["check"]["others_total"] == 0
    assert after[0] == before[0], "a new visible window"
    assert owner_moved or after[1] == before[1], "the real pointer moved with no input from the owner"
    assert after[2] == before[2], "~/.claude/mods changed"
    src = (ROOT / "scripts" / "pane_web.py").read_text(encoding="utf-8")
    assert not any(w in src for w in ("SetCursorPos", "SendInput", "mouse_event", "mklink", "headless=False"))


def test_real_main_tab_if_a_dump_is_possible():
    """Rows 1-2 on the real main tab: N of N, 0 neighbours (the claude.exe plugin test makes the dump; skipped where none)."""
    import pane_dump
    if pane_dump.claude_exe() is None:
        pytest.skip("no claude.exe")
    from playwright.sync_api import sync_playwright
    d = pane_dump.dump(str(ROOT), "live-fast", "main", False, 123)
    info = pw.build_page(d)
    # #994: one hover look. No Box draws a square fill of its own; the rounded light is the host Button's, one per label box.
    assert len(info["hover"]) == 0, [h["key"] for h in info["hover"]]
    assert len(info["labels"]) > 0
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip(f"no headless chromium: {e}")
        pg = b.new_page(viewport={"width": int(info["width"]) + 2, "height": int(info["height"]) + 2})
        pg.set_content(info["html"])
        got = pw.check_hover(pg, info)
        b.close()
    assert got["lit"] == got["n"], got["unlit"]
    assert got["others_total"] == 0
    assert got["labels_lit"] == got["labels"], got["labels_unlit"]
    assert got["labels_others"] == 0


def _ids(block):
    return re.findall(r"""\bid=["']([^"']+)["']""", block)


def _svg_blocks(html_text):
    return re.findall(r"<svg\b.*?</svg>", html_text, flags=re.S)


def test_svgs_share_no_ids_on_the_real_main_tab():
    """#926 row A: the page's <svg> elements share ids on main (the first definition wins); each Svg isolated -> 0."""
    import pane_dump
    if pane_dump.claude_exe() is None:
        pytest.skip("no claude.exe")
    d = pane_dump.dump(str(ROOT), "live-fast", "main", False, 123)
    blocks = _svg_blocks(pw.build_page(d)["html"])
    # #995 send-back 2 row 3: the rows' own light pictures are gone (one light, the host's rectangle): the tab bar, the card heads and the card pictures are 7
    assert len(blocks) >= 7
    ids = [i for b in blocks for i in _ids(b)]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    assert dups == [], f"{len(dups)} duplicate ids: {dups[:8]}"


def test_svg_reference_resolves_inside_its_own_svg():
    mk = lambda: ('<svg width="10" height="10"><defs><linearGradient id="g"><stop/></linearGradient></defs>'
                  '<rect fill="url(#g)"/><use href="#g"/></svg>')
    t = {"cols": 20, "tab": "t", "tree": box({"flexDirection": "column"}, [
        {"type": "Svg", "props": {"source": mk(), "width": 2, "height": 1}, "children": []},
        {"type": "Svg", "props": {"source": mk(), "width": 2, "height": 1}, "children": []}])}
    blocks = _svg_blocks(pw.build_page(t)["html"])
    assert len(blocks) == 2
    for b in blocks:
        refs = re.findall(r"url\(#([^)]+)\)", b) + re.findall(r'href="#([^"]+)"', b)
        assert refs and set(refs) <= set(_ids(b))
    assert not set(_ids(blocks[0])) & set(_ids(blocks[1]))
