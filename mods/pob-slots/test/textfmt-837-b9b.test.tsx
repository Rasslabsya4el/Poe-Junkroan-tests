import { test, expect } from 'claude-code/testing'
import { allPics, readPic, mountTab, type Payload } from './pics-837-b9b'
import { FAST } from './fixtures'
import { LIVE_FAST } from './fast-live'
import { LIVE as TODAY } from './tickets-live-20261011'
import { COST_SLOW_20261011, COST_TICKETS_20261011 } from './cost-live-20261011'
import { usd, limPct, thousands } from '../hooks/kit'
import { svgWords, dq } from './kit'

// #837 round 9b, unit 3: three text forms. B5: an unknown cell of an Agents row is the muted long dash of the Laptop card («—»), never an empty cell, «0» or «-».
// B7: money of 1000 and more is grouped with the very same space as the counts. B8: a percent is «number space sign» everywhere.
const chat = (name: string, o: any) => ({ sid: name, name, kind: 'chat', busy: false, issue: null, last: '', held: [], subagents: [], ...o })
const sub = (name: string, o: any) => ({ id: name, name, type: 'worker', issue: null, busy: true, digest: undefined, ...o })

test('#837 b9b B5: an unknown model, a context of 0 or none, a missing duration draw the muted long dash; real values stay', { timeoutMs: 60_000 }, async ($, on) => {
  const agents = [
    chat('autopilot #780', { model: '', ctx: 0, age: '-' }),
    chat('autopilot #781', { subagents: [sub('unit one', { model: '', ctx: 0 })] }), // no model, no ctx, no age at all
    chat('Brain: PoB', { model: 'Claude Opus 5.5', ctx: 12_400, age: '5 min' }),
  ]
  const { ui } = await mountTab($, on, { fast: JSON.stringify({ ...JSON.parse(FAST), agents }) }, null)
  const tree: any = await (ui as any).drawn()
  let rows = 0
  const seen: Record<string, any[]> = {}
  for (const n of allPics(tree)) {
    const { items } = readPic(n, 123)
    const nm = (t: string) => items.find(i => i.kind === 'text' && i.t === t)
    for (const name of ['autopilot #780', 'autopilot #781', 'unit one', 'Brain: PoB']) {
      const a = nm(name)
      if (a) seen[name] = items.filter(i => i.kind === 'text' && i.row === a.row && i.y === a.y)
    }
  }
  for (const name of ['autopilot #780', 'autopilot #781', 'unit one']) {
    const row = seen[name]
    expect(row, `the row of ${name} is drawn`).toBeTruthy()
    const dashes = row!.filter(i => i.t === '—')
    console.log(`B5 ${name}: ${row!.map(i => `«${i.t}» ${i.cls}`).join(' | ')}`)
    expect(dashes.length, `${name}: three long dashes`).toBe(3)
    expect(dashes.every(d => /\bmu\b/.test(d.cls)), `${name}: the dashes are muted`).toBe(true)
    expect(row!.filter(i => i.t === '0' || i.t === '-'), `${name}: no «0» / «-» word`).toEqual([])
    rows++
  }
  const real = seen['Brain: PoB']!
  expect(real.map(i => i.t), 'a real context of 12 thousand and a real duration stay').toEqual(expect.arrayContaining(['Opus 5.5', '12k', '5 мин']))
  // aligned as the cell's values are: the model dash starts where the model word starts, the context and duration dashes end where theirs end
  const d = seen['autopilot #780']!.filter(i => i.t === '—').sort((a, b) => a.x0 - b.x0)
  expect(Math.abs(d[0]!.x0 - real.find(i => i.t === 'Opus 5.5')!.x0), 'model dash on the model column x').toBeLessThan(0.6)
  expect(Math.abs(d[1]!.x1 - real.find(i => i.t === '12k')!.x1), 'context dash ends on the context column end').toBeLessThan(0.6)
  expect(Math.abs(d[2]!.x1 - real.find(i => i.t === '5 мин')!.x1), 'duration dash ends on the duration column end').toBeLessThan(0.6)
  expect(rows).toBe(3)
  await ui.unmount()
})

const LIVE: Payload = { fast: LIVE_FAST, tickets: TODAY }
const COST: Payload = { fast: '{}', tickets: COST_TICKETS_20261011, slow: COST_SLOW_20261011 }
const SCENES: { name: string; p: Payload; tab: string | null; then?: string[] }[] = [
  { name: 'main (fixture)', p: {}, tab: null },
  { name: 'main (live)', p: LIVE, tab: null },
  { name: 'builds (fixture)', p: {}, tab: 'builds' },
  { name: 'builds (live)', p: LIVE, tab: 'builds' },
  { name: 'tickets (live)', p: LIVE, tab: 'tickets' },
  { name: 'progress (live)', p: LIVE, tab: 'progress' },
  { name: 'costs day', p: COST, tab: 'cost', then: ['cost-day'] },
  { name: 'costs week', p: COST, tab: 'cost', then: ['cost-week'] },
  { name: 'costs month', p: COST, tab: 'cost', then: ['cost-month'] },
]
const wordsOf = async (ui: any) => {
  const out: string[] = []
  const walk = (n: any) => { if (n == null || typeof n !== 'object') return; if (n.type === 'Svg') { out.push(...svgWords(dq(String(n.props?.source ?? '')))); out.push(...String(n.props?.alt ?? '').split('\n')) } for (const c of n.children ?? []) walk(c) }
  walk(await ui.drawn())
  return out
}

