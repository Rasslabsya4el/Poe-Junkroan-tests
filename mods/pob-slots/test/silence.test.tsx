import { test, mock, expect } from 'claude-code/testing'
// #821: a flag file silences the pane's own work (pulls and redraws); a pull error is one `error` line in the redraw log.
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'

const LOG = 'bin/.cache/redraws.log'
const FLAG = 'bin/.cache/pane.silenced'
async function rig($: any, on: any, opts: { failFast?: boolean } = {}) {
  const clock = mock.clock(on)
  const files: Record<string, string> = {}
  const key = (p: string) => (p.endsWith('redraws.log') ? LOG : p.endsWith('pane.silenced') ? FLAG : p)
  const cur = { fast: FAST, fail: !!opts.failFast, calls: 0 }
  on('process.run', async (_$: any, e: any) => {
    cur.calls++
    if (cur.fail && e.argv[2] === 'fast') return { value: { exitCode: 1, stdout: '', stderr: 'boom\tat\nline two', isStdoutTruncated: false } } as any
    return { value: { exitCode: 0, stdout: ({ fast: cur.fast, tickets: TICKETS, slow: SLOW, orch: ORCH } as any)[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.exists', async (_$: any, e: any) => ({ value: key(e.path) in files }) as any)
  on('fs.read', async (_$: any, e: any) => { if (key(e.path) in files) return { value: files[key(e.path)] } as any; throw new Error('ENOENT') })
  on('fs.write', async (_$: any, e: any) => { files[key(e.path)] = e.text; return { value: undefined } as any })
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  return { clock, files, cur }
}
const lines = (files: Record<string, string>) => (files[LOG] ?? '').split('\n').filter(Boolean)
const changed = (cur: any) => { const f = JSON.parse(FAST); f.runs.queued = []; f.nonce = Math.random(); cur.fast = JSON.stringify(f) }

test('silenced: flag present = no collect call and no redraw over 3 ticks; removed = both are back', async ($, on) => {
  const { clock, files, cur } = await rig($, on)
  const base = lines(files).length
  files[FLAG] = ''
  cur.calls = 0
  for (let i = 0; i < 3; i++) { changed(cur); await clock.advance(5_000); await clock.settle() }
  expect(cur.calls, 'collect.py calls while silenced').toBe(0)
  expect(lines(files).length, 'redraw lines while silenced').toBe(base)
  delete files[FLAG]
  changed(cur)
  await clock.advance(5_000); await clock.settle()
  expect(cur.calls, 'pulls resume').toBeGreaterThan(0)
  expect(lines(files).length, 'redraw resumes').toBe(base + 1)
})

test('error line: a failing pull writes exactly one error line, a healthy pull none', async ($, on) => {
  const healthy = await rig($, on)
  expect(lines(healthy.files).filter(l => l.includes(' error ')).length).toBe(0)
})

test('error line: one line, single-line message', async ($, on) => {
  const { files } = await rig($, on, { failFast: true })
  const errs = lines(files).filter(l => / error pull /.test(l))
  expect(errs.length).toBe(1)
  expect(errs[0]).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d \S+ error pull .*line two$/)
})
