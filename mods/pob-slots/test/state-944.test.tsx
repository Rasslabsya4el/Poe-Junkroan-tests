import { test, expect, mock } from 'claude-code/testing'
import { PROPS, mountG, faceBase64 } from './kit'
import { SLOW, ORCH, TICKETS } from './fixtures'
import { LIVE_FAST } from './fast-live'
import { BUILD_816 } from './buildpanel-answer'
import { LIVE as TODAY } from './tickets-live-20261011'
import { LIVE_0811 } from './live-837-b17f'
import { MOD_DIR } from '../hooks/project'
import { PRESS_STAMP } from '../hooks/budget'

// #944 unit 2: the pane records its own state (hooks/staterec.ts) from the ui.render hook: one line of state.jsonl per state change (tab, row form, light cards, picked run, open build),
// the tree it drew in a ring file, the guard's own measure beside it. The fixtures are those of run-title-rows-937.test.tsx; `fs.write` is CAPTURED here, not dropped.
const DIR = `${MOD_DIR}/bin/.cache`
const STATE = `${DIR}/state.jsonl`
const LIMIT = 95_000, GUARD_STAMPS = 600 // #972: the guard is the host's 100,000 less 5,000
const REG_LEN = 1234, KIT_LEN = 567, VERSION = '9.9.9'
const FIELDS = ['t', 'session', 'entry', 'tab', 'picked', 'open', 'cards', 'guard', 'tree']

// the host hands paths back with backslashes
const norm = (p: unknown) => String(p).split('\\').join('/')

