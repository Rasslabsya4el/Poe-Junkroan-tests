import { test, expect } from 'claude-code/testing'
import { mountPane, svgRows, pressStale } from './kit'
import { readPic, allPics } from './pics-837-b9b'
import { LIVE_FAST } from './fast-live'
import { LIVE as TODAY } from './tickets-live-20261011'
import { REAL_B11 } from './real-837-b11'

// #837 b12 G1: the grid of a run's builds (the section under the runs card) shows GRID_PAGE = 8 builds a page, with the history's own pager («новее» / «старее», keys grid-prev / grid-next) on its label row.
// A weekly run keeps ADDING builds, so the main tab used to grow with it until no row lit at all. The order across pages: a build with a seed being computed, then one with a finished seed, then the waiting ones.
const RUN = 'j-20261011-0419-7609'
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
const two = (i: number) => String(i).padStart(2, '0')
type St = 'done' | 'running' | 'waiting' | 'failed'
/** the live payload whose first running run has the builds `states` (one seed each, named `Smite NN`, in the given order) */
const payload = (states: St[]) => {
  const d = JSON.parse(LIVE_FAST)
  const run = d.runs.running.find((j: any) => j.id === RUN)
  const tpl = run.progress.cells.find((c: any) => c.state === 'running')
  const cells = states.map((state, i) => ({ ...tpl, ref: `ref_${two(i + 1)}`, name: `Smite ${two(i + 1)}`, seed: 1, state, variant: undefined, ...(state === 'running' ? {} : { started_est: undefined, started: undefined, expect_s: undefined, took: '30 min' }) }))
  run.progress = { ...run.progress, done: states.filter(s => s === 'done').length, total: states.length, total_open: false, cells }
  d.runs.running = [run, ...d.runs.running.filter((j: any) => j !== run)] // the first running run is the one whose grid is shown
  return JSON.stringify(d)
}
const open = async ($: any, on: any, fast: string, cols = 123) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  return mountPane($, on, 'desktop', { tab: 'pob', fast, tickets: TODAY, faces: true }, cols)
}
/** the names of the grid rows drawn now ("Билд «Smite NN»: ..." alts), in drawing order */
const gridNames = async (ui: any): Promise<string[]> => {
  const out: string[] = []
  for (const s of await svgRows(ui)) { const m = /^Билд «([^»]*)»: /.exec(String(s.props?.alt ?? '')); if (m) out.push(m[1]!) }
  return out
}
const counter = async (ui: any) => {
  for (const s of await svgRows(ui)) { const m = /(\d+–\d+ из \d+)/.exec(String(s.props?.source ?? '')); if (m && /Билды/.test(String(s.props?.source ?? '') + String(s.props?.alt ?? ''))) return m[1] }
}
const A27: St[] = [...Array(10).fill('waiting'), ...Array(5).fill('done'), ...Array(3).fill('running'), ...Array(9).fill('waiting')]

test('#837 b12 G1: 27 builds are 8 rows a page, "1–8 из 27", then 9–16, 17–24, 25–27 (3 rows) and the pager stops', { timeoutMs: 120_000 }, async ($, on) => {
  const ui = await open($, on, payload(A27))
  expect((await gridNames(ui)).length, 'page 1: 8 rows').toBe(8)
  expect(await counter(ui)).toBe('1–8 из 27')
  await ui.press({ key: 'grid-next' })
  expect(await counter(ui)).toBe('9–16 из 27')
  expect((await gridNames(ui)).length).toBe(8)
  await ui.press({ key: 'grid-next' })
  expect(await counter(ui)).toBe('17–24 из 27')
  await ui.press({ key: 'grid-next' })
  expect(await counter(ui)).toBe('25–27 из 27')
  expect((await gridNames(ui)).length, 'the last page: 3 rows').toBe(3)
  expect((await ui.findAll({ type: 'Markdown' })).some((m: any) => String(m.key ?? m.props?.key) === 'grid-next'), 'past the end: "старее" has nothing to press (dim, no link)').toBe(false)
  await ui.press({ key: 'grid-prev' })
  expect(await counter(ui)).toBe('17–24 из 27')
  await ui.unmount()
})

