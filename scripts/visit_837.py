"""The visit of #837 (unit 2): one install of the candidate into the owner's monitor pane, then the hover check
of every row on every tab, then the verdict: "stays", or "put back" (the backup copied back).

  python scripts/visit_837.py --plan [--rows 14,12,8,6,5]
  python scripts/visit_837.py --run --out-dir <dir> [--tabs main:x:y,builds:x:y,tickets:x:y,cost:x:y,progress:x:y]
  python scripts/visit_837.py --run --dry-run ...        (prints the steps; calls no seam)

Every real thing is a keyword seam of run_visit(); the defaults only REFERENCE the real functions, so importing
this module calls nothing. Tests pass fakes. The tab heads come from find_tab_heads(picture) (the tab strip of the
pane); --tabs overrides them.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import time
import zlib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
for _p in (SCRIPTS, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pane_look as pl  # noqa: E402  (stdlib only at import; no call)
from junkroan.report_format import human_duration  # noqa: E402

# -- constants (the planned minutes come from these) ----------------------------------------------
PRESS_GATE_S = pl.IDLE_NEED_S     # 120 s: a gated call waits until the owner had no input this long
PRESS_RESETS_IDLE = True          # ASSUMED, not measured: an own press restarts that clock; hover-series does not
PRESS_S = 0.4                     # one press: the pointer's settle, the button, the put-back of the pointer
LOOK_S = 0.5                      # seconds per picture
HOVER_REST_S = pl.HOVER_REST_S    # 0.6 s: the pointer rests on the row before its picture
INSTALL_S = 20                    # the install of the candidate (one call)
SETTLE_S = 180                    # step 3: the looks at +60, +120, +180 s after the install
DEADLINE_S = 14 * 60              # step 5: 14 minutes after step 1 starts
PAINTED_BYTES = 250 * 1024        # step 1: a painted pane picture is at least this big
GREY_BYTES = 200 * 1024           # any picture under this is grey
SERIES_MAX = pl.SERIES_MAX        # 20 points per hover-series call
LOOK_AFTER_INSTALL_S = (60, 120, 180)
RECHECK_AFTER_PUT_BACK_S = 60
TILE_GROW_PX = 3                  # the diff counts inside the row's tile grown by 3 px each side
POINT_HALF_PX = 5                 # a row given as a bare point gets a 10 px tile round it
TAB_X_TOL_PX = 10                 # the underline span must hold the pressed head's x, +- this
UNDERLINE_RGB = (68, 147, 248)    # the active-tab underline colour
UNDERLINE_BOX = (1560, 105, 2000, 113)   # x0, y0, x1, y1 (inclusive), as the spec gives it
TAB_STRIP_BOX = (1560, 88, 2000, 102)    # x0, y0, x1, y1 (inclusive): the row of the five tab labels
TAB_LABEL_GAP_PX = 24             # empty columns wider than this separate two labels
TEXT_LUMA_MIN = 110               # light text: luminance above this
TAB_ORDER = ("main", "builds", "tickets", "cost", "progress")   # left to right: Главная Билды Тикеты Расходы Прогресс
N_TABS = len(TAB_ORDER)
DEFAULT_ROWS = (12, 12, 12, 12, 12)
INSTALL_NAME = "pob-slots"
CRASHPAD_DIR = r"C:\Users\user\AppData\Roaming\Claude\Crashpad"
PNG_SIG = b"\x89PNG\r\n\x1a\n"


# -- real seams (referenced as defaults; called only by --run) ------------------------------------
def real_press(x: int, y: int) -> int:
    if not pl.wait_for_pause():
        return 3
    return pl.do_press(x, y)


def real_look(path: str) -> int:
    return pl.do_look(path)


def real_hover_series(points, out_dir: str) -> int:
    if not pl.wait_for_pause():
        return 3
    os.makedirs(out_dir, exist_ok=True)
    return pl.do_hover_series(list(points), os.path.join(out_dir, "hover_{k}.png"))


def real_crashpad_mtime():
    newest = None
    for dirpath, _dirs, files in os.walk(CRASHPAD_DIR):
        for fn in files:
            t = os.path.getmtime(os.path.join(dirpath, fn))
            newest = t if newest is None or t > newest else newest
    return newest


def _mods():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.agentops import mods
    return mods


def real_install() -> int:
    return _mods().run_install(INSTALL_NAME)   # never force=True


def real_put_back() -> int:
    """The put-back of #837: scripts/mod_putback.py on the install folder (newest backup, byte-equal read)."""
    import mod_putback
    return mod_putback.main([str(_mods().install_root() / INSTALL_NAME)])


