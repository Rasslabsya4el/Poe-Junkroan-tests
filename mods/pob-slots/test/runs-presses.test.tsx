import { test, expect } from 'claude-code/testing'
import { mountPane, altLines, cutRows, dq, shown } from './kit'
import { LIVE_FAST } from './fast-live'
import { legacy } from './layout'
import { CELL_PX } from '../hooks/kit'

// #771 A6: the PoB runs card is ONE picture and its native presses lie over it, each in its own row's band. A press is a
// Link / Button in an absolute Box over a picture; the row it is in = the picture's row (a merged picture is cut by
// cutRows) whose px band holds the Box's top (cells * 19 px). Placing by px without the cell conversion drifts, and a
// press laid in another row's band is red here. Fixture: the live `fast` payload of 2026-10-11 07:19, 123 columns.
type Band = { alt: string; top: number; h: number }
type Press = { what: string; row: string; top: number }

const kids = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
const bandsOf = (svg: any): Band[] => {
  const src = dq(String(svg.props?.source ?? '')), H = Number(/height="([\d.]+)"/.exec(src)?.[1] ?? 0)
  if (altLines(svg.props?.alt).length < 2) return [{ alt: String(svg.props?.alt ?? ''), top: 0, h: H }]
  let y = 0
  return cutRows(svg.props.alt, src).map(c => { const h = Number(/height="([\d.]+)"/.exec(c.src)?.[1]); const b = { alt: c.alt, top: y, h }; y += h; return b })
}
// #972: a ticket number is drawn in the picture and a blank Button `lk-<card><row>-#N` lies over it; its press opens the issue URL, so the old expectation reads the key as that URL
const ticketUrl = (key: string): string => { const m = /^lk-.*-#(\d+)$/.exec(key); return m ? `https://github.com/Rasslabsya4el/Poe-Junkroan/issues/${m[1]}` : key }
/** the presses over each picture: [what it targets, the row it lies in, its top in cells] */
const collect = (tree: any): Press[] => {
  const out: Press[] = []
  const walk = (n: any) => {
    const ks = kids(n)
    ks.forEach((c, i) => {
      if (c.type !== 'Svg') return
      const bands = bandsOf(c)
      const find = (b: any, top: number) => {
        const t = top + (b.props?.position === 'absolute' ? Number(b.props?.top ?? 0) : 0)
        if (b.type === 'Link' || b.type === 'Button' || b.type === 'Markdown') {
          const px = t * CELL_PX
          // the row whose top is nearest to the press, and the press must lie in it (at most half a cell above its top, above its bottom)
          const near = [...bands].sort((x, y) => Math.abs(px - x.top) - Math.abs(px - y.top))[0]
          const band = near && px >= near.top - CELL_PX / 2 && px < near.top + near.h ? near : { alt: '(none)' }
          out.push({ what: b.type === 'Link' ? String(b.props.href) : ticketUrl(String(b.props.key)), row: band.alt, top: t })
        }
        for (const k of kids(b)) find(k, t)
      }
      for (let j = i + 1; kids(n)[j]?.type === 'Box' && kids(n)[j].props?.position === 'absolute'; j++) find(kids(n)[j], 0)
    })
    for (const c of ks) walk(c)
  }
  walk(tree)
  return out
}
const runsCard = (tree: any) => tree.children[2].children[0] // #983: the first card of the tab «POB»

// the presses of the card before A6 (each row its own picture, the press at its top): target and the row's alt line
const BEFORE: [string, string][] = [
  ["run-pick-j-20261011-0335-a997", "P1-#779-2 running, P1, pc, 1 слот"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/779", "P1-#779-2 running, P1, pc, 1 слот"],
  ["run-pick-j-20261011-0419-7609", "P1-#813-4 running: 1 / 7 билдов, P1, pc, 3 слота"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/813", "P1-#813-4 running: 1 / 7 билдов, P1, pc, 3 слота"],
  ["run-pick-j-20261011-0430-e070", "P1-#816 running: 1 / 2 билда, P1, pc, 1 слот"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/816", "P1-#816 running: 1 / 2 билда, P1, pc, 1 слот"],
  ["run-pick-j-20261011-0719-0ba0", "P1-#817-2 running, P1, pc, 1 слот"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/817", "P1-#817-2 running, P1, pc, 1 слот"],
  ["run-pick-j-20261011-0451-2cc8", "filler-absolution_minions-4 running, P2, laptop, 1 слот"],
  ["run-pick-j-20261011-0451-08c9", "filler-absolution_minions-5 running, P2, laptop, 1 слот"],
  ["run-pick-j-20261011-0451-ce79", "filler-absolution_minions-6 running, P2, laptop, 1 слот"],
  // #994: the first page's «previous» chevron is drawn dim and is no Button (it lights nothing)
  ["hist-next", "Готово"],
  ["run-hist-j-20261011-0445-a7c8", "P1-#817 failed, P1, pc"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/817", "P1-#817 failed, P1, pc"],
  ["run-hist-j-20261011-0430-2696", "P1-#816-3 done, P1, pc, 1 / 1 билд"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/816", "P1-#816-3 done, P1, pc, 1 / 1 билд"],
  ["run-hist-j-20261011-0419-2070", "P1-#813-2 done, P1, pc, 7 / 7 билдов"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/813", "P1-#813-2 done, P1, pc, 7 / 7 билдов"],
  ["run-hist-j-20261011-0419-e12c", "P1-#813-3 done, P1, pc, 7 / 7 билдов"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/813", "P1-#813-3 done, P1, pc, 7 / 7 билдов"],
  ["run-hist-j-20261011-0430-98a5", "P1-#816-2 done, P1, pc, 1 / 1 билд"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/816", "P1-#816-2 done, P1, pc, 1 / 1 билд"],
  ["run-hist-j-20261011-0025-b1e5", "P1-#785 stopped, P1, pc"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/785", "P1-#785 stopped, P1, pc"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/779", "Билды #779"],
]

test('#771 A6: the PoB runs card is one picture; every press has its old target and lies in its own row band', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: LIVE_FAST }, 123)
  const card = runsCard(legacy(shown(await (ui as any).drawn()))) // #837 unit 4b: the presses' flow rows read as the absolute Boxes of before (exact px: press-position.test.tsx)
  const pics = (n: any): number => (n?.type === 'Svg' && n.props?.alt !== 'row' ? 1 : 0) // #972: a row's spacer and its light are Svgs with the alt "row", no pictures of content + kids(n).reduce((s, c) => s + pics(c), 0)
  const got = collect(card)
  console.log('RUNS-PRESSES pictures', pics(card), 'presses', got.length)
  expect(got.length).toBe(25) // #994: the pager is two icon buttons; the dim «previous» of the first page is no Button
  expect(got.map(p => [p.what, p.row])).toEqual(BEFORE)
  expect(pics(card)).toBeLessThanOrEqual(2) // the card's own icon + the one picture
  await ui.unmount()
})

test('#771 A6: a press moved into another row\'s band is red', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: LIVE_FAST }, 123)
  const card = JSON.parse(JSON.stringify(runsCard(legacy(shown(await (ui as any).drawn())))))
  const before = collect(card).map(p => p.row)
  // lay every absolute press Box one row (2 cells) lower: each lands in the next row's band
  const shift = (n: any) => { if (n?.props?.position === 'absolute' && n.props.top != null && n.type === 'Box' && kids(n).some((k: any) => k.type === 'Link' || k.type === 'Button' || k.type === 'Markdown' || k.type === 'Box')) n.props.top += 2; kids(n).forEach(shift) }
  shift(card)
  const after = collect(card).map(p => p.row)
  expect(after).not.toEqual(before)
  await ui.unmount()
})