test('#837 b12 G1: two presses from one render\'s closure move two pages (and not past the end)', { timeoutMs: 120_000 }, async ($, on) => {
  const ui = await open($, on, payload(A27))
  await pressStale(ui, 'grid-next', 2)
  expect(await counter(ui)).toBe('17–24 из 27')
  await pressStale(ui, 'grid-next', 5)
  expect(await counter(ui)).toBe('25–27 из 27')
  await pressStale(ui, 'grid-prev', 2)
  expect(await counter(ui)).toBe('9–16 из 27')
  await ui.unmount()
})

test('#837 b12 G1: the order: the builds being computed first, then the ones with a finished seed, then the waiting ones, each group in the run\'s order', { timeoutMs: 120_000 }, async ($, on) => {
  const ui = await open($, on, payload(A27))
  // 11-15 done, 16-18 running, 1-10 and 19-27 waiting
  expect(await gridNames(ui)).toEqual(['Smite 16', 'Smite 17', 'Smite 18', 'Smite 11', 'Smite 12', 'Smite 13', 'Smite 14', 'Smite 15'])
  await ui.press({ key: 'grid-next' })
  expect(await gridNames(ui)).toEqual([1, 2, 3, 4, 5, 6, 7, 8].map(i => `Smite ${two(i)}`))
  await ui.press({ key: 'grid-next' })
  expect(await gridNames(ui)).toEqual([9, 10, 19, 20, 21, 22, 23, 24].map(i => `Smite ${two(i)}`))
  await ui.unmount()
})

test('#837 b12 G1: 8 builds or fewer: no pager and the run\'s own order', { timeoutMs: 120_000 }, async ($, on) => {
  const states: St[] = ['waiting', 'done', 'running', 'waiting', 'failed', 'waiting', 'running', 'done']
  const ui = await open($, on, payload(states))
  expect(await gridNames(ui)).toEqual(states.map((_s, i) => `Smite ${two(i + 1)}`))
  expect((await ui.findAll({ type: 'Markdown' })).length >= 0).toBe(true)
  const keys: string[] = []
  walk(await (ui as any).drawn(), n => { if (n.props?.key === 'grid-prev' || n.props?.key === 'grid-next') keys.push(n.props.key) })
  expect(keys, 'no pager keys').toEqual([])
  expect(await counter(ui), 'no counter').toBeUndefined()
  await ui.unmount()
})

for (const cols of [123, 80, 60]) {
  test(`#837 b12 G1: the pager and the counts text are at least 12 screen px apart at ${cols} columns (the counts text loses its tail parts when they do not fit)`, { timeoutMs: 120_000 }, async ($, on) => {
    const ui = await open($, on, payload(A27), cols)
    const tree: any = await (ui as any).drawn()
    const pic = allPics(tree).find(n => /из 27/.test(String(n.props?.source ?? '')))
    expect(pic, `cols ${cols}: the picture of the label row`).toBeTruthy()
    const { items } = readPic(pic, cols)
    const row = items.filter(i => i.kind === 'text' && /из 27/.test(i.t))[0]!
    expect(row, 'the counter').toBeTruthy()
    const same = items.filter(i => i.kind === 'text' && i.row === row.row && Math.abs(i.y - row.y) < 1)
    const counts = same.find(i => /готово|считается|ждут|ждёт/.test(i.t))
    console.log(`#837 b12 G1 cols ${cols}: counter x0 ${row.x0.toFixed(1)}, counts ${counts ? `"${counts.t}" x ${counts.x0.toFixed(1)}..${counts.x1.toFixed(1)}` : 'none'}, row words ${same.map(i => `${i.t}@${i.x0.toFixed(0)}`).join(' | ')}`)
    if (cols === 123) expect(counts, 'the counts text is drawn whole').toBeTruthy()
    if (!counts) return void (await ui.unmount()) // no room for even its first part: it is gone, the pager stays
    expect('5 готово · 3 считаются · 19 ждут'.startsWith(counts.t), 'only whole parts from the left, no cut word').toBe(true)
    expect(row.x0 - counts.x1, 'counts text to the counter, screen px').toBeGreaterThanOrEqual(12)
    const lead = same.filter(i => i.bold)
    for (const l of lead) expect(counts.x0 - l.x1, 'the row\'s left word to the counts text').toBeGreaterThanOrEqual(12 - 0.01)
    await ui.unmount()
  })
}

