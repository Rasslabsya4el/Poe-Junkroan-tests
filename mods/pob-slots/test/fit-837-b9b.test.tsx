import { test, expect } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, bars } from './kit'
import { textWidth } from '../hooks/draw'
import { allPics, readPic, mountTab } from './pics-837-b9b'

// #837 round 9b (B2, B3): a drawn cell is ellipsised only when its text really cannot fit the room up to the next drawn thing.
const fixture = (hist: any[], statuses?: string[]) => {
  const f = JSON.parse(FAST)
  const base = f.runs.queued[0]
  const cell0 = f.runs.running[0].progress.cells.find((c: any) => c.state === 'running')
  f.runs.queued = []
  // a running run whose child rows (the builds being computed) say `statuses`
  f.runs.running = statuses ? [{ ...base, id: 'j-r', tag: 'P2-core-3', issue: null, host: 'pc', priority: 'P2', state: 'running', locks: 2, workers: 2, left_h: '40 min',
    progress: { done: 1, total: 3, total_open: true, eta: null, dir: 'x', cells: statuses.map((st, i) => ({ ...cell0, name: `Kid ${i}`, ref: `ref-${i}`, class: 'Templar', stage: st, bar: { w: [0.4706, 0.528, 0.0014], fill: [1, 0.5, 0], at: 1 }, started: Math.round(Date.now() / 1000) - 600 })) } }] : []
  f.runs.history = hist.map((h, i) => ({ ...base, id: `h${i}`, tag: `P2-core-${i}`, issue: null, state: 'stopped', host: 'pc', priority: 'P2', workers: 2, dur: '15 min', rows_done: 1, rows_total: 3, ...h }))
  return JSON.stringify(f)
}
// the drawn width of a date: its digits are 0.55 em at 12 px (measured on the screen: «12.10 14:41» is 59 screen px = 61 picture px); the shared measure counts 0.64 em
const realW = (s: string) => textWidth(s) - (s.match(/\d/g)?.length ?? 0) * 0.09 * 12
const rowOf =async (ui: any, tag: string, state: string) => (await bars(ui)).filter((p: any) => String(p.alt).startsWith(`${tag} ${state}`))[0]

// B2: the first "Готово" row (two slot squares + a progress bar) drew «12.10 16…» although the room up to the bar holds the whole date
// #995 send-back 1 (defect 5: the date-time stood in «приоритет, слоты» with no head of its own): the date is the runs card's own column «начало», right-aligned at
// W - 112 (the time column's x less 16), so it is ALWAYS whole, whatever the slots; the meta column holds the pictures only, and the status text ends before the date
test('#837 b9b B2 / #995 send-back 1: a Готово row draws its whole date right-aligned in its own column «начало», never in the meta column, the status ending before it', async ($, on) => {
  const dates = [['12.10', '16:17'], ['12.10', '14:41'], ['12.10', '11:11'], ['09.10', '23:05'], ['12.10', '16:17']]
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: fixture(dates.map(([date, start], i) => ({ date, start, workers: i === 4 ? 8 : 2 }))) }, 123)
  const W = Math.round(123 * 7.8) + 4, whenEnd = W - 96 - 16
  for (const [i, [date, start]] of dates.entries()) {
    const p = await rowOf(ui, `P2-core-${i}`, 'stopped')
    expect(p, `row ${i}`).toBeTruthy()
    const tx = [...p!.src.matchAll(/<text x="([\d.]+)"([^>]*)>(\d\d\.\d\d[^<]*)</g)].map(m => ({ x: +m[1]!, end: /text-anchor="end"/.test(m[2]!), t: m[3]! }))
    console.log(`B2 row ${i} drawn ${JSON.stringify(tx)}`)
    expect(tx, `row ${i}: one date, whole, right-aligned at ${whenEnd}`).toEqual([{ x: whenEnd, end: true, t: `${date} ${start}` }])
    const act = [...p!.src.matchAll(/<text x="([\d.]+)"[^>]*>([^<]*(?:готово|остановлен|упал)[^<]*)</g)].map(m => ({ x: +m[1]!, t: m[2]! }))
    expect(act.length, `row ${i}: its status`).toBe(1)
    expect(act[0]!.x + textWidth(act[0]!.t), `row ${i}: the status ends before the date`).toBeLessThanOrEqual(whenEnd - realW(`${date} ${start}`) - 4)
  }
  await ui.unmount()
})

