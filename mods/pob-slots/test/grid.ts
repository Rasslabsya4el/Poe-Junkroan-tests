import { CELL_PX, PX_PER_COL, CARD_CHROME_PX, drawnW } from '../hooks/kit'
import { kids, isOverlay, cells, lenOf } from './layout'
import { flowH } from './rowheights'
import { dq } from './kit'

// #945 (unit 1, 1c): ONE reader of a drawn pane for the grid test. It gives no allowance:
//  - rows: every child of a card's overlay column (a row Box or a blank Svg), its top and height in px, and the centre of the text the card's picture draws in that row (`text`:
//    the first baseline of the row's picture item, or of the picture's texts inside the row's px band, minus BASE_TO_C; a row that draws no text: its middle);
//    and every absolute Box with a `top` and `height` in cells (a table's hover row), the same;
//  - placed: every Button / Link / Markdown under a row: `at` = the px top of the Box it stands in (the sum of the px heights above it), `host` = the line the host puts it on, `off` = the px between
//    the centre of the host's glyph on that line and the centre of the row's own drawn text. The host's rule (b11 probes, #937 comment 6145882941): a Button stands at its Box's px top exactly;
//    a ghost Link / Markdown is put on the NEAREST 19-px line of it (half up). The host's 19-px glyph is centred 9.5 px below its line; the picture's text of a row is centred BASE_TO_C above its
//    baseline (baseline 14.4 on a 26-px row: 10.5 below the row's top); BETA (b11: box centre minus text centre at the pure rule) = -1 px is the zero: off = host centre - text centre - BETA;
//  - pairs: every run title (`run-pick-` / `run-q-` / `run-hist-`) with its ticket number (`lk` text of its row's picture item): the title's drawn right edge and the ticket's left edge, in screen px
//    (markup px x the card's scale; a host Button's label starts HOST_TITLE_LEAD px right of its cell column and is drawnW at HOST_TITLE_PX wide, a ghost title is the picture's own word).
export type Row = { card: string; kind: 'row' | 'table'; top: number; height: number; first: string; text: number; textOf: 'text' | 'middle' }
export type FaceText = { x: number; cls: string; text: string }
// #972: `texts` = the words the row's picture draws (markup x), `scale` = screen px a markup px (the card's fit; a table's picture is 1:1), for the face check of the pointer elements (test/face.ts)
export type Placed = { card: string; el: string; key: string; at: number; host: number; off: number; text: number; row: string; run: string; lk: string; texts: FaceText[]; scale: number }
export type Pair = { card: string; key: string; right: number; tick: number; from: 'picture' | 'link' }
export type Grid = { rows: Row[]; placed: Placed[]; pairs: Pair[]; notes: string[] }

export const BETA = -1
export const BASE_TO_C = 3.9
export const GLYPH_C = CELL_PX / 2
const TITLE = /^run-(pick|q|hist)-/
const ROW_N = /^(?:hv-[a-z]+|[a-z]+-[rg])(\d+)$/
// a picture's words: a row picture's `<text x y>word</text>`, a table picture's `<tspan x y>word</tspan>` (#972: the table's own words are read too)
const TEXT = /<g transform="translate\(0 ([\d.]+)\)"|<(?:text|tspan)\b([^>]*\by="[\d.]+"[^>]*)>([^<]*)<\/(?:text|tspan)>/g
const attr = (s: string, name: string): number => Number(new RegExp(`\\b${name}="([\\d.-]+)"`).exec(s)?.[1] ?? NaN)
const unesc = (s: string) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&')
const keyOf = (n: any): string => String(n?.props?.key ?? '')
/** the 19-px line the host puts a ghost Link / Markdown at Y px on: 19 * round(Y / 19) */
export const hostLine = (y: number): number => CELL_PX * Math.round(y / CELL_PX)
/** the line a host element stands on: a Button at its Box's px top, anything else on the nearest 19-px line */
export const hostOf = (el: string, at: number): number => (el === 'Button' ? at : hostLine(at))
/** the px between the centre of the host's glyph on its line and the centre of the row's text, zero at the b11 pure rule */
export const offsetOf = (el: string, at: number, text: number): number => hostOf(el, at) + GLYPH_C - text - BETA
/** the run title's key under a node (`run-pick-` / `run-q-` / `run-hist-<job>`; the same in every form of the pane), '' when the node holds none */
const runKeyOf = (n: any): string => {
  const k = keyOf(n)
  const m = /run-(?:pick|q|hist)-j-[\w-]+/.exec(k)
  if (m) return m[0]
  for (const c of kids(n)) { const r = runKeyOf(c); if (r) return r }
  return ''
}
/** the first key under a node (a row's name for the report) */
const firstKey = (n: any): string => {
  if (keyOf(n)) return keyOf(n)
  for (const c of kids(n)) { const k = firstKey(c); if (k) return k }
  return ''
}
type PicText = { item: number; x: number; base: number; cls: string; text: string }
/** a picture's texts with their item (the count of `translate(0 y)` groups before it) and absolute baseline (the item's y + the text's y) */
const picOf = (srcRaw: string): { texts: PicText[] } => {
  const texts: PicText[] = []
  let y = 0, item = 0
  for (const m of dq(srcRaw).matchAll(TEXT)) {
    if (m[1] != null) { y = Number(m[1]); item++; continue }
    const a = m[2] ?? ''
    texts.push({ item, x: attr(a, 'x'), base: y + attr(a, 'y'), cls: /class="([^"]+)"/.exec(a)?.[1] ?? '', text: unesc(m[3] ?? '') })
  }
  return { texts }
}
/** the centre of the text a picture draws in a row: of its item n when the row has one, else of the texts whose baseline falls in the row's px band; the row's middle when it draws none */
const centreOf = (pic: { texts: PicText[] }, top: number, h: number, item: number | null): { c: number; of: 'text' | 'middle' } => {
  const own = pic.texts.filter(t => (item != null ? t.item === item : t.base > top + 1e-6 && t.base <= top + h + 1e-6))
  return own.length ? { c: Math.min(...own.map(t => t.base)) - BASE_TO_C, of: 'text' } : { c: top + h / 2, of: 'middle' }
}

