import { test, expect, mock } from 'claude-code/testing'
import { PROPS, mountG } from './kit'
import { SLOW, ORCH, TICKETS } from './fixtures'
import { LIVE_FAST } from './fast-live'
import { LIVE as TODAY } from './tickets-live-20261011'
import { BUILD_816 } from './buildpanel-answer'

// #837 round 3, item 1 (the size fallback). The pane's tree with the card rows' hover Boxes is measured where it is built (the ui.render hook's result, the serialized
// length with the functions left out); over HOVER_ROWS_LIMIT (90,000, the size tests' guard) the same tab is built once more with the card rows in the light form of
// 5e411403: no hover Box on a card row, everything else drawn. So the heaviest state stays under the guard and the lighter states keep their row hover.
// #972: the limit is the host's own: a drawn tree over 100,000 serialized characters unmounts the pane (claude-code index.d.ts: «every tree's bounds (20,000 nodes, 32 deep, 100,000 characters serialized) or the instance unmounts»).
// The mock's drawn tree carries the host's press stamps, so this number is the host's own less a 5,000 margin; the one drawn form (no size tier) measured 92,429 on the heaviest fixture here (open square, stats open) after the diets of #972.
const LIMIT = 95_000
const SIZE_5E41 = 88_918 // the fullest state at 5e411403
const fast = JSON.parse(LIVE_FAST)
const job = fast.runs.running.find((j: any) => j.id === 'j-20261011-0430-e070')
const CELL = `cell-${job.id}-stormbrand-1`
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
// #972: a keyed data-row Box `hv-<k><n>` of the cards Agents (ag), Merge (mg), PoB runs (run) lights NOTHING of its own: no `hover` prop (the square veil is gone; the light is the pointer element's)
const hoverRows = (tree: any) => { let n = 0; walk(tree, x => { if (x.type === 'Box' && /^hv-(ag|mg|run)\d+$/.test(String(x.props?.key ?? '')) && (x.hover != null || x.props?.hover != null)) n++ }); return n }
const keyedRows = (tree: any) => { let n = 0; walk(tree, x => { if (x.type === 'Box' && /^hv-(ag|mg|run)\d+$/.test(String(x.props?.key ?? ''))) n++ }); return n }
const cardBoxes = (tree: any) => { let n = 0; walk(tree, x => { if (x.type === 'Box' && /^(ag|mg|run)-r\d+$/.test(String(x.props?.key ?? ''))) n++ }); return n }

async function mount($: any, on: any, answer: 'hang' | 'full' | 'none') {
  const clock = mock.clock(on)
  const all: Record<string, string> = { fast: LIVE_FAST, tickets: answer === 'none' ? TODAY : TICKETS, slow: SLOW, orch: ORCH }
  on('process.run', async (_$: any, e: any) => {
    if (e.argv[2] === 'build') {
      if (answer === 'full') return { value: { exitCode: 0, stdout: BUILD_816, stderr: '', isStdoutTruncated: false } } as any
      return new Promise(() => {}) as any
    }
    return { value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.write', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await mountG($, { plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) })
  await ui.press({ key: 'tab-pob' }) // #983: the runs card lives on the tab «POB»
  return { ui, clock }
}
const size = async (ui: any) => JSON.stringify(await ui.drawn()).length

test('#837 b3 item 1: «Главная» and «POB» keep their 43 keyed hv- row Boxes together, none carries a hover prop, no light card Box', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui } = await mount($, on, 'none')
  // #983: the 43 rows of Agents, Merge and the runs card stand on two tabs now: both are read as one tree
  const pob = await ui.drawn(), szPob = await size(ui)
  await ui.press({ key: 'tab-main' })
  const tree = { children: [pob, await ui.drawn()] }
  const sz = Math.max(szPob, await size(ui))
  console.log(`#837 b3 main tab: ${sz} chars, ${keyedRows(tree)} keyed hv- rows, ${hoverRows(tree)} with a hover prop, ${cardBoxes(tree)} light card Boxes`)
  expect(sz).toBeLessThan(LIMIT)
  // #994: the three placeholder rows («ничего», «пусто» of Merge, «пусто» of the runs' queue) light nothing: they are no keyed row Box any more (43 - 3)
  // #1093: the fixture's `merge.full_run` replaces the «ничего» placeholder of the Merge queue with a keyed row (40 + 1)
  expect(keyedRows(tree), 'keyed hv- row Boxes on the main tab').toBe(41)
  expect(hoverRows(tree), 'row Boxes carrying a hover prop').toBe(0)
  expect(cardBoxes(tree), 'light card Boxes').toBe(0)
})

// #972: ONE form (no light card Box, no fallback tier): the main tab with the open square keeps every strip row of the cards keyed `hv-<card><n>` with no hover prop, and the measure stays under the guard
const hoverKeyed = keyedRows
for (const answer of ['hang', 'full'] as const) {
  test(`#837 b3 item 1: open square, ${answer === 'hang' ? 'fallback' : 'full layout'}`, { timeoutMs: 60_000 }, async ($, on) => {
    const { ui, clock } = await mount($, on, answer)
    await ui.press({ key: `run-pick-${job.id}` }); await clock.settle()
    await ui.press({ key: CELL }); await clock.settle()
    const tree = await ui.drawn()
    const sz = await size(ui)
    const hov = hoverRows(tree), keyed = hoverKeyed(tree), light = cardBoxes(tree)
    console.log(`#837 b3 open square ${answer === 'hang' ? 'fallback' : 'full'}: ${sz} chars (limit ${LIMIT}, spare ${LIMIT - sz}), ${keyed} keyed strip rows, ${hov} with a hover prop, ${light} light card Boxes`)
    expect(keyed, 'every card keeps its keyed strip rows').toBeGreaterThan(0)
    expect(hov, 'no keyed strip row carries a hover prop').toBe(0)
    expect(light, 'no card row is light (one form)').toBe(0)
    expect(sz, 'under the guard').toBeLessThan(LIMIT)
  })
}
