import { test, expect } from 'claude-code/testing'
import { mountPane, cutRows, dq } from './kit'
import { LIVE_FAST } from './fast-live'
import { textWidth } from '../hooks/draw'
import { PX_PER_COL } from '../hooks/kit'

// #837 unit 9 (runs-geometry), drawn tree: (B) the drawn `#N` of Agents and Merge stands at the baseline's x (352 + one cell), (C) a waiting
// (В очереди) title of PoB runs is drawn in the colour token of Merge's waiting row (class tx, no muted fill).
const kids = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
const pics = (card: any): any[] => {
  const out: any[] = []
  const walk = (n: any) => { if (n?.type === 'Svg' && String(n.props?.source ?? '').includes('<text')) out.push(n); for (const c of kids(n)) walk(c) }
  walk(card)
  return out
}
const texts = (src: string) => [...src.matchAll(/<text x="([\d.]+)"([^>]*)>([^<]*)<\/text>/g)].map(m => ({ x: Number(m[1]), attrs: m[2]!, t: m[3]! }))
/** the x of the drawn `#N` tickets of a card's rows (the most frequent one: the ticket column) */
const tickX = (card: any) => {
  const xs: number[] = []
  for (const p of pics(card)) for (const t of texts(dq(String(p.props.source)))) if (/^#\d+$/.test(t.t)) xs.push(t.x)
  const n = new Map<number, number>()
  for (const x of xs) n.set(x, (n.get(x) ?? 0) + 1)
  return [...n.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
}
const fixture = () => {
  const d = JSON.parse(LIVE_FAST)
  const base = d.runs.running[0]
  d.merge = { at: '2026-10-09T19:46:10', running: { branches: ['orch-677'], issues: [677], phase: 'suite', started: '2026-10-09T19:38:32', percent: 62, tests_done: 2647, tests_total: 4270, failed: 0, eta_s: 140, workers: 6, suite_out: 'x.out', eta_h: '2 min', elapsed_h: '7 min' },
    waiting: [{ branch: 'orch-621', issues: [621], position: 1, queued: '2026-10-09T19:40:01', waited_s: 369, eta_start_s: 140, waited_h: '6 min', eta_start_h: '2 min' }], landed: [] }
  d.runs.queued = [{ ...base, id: 'j-q1', state: 'queued', issue: 817, tag: 'P1-#817-9', progress: undefined, wait: { kind: 'slots', text: '' } }]
  return JSON.stringify(d)
}
/** the colour token of the first drawn text of the row whose alt matches */
const nameToken = (card: any, alt: RegExp) => {
  for (const p of pics(card)) {
    const src = dq(String(p.props.source))
    for (const r of cutRows(p.props.alt, src)) if (alt.test(String(r.alt ?? ''))) {
      const t = texts(r.src).find(x => x.x > 30 && !/^#\d+$/.test(x.t))
      if (t) return { cls: /class="(\w+)"/.exec(t.attrs)?.[1], fill: /fill:(#[0-9a-fA-F]+)/.exec(t.attrs)?.[1] ?? null, x: t.x, t: t.t }
    }
  }
  return null
}
/** #837 b18 (form A): a run title is a host Button in its row's Box; the Box's `left` (cells) is the title's column, `dimColor` its shade */
const titleBoxes = (card: any, key: RegExp) => {
  const out: { b: any; left: number }[] = []
  // `left` = the cells above the Button: each Box's marginLeft (a row's indent) and the `left` of each absolute Box (the overlay column, the title's own Box)
  const walk = (n: any, left: number) => {
    if (n?.type === 'Button' && key.test(String(n.props?.key ?? ''))) out.push({ b: n, left })
    const l = n?.type === 'Box' ? left + Number(n.props?.marginLeft ?? 0) + (n.props?.position === 'absolute' ? Number(n.props?.left ?? 0) : 0) : left
    for (const c of kids(n)) walk(c, l)
  }
  walk(card, 0)
  return out
}
/** #983: the runs card = the first card of the tab «POB» (Agents and Merge are read on «Главная» before it) */
const runsOf = async (ui: any) => { await ui.press({ key: 'tab-pob' }); return (await ui.drawn()).children[2].children[0] }
test("#837 u9: #N x of Agents = Merge = the baseline's, a waiting PoB runs title drawn as Merge's",{ timeoutMs: 60_000 }, async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: fixture() }, 123)
  const cards = (await (ui as any).drawn()).children[2].children
  const runsCard = await runsOf(ui)
  const [a, m, r] = [tickX(cards[0]), tickX(cards[1]), tickX(runsCard)]
  console.log(`TICKX agents ${a} merge ${m} runs ${r}`)
  expect(a).toBeTruthy()
  expect(m).toBe(a)
  // the baseline's native Link stood one cell (7.8 px) right of the column x (352): 359.8; PoB runs' own tick x (166) is NOT asserted: see the #837 u9 report
  expect(Math.abs(a! - (352 + 7.8)) < 0.05).toBe(true)
  const q = titleBoxes(runsCard, /^run-q-/)[0]
  const w = nameToken(cards[1], /waits/)
  console.log(`WAIT runs ${JSON.stringify(q?.b?.props)} merge ${JSON.stringify(w)}`)
  expect(q, 'a waiting runs row (the blank Button over the title)').toBeTruthy()
  expect(w, 'a waiting merge row').toBeTruthy()
  // #972: the waiting PoB runs title is drawn in the picture (class bt, 14 px) in the dim #c3c2b7 (tokens.ts titleDim; `dim: j.id !== shownId`), at x 38 as Merge's title; the Button over it is blank
  const qt = nameToken(runsCard, /P1-#817-9 queued/)
  console.log(`WAIT runs picture ${JSON.stringify(qt)}`)
  expect(qt, 'the waiting runs title is drawn in the picture').toBeTruthy()
  expect({ cls: qt!.cls, fill: qt!.fill, x: qt!.x }).toEqual({ cls: 'bt', fill: '#c3c2b7', x: 38 })
  expect(String(q!.b.props.label).replace(/\s/g, ''), 'the press over the title is blank').toBe('')
  expect(w!.x, 'the title x of Merge = the runs title x').toBe(qt!.x)
  expect({ cls: w!.cls, fill: w!.fill }).toEqual({ cls: 'tx', fill: null })
  await ui.unmount()
})

// #837 unit 11, autopilot comparison 00:08Z: the PoB runs card equals the baseline 50ea5412 in its title x, its title weight and colour, and its grid.
const rowsOf = (card: any, alt: RegExp) => {
  const out: { src: string; alt: string }[] = []
  for (const p of pics(card)) for (const r of cutRows(p.props.alt, dq(String(p.props.source)))) if (alt.test(String(r.alt ?? ''))) out.push({ src: r.src, alt: String(r.alt) })
  return out
}
const twoRunning = () => {
  const d = JSON.parse(fixture())
  d.runs.running.push({ ...d.runs.running[0], id: 'j-r2', tag: 'P1-#818-3', issue: 818, name: 'Second running run' })
  return JSON.stringify(d)
}
test('#837 unit 11 (1, 2): PoB runs titles stand on the column x 38 (#837 b9b B3: were 6 px right, baseline x 44), the not shown ones normal weight in the dim 195,194,183, the shown one 240,239,236', { timeoutMs: 60_000 }, async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: twoRunning() }, 123)
  const runsCard = await runsOf(ui)
  // #972: a run title is a picture text of class `bt` (14 px, one weight) at markup x 38 (the head «задача»'s x); the blank Button over it keeps the old key
  const title = (alt: RegExp) => rowsOf(runsCard, alt).map(r => texts(r.src).find(t => /class="bt"/.test(t.attrs))).filter(Boolean).map(t => ({ t: t!.t, x: t!.x, fill: /fill:(#[0-9a-fA-F]+)/.exec(t!.attrs)?.[1] }))
  const run = title(/ running/), waiting = title(/ queued/)
  console.log(`TITLE run ${JSON.stringify(run)} waiting ${JSON.stringify(waiting)}`)
  expect(run.length).toBeGreaterThanOrEqual(2)
  expect(waiting.length, 'a waiting run title').toBeGreaterThanOrEqual(1)
  for (const t of [...run, ...waiting]) expect(t.x, `the title «${t.t}» stands on the column x 38`).toBe(38)
  // shown = bright (#f0efec = tokens.ts titleText, 240,239,236), the others and the waiting one dim (#c3c2b7 = titleDim, 195,194,183)
  expect(run.filter(x => x.fill === '#f0efec').length, 'one shown run title, bright').toBe(1)
  expect(run.filter(x => x.fill === '#c3c2b7').length, 'the not shown run titles are dim').toBe(run.length - 1)
  expect(waiting.map(x => x.fill), 'the waiting titles are dim').toEqual(waiting.map(() => '#c3c2b7'))
  // the Buttons over the titles are blank
  for (const b of [...titleBoxes(runsCard, /^run-pick-/), ...titleBoxes(runsCard, /^run-q-/)]) expect(String(b.b.props.label).replace(/\s/g, ''), `the press ${b.b.props.key} is blank`).toBe('')
  await ui.unmount()
})
test('#837 unit 11 (3): the PoB runs status stands at x 622 as in the Merge card, the builds column is 552..618, the Готово meta cut to its 120 px', { timeoutMs: 60_000 }, async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: fixture() }, 123)
  const cards = (await (ui as any).drawn()).children[2].children
  const runsCard = await runsOf(ui)
  const actX = (card: any, alt: RegExp) => {
    const r = rowsOf(card, alt)[0]
    return r ? texts(r.src).filter(t => t.x > 600 && t.x < 700).map(t => t.x) : []
  }
  const runs = actX(runsCard, / queued,/), merge = actX(cards[1], /waits/)
  console.log(`ACTX runs ${JSON.stringify(runs)} merge ${JSON.stringify(merge)}`)
  expect(runs.length).toBeGreaterThan(0)
  expect(runs[0]).toBe(merge[0])
  const done = rowsOf(runsCard, / (done|failed|stopped|cancelled),/)
  expect(done.length).toBeGreaterThan(0)
  for (const r of done) for (const t of texts(r.src)) if (t.x > 428 && t.x < 552 && /^[0-9][0-9][.]/.test(t.t)) expect(t.x + textWidth(t.t) - (t.t.match(/\d/g)?.length ?? 0) * 0.09 * 12).toBeLessThanOrEqual(428 + 120 + 1) // #837 b9b B2: the date's digits are drawn 0.55 em, the shared measure counts 0.64
  await ui.unmount()
})