/** every Button / Link / Markdown under `box` (laid at `top` px, `h` px high) with `at` = the px top of the Box it stands in (a Box with `top` cells: its parent's top + that; in flow: the flow cursor) */
const elementsIn = (box: any, top: number, h: number): { el: any; at: number }[] => {
  const out: { el: any; at: number }[] = []
  const inside = (b: any, bTop: number, bH: number) => {
    let y = 0
    for (const c of kids(b)) {
      if (c.type === 'Link' || c.type === 'Button' || c.type === 'Markdown') { out.push({ el: c, at: bTop }); continue }
      if (c.type === 'Svg') { y += Number(c.props?.height ?? 0); continue }
      if (c.type !== 'Box') { inside(c, bTop, bH); continue }
      const p = c.props ?? {}
      let cTop: number, cH: number
      if (p.position === 'absolute') {
        cTop = bTop + (p.top != null ? cells(p.top) : 0)
        cH = p.height != null ? lenOf(p.height, bH) : p.bottom != null ? bH - cells(p.top) - cells(p.bottom) : CELL_PX
      } else {
        y += cells(p.marginTop)
        cTop = bTop + y
        cH = p.height != null ? lenOf(p.height, bH) : kids(c).some((k: any) => k.type === 'Svg') ? flowH(c) : CELL_PX
        y += cH + cells(p.marginBottom)
      }
      inside(c, cTop, cH)
    }
  }
  inside(box, top, h)
  return out
}

/** the ticket links under a row (a Link with no key: the ghost over the ticket number), each with the nearest absolute Box's `left` in cells (0 when none) */
const linksIn = (n: any, left: number, out: number[]): void => {
  for (const k of kids(n)) {
    const l = k.type === 'Box' && k.props?.position === 'absolute' && k.props?.left != null ? Number(k.props.left) : left
    if (k.type === 'Link' && !keyOf(k)) out.push(l)
    linksIn(k, l, out)
  }
}
/** the titles under a row, each with the nearest absolute Box's `left` in cells (0 when none) */
const titlesIn = (n: any, left: number, out: { el: any; left: number }[]): void => {
  for (const k of kids(n)) {
    const l = k.type === 'Box' && k.props?.position === 'absolute' && k.props?.left != null ? Number(k.props.left) : left
    if ((k.type === 'Button' || k.type === 'Markdown' || k.type === 'Link') && TITLE.test(keyOf(k))) out.push({ el: k, left: l })
    titlesIn(k, l, out)
  }
}

const addRow = (g: Grid, pic: { texts: PicText[] }, card: string, kind: 'row' | 'table', c: any, top: number, h: number, item: number | null, scale: number): void => {
  const t = centreOf(pic, top, h, item)
  const first = firstKey(c)
  // the ticket number the row's picture draws (`lk`), the name of a keyless ticket Link in a report
  const lk = pic.texts.find(q => q.cls === 'lk' && (item != null ? q.item === item : q.base > top + 1e-6 && q.base <= top + h + 1e-6))?.text ?? ''
  g.rows.push({ card, kind, top, height: h, first, text: t.c, textOf: t.of })
  const texts: FaceText[] = pic.texts.filter(q => (item != null ? q.item === item : q.base > top + 1e-6 && q.base <= top + h + 1e-6)).map(q => ({ x: q.x, cls: q.cls, text: q.text }))
  for (const s of elementsIn(c, top, h)) g.placed.push({ card, el: s.el.type, key: keyOf(s.el), at: s.at, host: hostOf(s.el.type, s.at), off: offsetOf(s.el.type, s.at, t.c), text: t.c, row: first, run: runKeyOf(c), lk, texts, scale })
}

