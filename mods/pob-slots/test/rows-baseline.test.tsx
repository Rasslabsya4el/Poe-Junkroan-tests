import { test, mock, expect } from 'claude-code/testing'
import { FAST, SLOW, ORCH, TICKETS } from './fixtures'
import { LIVE_FAST } from './fast-live'
import { BUILD_816 } from './buildpanel-answer'
import { PROPS, dq, mountG } from './kit'
import { flowH, flowSvgs } from './rowheights'
import { BASELINE_ROWS } from './baseline-rows-837'
import { HEAD_PITCH } from '../hooks/tokens'

// #837 (rows the baseline's way): the px height of every row and of each of the three cards of the Главная tab (Агенты, Merge, PoB runs) equals what the
// baseline 50ea5412 renders for the same fixture, in three cases (live-fast, full, open-square: the Stormbrand square of the live run open, the build
// answer in). The baseline's numbers are `baseline-rows-837.ts` (generated: `python scripts/baseline_rows_837.py --write`, which renders the baseline's own
// hooks on these fixtures; `--check` compares). A row's height here is read from the markup of the card's one picture: each row is its own
// `<g transform='translate(0 y)'>` (a row with no drawing, the 4-px gap, a zero-size `<g .../>` at its top), a row's height = the next row's top - its top.
//
// THE ONE KEPT DIFFERENCE (decided by ORCH 23f3edea, ticket rule 3): the column-head row (F04, the owner's table rule of #793, `test/rules.test.tsx`)
// does not exist in the baseline. It is the first row of each card's picture, HEAD_PITCH = 22 px (the baseline's label height), so each of the three
// cards is HEAD_PITCH taller than the baseline; it is excluded below, by name, and checked to be that high. Every other row and every card height equals the baseline's.
const CASES: [string, string, boolean][] = [['live-fast', LIVE_FAST, false], ['full', FAST, false], ['open-square', LIVE_FAST, true]]
const NAMES = ['Agents', 'Merge', 'PoB runs']

/** the rows of a picture, top to bottom, from its markup: the first at 0, each other at its `translate(0 y)` (a body or a zero-size marker) */
const rowHeightsOf = (src: string): number[] => {
  const s = dq(src)
  const H = Number(/^<svg[^>]* height="([\d.]+)"/.exec(s)?.[1])
  const tops = [0, ...[...s.matchAll(/<g transform="translate\(0 ([\d.]+)\)"\s*\/?>/g)].map(m => Number(m[1]))]
  return tops.map((t, i) => (i + 1 < tops.length ? tops[i + 1]! : H) - t)
}

/** #837 b10 S3: the row index (as in rowHeightsOf) of the «Билды» section's own head row (the word «сиды»), -1 when the picture has none */
const buildsHeadAt = (src: string): number => {
  const s = dq(src)
  const at = s.indexOf('>сиды<')
  return at < 0 ? -1 : [...s.matchAll(/<g transform="translate\(0 ([\d.]+)\)"\s*\/?>/g)].filter(m => m.index! < at).length
}

