import { test, expect } from 'claude-code/testing'
import { mountPane, altLines, cutRows, dq, shown } from './kit'
import { LIVE_FAST } from './fast-live'
import { CELL_PX, PILL, rowsSvg } from '../hooks/kit'
import { CARD_PITCH } from '../hooks/tokens'
import { spots, isBlank } from './layout'

// #837 pass 2 (baseline 50ea5412; the pass-1 drift test assumed a 19 px cell per strip row and is replaced): a strip row is
// 26 px (CARD_PITCH), not a whole number of engine cells, so what the kit promises is its own geometry: `rowsSvg` returns
// each row's top (`tops`) and height (`hs`) in px, the register gives a press Box exactly that span (register.tsx, unit 2),
// and the row's pill (20 px, rx 10) lies inside it: drift 0 px by construction. The mounted cards keep their press count and
// the one-picture rail.
type Band = { alt: string; top: number; h: number; own: number }
const kids = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
const bandsOf = (svg: any): Band[] => {
  const src = dq(String(svg.props?.source ?? '')), H = Number(/height="([\d.]+)"/.exec(src)?.[1] ?? 0)
  if (altLines(svg.props?.alt).length < 2) return [{ alt: String(svg.props?.alt ?? ''), top: 0, h: H, own: H }]
  let y = 0
  return cutRows(svg.props.alt, src, CELL_PX).map(c => { const h = Number(/height="([\d.]+)"/.exec(c.src)?.[1]); const ys = [...c.src.matchAll(/<text [^>]*? y="([\d.]+)"/g)].map(m => Number(m[1])); const b = { alt: c.alt, top: y, h, own: ys.length ? Math.ceil(Math.max(...ys) / CELL_PX) * CELL_PX : h }; y += h; return b })
}
// a gap row (one blank cell, no drawing, so no row of its own in a cut picture) ends the band of the row before it: the row's own height is the whole cells down to its last text line
type Drift = { what: string; row: string; top: number; height: number; dTop: number; dH: number }
const drifts = (card: any): Drift[] => {
  const out: Drift[] = []
  const walk = (n: any) => {
    const ks = kids(n)
    ks.forEach((c, i) => {
      if (c.type !== 'Svg') return
      const bands = bandsOf(c)
      // #837 (rows the baseline's way): a press lies in the Box of its own row (a blank Svg of the row's px height), read by `spots` in px
      if (isBlank(c)) return
      for (let j = i + 1; kids(n)[j]?.type === 'Box' && kids(n)[j].props?.position === 'absolute'; j++) {
        for (const s of spots(kids(n)[j], 0, Number(c.props?.height ?? 0))) {
          const near = [...bands].sort((x, y) => Math.abs(s.top - x.top) - Math.abs(s.top - y.top))[0]!
          out.push({ what: s.el.type === 'Link' ? String(s.el.props.href) : String(s.el.props.key), row: near.alt, top: s.top, height: s.bottom - s.top, dTop: s.top - near.top, dH: s.bottom - s.top - near.own })
        }
      }
    })
    for (const c of ks) walk(c)
  }
  walk(card)
  return out
}
// #972: a row's spacer and its light (the soft shape shown under the pointer) are Svgs with the alt "row": no pictures of content
const pics = (n: any): number => (n?.type === 'Svg' && !isBlank(n) && n.props?.alt !== 'row' ? 1 : 0) + kids(n).reduce((s, c) => s + pics(c), 0)
// #983: the runs card is the first card of the tab «POB»
const CARDS: [string, number, number, string?][] = [['Agents', 0, 11], ['Merge', 1, 5], ['PoB runs', 0, 25, 'pob']] // #994: the first page's dim «previous» chevron is no Button; #995: Merge's «Готово» is paged (its «next» chevron)

for (const [name, n, count, tab] of CARDS) {
  test(`#837: ${name} card: ${count} presses, one picture (the rows' px geometry is the kit's, tested below)`, async ($, on) => {
    on('fs.write', async () => ({ value: undefined }) as any)
    const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST, tab }, 123)
    const card = shown(await (ui as any).drawn()).children[2].children[n]
    const d = drifts(card)
    console.log(`PRESSES ${name}: presses ${d.length}, pictures ${pics(card)} (card icon + 1)`)
    expect(d.length).toBe(count)
    expect(pics(card)).toBeLessThanOrEqual(2) // the card's own icon + the one picture
    await ui.unmount()
  })
}

test('#837 pass 2: rowsSvg gives every strip row its own span: top = n x 26 px, height 26 px, its 20 px pill inside it', () => {
  const rows = [0, 1, 2, 3].map(i => ({ r: { kind: 'strip' as const, state: 'active' as const, text: `row ${i}`, ticket: { n: 700 + i, href: `https://github.com/x/y/issues/${700 + i}` } }, i }))
  const m = rowsSvg(rows, [{ key: 'name', x: 36, w: 400 }] as any, 600)
  const src = dq(m.svg)
  const pills = [...src.matchAll(/<rect [^>]*?height="20" rx="10"[^>]*?>/g)].length
  console.log(`ROWSSVG tops ${JSON.stringify(m.tops)} hs ${JSON.stringify(m.hs)} h ${m.h} pills ${pills}`)
  expect(CARD_PITCH).toBe(26)
  expect(PILL).toBe(20)
  expect(m.hs.every(h => h === CARD_PITCH)).toBe(true)
  expect(m.tops).toEqual([0, 26, 52, 78])
  expect(m.h).toBe(4 * CARD_PITCH)
  expect(pills).toBeGreaterThanOrEqual(4)
})
