"""#987: the pointer tool takes an element, proves on the after-picture that the pointer was on it, and counts the tries.

Runs on pictures and trees RECORDED from the real pane on 2026-10-14 (fixtures/pane_elements: `pane_elements.py record`
and `hover --keep-raw`); it starts no pointer, opens no window and reads no live pane.

    python -m pytest -q mods/pob-slots/bin/test_pane_elements.py
"""
import copy
import json
import time
from pathlib import Path

import pytest
from PIL import Image, ImageChops

import pane_elements as pe

FIX = Path(__file__).resolve().parent / "fixtures" / "pane_elements"


def record(name):
    return pe.load_record(FIX / ("rec-%s.json" % name))


def hover_fixture(name):
    """A recorded hover: its log line, the look before it, the look with the pointer on the element (as the screen was),
    and the after-picture the tool wrote (the pointer drawn); the three pictures are the same cut of the screen."""
    rec = json.loads((FIX / ("hover-%s.json" % name)).read_text(encoding="utf-8"))
    ox, oy = rec["origin"]

    def full(path):
        crop = Image.open(path).convert("RGB")
        im = Image.new("RGB", tuple(rec["screen"]), (0, 0, 0))
        im.paste(crop, (ox, oy))
        return im
    return rec, full(FIX / ("hover-%s.base.png" % name)), full(FIX / ("hover-%s.raw.png" % name)), FIX / ("hover-%s.png" % name)


# ---------------------------------------------------------------- row 2: the after-picture must show the pointer on the element

def test_the_pointer_is_read_off_the_picture_not_assumed():
    bare = Image.new("RGB", (300, 120), pe.PANE_BG)
    assert pe.find_pointer(bare) is None
    assert pe.find_pointer(pe.draw_pointer(bare, 57, 31)) == (57, 31)
    assert pe.find_pointer(pe.draw_pointer(bare, 0, 0)) == (0, 0)


@pytest.mark.parametrize("name", ["tab", "number", "row", "inert"])
def test_a_recorded_after_picture_shows_the_pointer_inside_its_element(name):
    rec, _base, _raw, after = hover_fixture(name)
    at = pe.check_after(after, rec["rect"], tuple(rec["origin"]))
    assert list(at) == rec["pointer"] == rec["sent"]
    assert pe.inside(rec["rect"], *at)


@pytest.mark.parametrize("name", ["tab", "number", "row"])
def test_a_pointer_outside_the_rectangle_fails_loudly(name):
    rec, _base, _raw, after = hover_fixture(name)
    l, t, r, b = rec["rect"]
    beside = [r + 1, t, r + 1 + (r - l), b]  # the rectangle right of the element: the pointer is not in it
    with pytest.raises(pe.Miss) as e:
        pe.check_after(after, beside, tuple(rec["origin"]))
    assert "outside the element's rectangle" in str(e.value)
    above = [l, t - 40, r, t - 21]
    with pytest.raises(pe.Miss):
        pe.check_after(after, above, tuple(rec["origin"]))


def test_a_picture_without_a_pointer_fails_loudly(tmp_path):
    rec, base, _raw, _after = hover_fixture("tab")
    ox, oy = rec["origin"]
    plain = tmp_path / "no-pointer.png"
    base.crop((ox, oy, ox + 400, oy + 100)).save(plain)
    with pytest.raises(pe.Miss) as e:
        pe.check_after(plain, rec["rect"], (ox, oy))
    assert "shows no pointer" in str(e.value)


# ---------------------------------------------------------------- what lit, read off the before and after pictures

def test_a_tab_head_lights_its_own_rectangle():
    rec, base, raw, _ = hover_fixture("tab")
    lit = pe.light_rect(base, raw, rec["rect"])
    assert lit is not None and list(lit["rect"]) == rec["lit"]
    l, t, r, b = lit["rect"]
    assert 30 <= r - l + 1 <= 70 and b - t + 1 == 19  # a word's width, one text line high
    assert pe.inside(lit["rect"], *rec["pointer"])
    assert pe.lit_region(base, raw, *rec["pointer"])["rect"] == lit["rect"]  # read from the point alone it is the same shape


def test_a_number_on_a_lit_row_is_cut_out_of_the_rows_light():
    rec, base, raw, _ = hover_fixture("number")
    lit = pe.light_rect(base, raw, rec["rect"])
    assert list(lit["rect"]) == rec["lit"]
    l, t, r, b = lit["rect"]
    assert r - l + 1 <= 60, "the number's own light, not the row's 900 px"
    assert rec["delta"] >= rec["light_beside"] + 3 and rec["light_beside"] > 0  # the row beside it is lit too, fainter
    assert pe.light_in(base, raw, (l - 60, t + 2, l - 20, b - 2)) < lit["delta"]


