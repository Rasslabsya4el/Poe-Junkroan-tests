import { mock } from 'claude-code/testing'
import { dq, ghostPress, PROPS } from './kit'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { textWidth } from '../hooks/draw'
import { PX_PER_COL, CARD_CHROME_PX } from '../hooks/kit'

// #837 round 9b: shared reading of the pane's pictures for the layout tests of this round. `readPic` gives every drawn word and icon of ONE picture with its extents in SCREEN px
// (a card picture has no `width` prop: the host fits it to its slot, x * fit; a table picture is 1:1); `allPics` walks the drawn tree; `mountTab` mounts the desktop pane on a payload and opens a tab.
export type Item = { kind: 'text' | 'icon'; t: string; x0: number; x1: number; y: number; row: number; cls: string; head: boolean; bold: boolean }
const unesc = (s: string) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&')
const attr = (a: string, k: string) => new RegExp(`(?:^|\\s)${k}="([^"]*)"`).exec(a)?.[1]

/** the markup width of a picture and the factor its px are drawn at on the screen */
export const fitOf = (n: any, cols: number) => {
  const src = dq(String(n.props?.source ?? ''))
  const W = +(/^<svg[^>]* width="([\d.]+)"/.exec(src)?.[1] ?? 0)
  if (n.props?.width != null) return { W, fit: Number(n.props.width) / W }
  const SW = Math.max(300, Math.min(W, Math.round(cols * PX_PER_COL - CARD_CHROME_PX)))
  return { W, fit: SW / W }
}

export function readPic(n: any, cols: number): { items: Item[]; fit: number; W: number; H: number } {
  const src = dq(String(n.props?.source ?? ''))
  const { W, fit } = fitOf(n, cols)
  const H = +(/^<svg[^>]* height="([\d.]+)"/.exec(src)?.[1] ?? 0)
  const body = src.replace(/<style>[\s\S]*?<\/style>/, '').replace(/<defs>[\s\S]*?<\/defs>/, m => '')
  const items: Item[] = []
  // rows of a card picture: `<g transform="translate(0 Y)">` (the first row is bare)
  const marks = [...body.matchAll(/<g transform="translate\(0 ([\d.]+)\)"/g)].map(m => ({ y: +m[1]!, i: m.index! }))
  const rowAt = (i: number) => { let y = 0; for (const m of marks) if (m.i < i) y = m.y; return y }
  for (const m of body.matchAll(/<text([^>]*)>([\s\S]*?)<\/text>/g)) {
    const a = m[1]!, inner = m[2]!
    const end = /text-anchor="end"/.test(a)
    const row = rowAt(m.index!)
    const cls0 = attr(a, 'class') ?? ''
    const bold = /\b(lb|ti|nm)\b/.test(cls0)
    const spans = [...inner.matchAll(/<tspan([^>]*)>([^<]*)<\/tspan>/g)]
    const parts = spans.length ? spans.filter(s => attr(s[1]!, 'x') != null).map(s => ({ x: +attr(s[1]!, 'x')!, y: +(attr(s[1]!, 'y') ?? 0), t: unesc(s[2]!), cls: attr(s[1]!, 'class') ?? cls0 }))
      : [{ x: +(attr(a, 'x') ?? 0), y: +(attr(a, 'y') ?? 0), t: unesc(inner), cls: cls0 }]
    for (const p of parts) {
      if (!p.t.trim()) continue
      const w = textWidth(p.t, 12, bold)
      const x0 = end ? p.x - w : p.x
      const head = /\bmu\b/.test(p.cls) && /^(13|16|46)$/.test(String(p.y)) && !spans.length
      items.push({ kind: 'text', t: p.t, x0: x0 * fit, x1: (x0 + w) * fit, y: row + p.y, row, cls: p.cls, head, bold })
    }
  }
  // icons: a `<g|path transform="translate(X Y) scale(S)">` (its own 13/12 px box from X) or a `<use href="#iN" x y/>` (centred on x)
  for (const m of body.matchAll(/<(?:g|path|use)[^>]* transform="translate\(([\d.-]+) ([\d.-]+)\) scale\(([\d.]+)\)"/g)) {
    const row = rowAt(m.index!)
    items.push({ kind: 'icon', t: '', x0: +m[1]! * fit, x1: (+m[1]! + 16 * +m[3]!) * fit, y: row + +m[2]! + 8 * +m[3]!, row, cls: '', head: false, bold: false })
  }
  for (const m of body.matchAll(/<use href="#i\d+" x="([\d.-]+)" y="([\d.-]+)"\/>/g)) {
    const row = rowAt(m.index!)
    items.push({ kind: 'icon', t: '', x0: (+m[1]! - 6) * fit, x1: (+m[1]! + 6) * fit, y: row + +m[2]! + 6, row, cls: '', head: false, bold: false })
  }
  return { items, fit, W, H }
}

export const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
export const allPics = (tree: any) => { const o: any[] = []; walk(tree, n => { if (n.type === 'Svg' && typeof n.props?.source === 'string') o.push(n) }); return o }

export type Payload = { fast?: string; tickets?: string; slow?: string; orch?: string }
export async function mountTab($: any, on: any, p: Payload, tab: string | null, cols = 123, then?: (ui: any, clock: any) => Promise<void>) {
  const clock = mock.clock(on)
  const all: Record<string, string> = { fast: p.fast ?? FAST, tickets: p.tickets ?? TICKETS, slow: p.slow ?? SLOW, orch: p.orch ?? ORCH }
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.write', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = ghostPress(true, await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(cols) }))
  if (tab) { await ui.press({ key: `tab-${tab}` }); await clock.settle() }
  if (then) await then(ui, clock)
  return { ui, clock }
}
