import { test } from 'claude-code/testing'
import { mountPane, altLines, cutRows, svgWords, dq } from './kit'
import { LIVE_FAST } from './fast-live'

// #771 A2/A3 probe: the main tab's pictures per card on the live payload (07:19), split by whether the picture has a native
// press over it (a Link/Button in the absolute Boxes that follow it, hooks/register.tsx rowOf) or none. After A3 the rows
// with no press are merged: a run of them is ONE picture (rowsSvg), so one picture here can hold many rows (`rows` counts
// the alt lines). Prints the table of what is left; asserts the cut of a merged picture into its rows (test/kit.ts
// cutRows) loses no word. Characters are JSON.stringify lengths of the drawn tree (what the desktop receives), so a quote
// inside the markup counts as 2.
const len = (n: any) => JSON.stringify(n).length
const hasPress = (n: any): boolean => !!n && typeof n === 'object' && (n.type === 'Link' || n.type === 'Button' || (n.children ?? []).some(hasPress))
// kind: a `table` (a picture at its markup's own width, `width` prop: tableSvg), a pressed row (its picture + the absolute
// Boxes after it that hold a native Link / Button: the row's own chars), or a bare row picture (no press: after A3 one
// picture holds a run of rows, `rows` = its alt lines).
type Pic = { kind: 'table' | 'pressed' | 'bare'; chars: number; rows: number; alt: string; src: string }
const picsOf = (n: any, out: Pic[]) => {
  const kids: any[] = n?.children ?? []
  kids.forEach((c, i) => {
    if (c?.type === 'Svg') {
      let j = i + 1, press = false, chars = len(c)
      while (kids[j]?.type === 'Box' && kids[j].props?.position === 'absolute' && c.props?.width == null) { press = press || hasPress(kids[j]); chars += len(kids[j]); j++ }
      out.push({ kind: c.props?.width != null ? 'table' : press ? 'pressed' : 'bare', chars, rows: altLines(c.props?.alt).filter(Boolean).length || 1, alt: String(c.props?.alt ?? ''), src: dq(String(c.props?.source ?? '')) })
    } else picsOf(c, out)
  })
}
const cards = (tree: any): [string, any][] => {
  const main = tree.children[2].children
  return [['tab bar', tree.children[0]], ...['Agents', 'Merge', 'PoB runs', 'PC', 'Laptop'].map((n, i) => [n, main[i]] as [string, any])]
}

test('rows probe: main tab 123 columns on the live payload', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
  const tree: any = await (ui as any).drawn()
  const lines = [`main tab ${len(tree)} chars`, 'card | card chars | rows with a native press (n, chars) | rows without (pictures, rows, chars) | tables (n, chars) | the rest (texts, boxes)']
  let nAll = 0, pressed = 0, bare = 0, tabs = 0, rest = 0
  for (const [name, g] of cards(tree)) {
    const pics: Pic[] = []
    picsOf(g, pics)
    const of = (k: Pic['kind']) => pics.filter(x => x.kind === k)
    const sum = (a: Pic[], f: 'chars' | 'rows') => a.reduce((s, x) => s + x[f], 0)
    const r = len(g) - sum(pics, 'chars')
    lines.push(`${name} | ${len(g)} | ${of('pressed').length}, ${sum(of('pressed'), 'chars')} | ${of('bare').length}, ${sum(of('bare'), 'rows')}, ${sum(of('bare'), 'chars')} | ${of('table').length}, ${sum(of('table'), 'chars')} | ${r}`)
    nAll += pics.length; pressed += sum(of('pressed'), 'chars'); bare += sum(of('bare'), 'chars'); tabs += sum(of('table'), 'chars'); rest += r
  }
  lines.push(`pictures ${nAll}; rows with a press ${pressed} chars, rows without ${bare}, tables ${tabs}, the rest ${rest}; of ${len(tree)}`)
  console.log('ROWS-PROBE\n' + lines.join('\n'))
})

test('rows probe: a merged picture cut into its rows keeps every word and every alt line', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
  const tree: any = await (ui as any).drawn()
  const pics: Pic[] = []
  picsOf(tree, pics)
  const merged = pics.filter(x => x.kind !== 'table' && x.rows > 1)
  if (!merged.length) throw new Error('no merged picture on the main tab: a run of rows (A3), or a card (A6, A7), is drawn as one')
  let rows = 0
  for (const m of merged) {
    const cut = cutRows(m.alt, m.src)
    rows += cut.length
    const want = altLines(m.alt).filter(Boolean)
    if (cut.length !== want.length || cut.some((c, i) => c.alt !== want[i])) throw new Error(`cut: ${cut.length} rows, ${want.length} alt lines: ${m.alt}`)
    const words = (a: string[]) => [...a].sort().join('\u0000')
    if (words(cut.flatMap(c => svgWords(c.src))) !== words(svgWords(m.src))) throw new Error(`a word lost or added by the cut of ${want[0]}`)
  }
  console.log(`merged pictures ${merged.length}, their rows ${rows}`)
})
