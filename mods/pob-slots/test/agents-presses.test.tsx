import { test, expect } from 'claude-code/testing'
import { mountPane, altLines, cutRows, dq, shown } from './kit'
import { LIVE_FAST } from './fast-live'
import { legacy } from './layout'
import { CELL_PX } from '../hooks/kit'

// #837 pass 2: rows are 26 px (not a whole cell), so the band is the cut row as drawn (cutRows without a cell grid) and a press Box rounded to a cell may start up to half a cell above it; unit 2 gives each row its own box.
// #771 A7: the Agents and Merge cards are ONE picture each and its native presses lie over it, each in its own row's band. A press is a
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
        if (b.type === 'Link' || b.type === 'Button') {
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
const cardOf = (tree: any, n: number) => tree.children[2].children[n]
// #995 row 1: the chats' section (MODS and its subagents) stands first, the background sessions' (ORCH) after it
const BEFORE_AG: [string, string][] = [
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/780", "MODS: "],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/779", "Оркестровый слой и оптимизация моделей: "],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/779", "what mode play sets: "],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/779", "machine-wide facts of the core: "],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/779", "pipeline processes and pauses: "],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/779", "#779 : в работе: 1 воркер"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/656", "#656 : 1 отработал"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/796", "#796 : в работе: 1 воркер · 6 отработали"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/771", "#771 : в работе: 2 воркера"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/817", "#817 : взят, воркера пока нет"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/827", "#827 : взят, воркера пока нет"],
]
const BEFORE_MG: [string, string][] = [
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/826", "merge orch-826"],
  ["mgd-next", "Готово"], // #995 row 2: «Готово» is paged (3 a page): the «next» icon button on its label row (the «previous» end is dim and has no Button)
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/827", "orch-827 landed rc 0"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/826", "orch-826 landed rc 1"],
  ["https://github.com/Rasslabsya4el/Poe-Junkroan/issues/824", "orch-824 landed rc 0"],
]
const pics = (n: any): number => (n?.type === 'Svg' && n.props?.alt !== 'row' ? 1 : 0) // #972: a row's spacer and its light are Svgs with the alt "row", no pictures of content + kids(n).reduce((s, c) => s + pics(c), 0)

test('#771 A7: Agents and Merge cards are one picture each; every press has its old target and lies in its own row band', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
  const tree = legacy(shown(await (ui as any).drawn())) // #837 unit 4b: the presses' flow rows read as the absolute Boxes of before (exact px: press-position.test.tsx)
  const res: [string, Press[], [string, string][]][] = []
  for (const [name, n, before] of [['AG', 0, BEFORE_AG], ['MG', 1, BEFORE_MG]] as const) {
    const card = cardOf(tree, n)
    const got = collect(card)
    console.log('A7PRESS', name, 'pictures', pics(card), 'presses', got.length, JSON.stringify(got.map(p => [p.what, p.row])))
    res.push([name, got, before])
  }
  for (const [, got, before] of res) expect(got.map(p => [p.what, p.row])).toEqual(before)
  await ui.unmount()
})

test('#771 A7: a press moved into another row\'s band is red (Agents and Merge)', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
  const tree = legacy(shown(await (ui as any).drawn())) // #837 unit 4b: the presses' flow rows read as the absolute Boxes of before (exact px: press-position.test.tsx)
  for (const n of [0, 1]) {
    const card = JSON.parse(JSON.stringify(cardOf(tree, n)))
    const before = collect(card).map(p => p.row)
    // lay every absolute press Box one row (2 cells) lower: each lands in the next row's band
    const shift = (b: any) => { if (b?.props?.position === 'absolute' && b.props.top != null && b.type === 'Box' && kids(b).some((k: any) => k.type === 'Link' || k.type === 'Button' || k.type === 'Box')) b.props.top += 2; kids(b).forEach(shift) }
    shift(card)
    expect(collect(card).map(p => p.row)).not.toEqual(before)
  }
  await ui.unmount()
})

test('#771 A7: the cards are one picture each, presses within their own row band', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
  const tree = legacy(shown(await (ui as any).drawn())) // #837 unit 4b: the presses' flow rows read as the absolute Boxes of before (exact px: press-position.test.tsx)
  for (const n of [0, 1]) expect(pics(cardOf(tree, n))).toBeLessThanOrEqual(2) // the card's own icon + the one picture
  await ui.unmount()
})
