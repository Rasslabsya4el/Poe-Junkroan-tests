import { test, mock, expect } from 'claude-code/testing'
// #837 pass 2 (rule 2, P4), unit 4b: where a press lands against ITS ROW, read for every kind of row, tolerance 0.
//  - table rows (Tickets «Цели» / «Вне целей», the Cost tables with «По ролям», Progress): each hover Box's top and bottom in px
//    (cells x 19) is the top and bottom of a row of ITS OWN picture, and the ticket-number Link inside lies on the title's line;
//  - card-strip presses (Agents, Merge, PoB runs): each press Box's top and bottom in px is its row's top and bottom in the
//    picture (rows are 26 px, an engine cell is 19 px, so a Box in whole cells cannot be exact: a height in % of the overlay can).
// The mock does not lay out; `spots` (test/layout.ts) is the small layout the engine applies to the Boxes this mod draws. Its numbers are what
// the desktop draws IF it lays the Svg out at its `height` prop in px. #837 (rows the baseline's way): a strip press lies in the Box of its own
// row (a blank Svg of the row's px height, the press at top 0 / bottom 0), so its band is that Svg's px height, read by `spots`.
import { FAST, SLOW, ORCH, TICKETS } from './fixtures'
import { LIVE as TODAY } from './tickets-live-20261011'
import { COST_SLOW_20261011, COST_TICKETS_20261011 } from './cost-live-20261011'
import { LIVE_FAST } from './fast-live'
import { CELL_PX } from '../hooks/kit'
import { CARD_PITCH } from '../hooks/tokens'
import { dq, mountPane, shown } from './kit'
import { kids, cells, spots, isBlank } from './layout'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const TK = JSON.parse(TODAY)
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
const unesc = (s: string) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&')
const mount = async ($: any, on: any, out: Record<string, string>) => {
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: out[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.write', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  return { ui, clock }
}
const svgH = (src: string) => Number(/^<svg[^>]* height="([\d.]+)"/.exec(dq(src))?.[1])

// ---- the table rows -------------------------------------------------------------------------------------------------
/** the tops of the rows a table picture draws: its words' lines, a 19-px row with its baseline at 14 */
const rowTopsOf = (src: string) => [...new Set([...dq(src).matchAll(/<(?:tspan|text)\b[^>]*? y="([\d.]+)"/g)].map(m => Math.floor(Number(m[1]) / CELL_PX) * CELL_PX))].sort((a, b) => a - b)
const tspans = (src: string) => [...dq(src).matchAll(/<tspan x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]*)<\/tspan>/g)].map(m => ({ x: +m[1]!, y: +m[2]!, t: unesc(m[3]!) }))
const tables = (tree: any, re: RegExp) => {
  const out: { svg: any; boxes: any[] }[] = []
  walk(tree, (n) => {
    const ks = kids(n)
    const svg = ks.find(c => c.type === 'Svg' && /<(tspan|text)\b/.test(dq(String(c.props?.source ?? ''))))
    const boxes = ks.filter(c => c.type === 'Box' && c.props?.position === 'absolute' && re.test(String(c.props?.key)))
    if (svg && boxes.length) out.push({ svg, boxes })
  })
  return out
}
/** the band of every hover Box (top and bottom px) against the rows of its picture, and the Link inside it against the band; returns the errors in px */
const tableErrors = (t: { svg: any; boxes: any[] }) => {
  const src = String(t.svg.props.source), H = svgH(src), tops = rowTopsOf(src)
  const errs: { what: string; err: number }[] = []
  for (const b of t.boxes) {
    expect(b.props.marginTop, 'the Box has a place of its own, no marginTop gap').toBeUndefined()
    const top = cells(b.props.top), bottom = top + cells(b.props.height)
    const row = tops.find(x => x === top)
    errs.push({ what: `band top ${top} is a row top`, err: row == null ? Math.min(...tops.map(x => Math.abs(x - top))) : 0 })
    const nextTop = tops.find(x => x > top) ?? H
    const wantBottom = Number(b.props.height) === 1 ? Math.min(top + CELL_PX, nextTop) : bottom // a wrapped row's own height is its span
    errs.push({ what: `band bottom ${bottom} is the row's bottom`, err: bottom - wantBottom })
    for (const s of spots(b, top, bottom - top)) errs.push({ what: `${s.el.type} line ${s.line} on the band top ${top}`, err: s.line - top })
  }
  return errs
}
const report = (label: string, errs: { err: number }[]) => { const max = Math.max(0, ...errs.map(e => Math.abs(e.err))); console.log(`${label}: ${errs.length} measures, max |error| ${max} px`); return max }