// B3 (a): the running run's title stands on the column: the same column as the head «задача» and the Готово rows' titles (was 6 px = 5.5 on the screen right of them)
// #972: a run title is drawn in the picture again (class `bt`, markup x 38) and the blank Button `run-pick-…` / `run-hist-…` over it holds the press; the title's x is the picture's, the head «задача» is a word of the same picture
const kidsOf = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
const buttonsOf = (tree: any, key: RegExp) => { const out: any[] = []; const go = (n: any) => { if (n?.type === 'Button' && key.test(String(n.props?.key ?? ''))) out.push(n); for (const c of kidsOf(n)) go(c) }; go(tree); return out }
test('#837 b9b B3a: a running run title starts at the x of the head «задача» and of the Готово rows titles (the same picture x, class bt)', async ($, on) => {
  const { ui } = await mountTab($, on, { fast: fixture([{ date: '12.10', start: '16:17' }], ['improvement loop']) }, 'pob', 123) // #983: the runs card lives on the tab «POB»
  const tree: any = await (ui as any).drawn()
  let head = NaN, headFit = NaN
  const titles: Record<string, { x0: number; cls: string; fit: number }> = {}
  for (const n of allPics(tree)) {
    const pic = readPic(n, 123)
    for (const it of pic.items) {
      if (it.kind !== 'text') continue
      if (it.t === 'задача') { head = it.x0; headFit = pic.fit }
      if (it.t === 'P2-core-3' || it.t === 'P2-core-0') titles[it.t] = { x0: it.x0, cls: it.cls, fit: pic.fit }
    }
  }
  const run = titles['P2-core-3'], done = titles['P2-core-0']
  console.log(`B3a head ${head} (markup ${(head / headFit).toFixed(1)}) running title ${run?.x0} class ${run?.cls} Готово title ${done?.x0} class ${done?.cls}`)
  expect(Number.isNaN(head), 'the head «задача» is drawn').toBe(false)
  expect(run, 'the running run title is drawn in a picture').toBeTruthy()
  expect(done, 'the Готово run title is drawn in a picture').toBeTruthy()
  expect(run!.cls, 'running title class').toBe('bt')
  expect(done!.cls, 'Готово title class').toBe('bt')
  // one column: the markup x of the head, of the running title and of the Готово title is the same (38)
  expect(Math.abs(run!.x0 - head), 'running title vs head, px').toBeLessThan(0.01)
  expect(Math.abs(done!.x0 - head), 'Готово title vs head, px').toBeLessThan(0.01)
  expect(Math.round(head / headFit), 'the head x in markup px').toBe(38)
  // the press over each title is a blank Button of the old key (no word of its own)
  const pick = buttonsOf(tree, /^run-pick-/).find(b => String(b.props.key).includes('j-r')), hist = buttonsOf(tree, /^run-hist-/).find(b => String(b.props.key).includes('h0'))
  expect(pick, 'the running title press').toBeTruthy()
  expect(hist, 'the Готово title press').toBeTruthy()
  for (const b of [pick, hist]) expect(String(b.props.label).replace(/\s/g, ''), 'the press is blank').toBe('')
  await ui.unmount()
})

// B3 (b): a child row's status may use the room up to 12 screen px before the duration text, and is cut exactly there
test('#837 b9b B3b: a child status of 40 characters is drawn whole when it ends >= 12 px before the duration text, a longer one is cut exactly there', async ($, on) => {
  const short = 'construction: gear pass 1 (empty tree 1)'
  const long = 'construction: gear pass 1 (empty tree) and then a lot more words about the move that follows it, long long'
  expect(short.length).toBe(40)
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: fixture([], [short, long]) }, 123)
  const fit = Math.round(123 * 7.8 - 29.4) / 963
  for (const [i, st] of [short, long].entries()) {
    const p = await rowOf(ui, `Kid ${i}:`, '')
    expect(p, `kid ${i}`).toBeTruthy()
    const tx = [...p!.src.matchAll(/<text x="([\d.]+)"([^>]*)>([^<]*)</g)].map(m => ({ x: +m[1]!, end: /text-anchor="end"/.test(m[2]!), t: m[3]!.replace(/&amp;/g, '&') }))
    const said = tx.find(t => t.t.startsWith('construction'))!
    const time = tx.find(t => t.end && /\d/.test(t.t))!
    expect(said && time, `kid ${i} draws its status and its duration`).toBeTruthy()
    const timeStart = time.x - textWidth(time.t)
    const gap = (timeStart - (said.x + textWidth(said.t))) * fit
    console.log(`B3b kid ${i}: status «${said.t}» x ${said.x} ends ${(said.x + textWidth(said.t)).toFixed(1)} duration «${time.t}» starts ${timeStart.toFixed(1)}: gap ${gap.toFixed(1)} screen px`)
    expect(gap, `kid ${i}: >= 12 screen px before the duration`).toBeGreaterThanOrEqual(12 - 0.01)
    if (i === 0) expect(said.t, 'the 40-character status is whole').toBe(st)
    else {
      expect(said.t.endsWith('…'), 'the long one is cut').toBe(true)
      // exactly there: one more character would pass the 12 px line
      const next = st.slice(0, said.t.length) + '…'
      expect((timeStart - (said.x + textWidth(next))) * fit, 'one more character would not fit').toBeLessThan(12)
    }
  }
  await ui.unmount()
})
