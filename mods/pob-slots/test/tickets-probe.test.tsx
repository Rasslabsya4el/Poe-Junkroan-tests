import { test, mock } from 'claude-code/testing'
// #671 row 1: probe (prints sizes, asserts nothing). Today's list: shared-tickets.json of 2026-10-11 08:00.
import { FAST, SLOW, ORCH } from './fixtures'
import { LIVE } from './tickets-live-20261011'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const OUT: Record<string, string> = { fast: FAST, tickets: LIVE, slow: SLOW, orch: ORCH }
const tk = JSON.parse(LIVE)
const issues: any[] = Object.values(tk.issues)
const big = issues.filter(i => i.kids.length > 0).sort((a, b) => b.kids.length - a.kids.length)
const parents = big.map(i => i.n)

test('probe: tickets tab sizes at 123 columns', { timeoutMs: 60_000 }, async ($, on) => {
  const clock = mock.clock(on)
  on('process.run', async (_$, e) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-tickets' }); await clock.settle()
  const measure = async (label: string) => {
    const d = JSON.stringify(await ui.drawn())
    const rows = (d.match(/hv-tk-\d+/g) ?? []).length
    const hid = [...d.matchAll(/не показан[а-я]* ещё (\d+)/g)].map(x => Number(x[1]))
    const hidden = hid.reduce((a, b) => a + b, 0)
    const segs = d.split('{"type":"Box","props":{"key":"hv-tk-').slice(1).map(x => x.length)
    const body = segs.slice(0, -1) // the last segment carries the rest of the tab
    console.log(`PR ${label}: size=${d.length} rows=${rows} hidden=${hid.join('+') || 0} hv-box chars/row mean=${body.length ? Math.round(body.reduce((a, b) => a + b, 0) / body.length) : 0} max=${Math.max(0, ...body)}`)
    return { size: d.length, rows, hidden }
  }
  // every row reachable from goals/loose when the given parents are open (what the tab would draw with no cap)
  const total = (openSet: Set<number>) => {
    const walk = (n: number): number => 1 + (openSet.has(n) ? (tk.issues[String(n)].kids as number[]).reduce((a, k) => a + (tk.issues[String(k)] ? walk(k) : 0), 0) : 0)
    return [...tk.goals, ...tk.loose].reduce((a: number, n: number) => a + (tk.issues[String(n)] ? walk(n) : 0), 0)
  }
  console.log(`PR issues=${issues.length} parents=${parents.length} top3=${big.slice(0, 3).map(i => `#${i.n}:${i.kids.length}`).join(' ')}`)
  const a = await measure('(a) nothing open, with cap')
  const per: number[] = []
  for (const i of big.slice(0, 3)) {
    await ui.press({ key: `tg-${i.n}` }); await clock.settle()
    const m = await measure(`(b) #${i.n} (${i.kids.length} children) open, with cap`)
    const tot = total(new Set([i.n]))
    const pr = (m.size - a.size) / (m.rows - a.rows)
    console.log(`PR   computed no cap: rows=${tot} (drawn ${m.rows} + hidden ${m.hidden}), chars/row (delta) ${Math.round(pr)}, size ~ ${Math.round(m.size + (tot - m.rows) * pr)}`)
    await ui.press({ key: `tg-${i.n}` }); await clock.settle()
  }
  // every parent open: a parent hidden by the cap has no button, so pass until nothing new opens
  const opened = new Set<number>()
  for (let pass = 0; pass < 6; pass++) {
    let n0 = opened.size
    for (const n of parents) { if (opened.has(n)) continue; try { await ui.press({ key: `tg-${n}` }); opened.add(n) } catch {} }
    await clock.settle()
    if (opened.size === n0) break
  }
  const c = await measure(`(c) every parent open (${opened.size} of ${parents.length} reachable), with cap`)
  const totC = total(new Set(parents))
  const prC = (c.size - a.size) / (c.rows - a.rows)
  console.log(`PR   computed no cap: rows=${totC} (drawn ${c.rows} + hidden ${c.hidden}), chars/row (delta) ${Math.round(prC)}, size ~ ${Math.round(c.size + (totC - c.rows) * prC)}`)
  await ui.unmount()
})