def test_a_rectangle_beside_the_light_reads_no_light():
    # the press of 04:33: a run title's right end was laid 6 px past its light and four presses went beside the button;
    # a rectangle that is not on the light must not be called lit
    rec, base, raw, _ = hover_fixture("tab")
    l, t, r, b = rec["lit"]
    w = r - l + 1
    assert pe.light_rect(base, raw, (r + 12, t, r + 12 + w, b)) is None
    assert pe.light_rect(base, raw, (l, t + 40, r, b + 40)) is None


def test_a_row_lights_and_a_non_clickable_place_lights_nothing():
    rec, base, raw, _ = hover_fixture("row")
    assert pe.lit_region(base, raw, *rec["pointer"]) is not None
    assert pe.light_in(base, raw, rec["rect"]) > 0
    rec, base, raw, _ = hover_fixture("inert")
    x, y = rec["pointer"]
    assert pe.lit_region(base, raw, x, y) is None
    assert pe.light_in(base, raw, (x - 20, y - 6, x + 20, y + 6)) == 0


# ---------------------------------------------------------------- row 1: the tree laid on the picture, confirmed there

@pytest.mark.parametrize("name", ["main", "builds", "cost"])
def test_every_button_of_a_recorded_tab_is_found_on_its_picture(name):
    im, state = record(name)
    s = pe.Snap(im, state)
    assert s.right - s.left + 1 == 950 and abs(s.cell - pe.HOST_CELL_PX) < 0.01
    shown = [e for e in s.elements if e["state"] == "ok" and e["kind"] == "button"]
    assert len(shown) >= 12
    assert [e["id"] for e in shown if not e["drawn"]] == []
    heads = [e for e in shown if e["id"].startswith("tab-")]
    assert [e["label"] for e in heads] == ["Главная", "POB", "Билды", "Тикеты", "Расходы", "Прогресс"]
    assert all(a["rect"][2] < b["rect"][0] for a, b in zip(heads, heads[1:]))
    assert all(abs(e["rect"][1] - heads[0]["rect"][1]) <= 2 for e in heads)  # one line; a word's own glyphs set it within 2 px


def test_the_cards_edges_are_found_where_rows_are_lighter_tiles():
    # 2026-10-14 04:12: on this tab the widest run of full card columns was 583 px of the card's 950; every tab head was laid
    # 0.61 of its way and the tool pressed «Билды» four times as «Тикеты»
    im, _state = record("builds")
    pic = pe.picture_cards(im)
    assert pic["right"] - pic["left"] + 1 == 950


def test_a_recorded_hover_lies_inside_the_same_elements_rectangle_of_the_recorded_tab():
    im, state = record("main")
    s = pe.Snap(im, state)
    for name in ("tab", "number", "row"):
        rec, _b, _r, _a = hover_fixture(name)
        el = s.get(rec["id"])
        assert pe.inside(el["rect"], *rec["pointer"]), (name, el["rect"], rec["pointer"])


def test_a_tree_of_another_tab_does_not_lie_on_the_picture():
    im, _ = record("main")
    _, other = record("builds")
    with pytest.raises(pe.MappingError):
        pe.Snap(im, other)


def _find(n, key):
    if isinstance(n, dict):
        if (n.get("props") or {}).get("key") == key:
            return n
        for c in n.get("children") or []:
            hit = _find(c, key)
            if hit is not None:
                return hit
    return None


def test_a_card_whose_rows_changed_is_stale_and_the_others_keep_their_place():
    im, state = record("main")
    fresh = {e["id"]: e for e in pe.Snap(im, state).elements}
    old = copy.deepcopy(state)
    merge = _find(old["tree"], "card-merge")
    merge["children"].append({"type": "Svg", "props": {"source": "<svg xmlns='http://www.w3.org/2000/svg' width='940' height='26'/>", "alt": "row", "height": 26}})
    s = pe.Snap(im, old)
    states = {c["key"]: c["state"] for c in s.cards}
    assert states["card-merge"] == "stale" and states["card-pc"] == "ok" and states["card-agents"] == "ok"
    for e in s.elements:
        if e.get("card") == "card-merge":
            assert e["state"] == "stale"
        elif e["kind"] != "inert":
            assert e["rect"] == fresh[e["id"]]["rect"], e["id"]  # the tab heads, the cards above and below


def test_a_misplaced_label_is_not_found_on_the_picture():
    im, state = record("cost")
    s = pe.Snap(im, state)
    el = dict(s.get("costg-spawn"))
    assert el["drawn"] and pe.face_on_picture(im, el) == el["rect"]
    l, t, r, b = el["rect"]
    for dx in (-40, 40):
        moved = dict(el, rect=(l + dx, t, r + dx, b))
        assert pe.face_on_picture(im, moved) is None
    # a 9-px drift along a row of controls is set right from the glyphs themselves
    assert pe.face_on_picture(im, dict(el, rect=(l + 9, t, r + 9, b))) == el["rect"]


