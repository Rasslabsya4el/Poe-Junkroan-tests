import { test, expect } from 'claude-code/testing'
import { mountPane, dq } from './kit'
import { LIVE_FAST } from './fast-live'
import { LIVE as TODAY } from './tickets-live-20261011'
import { CELL_PX, PILL } from '../hooks/kit'
import { kids, cells, isBlank } from './layout'

// #837 unit 4 (runs-title): in the PoB runs card the visible title of EVERY row (Идёт, В очереди, Готово: a running, a queued, a done, a
// failed, a stopped row, a title that is cut, a row with a ticket) has its vertical centre within 1.5 px of the row's icon centre.
// #837 b18 (form A): a title is a host Button with its own visible label, drawn by the host in the row's own Box at its top (`top` 0).
// The row's Box is as tall as its own blank strip Svg (the row's px height, 26), so this reads, per row: the title's centre (the Box's
// top + CELL_PX / 2, the label's cell line + 9.5) against the icon's centre (the row's top + PILL / 2).
const TOL = 1.5
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
const runsCard = (tree: any) => tree.children[2].children[0] // #983: the first card of the tab «POB»
/** the fixture: the live payload plus a queued row (a clone of a running one) and one of every finished state */
const fixture = () => {
  const d = JSON.parse(LIVE_FAST)
  const r = d.runs
  const base = r.running[0]
  r.queued = [
    { ...base, id: 'j-q1', state: 'queued', issue: 817, tag: 'P1-#817-9', progress: undefined, wait: { kind: 'slots', text: '' } },
    { ...base, id: 'j-q2', state: 'queued', issue: 813, tag: 'P1-#813-9', progress: undefined, wait: { kind: 'slots', text: '' } },
  ]
  const hist = r.history ?? r.recent
  const kinds = ['done', 'failed', 'stopped', 'cancelled']
  kinds.forEach((st, i) => hist.unshift({ ...hist[hist.length - 1], id: `j-h${i}`, state: st, issue: [779, 816, 817, 813][i], tag: `P1-#${i}-h` }))
  return JSON.stringify(d)
}
type Row = { y: number; h: number; body: string }
/** the picture's rows: a row's top and height from its `translate(0 y)` group (the first row is not wrapped) */
const picRows = (src0: string): Row[] => {
  const src = dq(src0)
  const H = Number(/^<svg[^>]* height="([\d.]+)"/.exec(src)![1])
  const inner = src.replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '').replace(/^(?:<style>[\s\S]*?<\/style>)?(?:<defs>[\s\S]*?<\/defs>)?/, '')
  const cuts = [...inner.matchAll(/<g transform="translate\(0 ([\d.]+)\)"(\/?)>/g)]
  const rows: Row[] = []
  const first = cuts[0] ? inner.slice(0, cuts[0].index) : inner
  rows.push({ y: 0, h: 0, body: first })
  cuts.forEach((m, k) => {
    const end = cuts[k + 1]?.index ?? inner.length
    rows.push({ y: Number(m[1]), h: 0, body: m[2] ? '' : inner.slice(m.index! + m[0].length, end) })
  })
  rows.forEach((r, k) => { r.h = (rows[k + 1]?.y ?? H) - r.y })
  return rows
}
const unesc = (s: string) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&')
test('#837 u4: PoB runs card: every row\'s title centre is within 1.5 px of its icon centre', { timeoutMs: 60_000 }, async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: fixture(), tickets: TODAY }, 123)
  const card = runsCard(await (ui as any).drawn())
  // the one picture and the overlay column over it
  let pic: any = null, overlay: any = null
  walk(card, (n) => {
    const ks = kids(n)
    const i = ks.findIndex(c => c.type === 'Svg' && !isBlank(c) && String(c.props?.alt ?? '').split(String.fromCharCode(10)).length > 3)
    if (i >= 0 && !pic) { pic = ks[i]; overlay = ks.slice(i + 1).find(c => c.type === 'Box' && c.props?.position === 'absolute') }
  })
  expect(pic, 'the runs card picture').toBeTruthy()
  const rows = picRows(String(pic.props.source))
  // the overlay's flow: a spacer Box or a row Box, each `height` cells; a row Box holds the presses
  let y = 0
  const out: { row: number; label: string; native: number; ghost: boolean }[] = []
  for (const c of kids(overlay)) {
    if (c.type === 'Svg') { y += Number(c.props?.height ?? 0); continue }
    // #837 b18 (form A): a row Box's flow height is its own blank Svg (the row's px strip, 26 or 22), not a cell count
    const strip = kids(c).find((x: any) => x.type === 'Svg')
    const hh = strip ? Number(strip.props?.height ?? 0) : cells(c.props?.height ?? 1)
    const top = y; y += hh
    walk(c, (b) => {
      if ((b.type !== 'Button' && b.type !== 'Markdown') || !/^run-(pick|q|hist)-/.test(String(b.props?.key))) return
      const ghost = b.type === 'Markdown' || !String(b.props?.label ?? '').trim() // #837 b8: a title press is a Markdown ghost link
      // the row this Box was cut for: the 26-px row whose top rounds to the Box's cell
      const cand = rows.map((r, k) => ({ k, r })).filter(x => x.r.h === PILL + 6).sort((a, b2) => Math.abs(Math.round(a.r.y / CELL_PX) * CELL_PX - top) - Math.abs(Math.round(b2.r.y / CELL_PX) * CELL_PX - top))[0]!
      out.push({ row: cand.k, label: String(b.props.label), native: top + CELL_PX / 2, ghost })
    })
  }
  expect(out.length, 'title presses').toBeGreaterThanOrEqual(10)
  const kindsSeen = new Set<string>()
  walk(overlay, (b) => { const m = /^run-(pick|q|hist)-/.exec(String(b.props?.key)); if ((b.type === 'Button' || b.type === 'Markdown') && m) kindsSeen.add(m[1]!) })
  expect([...kindsSeen].sort(), 'a running, a queued and a finished row').toEqual(['hist', 'pick', 'q'])
  const errs: number[] = []
  const lines: string[] = []
  for (const o of out) {
    const r = rows[o.row]!
    const iconC = r.y + PILL / 2
    let titleC = o.native
    if (o.ghost) {
      const t = [...r.body.matchAll(/<text [^>]*? y="([\d.]+)"[^>]*>([^<]*)<\/text>/g)].map(m => ({ y: +m[1]!, t: unesc(m[2]!) })).find(x => Math.abs(x.y - 4.4 - PILL / 2) <= TOL && x.t.trim().length > 3)
      expect(t, `the picture draws a title at the icon's centre (row@${r.y})`).toBeTruthy()
      titleC = r.y + t!.y - 4.4
    }
    const d = titleC - iconC
    errs.push(d)
    lines.push(`${o.ghost ? 'svg' : 'native'} row@${r.y} «${o.label.slice(0, 18)}» title ${titleC.toFixed(1)} icon ${iconC.toFixed(1)} diff ${d >= 0 ? '+' : ''}${d.toFixed(1)}`)
  }
  console.log(`RUNS-TITLE ${out.length} rows\n` + lines.join('\n'))
  expect(errs.filter(d => Math.abs(d) > TOL).length, lines.join('; ')).toBe(0)
  await ui.unmount()
})
