import { test, mock, expect } from 'claude-code/testing'
import { K } from '../hooks/tokens'
import { layout } from '../hooks/budget'
import { createRecorder } from '../hooks/staterec'
import type { StateInput } from '../hooks/staterec'
import { rowsSvg, emptyRow, LABEL_EM, LABEL_NB, LABEL_PAD } from '../hooks/kit'
import { TICKETS, SLOW, ORCH } from './fixtures'
import { LIVE_FAST } from './fast-live'
import { BUILD_816 } from './buildpanel-answer'
import { PROPS, dq, blankPx } from './kit'

// #994 (the owner, 14.10: «весь дешборд должен соблюдать один стиль»): the rules this ticket added, each held by its own check. The look itself is judged on the real pane
// (var/brain/monitor-1014/t4/); what a test can hold is held here.

test('#994 defect 9 / 2: a pinned unit stays on the drawn page whatever page is asked; with no pin the page asked is drawn', () => {
  const units = Array.from({ length: 30 }, () => 100)
  const lane = { key: 'rd', units, max: 10 }
  const asked = layout(Number.MAX_SAFE_INTEGER, [{ ...lane, at: 0 }]).plans.rd!
  expect(asked.page, 'no pin: the page asked').toBe(0)
  const pinned = layout(Number.MAX_SAFE_INTEGER, [{ ...lane, at: 0, pin: 27 }]).plans.rd!
  expect(pinned.shown.some(s => s.i === 27), 'the pinned unit is on the drawn page').toBe(true)
  expect(pinned.page, 'its page').toBe(2)
})

test('#994: the tree ring is shared by every session: a new session writes the file after the newest line\'s, never tree-00 over the owner\'s newest', async () => {
  const files = new Map<string, string>()
  const fs = { write: (p: string, t: string) => { files.set(p, t) }, read: (p: string) => files.get(p) ?? '', exists: (p: string) => files.has(p) }
  const input = (session: string, tab: string): StateInput => ({ session, tab, rowForm: 'one', lightCards: [], picked: null, open: null, cards: { grid: 'one', ag: 'one', mg: 'one', run: 'one' },
    measure: 1, firstMeasure: 1, limit: 95_000, forced: null, entry: { register: 1, kit: 1, version: 't' } })
  const owner = createRecorder(fs, 'd'), other = createRecorder(fs, 'd')
  for (const t of ['main', 'pob', 'builds']) await owner.record(input('owner', t), `{"tab":"${t}"}`)
  await other.record(input('other', 'main'), '{"tab":"other"}')
  const lines = String(files.get('d/state.jsonl')).trim().split('\n').map(l => JSON.parse(l))
  expect(lines.map(l => l.tree)).toEqual(['tree-00.json', 'tree-01.json', 'tree-02.json', 'tree-03.json'])
  expect(files.get('d/state/tree-02.json'), 'the owner\'s newest tree is still his').toBe('{"tab":"builds"}')
})

test('#994 defect 8 / 4 / placeholders: a busy row is one flat fill; a column head stands `hx` right of its column; a placeholder is `still`', () => {
  const cols = [{ key: 'name', x: 38, w: 300 }, { key: 'tick', x: 352, w: 66, hx: 7.8 }] as any
  const m = rowsSvg([{ r: { kind: 'head', cells: { name: 'задача', tick: 'тикет' } }, i: 0 }, { r: { kind: 'strip', state: 'active', cells: { name: 'run' } }, i: 0 }], cols, 963)
  const src = dq(m.svg)
  expect(/fill="url\(#d\d*\)"/.test(src.replace(/<defs>[\s\S]*?<\/defs>/g, '')), 'no speckle over a busy row').toBe(false)
  expect(/<text x="359\.8" y="16"[^>]*>тикет</.test(src), 'the head «тикет» over its numbers (x 352 + 7.8)').toBe(true)
  expect(emptyRow().still, 'the placeholder row lights nothing').toBe(true)
})

