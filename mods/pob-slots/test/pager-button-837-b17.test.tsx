import { test, expect } from 'claude-code/testing'
import { mountPane, svgWords, shown } from './kit'
import { LIVE_FAST } from './fast-live'
import { LIVE as TODAY } from './tickets-live-20261011'

// #837 b17 item 1 (the owner's hand, 2026-10-13: a pager word took 10-20 clicks; the ghost link of b8 landed on the host's 19-px line grid, off its text): the pager words «новее» / «старее» of the
// «Готово» list (hist-prev / hist-next) and of the grid of builds (grid-prev / grid-next) are host Buttons with a VISIBLE label on their label row, as in the old build; the picture draws no pager word and
// the Markdown ghost link of these keys is gone. A word at the end of the range stays visible and dim and takes no press.
// Fixture: the live payload of 2026-10-11 07:19 (6 finished runs a page, 13 pages) whose first running run shows a grid of 27 builds (8 a page).
const RUN = 'j-20261011-0419-7609'
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
const keyOf = (n: any) => String(n.key ?? n.props?.key ?? '')
const PAGER = /^(hist|grid)-(prev|next)$/
const payload = () => {
  const d = JSON.parse(LIVE_FAST)
  const run = d.runs.running.find((j: any) => j.id === RUN)
  const tpl = run.progress.cells.find((c: any) => c.state === 'running')
  const cells = Array.from({ length: 27 }, (_, i) => ({ ...tpl, ref: `ref_${String(i + 1).padStart(2, '0')}`, name: `Smite ${i + 1}`, seed: 1, state: 'waiting', variant: undefined, started_est: undefined, started: undefined, expect_s: undefined }))
  run.progress = { ...run.progress, done: 0, total: 27, total_open: false, cells }
  d.runs.running = [run, ...d.runs.running.filter((j: any) => j !== run)]
  return JSON.stringify(d)
}
const mount = async ($: any, on: any) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  return mountPane($, on, 'desktop', { tab: 'pob', fast: payload(), tickets: TODAY }, 123)
}
/** the two counters of the runs card ("1–6 из 80" of Готово, "1–8 из 27" of the grid), in drawing order, read from the card's picture */
const counters = async (ui: any): Promise<string[]> => {
  const out: string[] = []
  walk(await (ui as any).drawn(), n => { if (n.type === 'Svg') for (const m of String(n.props?.source ?? '').matchAll(/(\d+–\d+ из \d+)/g)) out.push(m[1]!) })
  return out
}

// #994 (the owner, 14.10: the pager words become two icon buttons): each pager is two chevrons drawn in the picture with a BLANK host Button over the live one; the end of the range is
// drawn dim (the faint shape) and is no Button at all: it lights nothing and takes no press. No pager word is drawn anywhere.
test('#994 pager: the live chevrons are blank host Buttons, the dim end is no Button, no ghost link, no pager word anywhere', { timeoutMs: 120_000 }, async ($, on) => {
  const ui = await mount($, on)
  const tree = shown(await (ui as any).drawn())
  const btn: { key: string; label: string; dim: boolean }[] = [], md: string[] = [], words: string[] = []
  walk(tree, n => {
    if (n.type === 'Button' && PAGER.test(keyOf(n))) btn.push({ key: keyOf(n), label: String(n.props?.label ?? ''), dim: !!n.props?.dimColor })
    if (n.type === 'Markdown' && PAGER.test(keyOf(n))) md.push(keyOf(n))
    if (n.type === 'Svg') words.push(...svgWords(String(n.props?.source ?? '')).filter(w => w === 'новее' || w === 'старее'))
  })
  console.log(`#837 b17 pager: ${md.length} Markdown ghost links, ${btn.length} Buttons with a label (${btn.map(b => `${b.key} "${b.label}"${b.dim ? ' dim' : ''}`).join(', ')}), ${words.length} picture texts holding a pager word`)
  expect(md, 'Markdown ghost links of hist-* / grid-*').toEqual([])
  expect(btn.map(b => b.key).sort(), 'the first page: only the two «next» chevrons are Buttons').toEqual(['grid-next', 'hist-next'])
  expect(btn.filter(b => b.label.trim()).map(b => b.key), 'Buttons with a non-blank label').toEqual([])
  expect(btn.filter(b => b.dim).map(b => b.key), 'no dim Button').toEqual([])
  expect(words, 'the picture draws no pager word').toEqual([])
  await ui.unmount()
})

test('#994 pager: a press on each chevron changes the page, both pagers, both directions (the dim end is no Button)', { timeoutMs: 120_000 }, async ($, on) => {
  const ui = await mount($, on)
  const c0 = await counters(ui)
  expect(c0.length, 'two counters').toBe(2)
  expect(c0[0], 'Готово page 1').toMatch(/^1–6 /)
  expect(c0[1], 'grid page 1').toBe('1–8 из 27')
  await ui.press({ key: 'hist-next' })
  const c1 = await counters(ui)
  expect(c1[0], 'hist-next moves the Готово page').toMatch(/^7–12 /); expect(c1[1], 'the grid stays').toBe(c0[1])
  await ui.press({ key: 'hist-prev' })
  expect(await counters(ui), 'hist-prev moves back').toEqual(c0)
  await ui.press({ key: 'grid-next' })
  const c2 = await counters(ui)
  expect(c2[1], 'grid-next moves the grid page').toBe('9–16 из 27'); expect(c2[0], 'Готово stays').toBe(c0[0])
  await ui.press({ key: 'grid-prev' })
  expect(await counters(ui), 'grid-prev moves back').toEqual(c0)
  console.log(`#837 b17 pager: hist-next ${c0[0]} -> ${c1[0]}, hist-prev back; grid-next ${c0[1]} -> ${c2[1]}, grid-prev back; dim presses at page 1 move nothing`)
  await ui.unmount()
})