def _old_put_back() -> int:
    mods = _mods()
    inst = mods.install_root() / INSTALL_NAME
    cache = inst / "bin" / ".cache" if (inst / "bin").is_dir() else inst / ".cache"
    backups = sorted(p for p in cache.glob("backup-*") if p.is_dir()) if cache.is_dir() else []
    if not backups:
        return 1
    import shutil
    newest = backups[-1]
    n = 0
    for src in newest.rglob("*"):
        if src.is_file():
            dst = inst / src.relative_to(newest)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    print(f"put back {n} files from {newest}")
    return 0


def real_find_points(picture: str):
    import pane_points   # written by another unit; imported here only
    return pane_points.find_points(picture)


def _png_raw(path: str):
    """(width, raw) of an 8-bit RGB PNG as pane_look.write_png writes it: every row filter 0."""
    data = Path(path).read_bytes()
    if data[:8] != PNG_SIG:
        raise ValueError("not a PNG: %s" % path)
    pos, w, h, idat = 8, 0, 0, []
    while pos + 8 <= len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if tag == b"IHDR":
            w, h, depth, ctype, _c, _f, interlace = struct.unpack(">IIBBBBB", body)
            if (depth, ctype, interlace) != (8, 2, 0):
                raise ValueError("only 8-bit RGB, not interlaced: %s" % path)
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
    raw = zlib.decompress(b"".join(idat))
    stride = w * 3
    if len(raw) != h * (stride + 1) or any(raw[0::stride + 1]):
        raise ValueError("unexpected PNG layout (filters other than 0): %s" % path)
    return w, raw


def _px(raw: bytes, w: int, x: int, y: int) -> bytes:
    off = y * (w * 3 + 1) + 1 + x * 3
    return raw[off:off + 3]


def _luma(px: bytes) -> float:
    return 0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2]


def real_diff_pixels(rest_png: str, hovered_png: str, tile) -> int:
    """Pixels that differ inside the row's tile (inclusive l, t, r, b) grown by TILE_GROW_PX each side.
    0 = the row did not light."""
    w1, a = _png_raw(rest_png)
    w2, hb = _png_raw(hovered_png)
    h1 = len(a) // (w1 * 3 + 1)
    left, top, right, bottom = tile
    n = 0
    for yy in range(max(0, top - TILE_GROW_PX), min(h1 - 1, bottom + TILE_GROW_PX) + 1):
        for xx in range(max(0, left - TILE_GROW_PX), min(w1 - 1, right + TILE_GROW_PX) + 1):
            if _px(a, w1, xx, yy) != _px(hb, w2, xx, yy):
                n += 1
    return n


def real_underline_span(picture: str):
    """(min x, max x) of the active-tab underline colour inside UNDERLINE_BOX, or None."""
    w, raw = _png_raw(picture)
    x0, y0, x1, y1 = UNDERLINE_BOX
    want = bytes(UNDERLINE_RGB)
    xs = [x for y in range(y0, y1 + 1) for x in range(x0, min(x1, w - 1) + 1) if _px(raw, w, x, y) == want]
    return (min(xs), max(xs)) if xs else None


