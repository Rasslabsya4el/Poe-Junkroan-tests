import { test, mock, expect } from 'claude-code/testing'
// #671: the Tickets tab stays under ~90k chars on the desktop (07.10: 98k drew, 139k froze), any branch open.
import { FAST, SLOW, ORCH } from './fixtures'
import { LIVE } from './tickets-live'
import { LIVE as TODAY } from './tickets-live-20261011'
import { cellsOf } from './tickets-cells'
import { GOLD } from './tickets-cells-20261011'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const OUT: Record<string, string> = { fast: FAST, tickets: LIVE, slow: SLOW, orch: ORCH }
const size = async (ui: any) => { try { return String(JSON.stringify(await ui.drawn()).length) } catch (err) { return 'REFUSED: ' + String(err).slice(0, 300) } }

test('desktop: tickets tab, open #670 and its children', { timeoutMs: 60_000 }, async ($, on) => {
  const clock = mock.clock(on)
  on('process.run', async (_$, e) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-tickets' }); await clock.settle()
  console.log(`SZ tickets closed ${await size(ui)}`)
  const OPENED = [670, 659, 567, 592, 594]
  for (const n of OPENED) {
    const t0 = Date.now()
    await ui.press({ key: `tg-${n}` }); await clock.settle()
    console.log(`SZ open ${n}: ${await size(ui)} (${Date.now() - t0} ms)`)
  }
  const tk = JSON.parse(LIVE)
  const parents = Object.values(tk.issues).filter((i: any) => i.kids.length > 0).map((i: any) => i.n).filter((n: number) => !OPENED.includes(n)) // tg- toggles: pressing an opened one again closes it
  for (const n of parents) { try { await ui.press({ key: `tg-${n}` }) } catch {} }
  await clock.settle()
  console.log(`SZ every parent open (${parents.length}): ${await size(ui)}`)
  expect(Number(await size(ui)), 'every branch open').toBeLessThan(90_000)
  await ui.unmount()
})

// ---- #671 rows 2-4: the 2026-10-11 list (shared-tickets.json, 696 issues, 84 parents), 123 columns, desktop surface.
const P123: any = { ...PROPS, bodyColumns: 123 }
const OUT_T: Record<string, string> = { fast: FAST, tickets: TODAY, slow: SLOW, orch: ORCH }
const TK = JSON.parse(TODAY)
const rowsOf = (openSet: Set<number>) => { // the ticket rows the tab holds with these branches open, no paging, no cap
  const walk = (n: number): number => 1 + (openSet.has(n) ? (TK.issues[String(n)].kids as number[]).reduce((a, k) => a + (TK.issues[String(k)] ? walk(k) : 0), 0) : 0)
  return [...TK.goals, ...TK.loose].reduce((a: number, n: number) => a + (TK.issues[String(n)] ? walk(n) : 0), 0)
}
const mountToday = async ($: any, on: any) => {
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT_T[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: P123 })
  await ui.press({ key: 'tab-tickets' }); await clock.settle()
  return { ui, clock }
}
const keysOf = (d: string) => [...d.matchAll(/"key":"hv-tk-(\d+)"/g)].map(m => Number(m[1]))
/** every page of the tab, from the first: [json, ticket numbers drawn] */
const pagesOf = async (ui: any, clock: any) => {
  for (let i = 0; i < 40; i++) { try { await ui.press({ key: 'tk-prev' }) } catch { break } await clock.settle() }
  const out: { d: string; keys: number[] }[] = []
  for (let i = 0; i < 40; i++) {
    const d = JSON.stringify(await ui.drawn())
    const keys = keysOf(d)
    if (out.length && JSON.stringify(out[out.length - 1].keys) === JSON.stringify(keys)) break // «старее» on the last page stays
    out.push({ d, keys })
    try { await ui.press({ key: 'tk-next' }) } catch { break }
    await clock.settle()
  }
  return out
}

// #972 / #983: with the row light a row draws ~970 characters, so #670's 97 rows no longer fit one page under the host's limit: the budget (hooks/budget.ts) pages them.
test('#671 row 2: the largest map (#670, 79 children) open: every row drawn over the pages the budget gives, none hidden, Вне целей drawn, every page under 95,000', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui, clock } = await mountToday($, on)
  await ui.press({ key: 'tg-670' }); await clock.settle()
  const pages = await pagesOf(ui, clock)
  const d = pages[0].d
  const want = rowsOf(new Set([670]))
  console.log(`R2 #670 open: size ${d.length}, ticket rows drawn ${pages[0].keys.length} of ${want}, hidden ${(d.match(/не показан/g) ?? []).length}, Вне целей ${d.includes('card-tk-loose') ? 'drawn' : 'MISSING'}, pages ${pages.length}`)
  expect(new Set(pages.flatMap(p => p.keys)).size, 'rows drawn over the pages = #670 children + the rows above').toBe(want)
  for (const p of pages) {
    expect(p.d.includes('не показан'), 'hidden-rows sentence').toBe(false)
    expect(p.d.includes('card-tk-loose'), 'Вне целей drawn').toBe(true)
    expect(p.d.length, 'size of a page').toBeLessThanOrEqual(95_000)
  }
  expect(pages.length, 'pages').toBeLessThanOrEqual(2)
  await ui.unmount()
})

