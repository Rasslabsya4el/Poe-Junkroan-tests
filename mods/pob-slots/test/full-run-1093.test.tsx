import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen } from './kit'

// #1093 (the owner's screenshot, 15.10 18:1x: the Merge card read «очередь: 0 идёт, 0 ждёт» and «Идёт: ничего» while the
// full run on main held the merge lock): the card draws `merge.full_run` (merge-status) as one running row under «Идёт»,
// merge first when both run, and the header counts it. Drawn from the pane's words (seen) on both surfaces.

const GHOST = JSON.parse(FAST)
const withMerge = (merge: any) => JSON.stringify({ ...GHOST, merge })
const card = (all: string[]) => all.slice(all.indexOf('Merge'), all.indexOf('PoB runs'))
// the fixture of #1093: `merge-status --json` with no merge running and the full run on main at 69 %, one failure
const FULL = { commit: '5d825abb', started: '2026-10-15T17:57:04', elapsed_s: 1199, percent: 69, tests_done: 2, tests_total: 3,
  failed: 1, out: 'var/agentops/full_run/5d825abb.out', eta_s: 100 }
const BUSY = { branches: ['orch-677'], issues: [677], phase: 'suite', started: '2026-10-15T17:50:00', percent: 62,
  tests_done: 2647, tests_total: 4270, failed: 0, eta_s: 140, workers: 6, suite_out: 'x.out' }

for (const surface of ['terminal', 'desktop'] as const) {
  // 1. a full run on main and no merge: one row named by its commit, its failure in the failed style, the header counts it
  test(`${surface}: #1093 a full run on main with no merge draws its row under Идёт and counts it`, async ($, on) => {
    const merge = { at: '2026-10-15T18:00:00', running: null, waiting: [], landed: [], full_run: FULL }
    const ui = await mountPane($, on, surface, { fast: withMerge(merge) }, 123)
    const all = card(await seen(ui))
    const need = ['full run on main 5d825abb', 'упало 1, ещё ~2 мин', '20 мин', 'очередь: 1 идёт, 0 ждёт']
    const miss = need.filter(n => !all.includes(n))
    if (miss.length) throw new Error('full run row or header missing: ' + JSON.stringify(miss) + ' in ' + JSON.stringify(all))
    if (all.includes('Идёт: ничего') || all.includes('ничего')) throw new Error('the card still says nothing runs: ' + JSON.stringify(all))
  })

  // 2. a merge and the full run at once: both rows, the merge first; the header counts both
  test(`${surface}: #1093 a merge and the full run at once draw two rows, the merge first, and the header says 2 идёт`, async ($, on) => {
    const merge = { at: '2026-10-15T18:00:00', running: BUSY, waiting: [], landed: [], full_run: { ...FULL, failed: 0 } }
    const ui = await mountPane($, on, surface, { fast: withMerge(merge) }, 123)
    const all = card(await seen(ui))
    // the first words of each row: the desktop card repeats the branch in a later table, so the first occurrence is the row's
    const iM = all.findIndex(x => x.includes('orch-677'))
    const iF = all.indexOf('full run on main 5d825abb')
    if (iM < 0 || iF < 0 || !(iM < iF)) throw new Error('merge row not before the full run row: ' + JSON.stringify(all))
    if (!all.includes('очередь: 2 идёт, 0 ждёт')) throw new Error('header does not count both: ' + JSON.stringify(all))
  })

  // 3. the full run with no failure: the running phase («тесты») and its time left, no «упало»
  test(`${surface}: #1093 a full run with no failure reads «тесты, ещё ~N» and draws no «упало»`, async ($, on) => {
    const merge = { at: '2026-10-15T18:00:00', running: null, waiting: [], landed: [], full_run: { ...FULL, failed: 0 } }
    const ui = await mountPane($, on, surface, { fast: withMerge(merge) }, 123)
    const all = card(await seen(ui))
    if (!all.includes('тесты, ещё ~2 мин')) throw new Error('no running-phase act on the full run row: ' + JSON.stringify(all))
    if (all.some(x => x.startsWith('упало'))) throw new Error('a failure word on a full run with no failure: ' + JSON.stringify(all))
  })

  // 4. full_run null: the card draws as before (no row, the header counts nothing)
  test(`${surface}: #1093 full_run null draws no full run row and the header counts 0`, async ($, on) => {
    const merge = { at: '2026-10-15T18:00:00', running: null, waiting: [], landed: [], full_run: null }
    const ui = await mountPane($, on, surface, { fast: withMerge(merge) }, 123)
    const all = card(await seen(ui))
    if (all.some(x => x.includes('full run on main'))) throw new Error('a full run row with full_run null: ' + JSON.stringify(all))
    if (!all.includes('очередь: 0 идёт, 0 ждёт')) throw new Error('header changed with full_run null: ' + JSON.stringify(all))
  })
}
