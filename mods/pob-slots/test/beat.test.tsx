import { test, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'

// 09.10, lost clicks: a fast pull every 5 s, but the pane is redrawn only on the 15-s beat or the
// moment something the owner reacts to changed (a square's state here); the CPU samples of the
// skipped pulls still reach the 10-min strip.
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const base = JSON.parse(FAST)
const payload = (at: string, cpu: number, done = false) => {
  const v = JSON.parse(JSON.stringify(base))
  v.at = at
  v.machine.cpu.pob = cpu
  if (done) v.runs.running[0].progress.cells[0].state = 'done'
  return JSON.stringify(v)
}

test('desktop: redraw on the beat or on a change, never on every pull', async ($, on) => {
  const clock = mock.clock(on)
  let cur = payload('10:00', 10)
  let pulls = 0
  on('process.run', async (_$, e) => {
    if (e.argv[2] === 'fast') pulls++
    const out: Record<string, string> = { fast: cur, tickets: TICKETS, slow: SLOW, orch: ORCH }
    return { value: { exitCode: 0, stdout: out[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  const footer = async () => (await ui.findAll({ type: 'Text', text: /^обновлено / }))[0]?.text
  const polygons = async () => {
    const svg = String((await ui.findAll({ type: 'Svg' })).find((s: any) => s.props?.alt === 'PC load')?.props?.source ?? '')
    return svg.split('<polygon').length - 1
  }
  const step = async (at: string, cpu: number, done = false) => {
    cur = payload(at, cpu, done)
    await clock.advance(5_000)
    await clock.settle()
    console.log(`${at}: pulls ${pulls}, footer "${await footer()}", polygons ${await polygons()}`)
  }
  if (await footer() !== 'обновлено 10:00') throw new Error('first draw: ' + await footer())
  await step('10:01', 50)
  if (await footer() !== 'обновлено 10:00') throw new Error('redrawn at 5 s')
  await step('10:02', 55)
  if (await footer() !== 'обновлено 10:00') throw new Error('redrawn at 10 s')
  await step('10:03', 60)
  if (await footer() !== 'обновлено 10:03') throw new Error('no redraw on the 15-s beat')
  // Four samples (10, 50, 55, 60) = two 15-s buckets: the strip is drawn (three layers).
  if (await polygons() !== 3) throw new Error('strip lost the skipped pulls')
  await step('10:04', 61, true)
  if (await footer() !== 'обновлено 10:04') throw new Error('a square turned done, no redraw')
  if (pulls !== 5) throw new Error(`pulls ${pulls}`)
  await ui.unmount()
})
