import { test, expect } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen, shown, isHiddenBox, rowLight, blankPx } from './kit'

// #995 send-back 2 (the pane pass of 14.10 10:3x on the installed 06444d74).
const runs = (n: number, running: any[] = []) => {
  const f = JSON.parse(FAST)
  const base = { ...f.runs.queued[0], state: 'done', host: 'pc', priority: 'P1', workers: 1, what: 'tests', kind_name: 'прогон тестов' }
  f.runs.running = running; f.runs.queued = []
  f.runs.history = Array.from({ length: n }, (_x, i) => ({ ...base, id: `j-20261014-01${String(i).padStart(2, '0')}-aaaa`, tag: `P1-#${900 + i}`, issue: 900 + i, date: '14.10', start: `01:${String(i).padStart(2, '0')}`, dur: '3 min' }))
  return { f, base }
}
const keyed = (tree: any, key: string): { n: any; parent: any }[] => {
  const out: { n: any; parent: any }[] = []
  const walk = (n: any, parent: any) => { if (!n || typeof n !== 'object') return; if (n.type === 'Button' && n.props?.key === key) out.push({ n, parent }); for (const c of n.children ?? []) walk(c, n) }
  walk(tree, null)
  return out
}

// row 1: the running P2-core row said «нет связи с ноутом,...»: the column «начало» narrowed «статус» on every row. A running row draws no «начало», so its status
// keeps the pane's width and reads whole, while the finished rows keep their «начало».
test('desktop: a running row with no «начало» draws its whole status «нет связи с ноутом, данные от 10:30»; finished rows keep «начало»', async ($, on) => {
  const { f, base } = runs(3)
  f.runs.running = [{ ...base, id: 'j-20261014-0030-core', tag: 'P2-core', issue: null, priority: 'P2', host: 'laptop', state: 'running', what: 'benchmark', kind_name: 'недельный прогон', stale: true, stale_since: '10:30', start: '00:30', dur: '10 h 0 min', age: '10 h 0 min' }]
  const words = await seen(await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 123))
  const all = words.join(' | ')
  console.log('#995 sb2 row 1: ' + words.filter(w => /нет связи|начало|14\.10 01:0/.test(w)).map(w => `«${w}»`).join(' '))
  if (!words.some(w => w.includes('нет связи с ноутом, данные от 10:30'))) throw new Error('the status is cut: ' + all)
  if (!words.some(w => w.trim() === 'начало')) throw new Error('no head «начало»: ' + all)
  if (!words.some(w => w.trim() === '14.10 01:00')) throw new Error('a finished row lost its «начало»: ' + all)
})

// row 2: a press that turned «Готово» to its last page unmounted its own Button, and on the pane the press after it was lost (1 in 2, measured). The dim end keeps its
// Button, under the same key, in a 0 x 0 clipped Box with no action: nothing is drawn there and the page does not move on a press of it.
test('desktop: a pager press that reaches the end keeps its Button mounted (hidden, no action); the next press turns the page back', async ($, on) => {
  const { f } = runs(8)
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 123)
  const t0 = await ui.drawn()
  expect(keyed(t0, 'hist-prev').length, 'page 1: hist-prev is mounted').toBe(1)
  expect(isHiddenBox(keyed(t0, 'hist-prev')[0]!.parent), 'page 1: hist-prev stands in the hidden Box').toBe(true)
  expect(keyed(shown(t0), 'hist-prev').length, 'page 1: hist-prev is not shown').toBe(0)
  await ui.press({ key: 'hist-next' })
  const t1 = await ui.drawn()
  const next = keyed(t1, 'hist-next')
  expect(next.length, 'last page: hist-next is still mounted').toBe(1)
  expect(isHiddenBox(next[0]!.parent), 'last page: hist-next stands in the hidden Box').toBe(true)
  expect(keyed(shown(t1), 'hist-prev').length, 'last page: hist-prev is shown').toBe(1)
  const w1 = (await seen(ui)).join(' | ')
  await ui.press({ key: 'hist-next' }) // the dim end: no action
  expect((await seen(ui)).join(' | '), 'a press of the dim end moves nothing').toBe(w1)
  await ui.press({ key: 'hist-prev' })
  const w2 = (await seen(ui)).join(' | ')
  if (!/1–6 из 8/.test(w2)) throw new Error('hist-prev did not turn back to page 1: ' + w2)
  console.log('#995 sb2 row 2: last page ' + (/7–8 из 8/.test(w1) ? '7–8 из 8' : '?') + ', back to 1–6 из 8; hist-next hidden on the last page, hist-prev hidden on the first')
  await ui.unmount()
})

// row 3 (a hovered row showed two lights: the row's reveal and the title Button's own host light over its title): ONE light, the host's rectangle. A row that presses has its Button over
// the whole pill; no row of any tab draws a light of its own (no reveal over a card row, no band over a table row).
test('desktop: one light: a finished run press Button spans its row, a failed one alike; no row draws a light of its own on any tab', { timeoutMs: 120_000 }, async ($, on) => {
  const { f, base } = runs(3)
  f.runs.history.push({ ...base, id: 'j-20261014-0200-fail', tag: 'P1-#967', issue: 967, state: 'failed', date: '14.10', start: '02:00', dur: '3 min' })
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 123)
  const lights: string[] = []
  const widths: Record<string, number> = {}
  const walk = (n: any, tab: string) => {
    if (!n || typeof n !== 'object') return
    if (n.type === 'Box' && rowLight(n)) lights.push(`${tab}:${n.props?.key}`)
    if (n.type === 'Box' && n.props?.display === 'none' && n.hover?.display === 'flex' && (n.children ?? []).some((c: any) => c?.type === 'Svg' && c.props?.alt === 'row')) lights.push(`${tab}:light`)
    if (n.type === 'Button' && /^run-hist-/.test(String(n.props?.key))) widths[String(n.props.key)] = blankPx(n.props.label) ?? -1
    for (const c of n.children ?? []) walk(c, tab)
  }
  walk(await ui.drawn(), 'pob')
  const ws = Object.values(widths)
  console.log(`#995 sb2 row 3: run row Buttons ${ws.length}, widths ${ws.map(w => Math.round(w)).join(', ')} px`)
  expect(ws.length, 'the finished runs (3 done, 1 failed) each have a row Button').toBe(4)
  // the pill of a 123-column card is ~900 screen px wide; a title's face was ~300-340 px
  for (const [k, w] of Object.entries(widths)) if (w < 800) throw new Error(`${k}: its Button is ${w} px wide, not the row's pill`)
  for (const tab of ['main', 'tickets', 'cost', 'progress', 'builds']) { await ui.press({ key: `tab-${tab}` }); walk(await ui.drawn(), tab) }
  expect(lights, 'row lights of their own').toEqual([])
  await ui.unmount()
})