def real_find_tab_heads(picture: str) -> dict:
    """Centre of each of the five tab labels in TAB_STRIP_BOX, left to right, named by TAB_ORDER.
    A label is a run of light (luminance > TEXT_LUMA_MIN) columns; empty columns up to TAB_LABEL_GAP_PX join
    runs into one label. Raises ValueError when the strip does not hold exactly five labels."""
    w, raw = _png_raw(picture)
    x0, y0, x1, y1 = TAB_STRIP_BOX
    light = [x for x in range(x0, min(x1, w - 1) + 1)
             if any(_luma(_px(raw, w, x, y)) > TEXT_LUMA_MIN for y in range(y0, y1 + 1))]
    labels: list = []
    for x in light:
        if labels and x - labels[-1][1] - 1 <= TAB_LABEL_GAP_PX:
            labels[-1][1] = x
        else:
            labels.append([x, x])
    if len(labels) != N_TABS:
        raise ValueError("%d labels in the tab strip, need %d" % (len(labels), N_TABS))
    cy = (y0 + y1) // 2
    return {name: ((a + b) // 2, cy) for name, (a, b) in zip(TAB_ORDER, labels)}


# -- the plan of minutes ----------------------------------------------------------------------------
def plan_minutes(rows=DEFAULT_ROWS, presses_step1: int = 5, presses_step4: int = 5) -> dict:
    """Planned seconds of the visit from the constants above. presses_step1 = 0 drops step 1's presses;
    presses_step4 = 4 is the order without the main tab's press. Returns steps (name -> s), presses, total_s."""
    def press_cost(n: int) -> float:
        if not n:
            return 0.0
        gate = n * PRESS_GATE_S if PRESS_RESETS_IDLE else PRESS_GATE_S
        return gate + n * PRESS_S

    steps = {
        "step 1 look and tab presses": LOOK_S + press_cost(presses_step1) + presses_step1 * LOOK_S,
        "step 2 install": INSTALL_S,
        "step 3 settle and looks": SETTLE_S + LOOK_S,
        "step 4 tabs and rows": (press_cost(presses_step4) + len(rows) * LOOK_S
                                 + sum(rows) * (HOVER_REST_S + LOOK_S)),
    }
    total = sum(steps.values())
    return {"steps": steps, "presses": presses_step1 + presses_step4, "total_s": total,
            "fits_14_min": total <= DEADLINE_S}


def print_plan(rows=DEFAULT_ROWS, say=print) -> None:
    rows_text = ", ".join("%s %d" % (n, r) for n, r in zip(TAB_ORDER, rows))
    orders = (
        ("default order (5 presses in step 1, 5 in step 4)", plan_minutes(rows, 5, 5)),
        ("fewer presses (0 in step 1, 4 in step 4: main tab not pressed)", plan_minutes(rows, 0, 4)),
    )
    say("rows per tab in the pane's order: %s; a press costs %s of gate (PRESS_RESETS_IDLE=%s)"
        % (rows_text, human_duration(PRESS_GATE_S), PRESS_RESETS_IDLE))
    for label, p in orders:
        say("plan, " + label)
        for name, s in p["steps"].items():
            say("  %s: %s" % (name, human_duration(s)))
        say("  sum: %s, presses: %d, fits_14_min: %s" % (human_duration(p["total_s"]), p["presses"], p["fits_14_min"]))


# -- the visit --------------------------------------------------------------------------------------
def _hms(t) -> str:
    return "-" if t is None else time.strftime("%H:%M:%S", time.localtime(t))


def _norm(item) -> dict:
    """A find_points item as a dict: the pane_points dict, or a tuple (x, y) / (card, row, x, y) (old tests)."""
    if isinstance(item, dict):
        x, y = item["x"], item["y"]
        tile = tuple(item["tile"]) if item.get("tile") else (x - POINT_HALF_PX, y - POINT_HALF_PX,
                                                            x + POINT_HALF_PX - 1, y + POINT_HALF_PX - 1)
        return {"card": item.get("card"), "row": item.get("row"), "x": x, "y": y, "tile": tile,
                "placeholder": bool(item.get("placeholder", False))}
    if len(item) == 2:
        card, row, (x, y) = None, None, item
    else:
        card, row, x, y = item
    return {"card": card, "row": row, "x": x, "y": y,
            "tile": (x - POINT_HALF_PX, y - POINT_HALF_PX, x + POINT_HALF_PX - 1, y + POINT_HALF_PX - 1),
            "placeholder": False}


def _mark(steps, name, t0, now, say):
    t1 = now()
    steps.append({"step": name, "start": t0, "end": t1})
    say("%s: %s to %s, %s" % (name, _hms(t0), _hms(t1), human_duration(t1 - t0)))


def _write_table(out: Path, res: dict) -> Path:
    lines = ["# Visit #837 unit 2: %s" % res["verdict"], "", res["reason"], "",
             "| tab | rows | lit | failed | placeholder not lit | not hovered | duration | start | end |",
             "|---|---|---|---|---|---|---|---|---|"]
    by_tab = {t["tab"]: t for t in res["tabs"]}
    for name in res["tab_names"]:
        t = by_tab.get(name)
        if t is None:
            lines.append("| %s | - | - | - | - | - | - | - | - |" % name)
            continue
        lines.append("| %s | %s | %d | %d | %d | %d | %s | %s | %s |" % (
            name, t["rows"], t["lit"], t["failed"], t["placeholder_not_lit"], t["rows"] - t["hovered"],
            human_duration(t["end"] - t["start"]), _hms(t["start"]), _hms(t["end"])))
    lines += ["", "| step | start | end | duration |", "|---|---|---|---|"]
    for s in res["steps"]:
        lines.append("| %s | %s | %s | %s |" % (s["step"], _hms(s["start"]), _hms(s["end"]),
                                                human_duration(s["end"] - s["start"])))
    lines += ["", "failed rows: " + ("; ".join("%s / card %s / row %s" % f for f in res["failed"]) or "none")]
    path = out / "visit_837_table.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_visit(*, out_dir, tabs=None, press=real_press, look=real_look, hover_series=real_hover_series,
              install=real_install, put_back=real_put_back, crashpad_mtime=real_crashpad_mtime,
              find_points=real_find_points, diff_pixels=real_diff_pixels, find_tab_heads=real_find_tab_heads,
              picture_size=os.path.getsize, underline_span=real_underline_span, now=time.time,
              sleep=time.sleep, say=print, shown_tab_first=False, deadline_s=DEADLINE_S) -> dict:
    """Run the visit. tabs = None (the heads come from find_tab_heads of the first picture) or [(name, x, y)] x5
    in the pane's order (an override). The tab shown at the start is the first one.
    shown_tab_first=True (the owner's go 20, #837 6126493155): step 1 is one look, no press; step 4 does not press
    the first tab (it is shown already); deadline_s replaces the 14 minutes."""
    if tabs is not None and len(tabs) != N_TABS:
        raise ValueError("the visit has %d tabs, not %d" % (len(tabs), N_TABS))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    steps: list = []
    tab_rows: list = []
    failed: list = []
    res = {"verdict": None, "reason": "", "failed": failed, "tabs": tab_rows, "steps": steps,
           "tab_names": list(TAB_ORDER) if tabs is None else [t[0] for t in tabs]}

    def finish(verdict: str, reason: str) -> dict:
        res["verdict"], res["reason"] = verdict, reason
        table = _write_table(out, res)
        say("verdict: %s. %s" % (verdict, reason))
        for tname, card, row in failed:
            say("failed row: %s, card %s, row %s" % (tname, card, row))
        say("table: %s" % table)
        return res

    # step 1: the pane painted; the tab heads found (or given); the five heads pressed, a look after each
    t1 = now()
    pane = str(out / "step1_pane.png")
    look(pane)
    if picture_size(pane) < PAINTED_BYTES:
        _mark(steps, "step 1 look and tab presses", t1, now, say)
        return finish("stopped", "grey: the pane picture is under 250 KB; no install")
    if tabs is None:
        try:
            heads = find_tab_heads(pane)
        except ValueError as e:
            _mark(steps, "step 1 look and tab presses", t1, now, say)
            return finish("stopped", "tab heads not found (%s); no install" % e)
        missing = [n for n in TAB_ORDER if n not in heads]
        if missing:
            _mark(steps, "step 1 look and tab presses", t1, now, say)
            return finish("stopped", "tab heads missing: %s; no install" % ", ".join(missing))
        tabs = [(n, heads[n][0], heads[n][1]) for n in TAB_ORDER]
    say("tab heads: " + ", ".join("%s (%d, %d)" % t for t in tabs))
    for i, (tname, x, y) in enumerate(tabs):
        if shown_tab_first:
            break
        rc = press(x, y)
        head = str(out / ("step1_tab%d.png" % i))
        look(head)
        if rc or picture_size(head) < GREY_BYTES:
            rc_note = "press exit %d" % rc if rc else "grey picture"
            _mark(steps, "step 1 look and tab presses", t1, now, say)
            return finish("stopped", "%s on %s; no install" % (rc_note, tname))
        span = underline_span(head)
        if span is None or not (span[0] - TAB_X_TOL_PX <= x <= span[1] + TAB_X_TOL_PX):
            _mark(steps, "step 1 look and tab presses", t1, now, say)
            return finish("stopped", "the press on %s did not switch the tab (underline %s); no install"
                          % (tname, span))
    _mark(steps, "step 1 look and tab presses", t1, now, say)

    # step 2: the Crashpad listing, then ONE install (never forced)
    t2 = now()
    cp_before = crashpad_mtime()
    say("crashpad: newest file %s" % _hms(cp_before))
    rc = install()
    t_inst = now()
    _mark(steps, "step 2 install", t2, now, say)
    if rc:
        return finish("stopped", "refused: install exit %d; nothing forced, no put-back" % rc)

    # step 3: three quiet looks after the install; a grey picture or a moved Crashpad time stops everything
    t3 = now()
    for at in LOOK_AFTER_INSTALL_S:
        sleep(max(0.0, t_inst + at - now()))
        p = str(out / ("step3_look_%ds.png" % at))
        look(p)
        if picture_size(p) < GREY_BYTES:
            _mark(steps, "step 3 settle and looks", t3, now, say)
            return finish("not finished", "grey picture at +%d s; nothing more pressed, no put-back: "
                                          "only the owner reloads his app" % at)
        if crashpad_mtime() != cp_before:
            _mark(steps, "step 3 settle and looks", t3, now, say)
            return finish("not finished", "Crashpad time moved at +%d s; nothing more pressed, no put-back: "
                                          "only the owner reloads his app" % at)
    _mark(steps, "step 3 settle and looks", t3, now, say)

    # step 4: per tab, press its head, look, the rows, hover-series over every row, diff inside each tile
    t4 = now()
    deadline_hit = False
    for i, (tname, x, y) in enumerate(tabs):
        if now() - t1 > deadline_s:
            deadline_hit = True
            break
        t_tab = now()
        rc = 0 if (shown_tab_first and i == 0) else press(x, y)
        if rc:
            _mark(steps, "step 4 tabs and rows", t4, now, say)
            return finish("not finished", "press on %s refused in step 4 (exit %d)" % (tname, rc))
        rest = str(out / ("step4_tab%d_rest.png" % i))
        look(rest)
        items = [_norm(it) for it in find_points(rest)]
        lit = bad = ph_not_lit = hovered = 0
        for g in range(0, len(items), SERIES_MAX):
            if now() - t1 > deadline_s:
                deadline_hit = True
                break
            group = items[g:g + SERIES_MAX]
            sdir = str(out / ("step4_tab%d_series%d" % (i, g // SERIES_MAX)))
            pts = [(it["x"], it["y"]) for it in group]
            rc = hover_series(pts, sdir)
            if rc == 3:   # owner back: this series once more, after --wait-for-pause
                rc = hover_series(pts, sdir)
                if rc == 3:
                    _mark(steps, "step 4 tabs and rows", t4, now, say)
                    return finish("not finished", "owner back twice on the series %d of %s"
                                  % (g // SERIES_MAX + 1, tname))
            if rc:
                _mark(steps, "step 4 tabs and rows", t4, now, say)
                return finish("not finished", "series on %s refused (exit %d)" % (tname, rc))
            for k, it in enumerate(group, 1):
                n = diff_pixels(rest, os.path.join(sdir, "hover_%d.png" % k), it["tile"])
                hovered += 1
                if n:
                    lit += 1
                elif it["placeholder"]:
                    ph_not_lit += 1          # the dim empty rows: counted, never a failed row
                else:
                    bad += 1
                    failed.append((tname, it["card"], it["row"]))
        tab_rows.append({"tab": tname, "rows": len(items), "lit": lit, "failed": bad,
                         "placeholder_not_lit": ph_not_lit, "hovered": hovered,
                         "start": t_tab, "end": now()})
        if deadline_hit:
            break
    _mark(steps, "step 4 tabs and rows", t4, now, say)

    # step 5: any failed row, or the 14 minutes gone with rows not hovered = put back
    if failed or deadline_hit:
        t5 = now()
        rc = put_back()
        sleep(RECHECK_AFTER_PUT_BACK_S)
        look(str(out / "step5_after_put_back.png"))
        _mark(steps, "step 5 put back and look", t5, now, say)
        why = ("%d failed row(s)" % len(failed)) if failed else \
            "%d minutes gone with rows not yet hovered" % (deadline_s // 60)
        extra = "" if rc == 0 else "; put-back exit %d" % rc
        return finish("put back", "%s%s" % (why, extra))
    total = sum(t["rows"] for t in tab_rows)
    ph = sum(t["placeholder_not_lit"] for t in tab_rows)
    return finish("stays", "%d rows on %d tabs, 0 failed, %d placeholder not lit (not failed)"
                  % (total, len(tab_rows), ph))


# -- command line -----------------------------------------------------------------------------------
DRY_STEPS = (
    "step 1: look (painted: 250 KB or more); tab heads from find_tab_heads (or --tabs); press each head, look "
    "after each (underline must move)",
    "step 2: crashpad listing; ONE install (never forced); refused = stop",
    "step 3: look at +60, +120, +180 s, no press; grey or moved Crashpad = stop, no put-back",
    "step 4: per tab: press head, look, find points, hover-series (<= 20 rows per call), diff inside each tile; "
    "placeholder rows not lit are counted, not failed",
    "step 5: failed row or 14 min with rows not hovered = put back, look 60 s later; else stays",
    "step 6: markdown table in --out-dir",
)


def _parse_tabs(text: str):
    out = []
    for part in text.split(","):
        name, x, y = part.split(":")
        out.append((name, int(x), int(y)))
    return out


def _parse_rows(text: str):
    return tuple(int(v) for v in text.split(","))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="print the planned minutes of both orders (calls nothing)")
    ap.add_argument("--run", action="store_true", help="run the visit on the real pane (owner's go only)")
    ap.add_argument("--dry-run", action="store_true", help="with --run: print the steps and call nothing")
    ap.add_argument("--rows", default=",".join(str(r) for r in DEFAULT_ROWS),
                    help="rows per tab in the pane's order (main, builds, tickets, cost, progress), e.g. 14,12,8,6,5")
    ap.add_argument("--tabs", help="optional override name:x:y x5 in the pane's order; default: found on the picture")
    ap.add_argument("--out-dir", help="where the pictures and the table go")
    ap.add_argument("--repo", help="the repo (worktree) the install copies from: sets AGENTOPS_MODS_REPO; required with --run")
    a = ap.parse_args(argv)
    if a.plan:
        print_plan(_parse_rows(a.rows))
        return 0
    if a.run:
        if not a.out_dir:
            print("refused: --run needs --out-dir")
            return 2
        if a.dry_run:
            for line in DRY_STEPS:
                print(line)
            return 0
        if not a.repo:
            print("refused: --run needs --repo (the candidate's worktree); an install from the main checkout is a different build")
            return 2
        if not (Path(a.repo) / "mods" / INSTALL_NAME).is_dir():
            print("refused: no mods/%s under %s" % (INSTALL_NAME, a.repo))
            return 2
        os.environ["AGENTOPS_MODS_REPO"] = str(Path(a.repo).resolve())
        tabs = _parse_tabs(a.tabs) if a.tabs else None
        res = run_visit(out_dir=a.out_dir, tabs=tabs, shown_tab_first=True, deadline_s=24 * 60 * 60)
        return 0 if res["verdict"] == "stays" else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
