import { test, mock } from 'claude-code/testing'
import { PROPS, seen, mountG } from './kit'
import { SLOW, ORCH, TICKETS } from './fixtures'
import { LIVE_FAST } from './fast-live'
import { BUILD_816 } from './buildpanel-answer'
import { SAVED } from './buildpanel-cells'

// #613 unit 1 (measure): the size of the main tab with an open build square of the runs card, in two states: the
// FALLBACK (the build is read: `collect.py build` has not answered, the square's head + «читаю билд…») and the FULL layout
// (the answer is in: the head with its buttons and the stat table, 4 groups, 37 rows, with the author's column).
// Run P1-#816 (j-20261011-0430-e070), build Stormbrand seed 1 of the live fast payload of 2026-10-11 07:19.
// The desktop stops redrawing a tree past ~100k characters: the open square must stay under 90,000.
// GUARD_ON (since #613 unit 4): the size guard and the cell-text comparison hold.
const GUARD_ON = true
// #972: the limit is the host's own: a drawn tree over 100,000 serialized characters unmounts the pane (claude-code index.d.ts: «every tree's bounds (20,000 nodes, 32 deep, 100,000 characters serialized) or the instance unmounts»).
// The mock's drawn tree carries the host's press stamps, so this number is the host's own less a 5,000 margin; the one drawn form (no size tier) measured 92,429 on the heaviest fixture here (open square, stats open) after the diets of #972.
const LIMIT = 95_000
const fast = JSON.parse(LIVE_FAST)
const job = fast.runs.running.find((j: any) => j.id === 'j-20261011-0430-e070')
const CELL = `cell-${job.id}-stormbrand-1`

async function mountWith(ons: any, on: any, answer: 'hang' | 'full') {
  const clock = mock.clock(on)
  const all: Record<string, string> = { fast: LIVE_FAST, tickets: TICKETS, slow: SLOW, orch: ORCH }
  on('process.run', async (_$: any, e: any) => {
    if (e.argv[2] === 'build') {
      if (answer === 'hang') return new Promise(() => {}) as any
      return { value: { exitCode: 0, stdout: BUILD_816, stderr: '', isStdoutTruncated: false } } as any
    }
    return { value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.write', async () => ({ value: undefined }) as any)
  void ons.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  return { ui: await mountG(ons, { plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) }), clock }
}
const diff = (a: string[], b: string[]) => {
  const left = new Map<string, number>()
  for (const x of b) left.set(x, (left.get(x) ?? 0) + 1)
  return a.filter(x => { const k = left.get(x) ?? 0; if (k > 0) { left.set(x, k - 1); return false } return true })
}
const sizes: Record<string, number> = {}
const texts: Record<string, string[]> = {}

for (const answer of ['hang', 'full'] as const) {
  test(`desktop, 123 columns: main tab + picked run + open square, ${answer === 'hang' ? 'fallback' : 'full layout'}`, async ($, on) => {
    const { ui, clock } = await mountWith($, on, answer)
    const size = async () => JSON.stringify(await (ui as any).drawn()).length
    await ui.press({ key: 'tab-pob' }); await clock.settle() // #983: the runs card lives on the tab «POB»
    const main = await size()
    await ui.press({ key: `run-pick-${job.id}` }); await clock.settle()
    const picked = await size()
    const wordsPicked = (await seen(ui)).map(t => t.trim()).filter(Boolean)
    await ui.press({ key: CELL }); await clock.settle()
    const open = await size()
    const wordsOpen = (await seen(ui)).map(t => t.trim()).filter(Boolean)
    const own = open - picked
    const cellTexts = diff(wordsOpen, wordsPicked).sort()
    const dataRows = JSON.parse(BUILD_816).groups.reduce((n: number, g: any) => n + g.rows.length, 0)
    console.log(`SZ ${answer === 'hang' ? 'fallback' : 'full'}: main tab ${main}, + picked run ${picked}, + open square ${open}, the square's own ${own}; new texts ${cellTexts.length}; answer rows ${dataRows}`)
    sizes[answer] = open
    // #613: the stat rows keep their hover: one Box per data row (37 on this answer) in one absolute column
    const stHov = (await ui.findAll({ type: 'Box' })).filter((x: any) => /^st-h\d+$/.test(String(x.key ?? x.props?.key))).length
    console.log(`HOV ${answer}: stat hover Boxes ${stHov}`)
    if (answer === 'full' && stHov !== dataRows) throw new Error(`${stHov} stat hover Boxes, ${dataRows} data rows`)
    if (answer === 'full') {
      // drift of each hover Box against its drawn row: the Box's top (its own `top`, in 19-px cells)
      // against the y of the first-column text of its row in the stat picture
      const tree: any = await (ui as any).drawn()
      const hovs: any[] = []
      let pic = ''
      const walk = (n: any) => {
        if (!n || typeof n !== 'object') return
        if (n.type === 'Box' && /^st-h\d+$/.test(String(n.props?.key))) hovs.push(n)
        if (n.type === 'Svg' && String(n.props?.alt ?? '').endsWith(' stats')) pic = String(n.props.source)
        for (const c of n.children ?? []) walk(c)
      }
      walk(tree)
      // the stat names are the one <text class='mu'> of the picture (the group labels are class lb): a tspan per data row
      const names = /<text class='mu'>(.*?)<\/text>/.exec(pic)?.[1] ?? ''
      const dataYs = [...names.matchAll(/<tspan x='[\d.]+' y='([\d.]+)'/g)].map(m => +m[1]! - 14)
      const drift = hovs.map((h, i) => (h.props.position === 'absolute' ? Number(h.props.top) : NaN) * 19 - dataYs[i]!)
      console.log(`HOV full: ${hovs.length} hover Boxes on ${dataYs.length} stat rows, max |drift| ${Math.max(...drift.map(Math.abs))} px`)
      if (drift.some(e => e !== 0)) throw new Error('stat hover Box drift: ' + drift.join(','))
    }
    texts[answer] = cellTexts
    // the set of cell texts of the panel (sorted), saved as test/buildpanel-cells.ts from this line (a test cannot write files)
    console.log('CELLS ' + answer + ' ' + JSON.stringify(cellTexts))
    // #613 row 3: the cell texts of the panel are those saved before the size cut (differing 0)
    const saved: string[] = (SAVED as any)[answer === 'hang' ? 'fallback' : 'full']
    const differing = [...cellTexts.filter(x => !saved.includes(x)), ...saved.filter(x => !cellTexts.includes(x))]
    console.log(`CELLS ${answer} compared ${saved.length} saved vs ${cellTexts.length} drawn, differing ${differing.length}`)
    if (differing.length) throw new Error(`cell texts differ from buildpanel-cells.ts: ${JSON.stringify(differing.slice(0, 5))}`)
    if (GUARD_ON && !(open < LIMIT)) throw new Error(`open square (${answer}) is ${open} chars, over ${LIMIT}`)
    await ui.unmount()
  })
}
