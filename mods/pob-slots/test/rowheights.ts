// #837 (rows the baseline's way): the px a card's rows stack to, read from the drawn tree. The mock does not lay out, so this is the small
// layout the engine applies to what these cards draw: an Svg is its `height` prop in px, a Text is one 19-px line, a Box with a `height` is that
// many cells (19 px) or its share, a column Box is the sum of its in-flow children (+ marginTop / marginBottom / paddingTop / paddingBottom in cells,
// + `gap`), a row Box the highest child, an absolute or `display: none` Box takes no room.
// The same functions read the tree of main and the tree of 50ea5412 (the baseline), so a row's height is the same number on both sides or it is a difference.
export const CELL = 19
const kidsOf = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
const num = (v: unknown) => (typeof v === 'number' ? v : 0)
/** the room a node takes in its parent's flow, px */
export const flowH = (n: any): number => {
  if (!n || typeof n !== 'object') return 0
  const p = n.props ?? {}
  if (n.type === 'Svg') return num(p.height)
  if (n.type === 'Text' || n.type === 'Link' || n.type === 'Button') return CELL
  if (n.type !== 'Box') return kidsOf(n).reduce((s, c) => s + flowH(c), 0)
  if (p.position === 'absolute' || p.display === 'none') return 0
  const own = typeof p.height === 'number' ? p.height * CELL : NaN
  const ks = kidsOf(n).filter(c => !(c.type === 'Box' && (c.props?.position === 'absolute' || c.props?.display === 'none')))
  const inner = p.flexDirection === 'row' ? Math.max(0, ...ks.map(flowH)) : ks.reduce((s, c) => s + flowH(c), 0) + Math.max(0, ks.length - 1) * num(p.gap) * CELL
  return (Number.isFinite(own) ? own : inner) + (num(p.marginTop) + num(p.marginBottom) + num(p.paddingTop) + num(p.paddingBottom)) * CELL
}
/** the in-flow Svgs of a card in order (the title picture, then its rows), each with its height prop and its markup */
export const flowSvgs = (n: any, out: { h: number; src: string }[] = []) => {
  if (!n || typeof n !== 'object') return out
  const p = n.props ?? {}
  if (n.type === 'Svg') { out.push({ h: num(p.height), src: String(p.source ?? '') }); return out }
  if (n.type === 'Box' && (p.position === 'absolute' || p.display === 'none')) return out
  for (const c of kidsOf(n)) flowSvgs(c, out)
  return out
}
