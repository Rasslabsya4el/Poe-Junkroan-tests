// #671 row 4: the cell texts of every ticket row of a drawn Tickets tab, whatever the way the picture is built.
// A row = its hover Box `hv-tk-<n>` (its own absolute Box: top and height in grid lines) over the table's Svg; the row's cells are the tspans
// whose y lies on its lines, the icons placed there (inline or by <use> of a <defs> icon: the same colour and path),
// and the native Link / Button labels inside the Box. The x of a cell is not part of it (a page fits its own columns).
import { GRID } from '../hooks/tokens'
import { CELL_PX } from '../hooks/kit'
import { dq, isLead } from './kit'

const walk = (n: any, f: (n: any, parent: any) => void, parent: any = null) => {
  if (n == null || typeof n !== 'object') return
  f(n, parent)
  for (const c of n.children ?? []) walk(c, f, n)
}
type Item = { x: number; y: number; sig: string }
const items = (svg: string): Item[] => {
  const out: Item[] = []
  for (const m of svg.matchAll(/<tspan x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]*)<\/tspan>/g)) out.push({ x: +m[1], y: +m[2], sig: `T:${m[3]}` })
  const head = (body: string) => body.slice(0, 48)
  const paint = (a: string) => (/fill="(#\w+)"/.exec(a)?.[1] ?? '') + '/' + (/stroke="(#\w+)"/.exec(a)?.[1] ?? '')
  const defs = new Map<string, { a: string; inner: string; body: string }>()
  for (const m of svg.matchAll(/<g id="(i\d+)" transform="translate\([^)]*\) scale\([^)]*\)" ([^>]*)><g ([^>]*)>(.*?)<\/g><\/g>/g)) defs.set(m[1], { a: m[2], inner: m[3], body: m[4] })
  for (const m of svg.matchAll(/<g transform="translate\(([\d.\-]+) ([\d.\-]+)\) scale\([^)]*\)" ([^>]*)><g ([^>]*)>(.*?)<\/g><\/g>/g)) {
    const size = 12
    out.push({ x: Math.round((+m[1] + size / 2) * 10) / 10, y: Math.round((+m[2] + size / 2) * 10) / 10, sig: `I:${paint(m[3])}:${m[4]}:${head(m[5])}` })
  }
  for (const m of svg.matchAll(/<use href="#(i\d+)" x="([\d.\-]+)" y="([\d.\-]+)"\/>/g)) {
    const d = defs.get(m[1])
    if (d) out.push({ x: +m[2], y: +m[3], sig: `I:${paint(d.a)}:${d.inner}:${head(d.body)}` })
  }
  return out
}
/** ticket number -> sorted cell signatures, over every table of the drawn tree. */
export const cellsOf = (tree: any): Record<number, string[]> => {
  const res: Record<number, string[]> = {}
  walk(tree, (node) => {
    const kids: any[] = node.children ?? []
    const svg = kids.find(c => c?.type === 'Svg' && String(c.props?.source ?? '').includes('<tspan'))
    if (!svg) return
    const it = items(dq(String(svg.props.source)))
    // #837 pass 2: each row has its OWN absolute hover Box (its `top` and `height` in cells)
    const boxes = kids.filter(c => c?.type === 'Box' && c.props?.position === 'absolute' && /^hv-tk-\d+$/.test(String(c?.props?.key)))
    if (!boxes.length) return
    for (const b of boxes) {
      const m = /^hv-tk-(\d+)$/.exec(String(b.props.key))!
      const topCells = Number(b.props.top)
      // the row's picture band is the grid line its top cell is
      const top = topCells * CELL_PX, bot = top + Math.max(1, Math.round(b.props.height ?? 1)) * CELL_PX
      const here: Item[] = it.filter(i => i.y >= top && i.y < bot)
      walk(b, (n, parent) => {
        if (isLead(parent, n)) return // #972: the lead of a pointer element (no-break spaces before its Button) is a position, not a cell text
        if (n.type === 'Link') here.push({ x: 1e6, y: top, sig: `L:${n.props.label}|${n.props.href}` })
        else if (n.type === 'Button') here.push({ x: 1e6 + 1, y: top, sig: `B:${n.props.label}` })
        else if (n.type === 'Text' && typeof n.children?.[0] === 'string' && n !== b) here.push({ x: 1e6 + 2, y: top, sig: `X:${n.children[0]}` })
      })
      res[+m[1]] = here.sort((a, c) => a.x - c.x || a.y - c.y).map(i => i.sig)
    }
  })
  return res
}