test('#837 b9b B7: usd groups thousands with the counts\' own separator', () => {
  expect(usd(1736)).toBe(`$1${thousands(1000)[1]}736`)
  expect(usd(12345)).toBe('$12 345')
  expect(usd(8073.4)).toBe('$8 073')
  expect(usd(999.6)).toBe('$1 000')
  expect(usd(99.5)).toBe('$99.50') // cents rules unchanged
  expect(usd(5)).toBe('$5.00')
  expect(thousands(1736)).toBe('1 736')
})
test('#837 b9b B8: limPct and a percent: number, space, sign', () => {
  expect([limPct(412, 16.5), limPct(33, 16.5), limPct(3.3, 16.5), limPct(0.01, 16.5), limPct(0, 16.5)]).toEqual(['25 %', '2.0 %', '0.2 %', '<0.1 %', '0 %'])
})

for (const s of SCENES) {
  test(`#837 b9b B7+B8: ${s.name}: no bare money of 4+ digits, every percent after a digit has the space before the sign`, { timeoutMs: 60_000 }, async ($, on) => {
    const { ui } = await mountTab($, on, s.p, s.tab, 123, async (ui, clock) => { for (const k of s.then ?? []) { await ui.press({ key: k }); await clock.settle() } })
    const words = await wordsOf(ui)
    const bare = words.filter(w => /\$\d{4,}/.test(w))
    // a ticket's own title (GitHub's text, «30% increased Movement Speed») is not ours to rewrite
    const titles = Object.values(JSON.parse(s.p.tickets ?? '{"issues":{}}').issues ?? {}).map((i: any) => String(i.title)).filter(t => t.includes('%')).map(t => t.slice(0, 20))
    const glued = words.filter(w => /\d%/.test(w) && !titles.some(t => w.includes(t)) && !/Day-1 boots always roll 30%/.test(w))
    const money = words.filter(w => /\$\d{1,3}( \d{3})+/.test(w))
    const pcts = words.filter(w => /\d %/.test(w))
    console.log(`B7/B8 ${s.name}: money grouped ${money.length} (${money.slice(0, 4).join(', ')}), bare ${bare.length}; percents spaced ${pcts.length}, glued ${glued.length} (${glued.slice(0, 6).join(', ')})`)
    expect(bare, 'money of 1000 or more without the thousands split').toEqual([])
    expect(glued, 'a percent glued to its digit').toEqual([])
    if (s.tab === 'cost') expect(money.length + pcts.length, 'the costs tab draws grouped money or spaced percents').toBeGreaterThan(0)
    await ui.unmount()
  })
}

// B8: the «% лимита» column is end-aligned; the percent with its space is one space wider, the bar left of it keeps >= 12 screen px to the text (before: the grid's own gap)
for (const period of ['cost-day', 'cost-week', 'cost-month']) {
  test(`#837 b9b B8: ${period}: the share bar keeps >= 12 screen px to its «% лимита» text, nothing cut`, { timeoutMs: 60_000 }, async ($, on) => {
    const { ui } = await mountTab($, on, COST, 'cost', 123, async (ui, clock) => { await ui.press({ key: period }); await clock.settle() })
    const tree: any = await (ui as any).drawn()
    let pairs = 0, min = 1e9
    const bad: string[] = []
    for (const n of allPics(tree)) {
      const { items, fit } = readPic(n, 123)
      const body = dq(String(n.props.source)).replace(/<style>[\s\S]*?<\/style>/, '')
      const bars = [...body.matchAll(/M([\d.]+) ([\d.]+)h([\d.]+)/g)].map(m => ({ r: (+m[1]! + +m[3]!) * fit, y: +m[2]! }))
      for (const it of items) {
        if (it.kind !== 'text' || it.head || !/\d %$|^0 %$/.test(it.t)) continue
        const b = bars.filter(q => Math.abs(q.y + 4 - it.y) < 7 && q.r <= it.x0 + 1).sort((a, c) => c.r - a.r)[0]
        if (!b) continue
        pairs++
        min = Math.min(min, it.x0 - b.r)
        if (it.x0 - b.r < 12) bad.push(`«${it.t}» ${(it.x0 - b.r).toFixed(1)} px`)
      }
    }
    console.log(`B8 fit ${period}: ${pairs} bar/percent pairs, nearest ${min.toFixed(1)} px, too close ${bad.length}${bad.length ? ': ' + bad.slice(0, 6).join(' | ') : ''}`)
    expect(pairs, 'the tab draws bars with percents').toBeGreaterThan(0)
    expect(bad).toEqual([])
    await ui.unmount()
  })
}
