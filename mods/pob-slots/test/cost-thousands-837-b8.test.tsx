import { test, expect } from 'claude-code/testing'
import { mock } from 'claude-code/testing'
import { COST_SLOW_20261011, COST_TICKETS_20261011 } from './cost-live-20261011'
import { dq, svgWords } from './kit'

// #837 round 8 (E): tab Расходы writes every integer >= 1000 of its count cells in ONE form: thousands split by a plain space («3 503», not «3503» next to «3 503»).
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
for (const period of ['cost-week', 'cost-month', 'cost-day']) {
  test(`#837 b8: Расходы (${period}): every count cell >= 1000 is grouped by thousands`, { timeoutMs: 60_000 }, async ($, on) => {
    const out: Record<string, string> = { fast: '{}', tickets: COST_TICKETS_20261011, slow: COST_SLOW_20261011, orch: '{}' }
    const clock = mock.clock(on)
    on('fs.write', async () => ({ value: undefined }) as any)
    on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: out[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
    on('ui.open', async () => ({ value: { isOpen: true } }) as any)
    on('ui.status', async () => ({ value: undefined }) as any)
    void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
    await clock.settle()
    const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
    await ui.press({ key: 'tab-cost' }); await clock.settle()
    await ui.press({ key: period }); await clock.settle()
    const words: string[] = []
    walk(await (ui as any).drawn(), n => { if (n.type === 'Svg') words.push(...svgWords(dq(String(n.props?.source ?? '')))) })
    const bare = words.filter(w => /^\d{4,}$/.test(w)), grouped = words.filter(w => /^\d{1,3}( \d{3})+$/.test(w))
    console.log(`cost thousands ${period}: grouped ${grouped.length} (${grouped.slice(0, 6).join(', ')}), bare 4+ digits ${bare.length} (${bare.slice(0, 6).join(', ')})`)
    expect(bare, 'an integer of 1000 or more written without the thousands split').toEqual([])
    expect(grouped.length, 'the grouped form is on the tab').toBeGreaterThan(0)
    await ui.unmount()
  })
}
