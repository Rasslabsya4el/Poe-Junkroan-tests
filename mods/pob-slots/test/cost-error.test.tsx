import { test, mock, expect } from 'claude-code/testing'
// #793 D2: a Cost-tab error is a card (title + a one-row table), never one bare muted repr.
import { FAST, TICKETS, ORCH } from './fixtures'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const ERR = { cut_error: "KeyError('input')" }
const SLOW_ERR = JSON.stringify({ at: '00:00:00', cost_day: ERR, cost_week: ERR, cost_month: ERR })
const OUT: Record<string, string> = { fast: FAST, tickets: TICKETS, slow: SLOW_ERR, orch: ORCH }

test('Расходы with cut_error draws a card titled «Расходы не посчитаны» with the message in a table row', async ($, on) => {
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  const s = JSON.stringify(await ui.drawn())
  expect(s).toContain('Расходы не посчитаны')
  expect(s).toContain('KeyError')
  expect(s).toContain('причина')
  await ui.unmount()
})
