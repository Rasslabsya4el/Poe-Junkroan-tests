import { test, mock, expect } from 'claude-code/testing'
// #771 B: the three periods of Расходы (week, month, day) at 123 columns on the LIVE cost payload of 2026-10-11
// (bin/.cache/shared-slow.json, written 07:46), guard 90,000 drawn characters as test/cost-size.test.tsx.
import { COST_SLOW_20261011, COST_TICKETS_20261011 } from './cost-live-20261011'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const OUT: Record<string, string> = { fast: '{}', tickets: COST_TICKETS_20261011, slow: COST_SLOW_20261011, orch: '{}' }
const size = async (ui: any) => Number(JSON.stringify(await ui.drawn()).length)

test('desktop, 123 columns, live cost payload of 2026-10-11: Расходы week, month and day', async ($, on) => {
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  const got: Record<string, number> = {}
  for (const k of ['cost-week', 'cost-month', 'cost-day']) {
    await ui.press({ key: k }); await clock.settle()
    got[k] = await size(ui)
  }
  console.log(`SZ live cost week ${got['cost-week']} month ${got['cost-month']} day ${got['cost-day']}`)
  // #771 B2: the cost tables' hover Boxes stand in one column (costTable), the picture and the text unchanged.
  for (const [k, v] of Object.entries(got)) expect(v, k).toBeLessThan(90_000)
  await ui.unmount()
})
