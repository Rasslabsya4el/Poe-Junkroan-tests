"""scripts/pane_layout.py: a hand-made tree gives hand-computed px (#843 unit 2). 0 PoB, no node."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pane_layout as pl  # noqa: E402


def svg(h, body, w=900):
    return {"type": "Svg", "props": {"source": f"<svg width='{w}' height='{h}'>{body}</svg>", "alt": "a\nb\nc", "height": h}}


def box(props, children=None, hover=None):
    n = {"type": "Box", "props": props, "children": children or []}
    if hover:
        n["hover"] = hover
    return n


def tree():
    rows = svg(114, "".join(f"<g transform='translate(0 {y})'><rect/></g>" for y in (9, 47, 85)))
    hov = {"backgroundColor": "#2f2f33"}
    presses = box({"position": "absolute", "top": 0, "left": 0, "right": 0, "flexDirection": "column"},
                  [box({"position": "absolute", "top": 2 * i, "left": 5, "height": 2, "alignItems": "center"},
                       [{"type": "Button", "props": {"key": f"b{i}", "label": "x"}}], hov) for i in range(3)])
    table = svg(57, "<text><tspan x='1' y='33'>a</tspan><tspan x='1' y='52'>b</tspan></text>")
    rowbox = lambda gap: box({"height": 1, **({"marginTop": gap} if gap else {})}, [], {"backgroundColor": "#58a6ff2e"})
    return {"cols": 100, "tree": box({"flexDirection": "column"}, [
        svg(30, "<text/>"),
        box({"flexDirection": "column"}, [rows, presses]),
        box({"flexDirection": "column"}, [table, box({"position": "absolute", "top": 0, "left": 2, "right": 0, "flexDirection": "column"},
                                                       [rowbox(1), rowbox(0)])]),
    ])}


def test_rows_and_hover_rects_in_px():
    r = pl.layout(tree())
    assert r["unhandled"] == []
    svgs = [p for p in r["prims"] if p["kind"] == "svg"]
    assert [s["y"] for s in svgs] == [0, 30, 144]
    assert svgs[1]["row_tops"] == [30, 68, 106]  # 30 + 0, 38, 76
    hov = [p for p in r["prims"] if p["kind"] == "hover_rect"]
    assert [(h["y"], h["h"]) for h in hov[:3]] == [(30, 38), (68, 38), (106, 38)]
    assert [h["y"] - t for h, t in zip(hov[:3], svgs[1]["row_tops"])] == [0, 0, 0]
    assert hov[0]["x"] == 5 * pl.COL_PX
    # the table: rows at 144 + 19, + 38; hover rects 1 cell high, the first behind a marginTop of 1 cell
    assert svgs[2]["row_tops"] == [144 + 19, 144 + 38]
    assert [h["y"] for h in hov[3:]] == [144 + 19, 144 + 38]
    assert all(h["h"] == 19 for h in hov[3:])


def test_unknown_prop_is_listed_not_dropped():
    t = tree()
    t["tree"]["children"][0]["props"]["blur"] = 3
    t["tree"]["children"].append({"type": "Marquee", "props": {}, "children": []})
    got = {(u["type"], u["prop"]) for u in pl.layout(t)["unhandled"]}
    assert ("Svg", "blur") in got and ("Marquee", "<type>") in got


def test_card_summary_and_drift_visible():
    t = tree()
    t["tree"]["children"][1]["children"][1]["children"][1]["props"]["top"] = 3  # a Box off its row by a cell
    t["tree"]["children"][1]["props"]["key"] = "card-x"
    t["tree"]["children"][1]["props"].update(backgroundColor="#262628", borderStyle="round")
    c = pl.cards(pl.layout(t)["prims"])
    assert c[0]["card"] == "card-x" and abs(c[0]["worst"]["offset"]) == 19


def test_old_picture_band_drift_is_read_from_the_drawn_band():
    """7a4317de: rows drawn 24 px apart as bands at their group's Y, press Boxes on the 19 px cell grid: the 9 px drift is visible."""
    band = "<rect x='28' width='935' height='20' rx='4' fill='#212123'/>"
    rows = svg(96, "".join(f"<g transform='translate(0 {y})'>{band}</g>" for y in (24, 48, 72)))
    presses = box({"position": "absolute", "top": 0, "left": 0, "right": 0, "flexDirection": "column"},
                  [box({"position": "absolute", "top": t, "left": 0, "height": 1}, [{"type": "Button", "props": {"key": f"b{t}", "label": "x"}}])
                   for t in (1, 3, 4)])  # tops 19, 57, 76 against bands at 24, 48, 72
    card = box({"flexDirection": "column", "key": "card-x", "backgroundColor": "#262628"}, [box({"flexDirection": "column"}, [rows, presses])])
    c = pl.cards(pl.layout({"cols": 100, "tree": card})["prims"])
    assert [o["offset"] for o in pl.band_offsets(pl.layout({"cols": 100, "tree": card})["prims"], 0, 999)] == [-5, 9, 4]
    assert c[0]["worst"]["offset"] == 9


