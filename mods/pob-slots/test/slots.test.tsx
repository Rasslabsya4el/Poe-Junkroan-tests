import { test, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { dq } from './kit'

// Owner 10.10 01:5x («опять»): P1-#604-2 said «5 слотов», the PC picture lit 1 square: the daemon's `slots_in_use`
// counts the submitted workers (1), not the 5 locks of the lone job it widened (#570). The held locks decide.
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const base = JSON.parse(FAST)
const locks = [1, 2, 8, 9, 10].map(slot => ({ slot, role: 'queue', pid: slot, age: '53 min' })).concat([{ slot: 3, role: 'other', pid: 3, age: '3.5 min' }])
const fast = JSON.stringify({ ...base, runs: { ...base.runs, slots: locks, daemon: { host: 'pc', age_s: 5, slots_total: 10, slots_in_use: 1, reserved: 0, reserved_until: null } } })

test('desktop: the PC slots show the held locks, not the daemon count', async ($, on) => {
  const clock = mock.clock(on)
  on('process.run', async (_$, e) => {
    const out: Record<string, string> = { fast, tickets: TICKETS, slow: SLOW, orch: ORCH }
    return { value: { exitCode: 0, stdout: out[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  const svg = dq(String((await ui.findAll({ type: 'Svg' })).find((s: any) => s.props?.alt === 'PC load')?.props?.source ?? ''))
  const cap = /text-anchor="end"[^>]*>([^<]*\/[^<]*)<\/text>/.exec(svg.slice(svg.indexOf('>PoB slots<')))?.[1] ?? ''
  console.log(`caption "${cap}"`)
  if (!cap.startsWith('6 / 10')) throw new Error('caption: ' + cap)
  await ui.unmount()
})
