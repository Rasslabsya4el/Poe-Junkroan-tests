import { test, mock, expect } from 'claude-code/testing'
// #771: the Расходы tab stays under ~90k drawn characters at the pane's real width (123 columns) in every mode
// (desktop pane freezes past ~100k: 98k and 113k drew, 115k and 139k froze).
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const OUT: Record<string, string> = { fast: FAST, tickets: TICKETS, slow: SLOW, orch: ORCH }
const size = async (ui: any) => Number(JSON.stringify(await ui.drawn()).length)

test('desktop, 123 columns: Расходы week, month and day each draw under 90,000 characters', async ($, on) => {
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
  console.log(`SZ cost week ${got['cost-week']} month ${got['cost-month']} day ${got['cost-day']}`)
  for (const [k, v] of Object.entries(got)) expect(v, k).toBeLessThan(90_000)
  await ui.unmount()
})