async function mount($: any, on: any, o: { payload?: string; tickets?: string; fail?: { on: boolean } } = {}) {
  const payload = o.payload ?? LIVE_FAST
  const fast = JSON.parse(payload)
  const job = fast.runs.running.find((j: any) => j.id === 'j-20261011-0430-e070') ?? fast.runs.running.find((j: any) => j.progress?.cells?.length)
  const clock = mock.clock(on)
  const cur = { fast: payload }
  const all = (): Record<string, string> => ({ fast: cur.fast, tickets: o.tickets ?? TICKETS, slow: SLOW, orch: ORCH })
  on('process.run', async (_$: any, e: any) => {
    if (e.argv[2] === 'build') return { value: { exitCode: 0, stdout: BUILD_816, stderr: '', isStdoutTruncated: false } } as any
    return { value: { exitCode: 0, stdout: all()[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  // the files: every write captured; the three files the build id is read from answer with a known text
  const files = new Map<string, string>([
    [`${MOD_DIR}/hooks/register.tsx`, 'r'.repeat(REG_LEN)], [`${MOD_DIR}/hooks/kit.tsx`, 'k'.repeat(KIT_LEN)],
    [`${MOD_DIR}/.claude-plugin/plugin.json`, JSON.stringify({ name: 'pob-slots', version: VERSION })],
  ])
  const writes: string[] = []
  on('fs.exists', async (_$: any, e: any) => { return { value: files.has(norm(e.path)) } as any })
  on('fs.read', async (_$: any, e: any) => {
    const m = /[\\/]asc[\\/](\w+)_16x16\.png$/.exec(String(e.path)) // the faces at their real size, as the 937 light-form case needs them
    if (m && e.as === 'bytes') return { value: { base64: faceBase64(m[1]!) } } as any
    if (files.has(norm(e.path))) return { value: files.get(norm(e.path)) } as any; throw new Error('ENOENT ' + e.path)
  })
  on('fs.write', async (_$: any, e: any) => {
    const p = norm(e.path)
    if (o.fail?.on && p.startsWith(DIR + '/state')) throw new Error('EACCES ' + p)
    writes.push(p); files.set(p, e.text); return { value: undefined } as any
  })
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await mountG($, { plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) })
  await ui.press({ key: 'tab-pob' }) // #983: the runs card lives on the tab «POB»
  await clock.settle()
  const lines = (): any[] => (files.get(STATE) ?? '').split('\n').filter(Boolean).map(l => JSON.parse(l))
  const press = async (key: string) => { await ui.press({ key }).catch(() => ui.press({ key, link: { href: 'https://a.invalid' } })); for (let i = 0; i < 8; i++) await clock.settle() }
  return { ui, clock, files, writes, lines, cur, job, press }
}

/** the runs card's form as the tree really took it (#972: one form): `hv-run<n>` keyed strip Boxes, and none of the old light `run-r<n>` row Boxes */
const form = (tree: unknown) => { const s = JSON.stringify(tree); return { light: s.match(/"key":"run-r\d+"/g)?.length ?? 0, mask: s.match(/"key":"hv-run\d+"/g)?.length ?? 0 } }
/** the host stamps `,"press":{"plugin":..,"handle":N}` on every element holding a handler (register.tsx GUARD_STAMPS); ui.drawn() carries them, the hook's own tree (what the guard measures and the state file holds) does not */
const STAMP = /,"press":\{"plugin":"[^"]*","handle":\d+\}/g
const bare = (tree: unknown) => JSON.stringify(tree).replace(STAMP, '')
/** the test's own measure of the drawn tree (the 937 test's): its host stamps are longer than the hook's own (`plugin` is "" in the hook's tree), so it is not the guard's number, within one GUARD_STAMPS of it */
const measureOf = (tree: unknown) => JSON.stringify(tree).length + GUARD_STAMPS
/** #972: every element with a press (a blank Button over each name / number now) carries a host stamp, so the sum of the stamps' extra length grew past one GUARD_STAMPS: the same measure with the host's plugin name written empty as the hook's own tree has it */
const measureHook = (tree: unknown) => { const j = JSON.stringify(tree); return j.replace(STAMP, '').length + (j.match(STAMP) ?? []).length * PRESS_STAMP } // #983: the budget's own measure of the drawn tree
/** the guard's own measure of the tree the hook returned = the length of the tree file the line names + 600 */
// #972: the guard counts the host's stamp per Button (30 characters each) plus 100, no longer one GUARD_STAMPS
// #983: the measure is the budget's own (hooks/budget.ts `sizeOf`): the tree with every stamp of an element with a handler counted as the host writes it, PRESS_STAMP characters
const fileMeasure = (files: Map<string, string>, line: any) => { const j = files.get(`${DIR}/state/${line.tree}`)!; return j.replace(STAMP, '').length + (j.match(STAMP) ?? []).length * PRESS_STAMP }
/** the file against the drawn tree, host stamps left out of both */
const sameTree = (files: Map<string, string>, line: any, drawn: unknown) => bare(JSON.parse(files.get(`${DIR}/state/${line.tree}`)!)) === bare(drawn)

test('#944 row 1+2: a pick is one state line (the one form: every card recorded as one), an open build is one more, its tree file is the drawn tree', { timeoutMs: 120_000 }, async ($, on) => {
  const { ui, files, lines, job, press } = await mount($, on)
  const before = lines().length
  await press(`run-pick-${job.id}`)
  const l1 = lines()
  expect(l1.length - before, 'one new line for the pick').toBe(1)
  const a = l1.at(-1)
  for (const k of FIELDS) expect(a, `field ${k}`).toHaveProperty(k)
  for (const k of ['measure', 'limit', 'forced', 'first_measure']) expect(a.guard, `guard.${k}`).toHaveProperty(k)
  expect(a.picked).toBe(job.id)
  expect(a.open).toBeNull()
  expect(a.tab).toBe('pob') // #972: the runs card lives on the tab «POB»
  expect(a.entry).toEqual({ register: REG_LEN, kit: KIT_LEN, version: VERSION })
  expect(a.guard.limit).toBe(LIMIT)
  expect(a.guard.forced).toBeNull()
  const t1: any = await ui.drawn()
  const f1 = form(t1)
  console.log(`#944 pick: lines ${before} -> ${l1.length}; runs card form in the tree: ${f1.mask} hv-run, ${f1.light} run-r; cards ${JSON.stringify(a.cards)}; guard ${JSON.stringify(a.guard)}; the test's own measure ${measureOf(t1)}`)
  expect(f1.mask, 'the picked state draws the runs card as keyed hv-run strip rows').toBeGreaterThan(0)
  expect(f1.light, 'no light run-r row Box').toBe(0)
  expect(a.cards, 'every card is recorded in the one form').toEqual({ grid: 'one', ag: 'one', mg: 'one', run: 'one' })
  expect(a.guard.first_measure, 'no card went light: first_measure = measure').toBe(a.guard.measure)
  expect(a.guard.measure, 'guard.measure = the returned tree file length + 30 a Button + 100').toBe(fileMeasure(files, a))
  console.log(`#944 pick: guard.measure ${a.guard.measure}, drawn with the plugin name emptied ${measureHook(t1)}, drawn as it is ${measureOf(t1)}`)
  expect(Math.abs(a.guard.measure - measureHook(t1)), 'within one GUARD_STAMPS of the own measure of ui.drawn() (the host plugin name emptied)').toBeLessThan(GUARD_STAMPS)
  expect(sameTree(files, a, t1), 'the tree file is the drawn tree (host stamps left out of both)').toBe(true)

  await press(`cell-${job.id}-stormbrand-1`)
  const l2 = lines()
  expect(l2.length - l1.length, 'one more line for the opened build').toBe(1)
  const b = l2.at(-1)
  expect(b.open, 'open = selectedAtom, the cell key of the build').toBe(`${job.id}|stormbrand|1`)
  expect(b.picked).toBe(job.id)
  const t2: any = await ui.drawn()
  const f2 = form(t2)
  console.log(`#944 open: lines ${l1.length} -> ${l2.length}; open ${b.open}; runs card: ${f2.mask} hv-run, ${f2.light} run-r; cards.run ${b.cards.run}; guard ${JSON.stringify(b.guard)}; tree file ${b.tree}`)
  expect(f2.light, 'no light run-r row Box').toBe(0)
  expect(b.cards).toEqual({ grid: 'one', ag: 'one', mg: 'one', run: 'one' })
  expect(b.guard.first_measure).toBe(b.guard.measure)
  expect(b.guard.measure).toBe(fileMeasure(files, b))
  expect(Math.abs(b.guard.measure - measureHook(t2))).toBeLessThan(GUARD_STAMPS)
  const text = files.get(`${DIR}/state/${b.tree}`)!
  expect(text, 'the tree file exists').toBeTruthy()
  // the comparison: JSON.stringify of the parsed file against JSON.stringify of ui.drawn() (the tree the hook returned, as the test host holds it)
  // the comparison: the parsed file and ui.drawn(), each as JSON with the host's `press` stamps left out (the hook's tree and the host's carry different handles and plugin text)
  expect(bare(JSON.parse(text))).toBe(bare(t2))
  await ui.unmount()
})

// the 937 fixtures: a run with live builds picked, 10 queued runs push the runs card to the light form (guard measure 81,212 in that test)
const scaleReal = (d: any, nq: number) => {
  const run = d.runs.running.find((j: any) => j.progress?.cells?.length)
  const cells: any[] = run.progress.cells
  const want: Record<string, number> = { running: 10, waiting: 12, done: 33, failed: 1 }
  const out: any[] = []
  for (const [st, n] of Object.entries(want)) {
    const base = cells.filter(c => c.state === st)
    for (let k = 0; k < n; k++) { const c = base[k % base.length]!; out.push(k < base.length ? c : { ...c, ref: `${c.ref}_x${k}`, name: `${c.name} ${k}` }) }
  }
  run.progress = { ...run.progress, cells: out, total: out.length, done: want.done! }
  const q = d.runs.queued[0]
  d.runs.queued = Array.from({ length: nq }, (_x, i) => i === 0 ? q : { ...q, id: `j-20261013-0900-q${String(i + 1).padStart(3, '0')}`, tag: `P2-core-${i + 4}`, name: `P2-core-${i + 4}` })
}
const heavy = (nq: number) => {
  const d = JSON.parse(LIVE_0811)
  const run = d.runs.running.find((j: any) => j.progress?.cells?.length)
  const { progress: _p, ...rest } = run
  d.runs.queued = [{ ...rest, id: 'j-20261013-0900-q001', tag: 'P2-core-4', state: 'queued', name: 'P2-core-4', wait: { kind: 'slots', text: 'ждёт слот' } }]
  scaleReal(d, nq)
  return JSON.stringify(d)
}

test('#944 row 3 (#983: no tree goes over the limit any more): the heaviest payload is recorded in the one form, its measure under the limit, the budget charged at or over it', { timeoutMs: 120_000 }, async ($, on) => {
  const { ui, files, lines, job, press } = await mount($, on, { payload: heavy(40), tickets: TODAY })
  await press(`run-pick-${job.id}`)
  const a = lines().at(-1)
  const t: any = await ui.drawn()
  const f = form(t)
  console.log(`#944 heavy (10 queued runs, 10 + 12 + 33 + 1 builds): runs card ${f.light} run-r, ${f.mask} hv-run; cards ${JSON.stringify(a.cards)}; guard ${JSON.stringify(a.guard)}; the test's own measure ${measureOf(t)}`)
  expect(f.light, 'no light run-r row Box (one form)').toBe(0)
  expect(f.mask, 'the runs card keeps its keyed hv-run strip rows').toBeGreaterThan(0)
  expect(a.cards, 'the over-the-limit tree is recorded in the one form as well').toEqual({ grid: 'one', ag: 'one', mg: 'one', run: 'one' })
  expect(a.guard.forced).toBeNull()
  expect(a.guard.measure, 'the budget keeps the heavy tree under the limit').toBeLessThanOrEqual(LIMIT)
  expect(a.budget.charged, 'the charge is at or over the measure').toBeGreaterThanOrEqual(a.guard.measure)
  expect(a.guard.first_measure, 'first_measure = measure').toBe(a.guard.measure)
  expect(a.guard.measure).toBe(fileMeasure(files, a))
  expect(Math.abs(a.guard.measure - measureOf(t))).toBeLessThan(2 * GUARD_STAMPS)
  await ui.unmount()
})

test('#944 row 4: ten redraws with nothing changed write no state line and no tree file', { timeoutMs: 120_000 }, async ($, on) => {
  const { ui, clock, files, writes, lines, cur, job, press } = await mount($, on)
  await press(`run-pick-${job.id}`)
  const nLines = lines().length
  const nTrees = writes.filter(p => p.startsWith(`${DIR}/state/`)).length
  const logLen = (files.get(`${DIR}/redraws.log`) ?? '').split('\n').filter(Boolean).length
  for (let i = 0; i < 10; i++) {
    cur.fast = JSON.stringify({ ...JSON.parse(LIVE_FAST), redraw_probe: i })
    await clock.advance(20_000); await clock.settle()
  }
  const logAfter = (files.get(`${DIR}/redraws.log`) ?? '').split('\n').filter(Boolean).length
  console.log(`#944 idle: redraws.log lines ${logLen} -> ${logAfter} (the redraws happened); state lines ${nLines} -> ${lines().length}; tree files written ${nTrees} -> ${writes.filter(p => p.startsWith(`${DIR}/state/`)).length}`)
  expect(logAfter - logLen, 'the ten payloads really redrew the pane').toBeGreaterThanOrEqual(5)
  expect(lines().length).toBe(nLines)
  expect(writes.filter(p => p.startsWith(`${DIR}/state/`)).length).toBe(nTrees)
  await ui.unmount()
})

test('#944 row 5 control: the picked state with the state writes working', { timeoutMs: 120_000 }, async ($, on) => {
  const m = await mount($, on)
  await m.press(`run-pick-${m.job.id}`)
  expect(bare(await m.ui.drawn()).length, 'the picked state is drawn').toBeGreaterThan(10_000)
  expect(m.lines().length, 'the control records').toBeGreaterThan(0)
  await m.ui.unmount()
})

// #983 send-back row 2: the failing tree and its control were two panes drawn about a second apart and compared character for character, while a computing build's
// time is drawn from the wall clock (hooks/addon.tsx `nowS = Date.now() / 1000`, `time: ~dur(el)`), which no test can hold (`Date.now` is read-only here, the hooks run
// in a realm of their own): a minute turning between the two draws made one character differ («~66 ч 20 мин» / «~66 ч 21 мин») and the test fail, about one run in forty.
// The `EACCES …/bin/.cache/state/tree-00.json` beside that failure is this file's own throwing `fs.write` hook as the engine names it under any failing test: no file
// of an installed pane is written (an `fs.write` no test hook answers has no implementation in the test engine at all).
// Now ONE pane draws the same picked state three times, each after the same two presses (unpick, pick): writes throwing, writes working, writes throwing again.
// What the wall clock draws only moves one way, so two equal failing trees prove nothing of it turned in between, and the control between them is held to them character for character.
test('#944 row 5: every state write throwing changes no redraw and throws nothing out', { timeoutMs: 120_000 }, async ($, on) => {
  let unhandled = 0
  const count = () => { unhandled++ }
  const proc: any = (globalThis as any).process
  proc?.on?.('unhandledRejection', count)
  const fail = { on: true }
  const m = await mount($, on, { fail })
  const pick = `run-pick-${m.job.id}`
  const stateWrites = () => m.writes.filter(p => p.startsWith(`${DIR}/state`)).length
  /** the picked state drawn anew: the same two presses before every reading */
  const repick = async () => { await m.press(pick); await m.press(pick); await m.clock.settle(); return bare(await m.ui.drawn()) }
  await m.press(pick)
  let failing = '', control = '', again = '', rounds = 0
  const ROUNDS = 5
  do {
    rounds++
    fail.on = true; failing = await repick()
    if (rounds === 1) {
      expect(m.lines().length, 'nothing recorded while every state write throws').toBe(0)
      expect(stateWrites(), 'no state file written while every state write throws').toBe(0)
    }
    fail.on = false; control = await repick()
    fail.on = true; again = await repick()
  } while (failing !== again && rounds < ROUNDS)
  console.log(`#944 failing writes: tree length ${failing.length}, control ${control.length}, identical ${failing === control}; rounds ${rounds}; state lines after the control ${m.lines().length}; unhandled rejections ${unhandled}`)

  expect(failing.length, 'the picked state is drawn').toBeGreaterThan(10_000)
  expect(failing === again, `the failing tree drawn before and after the control is the same one (no wall-clock time turned between them) within ${ROUNDS} rounds`).toBe(true)
  expect(failing, 'the tree is the control tree, character for character').toBe(control)
  expect(m.lines().length, 'the control between them recorded (the writes do work when they do not throw)').toBeGreaterThan(0)
  expect(unhandled, 'no exception out of the hook').toBe(0)
  proc?.off?.('unhandledRejection', count)
  await m.ui.unmount()
})
