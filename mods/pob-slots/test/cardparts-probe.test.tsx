import { test } from 'claude-code/testing'
import { mountPane } from './kit'
import { LIVE_FAST } from './fast-live'

// #771 A5: what a card's characters are, by part (probe: prints tables; asserts only that the parts sum to the card's
// length within 1 %). Fixture: the live `fast` payload of 2026-10-11 07:19 at 123 columns desktop. No product code.
// A picture = a node whose props.source is a string; a pressed-row picture = a picture whose parent holds an absolutely
// positioned Box (the native presses laid over it). Native = those absolute Boxes (Box/Link/Button JSON). Everything of
// the card that is neither a picture nor native is "card chrome" (the card's own Boxes, headers, spacers).
const PARTS = ['style', 'dither', 'icons', 'text', 'frames'] as const
type Part = typeof PARTS[number]
const L = (s: string) => JSON.stringify(s).length - 2 // a string's size inside the JSON
const kids = (n: any): any[] => (Array.isArray(n?.children) ? n.children : Array.isArray(n?.props?.children) ? n.props.children : []).filter((c: any) => c && typeof c === 'object')
const isAbs = (n: any) => n?.props?.position === 'absolute'

type Pic = { pressed: boolean; node: any; json: number; overhead: number; parts: Record<Part, number>; styleKey: string; dith: string[]; icons: string[] }

function splitSource(src: string) {
  const parts: Record<Part, number> = { style: 0, dither: 0, icons: 0, text: 0, frames: 0 }
  const dith: string[] = []
  const icons: string[] = []
  let rest = src
  const take = (re: RegExp, part: Part, key?: (m: string) => void) => {
    rest = rest.replace(re, (m: string) => { parts[part] += L(m); key?.(m); return '' })
  }
  let styleKey = ''
  take(/<style>[\s\S]*?<\/style>/g, 'style', m => { styleKey = m })
  take(/<pattern\b[\s\S]*?<\/pattern>/g, 'dither', m => dith.push(m.replace(/ id="[^"]*"/, '')))
  // icon defs: what is left inside <defs> after the patterns (an icon def is a <g|path id=..> with its path data)
  rest = rest.replace(/<defs>([\s\S]*?)<\/defs>/g, (m, inner: string) => {
    const wrapOverhead = L('<defs></defs>')
    // gradients, masks, clips in defs are frames; the icon defs are the elements carrying a path d= and an id
    const left = inner.replace(/<(g|path)\b[^>]*\bid="[^"]*"[^>]*?(\/>|>[\s\S]*?<\/\1>)/g, (e: string) => { parts.icons += L(e); icons.push((/ d="([^"]*)"/.exec(e)?.[1]) ?? e); return '' })
    parts.frames += wrapOverhead + L(left)
    return ''
  })
  // inline icons: an element with translate()+scale() on itself (rowIcon)
  take(/<path\b[^>]*transform="translate\([^"]*\) scale\([^"]*\)"[^>]*\/>/g, 'icons', m => icons.push(/ d="([^"]*)"/.exec(m)?.[1] ?? m))
  take(/<g\b[^>]*transform="translate\([^"]*\) scale\([^"]*\)"[^>]*>(?:(?!<g\b)[\s\S])*?<\/g>/g, 'icons', m => icons.push(m.replace(/^<g[^>]*>/, '')))
  take(/<text\b[\s\S]*?<\/text>/g, 'text')
  parts.frames += L(rest)
  return { parts, dith, icons, styleKey }
}

function collect(card: any) {
  const pics: Pic[] = []
  let native = 0, nativeN = 0
  const walk = (n: any, parent: any) => {
    if (typeof n?.props?.source === 'string') {
      const ks = parent ? kids(parent) : []
      const sp = splitSource(n.props.source)
      const json = JSON.stringify(n).length
      const srcJson = L(n.props.source)
      pics.push({ pressed: ks.some(isAbs), node: n, json, overhead: json - srcJson, ...sp })
      return
    }
    if (isAbs(n)) { native += JSON.stringify(n).length; nativeN++; return }
    kids(n).forEach(c => walk(c, n))
  }
  walk(card, null)
  return { pics, native, nativeN }
}

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0)
const uniq = (xs: string[]) => sum([...new Set(xs)].map(x => L(x)))

test('probe: what a card draws, by part, at 123 columns (live 2026-10-11 07:19 fast payload)', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
  const tree: any = await (ui as any).drawn()
  const cards = tree.children[2].children.slice(0, 5)
  const names = ['Agents', 'Merge', 'PoB runs']
  let rptTotal = 0
  for (const [ci, name] of names.entries()) {
    const card = cards[ci]
    const total = JSON.stringify(card).length
    const { pics, native, nativeN } = collect(card)
    const pr = pics.filter(p => p.pressed), up = pics.filter(p => !p.pressed)
    const col = (ps: Pic[], f: (p: Pic) => number) => sum(ps.map(f))
    const rows: [string, number, number][] = [
      ...PARTS.map(k => [k, col(pr, p => p.parts[k]), col(up, p => p.parts[k])] as [string, number, number]),
      ['svg element JSON (key/alt/width/height)', col(pr, p => p.overhead), col(up, p => p.overhead)],
    ]
    const picsTotal = col(pics, p => p.json)
    const chrome = total - picsTotal - native
    console.log(`CP ${name}: total ${total}, ${pics.length} pictures (${pr.length} pressed, ${up.length} unpressed), ${nativeN} native boxes ${native}, card chrome ${chrome}`)
    console.log(`CP ${name}  part | pressed-row pictures | unpressed pictures | native elements`)
    for (const [k, a, b] of rows) console.log(`CP ${name}  ${k} | ${a} | ${b} | -`)
    console.log(`CP ${name}  native Box/Link/Button JSON | - | - | ${native}`)
    console.log(`CP ${name}  card chrome (not picture, not native) | ${chrome}`)
    const rStyle = col(pics, p => L(p.styleKey)) - uniq(pics.map(p => p.styleKey))
    const rDith = col(pics, p => p.parts.dither) - uniq(pics.flatMap(p => p.dith))
    const rIcon = col(pics, p => p.parts.icons) - uniq(pics.flatMap(p => p.icons))
    // icons: only the path data is shared by a def; the per-use transform/paint stays, so this is the path data's repeats
    const rIconData = sum(pics.flatMap(p => p.icons).map(x => L(x))) - uniq(pics.flatMap(p => p.icons))
    const rpt = rStyle + rDith + rIconData
    rptTotal += rpt
    console.log(`CP ${name}  repeated per picture: style ${rStyle}, dither ${rDith}, icons (path data repeats) ${rIconData} [icon elements overall ${col(pics, p => p.parts.icons)}, repeat-minus-one by whole element ${rIcon}] = ${rpt}`)
    const sumParts = sum(rows.map(r => r[1] + r[2])) + native + chrome
    if (Math.abs(sumParts - total) > total * 0.01) throw new Error(`${name}: parts ${sumParts} vs total ${total}`)
  }
  console.log(`CP repeated per picture, three cards: ${rptTotal}`)
})