test('#994: a label row\'s pager is two chevrons in the picture: «previous» turned, the dim end in the faint shape', () => {
  const press = (dim: boolean) => ({ key: 'k', on: () => {}, dim })
  const m = rowsSvg([{ r: { kind: 'label', text: 'Готово', hot: [{ x: 900, w: 20, label: 'новее', pg: 'prev', drawn: { x: 900, w: 20 }, press: press(true) }, { x: 926, w: 20, label: 'старее', pg: 'next', drawn: { x: 926, w: 20 }, press: press(false) }] }, i: 0 }], [], 963)
  const src = dq(m.svg)
  expect(src.includes('rotate(180 8 8)'), 'the «previous» chevron is the same icon turned').toBe(true)
  expect(src.toLowerCase().includes(K.faint.toLowerCase()), 'the dim end is drawn in the faint shape').toBe(true)
  expect(/новее|старее/.test(src), 'no pager word is drawn').toBe(false)
})

test('#994 defect 10: a blank label is as wide as its face on the real pane (the four lights read 14.10)', () => {
  const EM = String.fromCharCode(0x2003), NB = String.fromCharCode(160)
  const read: [string, number][] = [[EM.repeat(21), 280], [EM.repeat(2) + NB.repeat(5), 48], [EM.repeat(2) + NB.repeat(3), 42], [EM + NB.repeat(4), 33]]
  for (const [label, lit] of read) expect(Math.abs(blankPx(label)! - lit), `${label.length} characters lit ${lit} px`).toBeLessThanOrEqual(1.5)
  expect(LABEL_EM + LABEL_NB + LABEL_PAD).toBeGreaterThan(0)
})

// defect 6: the owner saw the build open on POB close when he opened or closed a reading on Билды. The two tabs keep their own open build.
test('#994 defect 6: opening and closing a reading on Билды leaves the build open on POB open', { timeoutMs: 90_000 }, async ($, on) => {
  const clock = mock.clock(on)
  const d = JSON.parse(LIVE_FAST)
  const job = d.runs.running.find((j: any) => j.id === 'j-20261011-0430-e070')
  d.readings = { updated: '2026-10-10T08:16:47+00:00', rows: [{ run_dir: 'C:\\repo\\artifacts\\benchmark\\x', run_name: 'r', ref: 'cold_dot', seed: 1, variant: '', ratio_pct: 120, ours: 1, ours_h: '1', life: 4000, name: 'Cold Dot', class: 'Witch', asc: 'Elementalist', errors: 0, said: [] }] }
  const all: Record<string, string> = { fast: JSON.stringify(d), tickets: TICKETS, slow: SLOW, orch: ORCH, build: BUILD_816 }
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.write', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui: any = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) })
  const openPob = async () => (await ui.findAll({ type: 'Button' })).filter((b: any) => /^open-pob-/.test(String(b.key ?? b.props?.key ?? ''))).length
  await ui.press({ key: 'tab-pob' }); await clock.settle()
  await ui.press({ key: `run-pick-${job.id}` }); await clock.settle()
  await ui.press({ key: `cell-${job.id}-stormbrand-1` }); await clock.settle()
  expect(await openPob(), 'the POB build is open').toBe(1)
  await ui.press({ key: 'tab-builds' }); await clock.settle()
  const pick = (await ui.findAll({ type: 'Button' })).find((b: any) => /^rd-pick-/.test(String(b.key ?? b.props?.key ?? '')))
  const key = String(pick.key ?? pick.props.key)
  await ui.press({ key }); await clock.settle()
  expect(await openPob(), 'the reading is open on Билды').toBe(1)
  await ui.press({ key }); await clock.settle()
  await ui.press({ key }); await clock.settle()
  await ui.press({ key: 'tab-pob' }); await clock.settle()
  expect(await openPob(), 'the POB build is still open').toBe(1)
  await ui.unmount()
})
