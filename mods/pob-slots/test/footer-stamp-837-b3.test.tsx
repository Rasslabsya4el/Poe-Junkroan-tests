import { test, mock, expect } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { seen } from './kit'

// #837 b3 item 5: the footer of the Builds tab «обновлено HH:MM»: a stamp that is an ISO string with its own date reads `обновлено dd.mm HH:MM` when that date is not today's;
// today's stays `обновлено HH:MM`; a bare clock string stays as it is.
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const row = { run_dir: 'C:\repo\artifacts\benchmark\20261010-0422', run_name: 'P1-#604-3', ref: 'cold_dot', seed: 1, variant: '', pobbin_id: 'by4kos8YPJCx', author_pobbin_id: null,
  ratio_pct: 139, metric: 'CombinedDPS', ours: 345112, author: null, life: 5015, stop: 'converged', rank: null, audit: null, floors: null, note: '', added_at: '2026-10-10T08:16:46+00:00',
  name: 'Cold Dot', var: '', class: 'Witch', asc: 'Elementalist', metric_label: 'Combined DPS', ours_h: '345k', errors: null, warnings: null, floors_bad: null, said: [] }
const footer = async ($: any, on: any, updated: string) => {
  const f = JSON.parse(FAST)
  f.readings = { updated, rows: [row] }
  const clock = mock.clock(on)
  const OUT: Record<string, string> = { fast: JSON.stringify(f), tickets: TICKETS, slow: SLOW, orch: ORCH }
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.read', async (_$: any, e: any) => { throw new Error('ENOENT ' + e.path) })
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-builds' }); await clock.settle()
  const words = (await seen(ui)).map(t => t.trim()).filter(w => w.startsWith('обновлено'))
  await ui.unmount()
  return words
}
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d+Z$/, '+00:00')
const dm = (ms: number) => { const s = new Date(ms).toISOString(); return `${s.slice(8, 10)}.${s.slice(5, 7)}` }

test('#837 b3 item 5: a stamp of two days ago reads `обновлено dd.mm HH:MM`', async ($, on) => {
  const ms = Date.now() - 2 * 86_400_000
  const hhmm = new Date(ms).toISOString().slice(11, 16)
  const w = await footer($, on, iso(ms))
  console.log(`#837 b3 item 5 two days ago: ${JSON.stringify(w)}`)
  expect(w).toEqual([`обновлено ${dm(ms)} ${hhmm}`])
})

test('#837 b3 item 5: a stamp of today reads `обновлено HH:MM`', async ($, on) => {
  const ms = Date.now()
  const hhmm = new Date(ms).toISOString().slice(11, 16)
  const w = await footer($, on, iso(ms))
  console.log(`#837 b3 item 5 today: ${JSON.stringify(w)}`)
  expect(w).toEqual([`обновлено ${hhmm}`])
})