def sel(value, label=None):
    props = {"key": "s", "options": [{"value": "60", "label": "1 h"}, {"value": "7"}], "value": value}
    if label:
        props["label"] = label
    return {"type": "Select", "props": props}


def test_select_width_is_its_selected_labels_length():
    r = pl.layout({"cols": 100, "tree": box({"flexDirection": "row", "gap": 1}, [sel("60"), sel("7"), sel("60", "x:")])})
    texts = [p for p in r["prims"] if p["kind"] == "text"]
    assert [t["text"] for t in texts] == ["1 h", "7", "x: 1 h"]
    assert texts[1]["x"] - texts[0]["x"] == texts[0]["w"] + (texts[0]["w"] / 3) * 1  # width 3 cols + gap 1 col


def reserve_row_overlaps(d):
    r = pl.layout(d)
    texts = [p for p in r["prims"] if p["kind"] == "text" and p["text"].strip()]
    anchor = [p for p in texts if p["text"].strip() == "Зарезервировать"]
    assert anchor, "no reserve row in the tree"
    out = 0
    for a in anchor:
        row = sorted((p for p in texts if abs(p["y"] - a["y"]) < 1), key=lambda p: p["x"])
        out += sum(1 for p, q in zip(row, row[1:]) if p["x"] + p["w"] > q["x"] + 0.01)
    return out, [p["text"] for p in texts if abs(p["y"] - anchor[0]["y"]) < 1]


def test_reserve_row_text_boxes_do_not_overlap_on_the_real_main_tab():
    import pane_dump, pytest
    d = pane_dump.dump(str(Path(__file__).resolve().parents[1]), "live-fast", "main", False, 119)
    with pytest.raises(AssertionError, match="no reserve row"):
        reserve_row_overlaps(d)


def test_plain_button_in_absolute_box_gets_a_label_hover():
    """#926 row D: the host lights the label box of a plain Button / Link in an absolute Box (a guess about the closed host)."""
    btn = {"type": "Button", "props": {"key": "go", "label": "Open", "plain": True}, "children": []}
    link = {"type": "Link", "props": {"href": "x", "label": "#12"}, "children": []}
    absbox = lambda c, top: {"type": "Box", "props": {"position": "absolute", "top": top, "left": 3}, "children": [c]}
    flowbox = {"type": "Box", "props": {}, "children": [dict(btn)]}
    tree = {"type": "Box", "props": {"flexDirection": "column", "height": 4}, "children": [absbox(btn, 0), absbox(link, 2), flowbox]}
    r = pl.layout({"cols": 40, "tab": "t", "tree": tree})
    lh = [p for p in r["prims"] if p["kind"] == "label_hover"]
    assert len(lh) == 2  # the Button and the Link in absolute Boxes, not the one in flow
    b = lh[0]
    assert (b["x"], b["w"], b["h"]) == (3 * pl.COL_PX, 4 * pl.COL_PX, pl.CELL) and b["text"] == "Open"
    assert lh[1]["w"] == 3 * pl.COL_PX
