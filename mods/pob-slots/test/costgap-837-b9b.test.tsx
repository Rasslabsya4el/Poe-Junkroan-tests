import { test, expect } from 'claude-code/testing'
import { dq } from './kit'
import { allPics, readPic, mountTab, type Payload } from './pics-837-b9b'
import { COST_SLOW_20261011, COST_TICKETS_20261011 } from './cost-live-20261011'

// #837 round 9b (B9): the gap between a card's title and what follows differed by card on the Расходы tab (live: 6, 16 or 33 px). Two things follow a title: the table's head row under it (vertical) and, in a card with a sub
// («2 сессии · всего $2.57», «$0.01 из $6.63»), the muted sub right of it (horizontal). Wanted: one value of each in every card, in every period. The vertical one is read from the pictures (title baseline to the head row's
// baseline, screen px); the horizontal one is the sub's dx from the title's end: it must be a tspan that FOLLOWS the title in the same text (the host lays it out at the title's real width), never a separate text at an x
// estimated from a font table (textWidth is off by -7 .. +21 px against the real face: that was the 6 / 16 / 33).
const COST: Payload = { fast: '{}', tickets: COST_TICKETS_20261011, slow: COST_SLOW_20261011 }
const TITLE_Y = /<text x="[\d.]+" y="([\d.]+)" class="ti">/
// #972: the twelve cards stand in three groups behind a second switch: the three groups of a period are read one after another, their cards compared together
for (const period of ['day', 'week', 'month']) {
  test(`#837 b9b B9: costs ${period}: the same gap under and after the title in every card`, { timeoutMs: 60_000 }, async ($, on) => {
    const trees: any[] = []
    const { ui } = await mountTab($, on, COST, 'cost', 123, async (ui, clock) => {
      await ui.press({ key: `cost-${period}` }); await clock.settle()
      for (const group of ['roles', 'spawn', 'days']) { await ui.press({ key: `costg-${group}` }); await clock.settle(); trees.push(await ui.drawn()) }
    })
    const vert = new Map<string, number>(), horiz = new Map<string, number | string>()
    for (const tree of trees) {
    const pics = allPics(tree)
    for (let i = 0; i < pics.length - 1; i++) {
      const src = dq(String(pics[i].props.source))
      const ty = TITLE_Y.exec(src)
      if (!ty) continue
      const head = readPic(pics[i], 123), table = readPic(pics[i + 1], 123)
      const title = String(pics[i].props.alt).split(' · ')[0]!
      const cols = table.items.filter(it => it.head)
      expect(cols.length, `${title}: the table under the title has a head row`).toBeGreaterThan(0)
      vert.set(title, +(((head.H - +ty[1]!) * head.fit) + Math.min(...cols.map(c => c.y)) * table.fit).toFixed(1))
      const sub = /<text x="[\d.]+" y="17" class="su">/.test(src) ? 'separate text at an estimated x'
        : /class="ti">[^<]*<tspan[^>]*class="su"[^>]*>/.test(src) ? +(/<tspan[^>]*dx="([\d.]+)"[^>]*class="su"|<tspan[^>]*class="su"[^>]*dx="([\d.]+)"/.exec(src)?.slice(1).find(Boolean) ?? NaN) : null
      if (sub != null) horiz.set(title, sub)
    }
    }
    console.log(`B9 ${period}: ${vert.size} cards; title baseline -> head row ${JSON.stringify([...new Set(vert.values())])}; ${horiz.size} subs, title -> sub ${JSON.stringify([...new Set(horiz.values())])}`)
    expect(vert.size, 'the tab draws its cards').toBeGreaterThanOrEqual(8)
    expect([...vert].filter(([, v]) => v !== vert.get('По ролям')), 'every card has the «По ролям» card\'s vertical gap').toEqual([])
    expect(horiz.size, 'cards with a sub').toBeGreaterThanOrEqual(3)
    expect([...new Set(horiz.values())].length, `one title -> sub gap in every card: ${JSON.stringify([...horiz])}`).toBe(1)
    expect([...horiz.values()][0], 'the sub follows the title in the same text, 12 px (dx) after its end').toBe(12)
    const size = Math.max(...trees.map(t => JSON.stringify(t).length))
    console.log(`B9 ${period}: tab state ${size} chars`)
    expect(size, 'the tab state stays under the size guard').toBeLessThan(90_000)
    await ui.unmount()
  })
}
