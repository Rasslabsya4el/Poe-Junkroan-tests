import { test, expect } from 'claude-code/testing'
import { mountPane, seen, svgRows, pressStale } from './kit'
import { LIVE_FAST } from './fast-live'
import { LIVE as TODAY } from './tickets-live-20261011'

// #837 b9a A1: the host keeps the handler a link got when it was first mounted, so a ghost link's press runs the closure of an OLD render
// (owner, build 837-b8: a second press on a run title did nothing). A press must decide from the atom's value at PRESS time. The mock's
// `ui.press` always calls the newest handler; `pressStale` (kit) starts the presses together, so every one of them runs the closure of
// the one render they were all resolved from, which is what an old handler does.
const open = async ($: any, on: any) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  return mountPane($, on, 'desktop', { tab: 'pob', fast: LIVE_FAST, tickets: TODAY }, 123)
}
const pageLabel = async (ui: any) => {
  for (const s of await svgRows(ui)) { const m = /(\d+–\d+ из \d+)/.exec(String(s.props?.source ?? '')); if (m) return m[1] }
}
const J1 = 'run-pick-j-20261011-0419-7609' // the second running run (the first one is the designed fallback)

test('#837 b9a A1: a second press on a run title, from the same old handler, closes the run', { timeoutMs: 90_000 }, async ($, on) => {
  const ui = await open($, on)
  const before = await seen(ui)
  await ui.press({ key: J1 })
  const picked = await seen(ui)
  expect(picked, 'one press selects the run: the pane changed').not.toEqual(before)
  await ui.press({ key: J1 }) // the newest handler: closes (already worked)
  expect(await seen(ui)).toEqual(before)
  await pressStale(ui, J1, 2) // select, then close, both from one render
  expect(await seen(ui), 'two presses from one old render: the second closes it').toEqual(before)
  await pressStale(ui, J1, 3) // select, close, select
  expect(await seen(ui), 'three presses from one old render: open').toEqual(picked)
  await ui.unmount()
})

test('#837 b9a A1: the pager "старее" pressed twice from one old render goes page 1 -> 2 -> 3', { timeoutMs: 90_000 }, async ($, on) => {
  const ui = await open($, on)
  expect(await pageLabel(ui)).toBe('1–6 из 509')
  await pressStale(ui, 'hist-next', 2)
  expect(await pageLabel(ui)).toBe('13–18 из 509')
  await ui.unmount()
})

test('#837 b9a A1: "новее" from page 3, two presses from one old render, lands on page 1', { timeoutMs: 90_000 }, async ($, on) => {
  const ui = await open($, on)
  await pressStale(ui, 'hist-next', 2)
  expect(await pageLabel(ui)).toBe('13–18 из 509')
  await pressStale(ui, 'hist-prev', 2)
  expect(await pageLabel(ui)).toBe('1–6 из 509')
  await ui.unmount()
})