for (const [name, fast, build] of CASES) {
  test(`#837: ${name}: every row and card height of Agents, Merge and PoB runs is the baseline's (50ea5412), the head row the one kept difference`, { timeoutMs: 90_000 }, async ($, on) => {
    const clock = mock.clock(on)
    const all: Record<string, string> = { fast, tickets: TICKETS, slow: SLOW, orch: ORCH }
    on('process.run', async (_$: any, e: any) => {
      if (e.argv[2] === 'build') return { value: { exitCode: 0, stdout: BUILD_816, stderr: '', isStdoutTruncated: false } } as any
      return { value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
    })
    on('ui.open', async () => ({ value: { isOpen: true } }) as any)
    on('ui.status', async () => ({ value: undefined }) as any)
    on('fs.write', async () => ({ value: undefined }) as any)
    void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
    await clock.settle()
    const ui: any = await mountG($, { plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) })
    // #983: Agents and Merge are read on «Главная», the runs card on the tab «POB»
    const mainCards = (await ui.drawn()).children[2].children.slice(0, 2)
    await ui.press({ key: 'tab-pob' })
    if (build) {
      const job = JSON.parse(fast).runs.running.find((j: any) => j.id === 'j-20261011-0430-e070')
      await ui.press({ key: `run-pick-${job.id}` }); await clock.settle()
      await ui.press({ key: `cell-${job.id}-stormbrand-1` }); await clock.settle()
    }
    const cards = [...mainCards, (await ui.drawn()).children[2].children[0]]
    const diffs: string[] = []
    cards.forEach((card: any, n: number) => {
      // #837 u14 (autopilot comparison 6116270633 row 3): the baseline's 4-px gap rows between Agents sessions are pictures of their own that the host
      // lays out as round(4 / 19) = 0 cells: its sessions stood 26 px apart in the picture of the baseline. They are no row of the tip at all.
      const w0 = BASELINE_ROWS[name]![NAMES[n]!]!
      const gaps = w0.rows.filter(x => x === 4).length
      const want = { ...w0, h: w0.h - 4 * gaps, rows: w0.rows.filter(x => x !== 4) }
      // #837 b9a (A5, the owner's wish): a picked run with no builds draws ONE placeholder row («пусто», 26 px) under its «Билды» label, which the baseline left empty: the live-fast PoB runs card ends with it
      if (name === 'live-fast' && NAMES[n] === 'PoB runs') { want.h += 26; want.rows = [...want.rows, 26] }
      // #1093: the LIVE_FAST payload carries a real `merge.full_run`, so the Merge card draws its row (a 26 px row and the 30 px one of its track) after the first queue row: 56 px the baseline never had
      if (name !== 'full' && NAMES[n] === 'Merge') { want.h += 56; want.rows = [...want.rows.slice(0, 4), 26, 30, ...want.rows.slice(4)] }
      const svgs = flowSvgs(card)
      // the card's title picture, then the one picture of its rows, then what stands under it (the open square's own pictures)
      // #994 (defect 11): the gap above the open build is a blank picture of one line (it was `marginTop={1}`, which the host drew as half a line): the card's height counts it as the margin was, it is no row
      const title = svgs[0]!.h, rows = rowHeightsOf(svgs[1]!.src), rest = svgs.slice(2).filter(s => !/^<svg[^>]*\/>$/.test(dq(s.src))).map(s => s.h)
      // #837 b10 S3: the second kept difference: the builds section's head row, taken out of the rows by its word and checked to be HEAD_PITCH high
      const bh = buildsHeadAt(svgs[1]!.src)
      const bhRow = bh > 0 ? rows.splice(bh, 1)[0]! : 0
      if (bh > 0 && bhRow !== HEAD_PITCH) diffs.push(`${NAMES[n]}: builds head row ${bhRow} px, want ${HEAD_PITCH}`)
      const head = rows.shift()!
      // #995 row 1: the third kept difference: the Agents card's two section labels («Чаты», «Фоновые сессии»), a queue's label row of LABEL_PITCH (22 px) each, taken out here
      let secs = 0
      if (NAMES[n] === 'Agents') for (let i = rows.length - 1; i >= 0; i--) if (rows[i] === 22) { rows.splice(i, 1); secs++ }
      if (NAMES[n] === 'Agents' && secs !== 2) diffs.push(`Agents: ${secs} section label rows, want 2`)
      const got = [title, ...rows, ...rest]
      // #837 b9a (B4): the PoB runs card's rows picture is padded (blank, at the bottom) up to whole 19-px screen lines, so its LAST row and the card are taller than the baseline's by that pad (0 up to one line); it is cut off here and checked to be less than a line
      let pad = 0
      if (NAMES[n] === 'PoB runs') {
        const last = rows.length // index in `got` of the rows picture's last row (the title is 0)
        pad = Math.round((got[last]! - want.rows[last]!) * 100) / 100
        if (!(pad >= 0 && pad < 20)) diffs.push(`${NAMES[n]}: the rows picture's last row is ${pad} px taller than the baseline, want a pad from 0 to under one line`)
        else got[last] = got[last]! - pad
      }
      const h = Math.round((flowH(card) - HEAD_PITCH - (bh > 0 ? HEAD_PITCH : 0) - pad - 22 * secs) * 100) / 100
      console.log(`ROWS ${name} ${NAMES[n]}: head row ${head} px (kept), ${got.length} rows + title, card ${flowH(card)} px = baseline ${want.h} + ${HEAD_PITCH} + pad ${pad}; rows ${JSON.stringify(got)}`)
      if (head !== HEAD_PITCH) diffs.push(`${NAMES[n]}: head row ${head} px, want ${HEAD_PITCH}`)
      if (h !== want.h) diffs.push(`${NAMES[n]}: card ${h} px without the head, baseline ${want.h}`)
      if (got.length !== want.rows.length) diffs.push(`${NAMES[n]}: ${got.length} rows, baseline ${want.rows.length}`)
      got.forEach((x, i) => { if (Math.abs(x - want.rows[i]!) > 0.005) diffs.push(`${NAMES[n]} row ${i}: ${x} px, baseline ${want.rows[i]}`) })
    })
    console.log(`ROWS ${name}: rows differing from the baseline ${diffs.length}`)
    expect(diffs.join('; ')).toBe('')
    await ui.unmount()
  })
}

test('#837: the baseline table is the table of the three cases and three cards', () => {
  expect(Object.keys(BASELINE_ROWS)).toEqual(CASES.map(c => c[0]))
  for (const c of Object.values(BASELINE_ROWS)) expect(Object.keys(c)).toEqual(NAMES)
})
