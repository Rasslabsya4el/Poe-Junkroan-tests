import { test, mock, expect } from 'claude-code/testing'
import { seen } from './kit'
import { COST_SLOW_20261011, COST_TICKETS_20261011 } from './cost-live-20261011'

// #837 b3 item 4: the per-run price of «Роль на разных моделях»: a value above 0 and under 0.0005 reads `<$0.001` (not `$0.000`), 0 reads `$0`, the rest as before.
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }

test('#837 b3 item 4: perRun: 0.0002 per run is `<$0.001`, 0 is `$0`, 0.012 stays `$0.012`', async ($, on) => {
  const slow = JSON.parse(COST_SLOW_20261011)
  const rm = slow.cost_week.cut.by_role_model
  // three rows with 1000 runs: 0.20 usd (0.0002 a run), 0 usd (tokens only), 12 usd (0.012 a run)
  ;[0.2, 0, 12].forEach((usd, i) => { Object.assign(rm[i], { n: 1000, tokens: 1_000_000, cost_usd: usd }) })
  const OUT: Record<string, string> = { fast: '{}', tickets: COST_TICKETS_20261011, slow: JSON.stringify(slow), orch: '{}' }
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  await ui.press({ key: 'cost-week' }); await clock.settle()
  const words = (await seen(ui)).map(t => t.trim()).filter(Boolean)
  console.log(`#837 b3 item 4: "<$0.001" x${words.filter(w => w === '<$0.001').length}, "$0" x${words.filter(w => w === '$0').length}, "$0.000" x${words.filter(w => w === '$0.000').length}, "$0.012" x${words.filter(w => w === '$0.012').length}`)
  // the fixture's own live rows: one more row under 0.0005 a run (it read `$0.000` before: 3 of them with the two above)
  expect(words.filter(w => w === '<$0.001').length, '0.0002 a run (+ the live row)').toBe(2)
  expect(words.filter(w => w === '$0').length, '0 a run').toBe(1)
  expect(words.filter(w => w === '$0.000').length, 'no $0.000').toBe(0)
  expect(words.filter(w => w === '$0.012').length, '0.012 a run').toBeGreaterThanOrEqual(1)
  await ui.unmount()
})