test('#671 row 3: every parent open: every page under 90,000, the pages hold every row, no hidden-rows sentence', { timeoutMs: 120_000 }, async ($, on) => {
  const { ui, clock } = await mountToday($, on)
  const parents: number[] = Object.values(TK.issues).filter((i: any) => i.kids.length > 0).map((i: any) => i.n)
  const opened = new Set<number>()
  for (let pass = 0; pass < 8; pass++) { // a parent is pressed on the page that draws it
    const n0 = opened.size
    for (let i = 0; i < 40; i++) { try { await ui.press({ key: 'tk-prev' }) } catch { break } await clock.settle() }
    let last = ''
    for (let pg = 0; pg < 40; pg++) {
      for (const n of parents) { if (opened.has(n)) continue; try { await ui.press({ key: `tg-${n}` }); opened.add(n) } catch {} }
      await clock.settle()
      const here = JSON.stringify(keysOf(JSON.stringify(await ui.drawn())))
      if (here === last) break
      last = here
      try { await ui.press({ key: 'tk-next' }) } catch { break }
      await clock.settle()
    }
    if (opened.size === n0) break
  }
  const pages = await pagesOf(ui, clock)
  const seen = new Set<number>()
  let sum = 0, repeated = 0, largest = 0
  for (const p of pages) {
    largest = Math.max(largest, p.d.length)
    // a page that begins inside a branch repeats the rows above its first new row: the leading run of rows already drawn
    let lead = true
    for (const k of p.keys) { if (lead && seen.has(k)) repeated++; else { lead = false; sum++ } seen.add(k) }
    expect(p.d.length, 'a page').toBeLessThan(90_000)
    expect(p.d.includes('не показан'), 'hidden-rows sentence').toBe(false)
    expect(p.d.includes('card-tk-loose'), 'Вне целей on every page').toBe(true)
  }
  const want = rowsOf(new Set(parents))
  console.log(`R3 every parent open (${opened.size} of ${parents.length}): pages ${pages.length}, largest page ${largest}, rows over the pages ${sum} (+${repeated} repeated parent rows) of ${want} without paging, page sizes ${pages.map(p => p.d.length).join(' ')}`)
  expect(opened.size, 'parents opened').toBe(parents.length)
  expect(sum, 'ticket rows over the pages').toBe(want)
  await ui.unmount()
})

// #972: the parent's row drew its title and counts in the picture and the number as a native Link `L:#N|url`; now the number `#N` is a word of the picture (a `T:#N` cell) and a blank Button
// (whitespace only; the toggle's is exactly two no-break spaces, the number's is em spaces since #972) lies over it. The gold keeps its recorded cells; the Link becomes those two, and a row's cells are compared sorted.
const asNow = (cells: string[]): string[] => cells.flatMap(c => { const m = /^L:(#\d+)\|/.exec(c); return m ? [`T:${m[1]}`, 'B:blank'] : [c] }).sort()
/** #994 (the owner's rule: a title is ONE line cut with an ellipsis): a title the row draws cut («…» at its end) stands for the lines the parent wrapped it onto, when they read as its whole */
const clipBack = (cells: string[] | null, want: string[]): string[] | null => {
  if (!cells) return cells
  // the parent's wrapped lines of the cut title: the text lines of `want` this row does not draw whole, the first of them the start of what it draws (GOLD keeps its lines sorted)
  const rest = want.filter(x => x.startsWith('T:') && !/^T:#\d+$/.test(x) && !cells.includes(x))
  return cells.flatMap(c => {
    if (!/^T:.*…$/.test(c)) return [c]
    const pre = c.slice(2, -1).trimEnd()
    return rest.some(w => pre.startsWith(w.slice(2)) || w.slice(2).startsWith(pre)) && rest.reduce((n, w) => n + w.length - 2, 0) > pre.length ? rest : [c]
  })
}
const gotNow = (cells: string[] | null): string[] | null => cells && cells.map(c => /^B:\s+$/.test(c) && c !== 'B:  ' ? 'B:blank' : c).sort()
test('#671 row 4: the cell texts of a row are what the parent drew (cap 55, inline icons), the number now a picture word + a blank Button: differing 0', async ($, on) => {
  const { ui, clock } = await mountToday($, on)
  const got: Record<string, Record<number, string[]>> = { '0': cellsOf(await ui.drawn()) }
  for (const n of [670, 282, 334]) { await ui.press({ key: `tg-${n}` }); await clock.settle(); got[String(n)] = cellsOf(await ui.drawn()); await ui.press({ key: `tg-${n}` }); await clock.settle() }
  let compared = 0
  const differing: string[] = []
  for (const [cfg, rows] of Object.entries(GOLD)) for (const [n, want] of Object.entries(rows)) {
    compared++
    if (JSON.stringify(gotNow(clipBack(got[cfg]?.[Number(n)] ?? null, want))) !== JSON.stringify(asNow(want))) differing.push(`${cfg}:${n}`)
  }
  console.log(`R4 rows compared ${compared}, differing ${differing.length}${differing.length ? ' e.g. ' + differing[0] + ': ' + JSON.stringify(gotNow(got[differing[0].split(':')[0]]?.[Number(differing[0].split(':')[1])] ?? null)) + ' vs ' + JSON.stringify(asNow(GOLD[differing[0].split(':')[0]][differing[0].split(':')[1]])) : ''}`)
  expect(compared, 'rows compared').toBeGreaterThan(100)
  expect(differing, 'rows with other cell texts').toEqual([])
  await ui.unmount()
})
