import { test, expect } from 'claude-code/testing'
import { mountPane, altLines, cutRows, dq } from './kit'
import { LIVE_FAST } from './fast-live'
import { PILL } from '../hooks/kit'
import { CARD_PITCH as P } from '../hooks/tokens'
import { textWidth } from '../hooks/draw'
// #837 b9b B2: a date's digits are drawn 0.55 em at 12 px, the shared measure counts 0.64: the drawn width of a date is the measure less 0.09 em a digit
const dateW = (t: string) => textWidth(t) - (t.match(/\d/g)?.length ?? 0) * 0.09 * 12

// #837 pass 2 (moved from pass 1's 19 px rows / 17 px bands, baseline 50ea5412): a strip row of the Agents, Merge and PoB runs
// cards is a full pill 20 px high (rx 10) + 6 px air = 26 px apart (CARD_PITCH), one line, its text centred on the pill. A native
// press over it is the register's job (unit 2); here the picture's own geometry.
const kids = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
// #983: the runs card is the first card of the tab «POB»; Agents and Merge stay on «Главная»
const CARDS: [string, number, string?][] = [['Agents', 0], ['Merge', 1], ['PoB runs', 0, 'pob']]
const picOf = (card: any): any => { const f = (n: any): any => (n?.type === 'Svg' && altLines(n.props?.alt).length >= 2 ? n : kids(n).map(f).find(Boolean)); return f(card) }
/** the picture's rows: top (cell grid), drawn translate dy, first text line's baseline, the row's alt */
const rowsOf = (svg: any) => {
  const src = dq(String(svg.props.source))
  const dys = [...src.matchAll(/<g transform="translate\(0 ([\d.]+)\)">/g)].map(m => Number(m[1]))
  const cut = cutRows(svg.props.alt, src)
  let top = 0
  return cut.map(c => {
    const h = Number(/height="([\d.]+)"/.exec(c.src)?.[1])
    const dy = dys.find(d => d === top) ?? top
    const ys = [...c.src.matchAll(/<text [^>]*? y="([\d.]+)"/g)].map(m => Number(m[1]))
    const r = { alt: c.alt, top, h, dy, text: ys.length ? Math.min(...ys) : null }
    top += h
    return r
  })
}
for (const [name, n, tab] of CARDS) {
  test(`#837 pass 2: ${name} card: strip rows ${P} px apart, a 20 px full pill (rx 10) each, no band of rx 4`, async ($, on) => {
    on('fs.write', async () => ({ value: undefined }) as any)
    const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
    const svg = picOf((await (ui as any).drawn()).children[2].children[n])
    const rows = rowsOf(svg)
    const pilled = cutRows(svg.props.alt, dq(String(svg.props.source))).map(c => /rx="10"/.test(c.src))
    const gaps = rows.slice(1).map((r, i) => (pilled[i] && pilled[i + 1] ? r.top - rows[i]!.top : 0)).filter(Boolean)
    console.log(`PITCH ${name}: ${rows.length} rows, pill-to-pill distances ${JSON.stringify([...new Set(gaps)].sort((a, b) => a - b))} px`)
    expect(gaps.length).toBeGreaterThan(0)
    expect(gaps.every(g => g >= P)).toBe(true)
    expect(Math.min(...gaps)).toBe(P)
    const src = dq(String(svg.props.source))
    const pills = [...src.matchAll(/<rect [^>]*?height="(\d+)" rx="([\d.]+)"/g)].filter(m => m[2] === '10')
    expect(pills.length).toBeGreaterThan(0)
    expect(pills.every(m => Number(m[1]) === PILL)).toBe(true)
    expect(/ rx="4"/.test(src)).toBe(false)
    await ui.unmount()
  })
  test(`#837 pass 2: ${name} card: a row's text baseline sits on its pill's centre (4.4 px under it), within 1 px`, async ($, on) => {
    on('fs.write', async () => ({ value: undefined }) as any)
    const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
    const svg = picOf((await (ui as any).drawn()).children[2].children[n])
    const pilled = rowsOf(svg).filter(r => r.alt && r.text != null && /rx="10"/.test(cutRows(svg.props.alt, dq(String(svg.props.source))).find(c => c.alt === r.alt)?.src ?? ''))
    const off = pilled.map(r => Math.abs(r.text! - 4.4 - PILL / 2))
    console.log(`TEXTC ${name}: ${pilled.length} pilled rows, max offset ${Math.max(0, ...off).toFixed(2)} px`)
    expect(pilled.length).toBeGreaterThan(0)
    expect(off.every(d => d <= 1)).toBe(true)
    await ui.unmount()
  })
}

