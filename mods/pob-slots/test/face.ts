import { GHOST_PX, GHOST_PX_BOLD, drawnW, P0 } from '../hooks/kit'
import { seedW } from '../hooks/addon'
import { textWidth } from '../hooks/draw'
import { gridOf, type Placed } from './grid'
import { leadOfBox, blankPx, startPx } from './kit'

// #972: the pointer element against its drawn face. Every `pressEl` of a drawn tree (a plain Button alone in an absolute Box at top 0, [a Text of no-break spaces before it]) that lies on a card row or a
// table row, with the screen px where its light starts (the Box's `left` cells and the lead's no-break spaces) and how wide it is (em spaces + no-break spaces of a blank label), against the face the
// picture draws under it: a ticket number (`#N`, class lk in a card, ac in a table), a run title (the row's text nearest to it), a seed's capsule (the drawn number from 20 markup px left, seedW + 22 wide).
// A card's picture is fitted by the card's fit (`Placed.scale`), a table's is 1:1 and stands 2 cells right of the Box's origin (register.tsx: blankSpan(hp.x + 2, ..., 1, 2)).
export type FaceRead = { key: string; kind: 'ticket' | 'title' | 'seed' | 'visible' | 'other'; where: 'card' | 'table'; start: number; width: number | null; face: { x: number; w: number; text: string } | null; dStart: number | null; dWidth: number | null }
const TITLE = /^run-(pick|q|hist)-/
const nearest = (texts: Placed['texts'], scale: number, at: number, keep: (t: Placed['texts'][number]) => boolean) =>
  [...texts].filter(keep).sort((a, b) => Math.abs(a.x * scale - at) - Math.abs(b.x * scale - at))[0]

/** every pressEl of the tree, read against its face. `cols` = the pane's columns (the grid reader's scale). */
export const pressFaces = (tree: any, cols: number): FaceRead[] => {
  const g = gridOf(tree, cols)
  const placed = [...g.placed]
  const out: FaceRead[] = []
  const kids = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
  const walk = (n: any, box: any | null) => {
    if (!n || typeof n !== 'object') return
    if (n.type === 'Box' && n.props?.position === 'absolute') box = n
    if (n.type === 'Button') {
      const k = String(n.props?.key ?? '')
      const i = placed.findIndex(p => p.el === 'Button' && p.key === k)
      const p = i >= 0 ? placed.splice(i, 1)[0] : undefined
      if (p && box && box.props.top === 0 && n.props?.plain) {
        const where = p.card.startsWith('table') ? 'table' : 'card'
        const left = Number(box.props.left), lead = leadOfBox(box)
        const start = startPx(left + (where === 'table' ? 2 : 0), lead)
        const width = blankPx(n.props.label)
        const kind: FaceRead['kind'] = width == null ? 'visible' : /^(lk|tl)-/.test(k) ? 'ticket' : TITLE.test(k) ? 'title' : /^cell-/.test(k) ? 'seed' : 'other'
        let face: FaceRead['face'] = null
        const sc = p.scale
        if (kind === 'ticket') {
          const tail = /-(#?[0-9]+)$/.exec(k)?.[1] ?? ''
          const num = tail.startsWith('#') ? tail : '#' + tail
          const t = p.texts.find(q => q.text === num && (where === 'table' || q.cls === 'lk' || q.cls === 'ac'))
          if (t) face = { x: t.x * sc, w: (where === 'table' ? textWidth(t.text) : textWidth(t.text, 14)) * sc, text: t.text }
        } else if (kind === 'title') {
          const t = nearest(p.texts, sc, start, q => q.cls === 'nm' || q.cls === 'tx' || q.cls === 'mu' || q.cls === 'bt')
          // #995 send-back 2 row 3 (one light, the host's rectangle): a run title's press is the ROW's press, its Button laid over the row's whole pill (register.tsx rowsOne): its face starts
          // at the pill (P0 + the level's indent = the title's x less the name column's 38 - P0) and runs to the row's end, so only its start is read against the picture
          if (t) face = { x: (t.x - (38 - P0)) * sc, w: 0, text: t.text }
        } else if (kind === 'seed') {
          const t = nearest(p.texts, sc, start + 20 * sc, q => q.cls === 'tx' && /^\d+$/.test(q.text))
          if (t) face = { x: (t.x - 20) * sc, w: (seedW(t.text) + 22) * sc, text: t.text }
        }
        out.push({ key: k, kind, where, start, width, face, dStart: face ? start - face.x : null, dWidth: face && width != null && kind !== 'title' ? width - Math.max(2 * 97 / 35, face.w) : null })
      }
      return
    }
    for (const c of kids(n)) walk(c, box)
  }
  walk(tree, null)
  return out
}
