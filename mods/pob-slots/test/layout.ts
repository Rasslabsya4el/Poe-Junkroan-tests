import { CELL_PX } from '../hooks/kit'
import { flowH } from './rowheights'
// #837 pass 2 (unit 4b): the small layout the engine applies to the Boxes this mod draws over a picture (the mock does not lay out):
// `top`/`left`/`height`/`margin*` as numbers = cells of 19 px (a `height` may be fractional, a `top` is an integer), `height` as "N%" =
// that share of the parent's height in px, an absolute Box with `top` and `bottom` spans its parent.
// #837 (rows the baseline's way): a card's overlay column holds, per row with a press, a Box with NO `height` prop that holds a blank Svg of the
// row's own px height (the Svg's `height` prop in px is the Box's height; the presses lie in it at `top` 0 / `bottom` 0), and per run of rows
// with none one blank Svg; a flow Svg takes its `height` in px.
export const kids = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
export const cells = (v: unknown) => Number(v ?? 0) * CELL_PX
export const lenOf = (v: unknown, base: number) => (typeof v === 'string' && v.endsWith('%') ? parseFloat(v) / 100 * base : Number(v) * CELL_PX)
// #837 b6: a data row's height holder in the mask tier is the MASK: one path with a hole in the tile colour (paints only where the card is already bare tile), alt "row", as wide as its markup
export const isMask = (n: any) => n?.type === 'Svg' && n.props?.alt === 'row' && /^<svg [^>]*width='[\d.]+' height='[\d.]+'><path fill='#262628' d='[^']*'\/><\/svg>$/.test(String(n.props?.source ?? ''))
/** the blank Svg a card's overlay holds to give a row its height: a self-closing `<svg .../>`, no picture in it */
/** #837 b2: or a row's spacer (one transparent 1x1 rect, `opacity='0'`; the b1 probes drew it in the tile colour) */
export const isBlank = (n: any) => isMask(n) || (n?.type === 'Svg' && /^<svg[^>]*\/>$|^<svg[^>]*><rect width='1' height='[\d.]+'( fill='#262628')?( fill-opacity='0'| opacity='0')?\/><\/svg>$/.test(String(n.props?.source ?? '')))
const hasFlowSvg = (c: any) => kids(c).some((k: any) => k.type === 'Svg')
export type Spot = { el: any; top: number; bottom: number; line: number }
/** every Link / Button under `box` (a Box laid at `top` px with `h` px): its band = the nearest Box above it that has a height, its line top = that band's top */
export const spots = (box: any, top: number, h: number): Spot[] => {
  const out: Spot[] = []
  const inside = (b: any, bTop: number, bH: number, band: { top: number; bottom: number }) => {
    let y = 0 // the flow cursor inside b
    for (const c of kids(b)) {
      if (c.type === 'Link' || c.type === 'Button' || c.type === 'Markdown') { out.push({ el: c, top: band.top, bottom: band.bottom, line: band.top }); continue }
      if (c.type === 'Svg') { y += Number(c.props?.height ?? 0); continue }
      if (c.type !== 'Box') { inside(c, bTop, bH, band); continue }
      const p = c.props ?? {}
      const abs = p.position === 'absolute'
      let cTop: number, cH: number
      if (abs) {
        cTop = bTop + (p.top != null ? cells(p.top) : 0)
        cH = p.height != null ? lenOf(p.height, bH) : p.bottom != null ? bH - cells(p.top) - cells(p.bottom) : CELL_PX
      } else {
        y += cells(p.marginTop)
        cTop = bTop + y
        cH = p.height != null ? lenOf(p.height, bH) : hasFlowSvg(c) ? flowH(c) : CELL_PX // a Box with a blank Svg is as high as the Svg's px
        y += cH + cells(p.marginBottom)
      }
      inside(c, cTop, cH, p.height != null || (abs && p.bottom != null) || (!abs && hasFlowSvg(c)) ? { top: cTop, bottom: cTop + cH } : band)
    }
  }
  inside(box, top, h, { top, bottom: top + h })
  return out
}
/** the overlay Box a card's rows lay over a picture: absolute, a column, at the picture's top left */
export const isOverlay = (n: any) => n?.type === 'Box' && n.props?.position === 'absolute' && n.props.flexDirection === 'column' && n.props.top === 0 && n.props.left === 0 && n.props.right === 0
/** The old reading of the strip presses (before unit 4b): each press in an absolute Box at `top` whole cells (the row's top rounded) and `left`.
 *  Rewrites a copy of `tree` so: every overlay's in-flow rows (marginTop + height in cells, a press Box with a marginLeft or a row Box holding absolute presses)
 *  become absolute Boxes at the rounded cell of their flow top; the tests that read the presses' targets, rows and columns keep reading them as before.
 *  #837 b2: a data row's Box has the pill's `marginLeft`; its presses' `left` is that plus their own (the screen-px rule), so the old reading sees the press where it stands.
 *  Exact px are read by press-position.test.tsx, not here. */
export const legacy = <T,>(tree: T): T => {
  const copy: any = JSON.parse(JSON.stringify(tree))
  const go = (n: any) => {
    if (!n || typeof n !== 'object') return
    if (isOverlay(n)) {
      let y = 0 // in px: the rows' flow tops
      const out: any[] = []
      for (const c of kids(n)) {
        const p = c.props ?? {}
        if (c.type === 'Svg') { y += Number(p.height ?? 0); continue } // a blank run of rows with no press
        y += cells(p.marginTop)
        const rowH = c.type === 'Box' && p.height == null && hasFlowSvg(c) ? flowH(c) : cells(p.height ?? 1)
        const top = Math.round(y / CELL_PX), h = rowH / CELL_PX
        y += rowH
        const rest = { ...p }; delete rest.marginTop; delete rest.marginLeft
        if (p.marginLeft != null && !hasFlowSvg(c)) out.push({ ...c, props: { ...rest, position: 'absolute', top, left: Number(p.marginLeft), height: Math.max(1, Math.round(h)), alignItems: 'flex-start' } })
        else for (const a of kids(c)) { if (a.type === 'Svg') continue; const q = { ...a.props, top }; delete q.bottom; q.height = Math.max(1, Math.round(h)); if (p.marginLeft != null) q.left = Number(q.left ?? 0) + Number(p.marginLeft); out.push({ ...a, props: q }) }
      }
      n.children = out
    }
    for (const c of n.children ?? []) go(c)
  }
  go(copy)
  return copy
}