// #837 unit 1 (pobruns-ready-row): a PoB runs "Готово" row is ONE strip row (26 px): its date (`11.10 14:11`) stays on the row's own
// line, beside the priority bars / host / slot squares, never dropped under them on a second grid line (#773 picsDrop).
test('#837 pass 2: PoB runs card: every Готово row is one 26 px strip row, its date on the row', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST, tab: 'pob' }, 119)
  const svg = picOf((await (ui as any).drawn()).children[2].children[0])
  const rows = rowsOf(svg)
  const done = rows.filter(r => /^\S+ (done|failed|stopped|cancelled),/.test(r.alt ?? ''))
  // #995 send-back 1 (defect 5): the date is the card's own column «начало», right-aligned at W - 112 (119 columns: W 932, x 820), always whole; none is left in the meta column
  const dateTexts = [...dq(String(svg.props.source)).matchAll(/<text x="([\d.]+)"([^>]*)>(\d\d\.\d\d[^<]*)</g)].map(m => ({ x: Number(m[1]), end: /text-anchor="end"/.test(m[2]!), t: m[3]! }))
  const over = dateTexts.filter(d => !d.end || d.x !== Math.round(119 * 7.8) + 4 - 112 || !/^\d\d\.\d\d \d\d:\d\d$/.test(d.t))
  expect(dateTexts.length, 'a date a Готово row').toBe(done.length)
  console.log(`DONEROWS: ${done.length} rows, heights ${JSON.stringify([...new Set(done.map(r => r.h))])}, tops ${JSON.stringify(done.map(r => r.top))}`)
  expect(done.length).toBeGreaterThan(1)
  expect(done.every(r => r.h === P)).toBe(true)
  expect(done.slice(1).every((r, i) => r.top - done[i]!.top === P)).toBe(true)
  expect(over).toEqual([])
  await ui.unmount()
})

// #837 unit 4 (pics column width): at 119 cols a finished row of 1, 3, 7 and 10 slots draws min(slots, 8) squares and its
// date whole on the one 26 px row (baseline 50ea5412 drew 1,3,7,8; main drew 0 squares on every row).
test('#837 pass 2: PoB runs card: a Готово row of 1, 3, 7, 10 slots draws min(slots, 8) squares, its whole date in the column «начало», 26 px', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const fast = JSON.parse(LIVE_FAST)
  const want: Record<string, number> = { 'P1-#816-3': 1, 'P1-#813-2': 3, 'P1-#813-3': 7, 'P1-#785': 10 }
  for (const k of ['history', 'recent']) for (const j of fast.runs[k]) if (want[j.tag] != null) j.workers = want[j.tag]
  const ui = await mountPane($, on, 'desktop', { fast: JSON.stringify(fast), tab: 'pob' }, 119)
  const svg = picOf((await (ui as any).drawn()).children[2].children[0])
  const src = dq(String(svg.props.source))
  const cut = cutRows(svg.props.alt, src)
  const got = Object.entries(want).map(([tag, slots]) => {
    const c = cut.find(x => /^\S+ (done|failed|stopped),/.test(String(x.alt ?? '')) && String(x.alt).startsWith(`${tag} `))
    const sq = c ? (c.src.match(/h3v5h-3z/g) ?? []).length : -1
    // #995 send-back 1 (defect 5): whatever the squares, the date is whole in its own column «начало», right-aligned at W - 112 (119 columns: 820)
    const dates = c ? [...c.src.matchAll(/<text x="([\d.]+)"([^>]*)>(\d\d\.\d\d[^<]*)</g)].map(m => ({ x: Number(m[1]), end: /text-anchor="end"/.test(m[2]!), t: m[3]! })) : []
    const date = dates.length === 1 && dates.every(d => d.end && d.x === Math.round(119 * 7.8) + 4 - 112 && /^\d\d\.\d\d \d\d:\d\d$/.test(d.t))
    const h = Number(/height="([\d.]+)"/.exec(c?.src ?? '')?.[1])
    return { tag, slots, want: Math.min(slots, 8), sq, date, h }
  })
  console.log(`PICSW: ${JSON.stringify(got)}`)
  for (const g of got) {
    expect(g.sq).toBe(g.want)
    expect(g.date).toBe(true)
    expect(g.h).toBe(P)
  }
  await ui.unmount()
})

// #837 b3 item 3: at 123 columns every finished row of the PoB runs card shows its whole `dd.mm hh:mm`.
// #995 send-back 1 (defect 5): in its own column «начало» (right-aligned at W - 112 = 851), headed «начало» on the card's head row at the same x; the meta column draws no date
test('#837 b3 item 3 / #995 send-back 1: PoB runs card at 123 columns: every Готово row shows its whole dd.mm hh:mm under the head «начало»', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST, tab: 'pob' }, 123)
  const svg = picOf((await (ui as any).drawn()).children[2].children[0])
  const src = dq(String(svg.props.source))
  const whenEnd = Math.round(123 * 7.8) + 4 - 112
  const head = [...src.matchAll(/<text x="([\d.]+)"([^>]*)>начало</g)].map(m => ({ x: Number(m[1]), end: /text-anchor="end"/.test(m[2]!) }))
  expect(head, 'the head «начало», right-aligned on the column').toEqual([{ x: whenEnd, end: true }])
  const cut = cutRows(svg.props.alt, src)
  let whole = 0
  for (const c of cut) {
    if (!/^\S+ (done|failed|stopped),/.test(String(c.alt ?? ''))) continue
    const dates = [...c.src.matchAll(/<text x="([\d.]+)"([^>]*)>(\d\d\.\d\d[^<]*)</g)].map(m => ({ x: Number(m[1]), end: /text-anchor="end"/.test(m[2]!), t: m[3]! }))
    expect(dates.length, `${c.alt}: one date`).toBe(1)
    for (const d of dates) {
      expect(d.end && d.x === whenEnd, `${c.alt}: the date stands right-aligned at ${whenEnd} (x ${d.x})`).toBe(true)
      expect(d.t, `${c.alt}: the whole date`).toMatch(/^\d\d\.\d\d \d\d:\d\d$/); whole++
    }
  }
  console.log(`#837 b3 item 3: ${whole} Готово rows show the whole date in «начало»`)
  expect(whole, 'there are Готово rows in the fixture').toBeGreaterThan(0)
  await ui.unmount()
})