def test_what_acts_outside_the_pane_is_named():
    im, state = record("main")
    s = pe.Snap(im, state)
    acting = {e["id"]: e["acts"] for e in s.elements if e["acts"]}
    assert any(k.startswith("lk-") for k in acting) and "res-go-pc" in acting and "res-n-pc" in acting
    assert all(not e["acts"] for e in s.elements if e["id"].startswith("tab-"))
    assert pe.acts("open-pob-x") and pe.acts("tl-tkg-0-#780") and pe.acts("tg-780") is None and pe.acts("run-pick-j-1") is None


def test_the_pages_own_shift_is_read_off_two_pictures():
    im, _ = record("cost")
    pic = pe.picture_cards(im)
    l, r, (vt, vb) = pic["left"], pic["right"], pic["viewport"]
    page = (l, vt, r + 1, vb + 1)
    assert pe.page_shift(im, im, page) == 0
    moved = im.copy()
    moved.paste(im.crop((l - 12, vt + 300, r + 13, vb + 1)), (l - 12, vt))
    assert pe.page_shift(im, moved, page) == 300
    assert pe.page_shift(moved, im, page) == -300


# ---------------------------------------------------------------- rows 3 and 4: a press counts its tries (a rig, no pointer)

class Rig:
    """The pane as files and pictures: the recorded tab's state in a cache folder, a look that returns its picture, and a
    press that takes effect on the `works_on`-th click (the pane then writes its next state line, as the real one does)."""

    def __init__(self, tmp_path, monkeypatch, works_on, land=(0, 0), lights=True):
        self.im, self.state = record("main")
        self.cache = tmp_path / "cache"
        (self.cache / "state").mkdir(parents=True)
        self.clicks, self.hovers, self.works_on, self.land, self.lights = [], [], works_on, land, lights
        self.face = pe.Snap(self.im, self.state).get("tab-pob")["rect"]
        self.write(self.state["tree"], "main", 0)
        monkeypatch.setattr(pe, "look", lambda: self.im)
        monkeypatch.setattr(pe, "raw_press", self.raw_press)
        monkeypatch.setattr(pe, "raw_hover", self.raw_hover)
        self.pane = pe.Pane(tmp_path / "out", self.cache)
        self.pane.line_wait = 0.05

    def raw_hover(self, x, y, out, box=None):
        """The pointer rests on the point: the host lights the tab head when the point is on it (and the rig says it lights)."""
        at = (x + self.land[0], y + self.land[1])
        self.hovers.append((x, y))
        im = self.im
        if self.lights and pe.inside(self.face, *at):
            l, t, r, b = self.face
            lit = ImageChops.add(im.crop((l, t, r + 1, b + 1)), Image.new("RGB", (r - l + 1, b - t + 1), (17, 17, 17)))
            im = im.copy()
            im.paste(lit, (l, t))
        marked = pe.draw_pointer(im, *at)
        (marked.crop(box) if box else marked).save(out)
        return im, at

    def write(self, tree, tab, n):
        (self.cache / "state" / ("tree-%02d.json" % n)).write_text(json.dumps(tree), encoding="utf-8")
        line = dict(self.state["line"], t=time.strftime("%Y-%m-%dT%H:%M:%S"), tab=tab, tree="tree-%02d.json" % n)
        with open(self.cache / "state.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    def raw_press(self, x, y, out, box=None):
        at = (x + self.land[0], y + self.land[1])
        self.clicks.append((x, y))
        marked = pe.draw_pointer(self.im, *at)
        (marked.crop(box) if box else marked).save(out)
        if len(self.clicks) == self.works_on:  # the press lands: the pane redraws another tab and writes its line
            tree = copy.deepcopy(self.state["tree"])
            _find(tree, "tab-main")["props"]["dimColor"] = True
            _find(tree, "tab-pob")["props"].pop("dimColor", None)
            self.write(tree, "pob", 1)
        return self.im, at


def test_a_press_that_works_at_once_is_one_try(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, works_on=1)
    rec = rig.pane.press("tab-pob")
    assert (rec["tries"], rec["pressed"], rec["change"]) == (1, True, "tab main -> pob")
    assert len(rig.clicks) == 1 and pe.inside(rec["rect"], *rig.clicks[0])


def test_a_press_that_needs_three_clicks_says_three(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, works_on=3)
    rec = rig.pane.press("tab-pob", "left")
    assert (rec["tries"], rec["pressed"]) == (3, True)
    assert rec["on_light"] == [True, True]  # the two tries that did nothing were ON the lit element: its defect, counted
    assert rec["face"] == "its light on a hover picture"
    assert rig.clicks[0][0] == rig.face[0] + pe.EDGE_IN  # near the left end of the LIGHT, and still inside it
    assert all(pe.inside(rig.face, *c) for c in rig.clicks)


def test_a_press_that_never_works_is_never_called_pressed(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, works_on=99)
    rec = rig.pane.press("tab-pob", "right", tries=4)
    assert (rec["tries"], rec["pressed"], rec["change"]) == (4, False, "nothing")
    assert rig.clicks[0][0] == rig.face[2] - pe.EDGE_IN
    log = [json.loads(ln) for ln in (tmp_path / "out" / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log[-1]["tries"] == 4 and log[-1]["pressed"] is False and log[-1]["on_light"] == [True] * 4


def test_a_try_with_no_light_under_the_pointer_is_the_tools_miss_not_the_elements_defect(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, works_on=99, lights=False)
    with pytest.raises(pe.Miss) as e:
        rig.pane.press("tab-pob")
    assert "beside the element" in str(e.value) and len(rig.clicks) == 1  # one try, then it stops: no count of four
    log = [json.loads(ln) for ln in (tmp_path / "out" / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "miss" in log[-1]
    tot = pe.report(tmp_path / "out" / "log.jsonl", tmp_path / "tables")
    assert tot["misses"] == 1 and tot["never"] == [] and tot["slow"] == []


def test_a_press_whose_picture_shows_the_pointer_elsewhere_is_a_miss_not_a_look(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, works_on=1, land=(120, 0))
    with pytest.raises(pe.Miss):
        rig.pane.press("tab-pob")
    log = [json.loads(ln) for ln in (tmp_path / "out" / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "outside the element's rectangle" in log[-1]["miss"]
    with pytest.raises(pe.Miss):
        rig.pane.hover("tab-pob")


def test_what_acts_outside_the_pane_is_refused(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, works_on=1)
    with pytest.raises(SystemExit) as e:
        rig.pane.press("res-go-pc")
    assert "never pressed" in str(e.value) and rig.clicks == []


def test_the_tables_count_tries_and_misses(tmp_path):
    log = tmp_path / "log.jsonl"
    rows = [
        dict(action="hover", id="tab-pob", kind="button", label="POB", at="centre", tab="main", view="", pic="a.png", lights=True),
        dict(action="press", id="tab-pob", kind="button", label="POB", at="centre", tab="main", view="", tries=1, pressed=True, change="tab main -> pob", pics=["b.png"]),
        dict(action="press", id="tab-pob", kind="button", label="POB", at="left", tab="main", view="", tries=3, pressed=True, change="tab main -> pob", pics=["c.png"]),
        dict(action="press", id="tab-pob", kind="button", label="POB", at="right", tab="main", view="", tries=4, pressed=False, change="nothing", pics=["d.png"]),
        dict(action="hover", id="hv-mg2", kind="row", label="ничего", at="centre", tab="main", view="", pic="e.png", lights=True),
        dict(action="hover", id="inert:merge~2", kind="inert", label="Идёт", at="centre", tab="main", view="", pic="f.png", lights=False),
        dict(action="hover", id="lk-mg6-#985", kind="button", label="  ", at="centre", tab="main", view="", pic="g.png", lights=True, acts="opens the ticket in the browser"),
        dict(action="hover", id="tab-cost", kind="button", label="Расходы", at="centre", tab="main", view="", pic="h.png", miss="outside"),
    ]
    log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    tot = pe.report(log, tmp_path / "tables")
    assert tot["elements"] == 5 and tot["misses"] == 1 and tot["presses"] == 3 and tot["press_tries"] == 8
    assert len(tot["slow"]) == 1 and len(tot["never"]) == 1 and tot["not_pressed_acts"] == 1
    assert tot["placeholders"] == 1 and len(tot["placeholders_lit"]) == 1 and tot["inert"] == 1 and tot["inert_lit"] == []
    t3 = (tmp_path / "tables" / "table-rows3-elements.md").read_text(encoding="utf-8")
    assert "| 1 / 3 / never (4) |" in t3 and "hover only, press skipped: acts" in t3 and "MISS x1" in t3
    t4 = (tmp_path / "tables" / "table-row4-presses-over-one-try.md").read_text(encoding="utf-8").splitlines()
    assert len(t4) == 2 + 2  # the 3-try press and the one that never pressed; the 1-try press is not a defect
    t5 = (tmp_path / "tables" / "table-row5-placeholders-and-cells.md").read_text(encoding="utf-8")
    assert "NO: it lights" in t5 and "| yes |" in t5
