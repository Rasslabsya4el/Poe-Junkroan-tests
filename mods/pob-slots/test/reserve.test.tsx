import { dq } from './kit'
import { test, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'

// #622: the reservation row of the PC in its four states (one compact row, owner 09.10), the reserved
// squares (r4c: the owner's `you` grey) and caption in the PC picture. #995 row 4: the row is gone in all four states.
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const base = JSON.parse(FAST)
const fastWith = (daemon: any) => JSON.stringify({ ...base, runs: { ...base.runs, daemon } })
const in30 = new Date(Date.now() + 30 * 60_000).toISOString()

const STATES: Record<string, any> = {
  none: { host: 'pc', age_s: 5, slots_total: 7, slots_in_use: 4, reserved: 0, reserved_until: null },
  active: { host: 'pc', age_s: 5, slots_total: 4, slots_in_use: 4, reserved: 3, reserved_until: in30 },
  stale: { host: 'pc', age_s: 300, slots_total: 7, slots_in_use: 4, reserved: 0, reserved_until: null },
  nobackend: { host: 'pc', age_s: 5, slots_total: null, slots_in_use: null, reserved: null, reserved_until: null },
}

const texts = async (ui: any) => (await ui.findAll({ type: 'Text' })).map((x: any) => x.text).join(' | ')
const pcSvg = async (ui: any) => dq(String((await ui.findAll({ type: 'Svg' })).find((s: any) => s.props?.alt === 'PC load')?.props?.source ?? ''))
const count = (s: string, needle: string) => s.split(needle).length - 1

for (const [state, daemon] of Object.entries(STATES)) {
  test(`desktop: reservation row, ${state}`, async ($, on) => {
    const clock = mock.clock(on)
    const calls: string[][] = []
    on('process.run', async (_$, e) => {
      if (e.argv[1] === 'scripts/runs.py') {
        calls.push([...e.argv])
        return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false } } as any
      }
      const out: Record<string, string> = { fast: fastWith(daemon), tickets: TICKETS, slow: SLOW, orch: ORCH }
      return { value: { exitCode: 0, stdout: out[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
    })
    on('ui.open', async () => ({ value: { isOpen: true } }) as any)
    on('ui.status', async () => ({ value: undefined }) as any)
    void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
    await clock.settle()
    const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
    const all = await texts(ui)
    const svg = await pcSvg(ui)
    const release = await ui.find({ type: 'Button', key: 'res-rel-pc' } as any)
    const reserve = await ui.find({ type: 'Button', key: 'res-go-pc' } as any)
    const sel = await ui.find({ type: 'Select', key: 'res-n-pc' } as any)
    const row = all.split(' | ').filter((x: string) => /резерв|slots на|демон|#621|ещё/.test(x)).join(' | ')
    const cap = /text-anchor="end"[^>]*>([^<]*\/[^<]*)<\/text>/.exec(svg.slice(svg.indexOf('>PoB slots<')))?.[1]
    console.log(`${state}: ${row} | caption "${cap}" owner squares ${count(svg, `rx="4" fill="#c9c9cf"`)} | reserve ${!!reserve} release ${!!release} select ${!!sel} | size ${JSON.stringify(await ui.drawn()).length}`)
    // The old separate `slots N / M` text line and the warning sentence are gone from every state.
    if (/slots \d+ \/ \d+|кнопки ответят/.test(all)) throw new Error('old lines: ' + row)
    // #995 row 4 (the owner, 14.10: «Резервы убираем нахуй, бесполезные»): in every state of the daemon the PC card draws no reservation row: no selects, no
    // «Зарезервировать», no «Снять», no word «резерв» in its rows or its caption; the daemon's reserved slots still show as the owner's squares
    if (reserve || release || sel || row) throw new Error(`${state}: a reservation row: ${row} reserve ${!!reserve} release ${!!release} select ${!!sel}`)
    if (/резерв/.test(svg)) throw new Error(`${state}: «резерв» in the PC picture: ${cap}`)
    if (state === 'none' && cap !== '4 / 7') throw new Error('none picture: ' + cap)
    if (state === 'active' && (cap !== '4 / 4' || count(svg, `rx="4" fill="#c9c9cf"`) !== 3)) throw new Error('active picture: ' + cap)
    if (calls.length) throw new Error('runs.py reserve ran: ' + JSON.stringify(calls))
    await ui.unmount()
  })
}
