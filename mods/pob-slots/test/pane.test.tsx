import { mountG } from './kit'
import { test, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH, CELLS, BUILD } from './fixtures'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const OUT: Record<string, string> = { fast: FAST, tickets: TICKETS, slow: SLOW, orch: ORCH, cells: CELLS, build: BUILD }
const dups = async (ui: any) => { const t = await ui.drawn(); const seen: Record<string, number> = {}; let n = 0; const walk = (x: any) => { if (!x || typeof x !== 'object') return; n++; const kk = x.props?.key; if (kk != null) seen[kk] = (seen[kk] ?? 0) + 1; for (const c of (x.children ?? x.props?.children ?? [])) walk(c) }; walk(t); const d = Object.entries(seen).filter(([, v]) => v > 1); return `nodes ${n}, keys ${Object.keys(seen).length}, dup ${JSON.stringify(d).slice(0, 400)}` }
const size = async (ui: any) => { try { return String(JSON.stringify(await ui.drawn()).length) } catch (err) { return 'REFUSED: ' + String(err).slice(0, 600) } }

for (const surface of ['terminal', 'desktop'] as const) {
  test(`${surface}: run 580-2, press a square`, async ($, on) => {
    const clock = mock.clock(on)
    on('process.run', async (_$, e) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
    on('ui.open', async () => ({ value: { isOpen: true } }) as any)
    on('ui.status', async () => ({ value: undefined }) as any)
    void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch((e: any) => console.log('cmd', String(e).slice(0, 200)))
    await clock.settle()
    const ui = await mountG($, { plugin: 'pob-slots', surface, component: 'Pane', requestId: 'pob', props: PROPS })
    await ui.press({ key: 'tab-pob' }) // #983: the runs card lives on the tab «POB»
    console.log(`${surface}: start ${await size(ui)}`)
    // History shows 6 runs a page (#683 r3): page on until the run's row is drawn.
    const RUN = 'run-hist-j-20261006-1042-6ea8'
    const drawn = async () => [...(await ui.findAll({ type: 'Markdown' })), ...(await ui.findAll({ type: 'Button' }))].some((b: any) => b.key === RUN)
    for (let i = 0; i < 40 && !(await drawn()); i++) { await ui.press({ key: 'hist-next' }); await clock.settle() }
    await ui.press({ key: RUN })
    await clock.settle()
    const cells = [...(await ui.findAll({ type: 'Markdown' })), ...(await ui.findAll({ type: 'Button' }))].filter((b: any) => String(b.key).startsWith('cell-'))
    console.log(`${surface}: run picked ${await size(ui)}, cells ${cells.length}`)
    await ui.press({ key: 'cell-j-20261006-1042-6ea8-smite-4' })
    await clock.settle()
    const stats = await ui.findAll({ type: 'Text', text: /Fire Max Hit/ })
    console.log(`${surface}: square open ${await size(ui)}, Fire Max Hit texts ${stats.length}`)
    console.log(`${surface}: ${await dups(ui)}`)
    for (const t of ['tab-builds', 'tab-tickets', 'tab-cost', 'tab-progress']) { await ui.press({ key: t }); await clock.settle(); console.log(`${surface}: ${t} ${await size(ui)}`) }
    await ui.unmount()
  })
}
