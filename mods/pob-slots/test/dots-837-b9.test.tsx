import { test, expect, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH, BUILD } from './fixtures'
import { dq, ghostPress } from './kit'
import { rowsSvg } from '../hooks/kit'
import { K } from '../hooks/tokens'

// #837 b9 A7 (seen in the real pane, picture 32_build_open_z): the dots texture (a dither of small dots over a row's pill) marks ONLY a row that works now. An OPENED build on
// the Builds tab was drawn with the selection outline AND the dots, because its row carried the class colour and was not calm, and the kit takes "has a colour and is not calm" for
// "running". A build row is never working: opened = the outline only. A working row = the dots; a working selected row = both.
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const DIR = 'C:\repo\artifacts\benchmark\20261010-0422'
const row = (ref: string, seed: number, extra: any) => ({ run_dir: DIR, run_name: 'P1-#604-3', ref, seed, variant: '', pobbin_id: 'by4kos8YPJCx', author_pobbin_id: null,
  ratio_pct: null, metric: 'CombinedDPS', ours: null, author: null, life: null, stop: null, rank: null, audit: null, floors: null, note: '', added_at: '2026-10-10T08:16:46+00:00',
  name: '', var: '', class: null, asc: null, metric_label: 'Combined DPS', ours_h: '', errors: null, warnings: null, floors_bad: null, said: [], ...extra })
const ROWS = [
  row('cold_dot', 1, { author_pobbin_id: 'UNVUy73ibtBL', ratio_pct: 139, ours: 345112, ours_h: '345k', life: 5015, stop: 'converged', name: 'Cold Dot', class: 'Witch', asc: 'Elementalist' }),
  row('01 marauder_chieftain_imperial_staff', 2, { metric: 'TotalDotDPS', metric_label: 'Total DoT DPS', ours: 216282, ours_h: '216k', life: 4513, rank: 1, name: 'Volcanic Fissure', class: 'Marauder', asc: 'Chieftain', errors: 0, warnings: 0, floors_bad: false }),
]
const f = JSON.parse(FAST)
f.readings = { updated: '2026-10-10T08:16:47+00:00', rows: ROWS }

const dots = (src: string) => /<pattern/.test(src) && /fill="url\(#d/.test(src)
const outline = (src: string) => src.includes(`stroke="${K.accent}" stroke-opacity=".55"`)

test('#837 b9 A7: an opened build row on the Builds tab has the selection outline and NO dots; a build row at rest has neither', { timeoutMs: 60_000 }, async ($, on) => {
  const clock = mock.clock(on)
  const OUT: Record<string, string> = { fast: JSON.stringify(f), tickets: TICKETS, slow: SLOW, orch: ORCH, build: BUILD, openpob: JSON.stringify({ ok: true, link: 'pob://pobbin/x', where: 'pobb.in/x' }) }
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.read', async () => { throw new Error('ENOENT') })
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui: any = ghostPress(true, await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS }))
  await ui.press({ key: 'tab-builds' }); await clock.settle()
  const strips = async () => (await ui.findAll({ type: 'Svg' })).map((x: any) => x.props ?? x).filter((p: any) => / · Life [\d,]+/.test(String(p.alt))).map((p: any) => dq(String(p.source)))
  const rest = await strips()
  expect(rest.length).toBe(2)
  console.log(`A7 at rest: outline ${rest.map(outline)} dots ${rest.map(dots)}`)
  expect(rest.some(outline) || rest.some(dots), 'no row at rest has the outline or the dots').toBe(false)
  const key = (await ui.findAll({ type: 'Button' })).map((m: any) => String(m.key ?? '')).filter((k: string) => /^rd-pick-/.test(k))[1]!
  await ui.press({ key }); await clock.settle()
  const open = await strips()
  console.log(`A7 opened: outline ${open.map(outline)} dots ${open.map(dots)}`)
  expect(open.filter(outline).length, 'exactly the opened row has the outline').toBe(1)
  expect(open.some(dots), 'no dots on an opened build row').toBe(false)
  await ui.unmount()
})

// #994 (defect 8, the owner's ticket: «a speckle texture on the fill of busy rows: one flat fill»): no row has the dots any more; the outline is the selection's alone
test('#994: a working row (a live run) is one flat fill, no dots; a working selected row has the outline and no dots; a selected row at rest has the outline only', () => {
  const spec = (extra: any) => ({ r: { kind: 'strip' as const, state: 'active' as const, cells: { name: 'run' }, ...extra }, i: 0 })
  const draw = (extra: any) => dq(rowsSvg([spec(extra)], [{ key: 'name', x: 36, w: 400 }] as any, 600).svg)
  const working = draw({})
  const both = draw({ sel: true })
  const sel = draw({ sel: true, calm: true, color: '#aabbcc' })
  console.log(`A7 working: outline ${outline(working)} dots ${dots(working)}; working+sel: outline ${outline(both)} dots ${dots(both)}; sel at rest: outline ${outline(sel)} dots ${dots(sel)}`)
  expect(!dots(working) && !outline(working), 'working: no dots, no outline').toBe(true)
  expect(!dots(both) && outline(both), 'working + selected: the outline, no dots').toBe(true)
  expect(!dots(sel) && outline(sel), 'selected at rest: outline only').toBe(true)
})
