import { test, mock, expect } from 'claude-code/testing'
// #771: one line per real redraw in bin/.cache/redraws.log; an unchanged payload writes none; the file is capped.
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'

const LOG = 'bin/.cache/redraws.log'
async function rig($: any, on: any, seed = '') {
  const clock = mock.clock(on)
  const files: Record<string, string> = seed ? { [LOG]: seed } : {}
  const key = (p: string) => (p.endsWith('redraws.log') ? LOG : p)
  const cur = { fast: FAST }
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: ({ fast: cur.fast, tickets: TICKETS, slow: SLOW, orch: ORCH } as any)[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
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

test('redraw log: the first draw writes one line, an unchanged payload none', async ($, on) => {
  const { clock, files } = await rig($, on)
  const first = lines(files)
  expect(first.length, 'one line for the first redraw').toBe(1)
  expect(first[0]).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d \S+ main \d+$/)
  await clock.advance(30_000); await clock.settle()
  expect(lines(files).length, 'same payload, no new line').toBe(1)
})

test('redraw log: a changed payload writes one more line', async ($, on) => {
  const { clock, files, cur } = await rig($, on)
  const f = JSON.parse(FAST)
  f.runs.queued = []
  cur.fast = JSON.stringify(f)
  await clock.advance(20_000); await clock.settle()
  expect(lines(files).length).toBe(2)
})

test('redraw log: past 1 MB it keeps the newest half', async ($, on) => {
  const old = Array.from({ length: 30_000 }, (_, i) => `2026-10-10T00:00:00 sid main ${100_000 + i}`).join('\n') + '\n'
  expect(old.length).toBeGreaterThan(1_000_000)
  const { files } = await rig($, on, old)
  const l = lines(files)
  expect(l.length).toBeLessThan(16_000)
  expect(l.length).toBeGreaterThan(14_000)
  expect((files[LOG] ?? '').length).toBeLessThan(600_000)
  expect(l.at(-2)).toContain("129999")
  expect(l.at(-1)).toMatch(/ main \d+$/)
})
