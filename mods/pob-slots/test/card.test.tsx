import { test, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { svgRows, dq } from './kit'

// 09.10, redrawn by #683 r3 / r4c: the PC picture has no cores row (the CPU bar carries the load), a running run is a
// row whose meta carries its host and the slots it holds (locks), and a laptop out of reach is the same card,
// empty (its slot squares only, `—` captions, «offline» on the title line), with one red line and a muted `шло:` line.
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const base = JSON.parse(FAST)
const payload = () => {
  const v = JSON.parse(JSON.stringify(base))
  v.machine.cpu = { pob: 4, agents: 4, you: 4 } // 0.48 core each: per-role rounding drew none, cumulative draws one
  v.runs.slots = []
  v.runs.running[0].workers = 1
  v.runs.running[0].locks = 5
  v.laptop = {
    error: 'Connection to 100.77.22.117 port 22 timed out',
    offline: { lost: '11:00', lost_ago: '1 min', seen: '10:59', seen_ago: '2 min', cores: 8, slots_total: 3,
      running: [{ tag: 'P1-#555', workers: 2, done: 3, total: 8, eta: '12:30' }], queued: 0,
      verdict: 'раны идут сами до ~12:30', restore: 'к ~12:30 (тогда hand-back в тикет)' },
  }
  return JSON.stringify(v)
}
const count = (s: string, needle: string) => s.split(needle).length - 1

test('desktop: cores rounding, host column, locks, laptop offline card', async ($, on) => {
  const clock = mock.clock(on)
  on('process.run', async (_$, e) => {
    const out: Record<string, string> = { fast: payload(), tickets: TICKETS, slow: SLOW, orch: ORCH }
    return { value: { exitCode: 0, stdout: out[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  const svgs = await svgRows(ui) // #771: a merged picture read row by row
  const pc = dq(String(svgs.find((s: any) => s.props?.alt === 'PC load')?.props?.source ?? ''))
  const lap = dq(String(svgs.find((s: any) => s.props?.alt === 'Laptop offline')?.props?.source ?? ''))
  const texts = (await ui.findAll({ type: 'Text' })).map((x: any) => x.text)
  const buttons = (await ui.findAll({ type: 'Button' })).map((b: any) => [String(b.key), String(b.props?.label ?? '')])
  // the slot squares (r4c: rx 4; filled = busy in the role colour, outlined = free)
  const cores = { pob: count(pc, `rx="4" fill="#3987e5"`), agents: count(pc, `rx="4" fill="#d55181"`), you: count(pc, `rx="4" fill="#c9c9cf"`) }
  // #983: the running run is a row of the runs card, on the tab «POB»
  await ui.press({ key: 'tab-pob' })
  const runSvgs = await svgRows(ui)
  const run = dq(String(runSvgs.find((s: any) => String(s.props?.alt).includes(' running'))?.props?.source ?? ''))
  console.log(`cores drawn ${JSON.stringify(cores)} | laptop svg ${lap.length} chars, squares ${count(lap, 'rx="4"')} | run strip ${run.length} chars | texts ${texts.filter(t => /host|нет связи|шло:|связь|hand-back/.test(t)).join(' | ')} | size ${JSON.stringify(await ui.drawn()).length}`)

  // No cores row: the only role squares are the slots (none busy here: runs.slots is empty).
  if (cores.pob + cores.agents + cores.you !== 0 || pc.includes('>cores<')) throw new Error('cores row is back: ' + JSON.stringify(cores))
  if (texts.some(t => t.includes('▦'))) throw new Error('a ▦ mark')
  // The running run: one row, its meta = priority, host, the slots it holds (locks 5, not workers 1).
  // #773: the slots it holds are five small squares in the picture, the words are in the row's alt
  const runAlt = String(runSvgs.find((s: any) => String(s.props?.alt).includes(' running'))?.props?.alt ?? '')
  if (!runAlt.includes('5 слотов') || runAlt.includes('1 слот') || count(run, 'h3v5h-3z') !== 5) throw new Error('run strip: ' + runAlt + ' ' + count(run, 'h3v5h-3z'))
  // The laptop: its 3 slots as free squares, the dash captions, «offline» red on the title line, one red line, the run
  // that was going.
  if (count(lap, 'rx="4" fill="none"') !== 3 || !lap.includes('>—<') || !lap.includes('class="er">offline<')) throw new Error('laptop card: ' + count(lap, 'rx="4"'))
  if (!texts.includes('нет связи с 11:00 · 1 min') || !texts.includes('шло: P1-#555 · 2 slots · 3/8')) throw new Error('laptop lines')
  if (texts.some(t => /hand-back|раны идут/.test(t))) throw new Error('verdict drawn')
  if (buttons.some(([k]) => k === 'res-go-laptop')) throw new Error('reservation row while offline')
  await ui.unmount()
})
