import { test, expect, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { PROPS, ghostPress, dq } from './kit'
import { CELL_PX } from '../hooks/kit'

// #837 round 9a (B4): opening a run's section moved every row above it 2 px down (r8/13_run1_jump_z.png: the card's title stays, the column heads, «Идёт»,
// «Готово» and the rows all sit 2 px lower). The card's rows are ONE picture; the host fits it to the slot (x 930 / 963 at 123 columns) and gives it whole 19-px lines:
// a picture whose height is not a whole number of lines on the screen sits in them off by half the slack, and the slack changes with every row the section adds.
// Wanted: the picture is a whole number of lines in every state (closed / a run with builds / a run with none), so its rows stand where they stood; the «Готово» rows
// (drawn y in the picture and the row's host Box top) are the same in all states.
// #837 b18: the runs card picture is stretched into its slot (preserveAspectRatio 'none', built with fit 1: hooks/kit.tsx rowsSvg, register.tsx rowsOne), so its y is NOT scaled with its x (the
// host's 0.9657 is for x only): the slot is the picture's own height H px and must be a whole number of CELL_PX lines itself (H / 19, not H x fit / 19). A run title is a host Button, the picture
// draws no title: the Готово row is found by its status word, and it stands in the picture at the px the row's host Box does (the Box's top = the heights above it).
const COLS = 123
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
const firstSvgH = (n: any): number => { let h = 0; walk(n, x => { if (!h && x.type === 'Svg') h = Number(x.props?.height) || 0 }); return h }

async function measure($: any, on: any, mode: 'closed' | 'empty' | 'builds') {
  const v = JSON.parse(FAST)
  v.runs.running = []
  const hist = v.runs.history ?? v.runs.recent ?? []
  v.runs.history = [{ ...hist[0], id: 'j-stop-1', tag: 'P2-core', issue: null, state: 'stopped', progress: undefined, what: 'benchmark', rows_done: 0, rows_total: mode === 'builds' ? 2 : 0 }, ...hist]
  const cells = mode === 'builds' ? [{ ref: 'a', name: 'A', seed: 1, state: 'done', took: '5 min' }, { ref: 'a', name: 'A', seed: 2, state: 'running' }] : []
  const OUT: Record<string, string> = { fast: JSON.stringify(v), tickets: TICKETS, slow: SLOW, orch: ORCH, cells: JSON.stringify({ progress: { done: 1, total: 2, total_open: false, eta: null, cells } }) }
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = ghostPress(true, await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(COLS) }))
  await ui.press({ key: 'tab-pob' }) // #983: the runs card lives on the tab «POB»
  if (mode !== 'closed') { await ui.press({ key: 'run-hist-j-stop-1' }); await clock.settle() }
  const tree: any = await (ui as any).drawn()
  let pic: any = null, col: any = null
  walk(tree, n => {
    if (n.type === 'Svg' && /Готово/.test(String(n.props?.alt ?? '')) && /P2-core/.test(String(n.props?.alt ?? ''))) pic = n
    if (n.type === 'Box' && n.props?.position === 'absolute' && (n.children ?? []).some((c: any) => /^hv-run/.test(String(c.props?.key ?? '')))) col = n
  })
  expect(pic, 'the run card picture').toBeTruthy()
  const src = dq(String(pic.props.source))
  const H = Number(/height="([\d.]+)"/.exec(src)![1])
  const stretched = /^<svg[^>]* preserveAspectRatio=['"]none['"]/.test(src)
  const rows = src.split('<g transform="translate(0 ').slice(1)
  const ys = (re: RegExp) => { const r = rows.find(x => re.test(x)); return r ? Number(/^([\d.]+)\)/.exec(r)![1]) : -1 }
  const lbY = ys(/class="lb">Готово/), runY = ys(/>benchmark · остановлен</)
  // the host Box top of the P2-core row: the heights of what comes before it in the absolute column
  let top = 0, at = -1
  ;(col?.children ?? []).forEach((c: any, k: number) => { if (at < 0) { if (/^hv-run/.test(String(c.props?.key ?? '')) && /P2-core|run-hist-j-stop-1/.test(JSON.stringify(c))) at = k; else top += firstSvgH(c) } })
  await ui.unmount()
  return { H, lines: H / CELL_PX, stretched, slot: Number(pic.props?.height), lbY, runY, top }
}

const got: Record<string, Awaited<ReturnType<typeof measure>>> = {}
test('#837 b9a B4: closed', async ($, on) => { got.closed = await measure($, on, 'closed') })
test('#837 b9a B4: a run with no builds opened', async ($, on) => { got.empty = await measure($, on, 'empty') })
test('#837 b9a B4: a run with builds opened', async ($, on) => { got.builds = await measure($, on, 'builds') })
test('#837 b9a B4: the run card picture is a whole number of lines in every state; the «Готово» rows stand where they stood', () => {
  const a = got.closed!, b = got.empty!, c = got.builds!
  for (const [n, m] of [['closed', a], ['run with no builds', b], ['run with builds', c]] as const) console.log(`${n}: picture ${m.H} px = ${m.lines.toFixed(3)} lines (stretched ${m.stretched}, Svg height prop ${m.slot}); «Готово» label y ${m.lbY}, row y ${m.runY}, host Box top ${m.top}`)
  for (const m of [a, b, c]) {
    expect(m.stretched, 'the picture stretches into its slot: its y is not scaled with its x').toBe(true)
    expect(Math.abs(m.lines - Math.round(m.lines)), 'whole lines').toBeLessThan(0.01)
    expect(m.slot, 'the slot the host gives the Svg is the height of its markup').toBe(m.H)
  }
  expect(a.lbY).toBeGreaterThan(0)
  expect(a.runY, 'the Готово row is drawn in the picture').toBeGreaterThan(a.lbY)
  for (const m of [a, b, c]) expect(m.runY, 'the row stands in the picture at its host Box top').toBe(m.top)
  expect(b.lbY, 'label y').toBe(a.lbY); expect(c.lbY, 'label y').toBe(a.lbY)
  expect(b.runY, 'row y').toBe(a.runY); expect(c.runY, 'row y').toBe(a.runY)
  expect(b.top, 'Box top').toBe(a.top); expect(c.top, 'Box top').toBe(a.top)
})