test('#837 pass 2 P4: Tickets «Цели» / «Вне целей»: each ticket-number press (a blank Button tl-tk…, #972) lies on its title\'s line, its band is the row\'s own top and bottom', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui, clock } = await mount($, on, { fast: FAST, tickets: TODAY, slow: SLOW, orch: ORCH })
  await ui.press({ key: 'tab-tickets' }); await clock.settle()
  await ui.press({ key: 'tg-670' }); await clock.settle()
  const errs: { what: string; err: number }[] = []
  let links = 0, titled = 0
  for (const t of tables(await ui.drawn(), /^hv-tk-\d+$/)) {
    errs.push(...tableErrors(t))
    const ts = tspans(String(t.svg.props.source))
    let at = 0
    for (const b of t.boxes) {
      const n = Number(/(\d+)$/.exec(String(b.props.key))![1])
      const title = unesc(String(TK.issues[String(n)].title)).slice(0, 14)
      let j = at
      while (j < ts.length && !ts[j]!.t.startsWith(title)) j++
      expect(j < ts.length, `a title for #${n}`).toBe(true)
      at = j + 1
      const titleTop = ts[j]!.y - 14, sp = spots(b, cells(b.props.top), cells(b.props.height)).filter(s => s.el.type === 'Button' && new RegExp(`^tl-tk[\\w-]*-#?${n}$`).test(String(s.el.props?.key)))
      expect(sp.length, `#${n} has its ticket Button tl-tk…-${n}`).toBe(1)
      // #972: the number is drawn in the table's picture (class ac); the Button over it is blank, in an absolute Box at the top of the row's keyed Box
      expect(new RegExp(`class="ac"[^>]*>(?:<tspan[^>]*>[^<]*</tspan>)*<tspan[^>]*>#${n}<`).test(dq(String(t.svg.props.source))), `#${n} is drawn in the picture, class ac`).toBe(true)
      expect(String(sp[0]!.el.props.label).replace(/\s/g, ''), `#${n} Button is blank`).toBe('')
      links++; titled++
      errs.push({ what: `#${n} ticket Button line against its title's line`, err: sp[0]!.line - titleTop })
    }
  }
  const max = report('tickets', errs)
  console.log(`tickets: ${links} Links read against ${titled} titles`)
  expect(links).toBeGreaterThanOrEqual(60) // #983: the rows of the page the budget gives (hooks/budget.ts), no longer the 97 of the old 60,000-character literal
  expect(max, errs.filter(e => e.err).slice(0, 5).map(e => `${e.what}: ${e.err}`).join('; ')).toBe(0)
  await ui.unmount()
})

test('#837 pass 2 P4: Cost tables (week, «По ролям» first row too): every hover Box is the top and bottom of a row of its picture', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui, clock } = await mount($, on, { fast: '{}', tickets: COST_TICKETS_20261011, slow: COST_SLOW_20261011, orch: '{}' })
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  await ui.press({ key: 'cost-week' }); await clock.settle()
  const errs: { what: string; err: number }[] = []
  const ts = tables(await ui.drawn(), /^hv-/)
  for (const t of ts) errs.push(...tableErrors(t))
  const max = report(`cost week: ${ts.length} tables`, errs)
  expect(ts.length, 'cost tables').toBeGreaterThan(2)
  expect(errs.length, 'measures').toBeGreaterThan(10)
  expect(max, errs.filter(e => e.err).slice(0, 5).map(e => `${e.what}: ${e.err}`).join('; ')).toBe(0)
  await ui.unmount()
})

