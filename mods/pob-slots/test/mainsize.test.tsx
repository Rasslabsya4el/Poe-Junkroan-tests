import { test } from 'claude-code/testing'
import { mountPane } from './kit'
import { LIVE_FAST } from './fast-live'

// #771 A1: the main tab on a live-sized `fast` payload (bin/.cache/shared-fast.json of 2026-10-11 07:19: 6 agent rows
// with their subagents, a merge with running + full_run + landed, runs on PC and laptop): the desktop stops redrawing a
// tree past ~100k characters, so the main tab stays under 90k. Before #771 A3 it drew ~122,150 chars on this payload; A3
// (a run of rows with no press = ONE picture) ~113,100; A6 (the PoB runs card = ONE picture, the presses laid over it)
// ~95,150; A7 (the Agents and Merge cards too) ~78,800.
test('desktop, 123 columns: the main tab on the live payload of 2026-10-11 07:19 draws under 90,000 characters', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST, faces: true }, 123)
  const tree: any = await (ui as any).drawn()
  const sz = JSON.stringify(tree).length
  const cards = tree.children[2].children.slice(0, 5)
  console.log('SZ live main tab', sz, 'per card', ['Agents', 'Merge', 'PoB runs', 'PC', 'Laptop'].map((n, i) => `${n} ${JSON.stringify(cards[i]).length}`).join(', '))
  if (!(sz < 90_000)) throw new Error('main tab is ' + sz + ' chars, over 90,000')
})