/** a card's overlay column: its rows in order, their px tops, the elements under each, and the run titles with their ticket numbers */
const cardRows = (col: any, parent: any, name: string, cols: number, g: Grid): void => {
  const svg = kids(parent).find((c: any) => c.type === 'Svg')
  const srcRaw = String(svg?.props?.source ?? '')
  const pic = picOf(srcRaw)
  const W = attr(dq(srcRaw), 'width')
  const scale = (cols * PX_PER_COL - CARD_CHROME_PX) / W
  // #972: a row Box's `height` is a percentage of the overlay (= the picture's px height H); a numeric height is cells, a Box with a blank Svg takes the Svg's px (flowH)
  const H = attr(dq(srcRaw), 'height')
  let y = 0
  for (const c of kids(col)) {
    const mt = cells(c.props?.marginTop), mb = cells(c.props?.marginBottom)
    const hp = c.props?.height
    const h = typeof hp === 'string' && hp.endsWith('%') ? parseFloat(hp) / 100 * H : flowH(c) - mt - mb, top = y + mt
    const n = ROW_N.exec(keyOf(c))?.[1]
    addRow(g, pic, name, 'row', c, top, h, n != null ? Number(n) : null, scale)
    const ts: { el: any; left: number }[] = []
    titlesIn(c, 0, ts)
    for (const t of ts) {
      const key = keyOf(t.el)
      if (n == null) { g.notes.push(`${name}: title ${key} in a row with no item number`); continue }
      const tx = pic.texts.filter(q => q.item === Number(n))
      const base = Number(c.props?.marginLeft ?? 0)
      // the ticket's left edge in screen px: the number the picture draws (`lk`), else the row's host Link (a ghost Link stands on its cell column: (the row's margin + its Box's left) x PX_PER_COL)
      const lk = tx.find(q => q.cls === 'lk' && /^#\d+$/.test(q.text))
      const lks: number[] = []
      linksIn(c, 0, lks)
      const tickX = lk ? lk.x * scale : lks.length ? (base + Math.min(...lks)) * PX_PER_COL : NaN
      if (Number.isNaN(tickX)) { g.notes.push(`${name}: title ${key} with no ticket number drawn`); continue }
      // #972: every title is drawn in the picture: the row's leftmost word of the classes a title is drawn in: `nm` (13 px, semibold), `bt` (14 px, regular: a queue / running / history title), `tx`, `mu` (12 px)
      const word = tx.filter(q => q.cls === 'tx' || q.cls === 'nm' || q.cls === 'mu' || q.cls === 'bt').sort((a, b) => a.x - b.x)[0]
      if (!word) { g.notes.push(`${name}: title ${key} has no drawn word`); continue }
      const right = (word.x + drawnW(word.text, word.cls === 'nm', word.cls === 'nm' ? 13 : word.cls === 'bt' ? 14 : 12)) * scale
      void base; void t.left
      g.pairs.push({ card: name, key, right, tick: tickX, from: lk ? 'picture' : 'link' })
    }
    y = top + h + mb
  }
}

/** every card (an overlay column and its picture) and every table row (an absolute Box with `top` and `height` in cells) of a drawn tree */
export const gridOf = (tree: any, cols = 123): Grid => {
  const g: Grid = { rows: [], placed: [], pairs: [], notes: [] }
  let cardNo = 0, tableNo = 0
  const scan = (n: any, parent: any): void => {
    if (n == null || typeof n !== 'object') return
    if (isOverlay(n)) { cardNo++; cardRows(n, parent, `card${cardNo}`, cols, g); return }
    if (n.type === 'Box' && n.props?.position === 'absolute' && typeof n.props.top === 'number' && typeof n.props.height === 'number') {
      const top = cells(n.props.top), h = cells(n.props.height)
      const svg = kids(parent).find((c: any) => c.type === 'Svg')
      addRow(g, picOf(String(svg?.props?.source ?? '')), `table${++tableNo}`, 'table', n, top, h, null, 1)
      return
    }
    for (const c of kids(n)) scan(c, n)
  }
  scan(tree, null)
  return g
}
