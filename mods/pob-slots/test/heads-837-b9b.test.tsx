import { test, expect } from 'claude-code/testing'
import { allPics, readPic, mountTab, type Payload } from './pics-837-b9b'
import { LIVE_FAST } from './fast-live'
import { LIVE as TODAY } from './tickets-live-20261011'
import { COST_SLOW_20261011, COST_TICKETS_20261011 } from './cost-live-20261011'

// #837 round 9b (B1): two column heads read as one phrase in the real pane («контекст делает», «билды статус»: 4 px apart). Wanted: at least 12 screen px between any two neighbouring heads of every card and
// table of every tab, and 6 px between a cell's text and the next cell's icon («115k» touched the activity icon). Read from the pictures the pane draws, at the pane's real width (123 columns).
const LIVE: Payload = { fast: LIVE_FAST, tickets: TODAY }
const COST: Payload = { fast: '{}', tickets: COST_TICKETS_20261011, slow: COST_SLOW_20261011 }
const SCENES: { name: string; p: Payload; tab: string | null; then?: string[] }[] = [
  { name: 'main (fixture)', p: {}, tab: null },
  { name: 'main (live)', p: LIVE, tab: null },
  { name: 'builds (fixture)', p: {}, tab: 'builds' },
  { name: 'builds (live)', p: LIVE, tab: 'builds' },
  { name: 'tickets (fixture)', p: {}, tab: 'tickets' },
  { name: 'tickets (live)', p: LIVE, tab: 'tickets' },
  { name: 'progress (fixture)', p: {}, tab: 'progress' },
  { name: 'progress (live)', p: LIVE, tab: 'progress' },
  { name: 'costs week (fixture)', p: {}, tab: 'cost', then: ['cost-week'] },
  { name: 'costs day (live)', p: COST, tab: 'cost', then: ['cost-day'] },
  { name: 'costs week (live)', p: COST, tab: 'cost', then: ['cost-week'] },
  { name: 'costs month (live)', p: COST, tab: 'cost', then: ['cost-month'] },
]
const MIN_HEAD_GAP = 12, MIN_ICON_GAP = 6

for (const s of SCENES) {
  test(`#837 b9b B1: ${s.name}: every neighbouring column heads >= ${MIN_HEAD_GAP} px apart, a cell's text >= ${MIN_ICON_GAP} px before the next cell's icon`, { timeoutMs: 60_000 }, async ($, on) => {
    const { ui } = await mountTab($, on, s.p, s.tab, 123, async (ui, clock) => { for (const k of s.then ?? []) { await ui.press({ key: k }); await clock.settle() } })
    const tree: any = await (ui as any).drawn()
    const bad: string[] = []
    let heads = 0, pairs = 0
    for (const n of allPics(tree)) {
      const { items } = readPic(n, 123)
      // heads: the head words of one line (a row of a card picture, a table's first line, the machine card's third line)
      const lines = new Map<number, typeof items>()
      for (const it of items) if (it.head) lines.set(it.y, [...(lines.get(it.y) ?? []), it])
      for (const [y, hs] of lines) {
        hs.sort((a, b) => a.x0 - b.x0)
        heads += hs.length
        for (let i = 1; i < hs.length; i++) {
          const gap = hs[i]!.x0 - hs[i - 1]!.x1
          if (gap < MIN_HEAD_GAP) bad.push(`head «${hs[i - 1]!.t}» «${hs[i]!.t}» at y ${y}: ${gap.toFixed(1)} px`)
        }
      }
      // a text and the icon of the NEXT cell on one line: the nearest text that ends left of the icon, on the icon's line (centres within 5 px)
      for (const ic of items.filter(i => i.kind === 'icon')) {
        const left = items.filter(i => i.kind === 'text' && !i.head && i.x1 <= ic.x0 + 1 && Math.abs(i.y - 4.5 - ic.y) <= 5)
        if (!left.length) continue
        const a = left.reduce((p, q) => (q.x1 > p.x1 ? q : p))
        pairs++
        if (ic.x0 - a.x1 < MIN_ICON_GAP) bad.push(`text «${a.t}» -> icon at ${ic.x0.toFixed(1)}: ${(ic.x0 - a.x1).toFixed(1)} px`)
      }
    }
    console.log(`B1 ${s.name}: ${heads} head words, ${pairs} text-icon pairs, ${bad.length} too close${bad.length ? ': ' + bad.slice(0, 12).join(' | ') : ''}`)
    expect(heads, 'the scene draws column heads').toBeGreaterThan(0)
    expect(bad, 'heads or text-icon pairs closer than wanted').toEqual([])
    await ui.unmount()
  })
}