// #995 send-back 1 (defect 4, the brain's pass 14.10: «rows light on hover, a press opens nothing (не разобран 6)»): a Progress count row opens nothing, so it has no
// row Box and no Button: nothing lights over the two tables
test('#995 send-back 1: Progress tables: no count row has a Box or a Button (a press opens nothing, so nothing lights)', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui, clock } = await mount($, on, { fast: FAST, tickets: TODAY, slow: SLOW, orch: ORCH })
  await ui.press({ key: 'tab-progress' }); await clock.settle()
  const json = JSON.stringify(await ui.drawn())
  const rowKeys = json.match(/"key":"(hv-prog-[^"]*|p[lo]-h\d+)"/g) ?? []
  console.log(`progress: ${rowKeys.length} row Boxes; tables ${(json.match(/"alt":"(По тикетам|Остальное)"/g) ?? []).length}`)
  expect(rowKeys, 'row Boxes over the Progress tables').toEqual([])
  expect((json.match(/"alt":"(По тикетам|Остальное)"/g) ?? []).length, 'the two tables').toBe(2)
  await ui.unmount()
})

// ---- the card strips ------------------------------------------------------------------------------------------------
/** the tops of a strip picture's rows (the first at 0, the others each in its own `translate(0 y)`) */
const stripTops = (src: string) => [0, ...[...dq(src).matchAll(/<g transform="translate\(0 ([\d.]+)\)">/g)].map(m => Number(m[1]))]
// #983: the runs card is the first card of the tab «POB»
const CARDS: [string, number, number, string?][] = [['Agents', 0, 11], ['Merge', 1, 5], ['PoB runs', 0, 25, 'pob']] // #994: the first page's dim «previous» chevron is no Button; #995: Merge's «Готово» is paged (its «next» chevron)
for (const [name, n, count, tab] of CARDS) {
  test(`#837 pass 2 P4: ${name} card: each of its ${count} presses lies on its own row (Box top within half a cell of the row's top, its centre inside the row)`, { timeoutMs: 60_000 }, async ($, on) => {
    on('fs.write', async () => ({ value: undefined }) as any) // mountPane has no handler for it: the file would end on "no implementation for fs.write"
    const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST, tab }, 123)
    const card = shown(await (ui as any).drawn()).children[2].children[n]
    const errs: { what: string; err: number }[] = []
    let seen = 0
    walk(card, (b) => {
      const ks = kids(b)
      ks.forEach((svg, i) => {
        if (svg.type !== 'Svg' || isBlank(svg)) return // a row's blank Svg (its px height) is not a picture of rows
        const src = String(svg.props?.source ?? ''), H = svgH(src), tops = stripTops(src)
        const over = ks.slice(i + 1).filter(c => c.type === 'Box' && c.props?.position === 'absolute')
        for (const o of over) for (const s of spots(o, 0, H)) {
          seen++
          const row = [...tops].sort((a, c) => Math.abs(a - s.top) - Math.abs(c - s.top))[0]!
          const next = tops.find(x => x > row) ?? H
          const rowH = Math.min(next - row, CARD_PITCH)
          // #837 variant B: a row is whole cells (cumulative rounding), so its Box top is within half a cell of its row's picture top
          const id = String(s.el.props?.href ?? s.el.props?.key), centre = s.line + CELL_PX / 2
          errs.push({ what: `${id} band top ${s.top} vs row ${row}`, err: Math.max(0, Math.abs(s.top - row) - CELL_PX / 2) })
          errs.push({ what: `${id} centre ${centre} outside row ${row}..${row + rowH}`, err: Math.max(0, row - centre, centre - (row + rowH)) })
        }
      })
    })
    const max = report(`${name}: ${seen} presses`, errs)
    expect(seen).toBe(count)
    expect(errs.every(e => Math.abs(e.err) <= 0.001), errs.filter(e => Math.abs(e.err) > 0.001).slice(0, 4).map(e => `${e.what}: ${e.err.toFixed(2)}`).join('; ') + ` (max ${max.toFixed(2)} px)`).toBe(true)
    await ui.unmount()
  })
}
