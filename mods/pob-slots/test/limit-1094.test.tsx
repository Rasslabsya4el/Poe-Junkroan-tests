import { test, expect, mock } from 'claude-code/testing'
// #1094 unit 3a: the money figures of the Cost tab follow the plan price the payload carries (`total.limit_usd_per_pct`).
// No plan (the price null): no «≈ N % недельного лимита» head, no «1 % недельного лимита ≈ $… по ценам API» line,
// no per-row «% лимита» figure. A price: the figures as before.
import { FAST, TICKETS, ORCH, SLOW } from './fixtures'
import { limPct } from '../hooks/kit'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }

// the fixture's three cuts with the plan price taken away (a payload of a machine with no plan)
const noPlan = (json: string) => {
  const s = JSON.parse(json)
  for (const k of ['cost_day', 'cost_week', 'cost_month']) { const t = s[k].cut.total; t.limit_pct = null; t.limit_usd_per_pct = null }
  return JSON.stringify(s)
}

const drawCost = async ($: any, on: any, slow: string): Promise<string> => {
  const clock = mock.clock(on)
  const OUT: Record<string, string> = { fast: FAST, tickets: TICKETS, slow, orch: ORCH }
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  const s = JSON.stringify(await ui.drawn())
  await ui.unmount()
  return s
}

test('limPct: no plan price draws no figure; a price gives the percent of the weekly limit', () => {
  expect(limPct(16.5, null)).toBe('')
  expect(limPct(16.5, 16.5)).toBe('1.0 %')
  expect([limPct(412, 16.5), limPct(33, 16.5), limPct(3.3, 16.5), limPct(0.01, 16.5), limPct(0, 16.5)]).toEqual(['25 %', '2.0 %', '0.2 %', '<0.1 %', '0 %'])
})

test('Расходы with no plan price draws no money figure of the weekly limit and no per-row percent', async ($, on) => {
  const s = await drawCost($, on, noPlan(SLOW))
  expect(s).toContain('токенов') // the tab still draws its tables
  expect(s).not.toContain('недельного лимита')
  expect(s).not.toContain('по ценам API')
  expect(s).not.toContain('% лимита') // #1094 carried finding: no plan = the column is removed (header and cells), not blanked
  expect(s).not.toContain('0 %')
  expect(/\d %/.test(s)).toBe(false)
})

test('Расходы with a plan price draws the figures of the limit (the head, the one line, the per-row percent)', async ($, on) => {
  const s = await drawCost($, on, SLOW)
  expect(s).toContain('недельного лимита')
  expect(s).toContain('по ценам API')
  expect(/\d %/.test(s)).toBe(true)
})
