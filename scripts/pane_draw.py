"""Rasterize the drawn pane of one ref to a PNG (#843 unit 3).

  python scripts/pane_draw.py --ref <commit|worktree> --fixture live-fast|full|fallback --tab <name|all>
      [--hover <row key>] [--open-square] [--cols N] [--scale S] --out <dir>
  python scripts/pane_draw.py --pair <refA> <refB> --fixture ... --tab ... --out <dir>

pane_dump.dump (the drawn tree) -> pane_layout.layout (px primitives) -> PIL: filled Boxes, text runs, and every Svg
at its place. An Svg is rendered by headless chromium through playwright (one browser for the whole picture, no window,
nothing installed); where chromium cannot start, the Svg is a grey placeholder and the footer says so. `--hover KEY`
paints the hover Box's own background (a hover_rect whose key is or contains KEY) over the cells the engine gives it.
SCALE 1.0 is the device scale of the calibration picture (docs/research/pictures-613-837/after-install-main-11-35.png,
2560x1440: 119 cols, cards 950 px wide = COL_PX 7.98 per col; calibrated in tests/test_pane_draw.py). The last footer line of the PNG names the font and the Svg renderer.
Never installs the mod, never clicks, never touches the desktop app; the last log line is `installs 0 clicks 0 desktop 0`.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pane_dump  # noqa: E402
import pane_layout  # noqa: E402

SCALE = 1.0  # the calibration picture: 2560 px wide screen, device scale 1, 119 cols x COL_PX = 950 px
BG = (26, 26, 25)  # the pane's own background in the calibration picture
TEXT = "#f0f6fc"
LINK = "#58a6ff"
FOOT_H = 22
HEAD_H = 26
TABS = ["main", "tickets", "cost", "progress", "builds"]  # the tab ids of register.tsx / addon.tsx
MAX_BYTES = 400 * 1024
FONTS = [("Segoe UI", "segoeui.ttf"), ("Consolas", "consola.ttf"), ("Lucida Console", "lucon.ttf"), ("DejaVu Sans Mono", "DejaVuSansMono.ttf")]


def load_font(size: float) -> tuple[ImageFont.FreeTypeFont, str]:
    for name, f in FONTS:
        for d in ("C:/Windows/Fonts/", ""):
            try:
                return ImageFont.truetype(d + f, max(6, round(size))), name
            except OSError:
                continue
    return ImageFont.load_default(), "PIL default bitmap"


def rgba(c: str | None, default: str = TEXT) -> tuple[int, int, int, int]:
    c = (c or default).lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if not re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", c):
        c = default.lstrip("#")
    v = [int(c[i:i + 2], 16) for i in range(0, len(c), 2)]
    return (v[0], v[1], v[2], v[3] if len(v) == 4 else 255)


def render_svgs(svgs: list[dict], scale: float) -> tuple[list[Image.Image | None], str]:
    """Every Svg prim to an RGBA image at `scale`; (images, renderer name). Headless chromium via playwright."""
    if not svgs:
        return [], "no Svg"
    try:
        from playwright.sync_api import sync_playwright
        out: list[Image.Image | None] = []
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                pg = b.new_page(device_scale_factor=scale, viewport={"width": 1600, "height": 1000})
                for s in svgs:
                    pg.set_content("<html><body style='margin:0;background:transparent'>" + s["source"] + "</body></html>")
                    png = pg.locator("svg").first.screenshot(omit_background=True)
                    out.append(Image.open(io.BytesIO(png)).convert("RGBA"))
            finally:
                b.close()
        return out, "chromium headless (playwright)"
    except Exception as e:  # no browser / no playwright: placeholders, named in the footer
        return [None] * len(svgs), f"Svg NOT rendered ({type(e).__name__}: {str(e)[:60]}), grey placeholders"


def draw(res: dict, scale: float = SCALE, hover: str | None = None, label: str = "") -> Image.Image:
    """res = pane_layout.layout(...) output. Returns an RGB image: content then a footer line."""
    prims = res["prims"]
    cols = res["cols"]
    w_px = round(cols * pane_layout.COL_PX * scale)
    bottom = max([p["y"] + p["h"] for p in prims] or [0])
    h_px = round(bottom * scale)
    img = Image.new("RGBA", (w_px, h_px + FOOT_H), BG + (255,))
    font, font_name = load_font(12 * scale)
    svgs = [p for p in prims if p["kind"] == "svg"]
    t0 = time.time()
    pics, svg_how = render_svgs(svgs, scale)
    pic_of = {id(s): im for s, im in zip(svgs, pics)}
    painted = 0
    for p in prims:
        x0, y0 = round(p["x"] * scale), round(p["y"] * scale)
        x1, y1 = round((p["x"] + p["w"]) * scale), round((p["y"] + p["h"]) * scale)
        k = p["kind"]
        if k == "rect":
            _fill(img, (x0, y0, x1, y1), rgba(p["color"]))
        elif k == "hover_rect":
            if hover and (p.get("key") == hover or hover in str(p.get("key"))):
                _fill(img, (x0, y0, x1, y1), rgba(p["color"]))
                painted += 1
        elif k == "svg":
            im = pic_of.get(id(p))
            if im is None:
                _fill(img, (x0, y0, x1, y1), (60, 60, 64, 255))
            else:
                img.alpha_composite(im, (x0, y0))
        elif k == "text":
            col = rgba(p.get("color"), LINK if p.get("of") == "Link" else TEXT)
            ImageDraw.Draw(img).text((x0, y0 + round(pane_layout.TEXT_BASE * scale)), p["text"], fill=col, font=font, anchor="ls")
    unsup = ', '.join(u['type'] + '.' + u['prop'] for u in res['unhandled']) or 'none'
    foot = (f"{label} | {cols} cols | scale {scale} | font {font_name} | svg: {svg_how} ({len(svgs)}) | "
            f"unsupported: {unsup}"
            + (f" | hover {hover}: {painted} rect(s)" if hover else ""))
    d = ImageDraw.Draw(img)
    d.rectangle((0, h_px, w_px, h_px + FOOT_H), fill=(12, 12, 12, 255))
    d.text((4, h_px + FOOT_H - 6), foot, fill=(160, 168, 179, 255), font=ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 11) if Path("C:/Windows/Fonts/segoeui.ttf").exists() else font, anchor="ls")
    res["_svg_seconds"] = time.time() - t0
    return img.convert("RGB")


def _fill(img: Image.Image, box: tuple[int, int, int, int], c: tuple[int, int, int, int]) -> None:
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    if c[3] == 255:
        ImageDraw.Draw(img).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=c)
    else:
        over = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), c)
        img.alpha_composite(over, (box[0], box[1]))


def save_small(img: Image.Image, path: Path) -> int:
    """Save under MAX_BYTES: palette PNG with fewer colours, then smaller, until it fits. Returns the size."""
    cur = img
    while True:
        for n in (256, 64, 32, 16):
            q = cur.quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
            buf = io.BytesIO()
            q.save(buf, "PNG", optimize=True)
            if len(buf.getvalue()) < MAX_BYTES:
                path.write_bytes(buf.getvalue())
                return len(buf.getvalue())
        cur = cur.resize((int(cur.width * 0.8), int(cur.height * 0.8)), Image.LANCZOS)


def picture(ref: str, fixture: str, tab: str, open_square: bool, cols: int, scale: float, hover: str | None,
            slots: list[int] | None = None) -> Image.Image:
    d = pane_dump.dump(ref, fixture, tab, open_square, cols, slots=slots)
    res = pane_layout.layout(d)
    return draw(res, scale, hover, f"{ref[:40]} | {fixture} | {tab}")


def pair_image(a: Image.Image, b: Image.Image, na: str, nb: str) -> Image.Image:
    gap = 12
    out = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height) + HEAD_H), (0, 0, 0))
    out.paste(a, (0, HEAD_H))
    out.paste(b, (a.width + gap, HEAD_H))
    d = ImageDraw.Draw(out)
    f = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 16) if Path("C:/Windows/Fonts/segoeuib.ttf").exists() else None
    d.text((4, 20), na, fill=(240, 246, 252), font=f, anchor="ls")
    d.text((a.width + gap + 4, 20), nb, fill=(240, 246, 252), font=f, anchor="ls")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref")
    ap.add_argument("--pair", nargs=2, metavar=("REF_A", "REF_B"))
    ap.add_argument("--fixture", default="live-fast", choices=["live-fast", "full", "fallback", "held", "cache", "cache-wait"])
    ap.add_argument("--tab", default="main")
    ap.add_argument("--hover")
    ap.add_argument("--open-square", action="store_true")
    ap.add_argument("--pressed-only", action="store_true", help="only the run-pick press (the pressed/dimmed state), no cell press")
    ap.add_argument("--cols", type=int, default=119)
    ap.add_argument("--scale", type=float, default=SCALE)
    ap.add_argument("--out", required=True)
    ap.add_argument("--slots", help="comma list: workers of the first finished runs (#837 L7), e.g. 1,3,7,10")
    ap.add_argument("--name", help="file stem instead of <fixture>-<tab>")
    a = ap.parse_args(argv)
    if not a.ref and not a.pair:
        ap.error("--ref or --pair is required")
    if a.pressed_only:
        a.open_square = "pick"
    slots = [int(x) for x in a.slots.split(",")] if a.slots else None
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    from junkroan.report_format import human_duration
    for tab in (TABS if a.tab == "all" else [a.tab]):
        t0 = time.time()
        if a.pair:
            ims = [picture(r, a.fixture, tab, a.open_square, a.cols, a.scale, a.hover, slots) for r in a.pair]
            img = pair_image(ims[0], ims[1], *a.pair)
            path = out / f"pair-{a.name or a.fixture + '-' + tab}.png"
        else:
            img = picture(a.ref, a.fixture, tab, a.open_square, a.cols, a.scale, a.hover, slots)
            path = out / f"{a.name or a.fixture + '-' + tab}.png"
        n = save_small(img, path)
        print(f"{path} {img.width}x{img.height} px, {n // 1024} KB, {human_duration(time.time() - t0)}")
    print("installs 0 clicks 0 desktop 0")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    raise SystemExit(main())
