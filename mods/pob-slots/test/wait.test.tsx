import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen } from './kit'

// #706: a queued PoB run says what the daemon really waits for (`wait.text`, collect.py copies the daemon's `waits`),
// #837 pass 2 withdrew «привязан к ...» and the rest: see the tests below.
const withWaits = (lapFree: number) => {
  const f = JSON.parse(FAST)
  const [a, b] = f.runs.queued
  a.wait = { kind: 'ram', text: 'RAM: свободно 4.4 из 8 GB' }; a.host_fixed = true; a.takes_h = '36 min'
  b.wait = { kind: 'after', text: 'ждёт конца P1-#553-8' }; b.takes_h = '12 min'
  f.runs.queued.push({ ...b, id: 'j-plain', tag: 'P2-#1-1', issue: 1, wait: undefined, start_h: '14 min', start_s: 840 })
  f.laptop = { runs: { ...f.runs, running: [], queued: [], daemon: { host: 'laptop', age_s: 3, slots_total: 6, slots_in_use: 6 - lapFree, reserved: 0, reserved_until: null } } }
  return JSON.stringify(f)
}

// #837 pass 2 (owner 11.10, point 6): the yellow reason says what the job waits for and how long; nothing else.
for (const surface of ['terminal', 'desktop'] as const) {
  test(`${surface}: queued rows print only what they wait for and how long`, async ($, on) => {
    const all = (await seen(await mountPane($, on, surface, { tab: 'pob', fast: withWaits(4) }, 160))).join(' | ')
    for (const need of ['ждёт RAM', 'ждёт конца #553', 'ждёт слот · ~14 мин'])
      if (!all.includes(need)) throw new Error(`missing «${need}» in ${all}`)
    console.log(`${surface} queued reasons: ` + all.split(' | ').filter(w => /^ждёт (RAM|конца|слот)/.test(w)).map(w => `«${w}»`).join(' '))
  })
  for (const free of [4, 0]) test(`${surface}: no «привязан», «свободно», «займёт» in a queued row (Laptop free slots ${free})`, async ($, on) => {
    const all = (await seen(await mountPane($, on, surface, { tab: 'pob', fast: withWaits(free) }, 160))).join(' | ')
    for (const bad of ['привязан', 'свободно', 'займёт'])
      if (all.includes(bad)) throw new Error(`«${bad}» drawn (Laptop free ${free}): ` + all)
  })
}

// #683 r5 pt 2: a History row of a run with builds says how many, so the owner sees which rows have squares.
test('desktop: a History row with builds carries its count', async ($, on) => {
  const f = JSON.parse(FAST)
  const base = { ...f.runs.queued[0], state: 'done', dur: '55 min', date: '10.10', start: '00:46' }
  f.runs.history = [{ ...base, id: 'h1', tag: 'P1-#553-8', issue: 553, rows_done: 6, rows_total: 6 },
    { ...base, id: 'h2', tag: 'P1-#620-2', issue: 620 },
    { ...base, id: 'h3', tag: 'P1-#632-6', issue: 632, rows_done: 1, rows_total: 1 }]
  const all = (await seen(await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 160))).join(' | ')
  if (!all.includes('6 / 6 билдов')) throw new Error('no build count: ' + all)
  if (all.includes('готово · 0')) throw new Error('a count on a run without builds')
  // the noun agrees with the total: 1 / 1 билд (owner's screenshot 10.10 01:37 read «1 / 1 билдов»)
  if (!all.includes('1 / 1 билд') || all.includes('1 / 1 билдов')) throw new Error('plural: ' + all)
})