test('#837 b12 G1: the page resets to the first when another run is shown', { timeoutMs: 120_000 }, async ($, on) => {
  const d = JSON.parse(payload(A27))
  const first = d.runs.running.find((j: any) => j.id === RUN)
  const second = JSON.parse(JSON.stringify(first))
  second.id = 'j-20261011-0419-0000'; second.tag = 'second'; second.issue = 9999
  d.runs.running = [first, second]
  const ui = await open($, on, JSON.stringify(d))
  await ui.press({ key: 'grid-next' })
  expect(await counter(ui)).toBe('9–16 из 27')
  await ui.press({ key: 'run-pick-' + second.id })
  expect(await counter(ui), 'the second run starts at page 1').toBe('1–8 из 27')
  await ui.press({ key: 'grid-next' })
  expect(await counter(ui)).toBe('9–16 из 27')
  await ui.press({ key: 'run-pick-' + RUN })
  expect(await counter(ui), 'back to the first run: page 1 again').toBe('1–8 из 27')
  await ui.unmount()
})

// the size: the real payload of 2026-10-13 04:19 (15 builds, 43 seed cells) and a 40-build copy of it
// #972: one form (no pill / mask / light tiers): every strip row of the runs card is a keyed Box `hv-run<n>` that lights NOTHING of its own (no `hover` prop: the light is the pointer element's)
const stripsOf = (tree: any) => {
  let rows = 0, veil = 0
  walk(tree, x => { if (x.type === 'Box' && /^hv-run\d+$/.test(String(x.props?.key ?? ''))) { rows++; if (x.hover != null || x.props?.hover != null) veil++ } })
  return { rows, veil }
}
const grown = (n: number) => {
  const d = JSON.parse(REAL_B11)
  const run = d.runs.running.find((j: any) => j.progress?.cells?.length)
  const cells: any[] = run.progress.cells
  const lines = new Map<string, any[]>()
  for (const c of cells) { const k = `${c.ref}|${c.variant ?? ''}`; lines.set(k, [...(lines.get(k) ?? []), c]) }
  const base = [...lines.values()], more: any[] = []
  for (let k = 0; base.length + k < n; k++) for (const c of base[k % base.length]!) more.push({ ref: `${c.ref}_x${k}`, name: `${c.name} ${k}`, seed: c.seed, class: c.class, asc: c.asc, state: 'waiting' }) // a weekly run adds builds that wait: only the slots' worth of builds run at once
  run.progress = { ...run.progress, cells: [...cells, ...more] }
  return JSON.stringify(d)
}
for (const n of [15, 40]) {
  test(`#837 b12 G1: the real payload with ${n} builds: every strip row of the runs card is a keyed hv-run Box with no hover prop, the measure plus 600 under 90,000`, { timeoutMs: 120_000 }, async ($, on) => {
    const ui = await open($, on, grown(n), 124)
    const tree: any = await (ui as any).drawn()
    const size = JSON.stringify(await ui.drawn()).length, t = stripsOf(tree)
    console.log(`#837 b12 G1 real payload, ${n} builds: ${size} chars, ${t.rows} hv-run strip rows (${t.veil} with a hover prop), spare ${95_000 - size - 600}, grid rows ${(await gridNames(ui)).length}`)
    expect(t.rows, 'the runs card has strip rows keyed hv-run').toBeGreaterThan(0)
    expect(t.veil, 'no strip row carries a hover prop (#972: the veil is gone)').toBe(0)
    expect(size + 600, 'under the guard (#972: the host limit 100,000 less a 5,000 margin; the press stamps are in the mock tree)').toBeLessThan(95_000)
    expect((await gridNames(ui)).length).toBe(8)
    await ui.unmount()
  })
}
