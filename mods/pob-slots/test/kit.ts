import { mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { PX_PER_COL, NBSP_PX, BLANK_PX, LABEL_EM, LABEL_NB, LABEL_PAD } from '../hooks/kit'

// Shared by the main-tab tests (#683 r3): mount the pane on a surface with the collector's answers, and read
// every word it shows, wherever the design put it (a Text, a Link, a picture's alt, the words inside a picture).
export const PROPS = (cols = 60): any =>
  ({ title: 'Junkroan', isFocused: false, bodyColumns: cols, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} })

/** #837 b17f: the ascendancy faces the pane reads from the mod's assets/asc (`<name>_16x16.png`, as bytes), at the REAL size: a 16 px face file is ~786 bytes = 1,048 base64 characters (1,070 as the data URI the pane embeds).
 *  Until now `$.fs.read` was not mocked in the size tests, the faces came out empty and every size they printed was ~19,000 characters short of the pane's (18 faces on the runs card of the real payload).
 *  The characters are made from the name (a distinct face a name), valid base64 alphabet, not a picture: only the length matters to a size test. */
export const FACE_BASE64_CHARS = 1048
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
export const faceBase64 = (name: string) => {
  let h = 2166136261
  for (const ch of name) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0
  let s = ''
  for (let i = 0; i < FACE_BASE64_CHARS; i++) { h = (Math.imul(h, 1664525) + 1013904223) >>> 0; s += B64[h >>> 26] }
  return s
}
/** the file reader of the size tests: a 16 px face of the mod's assets/asc answers with its bytes, anything else is not there */
export const faceReads = (on: any) =>
  on('fs.read', async (_$: any, e: any) => {
    const m = /[\\/]asc[\\/](\w+)_16x16\.png$/.exec(String(e.path))
    if (m && e.as === 'bytes') return { value: { base64: faceBase64(m[1]!) } } as any
    throw new Error('ENOENT ' + e.path)
  })

/** #983: `tab` = the tab the test reads (its id: 'pob' = the tab «POB» with the runs card, since #972 no longer on «Главная»): pressed once the pane is mounted */
export async function mountPane($: any, on: any, surface: 'terminal' | 'desktop', out: { fast?: string; tickets?: string; faces?: boolean; tab?: string }, cols = 60) {
  if (out.faces) faceReads(on)
  const clock = mock.clock(on)
  const all: Record<string, string> = { fast: out.fast ?? FAST, tickets: out.tickets ?? TICKETS, slow: SLOW, orch: ORCH }
  on('process.run', async (_$: any, e: any) =>
    ({ value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = ghostPress(surface === 'desktop', await $.ui.mount({ plugin: 'pob-slots', surface, component: 'Pane', requestId: 'pob', props: PROPS(cols) }))
  if (out.tab) { await ui.press({ key: `tab-${out.tab}` }); await clock.settle() }
  return ui
}
/** #983: one reading over several tabs, in order (`ids`: 'main', 'pob', ...): each tab is pressed and read, the readings joined. For a test that speaks of cards which stood on one tab before #972. */
export const onTabs = async <T,>(ui: any, ids: string[], read: (ui: any) => Promise<T[]>): Promise<T[]> => {
  const out: T[] = []
  for (const id of ids) { await ui.press({ key: `tab-${id}` }); out.push(...await read(ui)) }
  return out
}
/** #972: a row's light: the soft rounded shape shown under the pointer = an absolute Box (`display` none, flex on hover) holding one Svg with the alt "row", the first child of the row's keyed Box.
 *  `true` when `box` (a card row's or a table row's keyed Box) carries it. */
export const rowLight = (box: any): boolean => (box?.children ?? []).some((c: any) => c?.type === 'Box' && c.props?.position === 'absolute' && c.props?.display === 'none' && c.hover?.display === 'flex'
  && (c.children ?? []).some((s: any) => s?.type === 'Svg' && s.props?.alt === 'row' && /fill-opacity='\.07'/.test(String(s.props?.source ?? ''))))
/** #983: the tab «POB» of a pane mounted by hand (`$.ui.mount`): the runs card, the picked run's builds and the open build live there */
export const toPob = async (ui: any, clock?: { settle: () => Promise<unknown> }) => { await ui.press({ key: 'tab-pob' }); await clock?.settle(); return ui }

/** #837 b8: the presses over a card's picture (a run's title, a seed) are no Buttons but a Markdown ghost link of no-break spaces; `ui.press` of their key presses that link.
 *  #837 b17: the pager words are host Buttons with a visible label again (their keys are gone from here).
 *  #837 b18: a run's title is a host Button with a visible label too (the keys run-pick- / run-q- / run-hist- are gone from here). */
export const GHOST_KEY = /^cell-/
export const GHOST_HREF = 'https://a.invalid'
/** #837 b11 D6: the seeds of one row are the links of ONE Markdown: its key is its first seed's key, each link is `https://a.invalid/<the seed key's tail after the stem>` (the stem = the Markdown's key less the first
 *  link's tail). A Markdown node as its links `{ key, n, off }`: the seed key each names, a copy of the node holding that one link alone (what a single ghost link was: `[nbsp...](GHOST_HREF)`), and the no-break spaces
 *  before it in the text (`off`: those of the gaps and of the links before). A Markdown with no such link gives itself, `key` = its own. */
const LINK = /\]\(https:\/\/a\.invalid\/([^)]*)\)/g
export const seedLinks = (md: any): { key: string; n: any; off: number }[] => {
  const text = String(md?.props?.text ?? md?.text ?? ''), mk = String(md?.props?.key ?? md?.key ?? '')
  const links = [...text.matchAll(LINK)]
  if (!links.length) return [{ key: mk, n: md, off: 0 }]
  const stem = mk.slice(0, mk.length - decodeURIComponent(links[0]![1]!).length)
  return links.map(m => {
    const start = text.lastIndexOf('[', m.index!), key = stem + decodeURIComponent(m[1]!)
    return { key, off: text.slice(0, start).replace(/\[|\]\([^)]*\)/g, '').length, n: { ...md, props: { ...md.props, key, text: text.slice(start, m.index!) + '](' + GHOST_HREF + ')' } } }
  })
}
export const ghostPress = (on: boolean, ui: any) => {
  if (!on) return ui
  const out = Object.create(ui)
  Object.defineProperty(out, 'press', { value: async (target: any) => {
    if (typeof target?.key !== 'string' || !GHOST_KEY.test(target.key) || target.link) return ui.press(target)
    // #972: a seed is a plain Button (pressEl) since the one pointer element; the Markdown search below serves an older ref (scripts/pane_dump.py --ref)
    if ((await ui.findAll({ type: 'Button' })).some((b: any) => String(b.key ?? b.props?.key ?? '') === target.key)) return ui.press(target)
    // a seed of a row's one Markdown: press that Markdown (its own key) with the link's href
    if (target.key.startsWith('cell-')) {
      for (const md of await ui.findAll({ type: 'Markdown' })) {
        const mk = String(md.key ?? md.props?.key ?? '')
        if (!mk.startsWith('cell-')) continue
        const text = String(md.props?.text ?? md.text ?? ''), first = [...text.matchAll(LINK)][0]
        if (!first || !seedLinks(md).some(l => l.key === target.key)) continue
        const stem = mk.slice(0, mk.length - decodeURIComponent(first[1]!).length)
        return ui.press({ ...target, key: mk, link: { href: 'https://a.invalid/' + encodeURIComponent(target.key.slice(stem.length)) } })
      }
    }
    return ui.press({ ...target, link: { href: GHOST_HREF } })
  } })
  return out
}

/** #613: the pane writes Svg attributes with `'`; this gives a source back with `"` so the old regexes read it as before. */
export const dq = (svg: string) => flat(svg).replace(/<[a-zA-Z][^>]*>/g, tag => tag.replace(/(\s[\w:-]+)='([^"']*)'/g, '$1="$2"'))
/** #613: a shape two rows of a picture draw alike is one `<g id='bN'>` in its defs and a `<use href='#bN' paint/>` a row; this writes
 *  each use out again as the row drew it before (the paint on the first rect of a band shape, else a <g paint> around the uses) and drops the defs' copies. */
export const flat = (svg00: string) => {
  // #837 b17f: a face a picture draws twice or more is `<image id='fN' href='data:..' width height style/>` in its defs and `<use href='#fN' x y/>` where it stood: put back as it stood
  const faces = new Map<string, string>()
  const svg0 = svg00.replace(/<image id='(f\d+)' href='(data:[^']*)' width='(\d+)' height='(\d+)' style='image-rendering:pixelated'\/>/g, (_, id, href, w, h) => { faces.set(id, `href='${href}'|width='${w}' height='${h}' style='image-rendering:pixelated'`); return '' })
  const unf = faces.size ? svg0.replace(/<defs><\/defs>/, '').replace(/<use href='#(f\d+)' x='([^']*)' y='([^']*)'\/>/g, (_, id, x, y) => { const [href, rest] = faces.get(id)!.split('|'); return `<image ${href} x='${x}' y='${y}' ${rest}/>` }) : svg0
  // #837: `class='.. e'` (rule `.e{text-anchor:end}`) is `text-anchor='end' class='..'`, as the word was written
  const svg = unf.includes('.e{text-anchor:end}')
    ? unf.replace('.e{text-anchor:end}</style>', '</style>').replace(/<(?:text|tspan)[^>]*>/g, tag => tag.replace(/ class='([^']*) e'/, " text-anchor='end' class='$1'"))
    : unf
  // #837: a shape a picture draws alike twice or more is `<tag id='qN' ../>` in its defs and `<use href='#qN'/>` where it stood: put back as it stood
  const shapes = new Map<string, string>()
  const unq = svg.replace(/<(rect|path|circle|polygon|use) id='(q\d+)'([^>]*\/>)/g, (_, tag, id, rest) => { shapes.set(id, `<${tag}${rest}`); return '' })
  const svg1 = shapes.size ? unq.replace(/<defs><\/defs>/, '').replace(/<use href='#(q\d+)'\/>/g, (_, id) => shapes.get(id)!) : unq
  const defs = new Map<string, string>()
  const body = svg1.replace(/<g id='(b\d+)'>(.*?)<\/g>/g, (_, id, c) => { defs.set(id, c); return '' })
  return defs.size ? body.replace(/<use href='#(b\d+)' ([^>]*?)\/>/g, (_, id, paint) => {
    const c = defs.get(id)!
    return c.startsWith('<rect') ? c.replace(/\/>/, ` ${paint}/>`) : `<g ${paint}>${c}</g>`
  }) : svg1
}
const unesc = (s: string) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&')
/** The words inside one SVG picture: its <text> / <tspan> runs, trimmed. */
export const svgWords = (src: string) =>
  [...src.replace(/<style>[\s\S]*?<\/style>/g, '').matchAll(/>([^<>]+)</g)].map(m => unesc(m[1]!).trim()).filter(Boolean)

/** #837: a card row's link is a ghost: a Link holding a transparent Text (its word is drawn in the row's picture). */
export const ghostText = (n: any): string | null => {
  const t = (n?.children ?? []).find((c: any) => c?.type === 'Text' && c.props?.color === '#00000000')
  return t ? (t.children ?? []).map((c: any) => (typeof c === 'string' ? c : '')).join('') : null
}
/** a Link's word: its `label`, or its ghost's text */
export const linkLabel = (n: any): string => String(n?.props?.label ?? ghostText(n) ?? '')

/** Every word on the pane in drawing order: Texts, Link labels, and each picture's alt then its words. */
export async function seen(ui: any): Promise<string[]> {
  const out: string[] = []
  const walk = (n: any) => {
    if (!n || typeof n !== 'object') return
    if (n.type === 'Text') { out.push(textOf(n)); return }
    if (n.type === 'Link') { if (!n.props?.label && ghostText(n)) return; out.push(String(n.props?.label ?? '')) } // #837: a ghost Link (a #00000000 Text) speaks with the word its row's picture draws
    if (n.type === 'Button') out.push(String(n.props?.label ?? ''))
    // #972: a Svg with the alt "row" is a row's spacer or its light (the shape shown under the pointer): it says no word of the pane
    if (n.type === 'Svg' && n.props?.alt !== 'row') { out.push(...altLines(n.props?.alt)); out.push(...svgWords(String(n.props?.source ?? ''))) }
    for (const c of n.children ?? []) walk(c)
  }
  const textOf = (n: any): string => typeof n === 'string' ? n : (n.children ?? []).map(textOf).join('')
  walk(await ui.drawn())
  return out
}

/** The icons of one picture in drawing order (a state mark, a rail icon): which one (told by its path), its colour,
 *  its left edge, whether it spins, and `reused` = it is a <use> of an icon drawn earlier in the picture (a strip
 *  draws a still seed mark once: its later ones are the same drawing moved by x). */
const ICON_PATH: [string, string][] = [['done', 'm10.28-1.72'], ['failed', 'M6.03 4.97'], ['running', 'M21 12a9'], ['waiting', 'Zm7-3.25v2.992']]
export const marks = (src0: string) => {
  const src = dq(src0)
  const byId: Record<string, { kind: string; color: string; x: number; spin: boolean }> = {}
  const out: { kind: string; color: string; x: number; spin: boolean; reused: boolean }[] = []
  // #771: a row picture draws an icon as one <path> or one <g> with its own transform and paint; an icon used twice or
  // more in a merged picture is one def (<defs><path id="iN"/>) and a <use href="#iN" transform paint/> each.
  const defs: Record<string, string> = {}
  for (const d of src.matchAll(/<(path|g) id="(i\d+)"[^>]*?(?:\/>|>(.*?)<\/g>)/g)) defs[d[2]!] = d[0]
  const AT = String.raw`transform="translate\(([\d.]+) [\d.]+\) scale\([\d.]+\)"`
  const PAINT = String.raw`(?:fill="(#\w+)"|fill="none" stroke="(#\w+)"[^>]*?)`
  const re = new RegExp([
    String.raw`<g(?: id="(\w+)")? ${AT} ${PAINT}>(<g[^>]*>)?(.*?)<\/g>`,  // 1 id, 2 x, 3 fill, 4 stroke, 5 inner <g>, 6 body
    String.raw`<path(?: id="(\w+)")? ${AT} ${PAINT} d="([^"]*)"\/>`,  // 7 id, 8 x, 9 fill, 10 stroke, 11 d
    String.raw`<use href="#(i\d+)" ${AT} ${PAINT}\/>`,  // 12 ref, 13 x, 14 fill, 15 stroke
    String.raw`<use href="#(m\w)" x="([\d.]+)"\/>`,  // 16 id, 17 dx
  ].join('|'), 'g')
  for (const m of src.matchAll(re)) {
    if (m[16]) { const first = byId[m[16]]; if (first) out.push({ ...first, x: Math.round((first.x + Number(m[17])) * 10) / 10, reused: true }); continue }
    const body = m[6] ?? m[11] ?? defs[m[12]!] ?? ''
    const id = m[1] ?? m[7]
    const one = { kind: ICON_PATH.find(([, p]) => body.includes(p))?.[0] ?? '?', color: (m[3] ?? m[4] ?? m[9] ?? m[10] ?? m[14] ?? m[15])!, x: Number(m[2] ?? m[8] ?? m[13]), spin: !!m[5] && m[5].includes('class="sp"') }
    if (id) byId[id] = one
    out.push({ ...one, reused: false })
  }
  return out
}

/** The alt of a picture one line a row (a merged picture of several rows joins their alts with a newline). */
export const altLines = (alt: unknown) => String(alt ?? '').split(String.fromCharCode(10))

/** #771: a run of rows with no press is ONE picture (rowsSvg). The test reads a row as it did before: this cuts such a
 *  picture into one pseudo-picture a row (alt = that row's line; source = the picture's style and defs + that row's own
 *  drawing at its own y 0, its height the way down to the next row). A picture of one row comes back as it is. A cut
 *  that does not fit its alt lines (rows with a body and rows with an alt are not the same rows) throws. */
/** #837: `grid` = a cell grid the picture's rows sit on (rowsSvg's pitch): a row's translate is its top + a centring pad < one cell, so the row's top is the translate floored to the grid. */
export const cutRows = (alt: unknown, src0: string, grid = 0): { alt: string; src: string }[] => {
  const src = dq(src0)
  const lines = altLines(alt).filter(Boolean)
  const head = /^<svg[^>]*>/.exec(src)?.[0]
  if (!head || !src.endsWith('</svg>')) return [{ alt: String(alt ?? ''), src }]
  const inner = src.slice(head.length, -'</svg>'.length)
  const lead = /^(?:<style>[\s\S]*?<\/style>)?(?:<defs>[\s\S]*?<\/defs>)?/.exec(inner)![0]
  // #837: a zero-size `<g transform="translate(0 y)"/>` marks a row with no drawing (a gap): it is no row drawing here, the row before it keeps the gap in its height as before
  const rest = inner.slice(lead.length).replace(/<g transform="translate\(0 [\d.]+\)"\/>/g, '')
  const tops: { y: number; body: string }[] = []
  let at = 0, depth = 0, cur = '', wrap: number | null = null, y = 0
  const tag = /<(\/?)([a-zA-Z]+)([^>]*?)(\/?)>/g
  let m: RegExpExecArray | null
  let last = 0
  const flushRaw = (end: number) => { cur += rest.slice(last, end) }
  while ((m = tag.exec(rest))) {
    const [all, close, name, attrs, self] = m as unknown as string[]
    if (depth === 0 && !close) {
      // #837: a zero-size `<g transform="translate(0 y)"/>` is the marker of a row with no drawing (a gap): no body, no row drawing here
      const w = name === 'g' ? /^ transform="translate\(0 ([\d.]+)\)"$/.exec(attrs!) : null
      if (w && !self) { flushRaw(m.index); if (cur) tops.push({ y, body: cur }); cur = ''; y = grid ? Math.floor(Number(w[1]) / grid) * grid : Number(w[1]); wrap = m.index + all!.length; depth = 1; last = wrap; continue }
    }
    if (self) continue
    if (close) { depth--; if (depth === 0 && wrap != null) { tops.push({ y, body: rest.slice(wrap, m.index) }); wrap = null; cur = ''; last = m.index + all!.length } }
    else depth++
  }
  if (wrap == null) { flushRaw(rest.length); if (cur) tops.push({ y, body: cur }) }
  const H = Number(/height="([\d.]+)"/.exec(head)?.[1])
  const first = tops.length ? tops : [{ y: 0, body: '' }]
  if (first.length === 1 && lines.length <= 1) return [{ alt: lines[0] ?? '', src }]
  if (first.length !== lines.length) throw new Error(`a merged picture has ${first.length} row drawings and ${lines.length} alt lines: ${lines.join(' | ')}`)
  // #837 b9a: a still mark is drawn once for the WHOLE picture (`<g id="mw">`), a later row only `<use>`s it; a row cut out of the picture shows that mark by writing the first element out again, moved by the use's x
  const owner: Record<string, string> = {}
  for (const t of first) for (const e of t.body.matchAll(/<path id="(m\w)"[^>]*\/>|<g id="(m\w)"[^>]*>.*?<\/g>/g)) owner[e[1] ?? e[2]!] ??= e[0]
  const own = (body: string) => body.replace(/<use href="#(m\w)" x="([-\d.]+)"\/>/g, (all, id: string, dx: string) => {
    const el = owner[id]
    if (!el || body.includes(`id="${id}"`)) return all
    return el.replace(` id="${id}"`, '').replace(/translate\(([-\d.]+) /, (_m, x: string) => `translate(${Math.round((Number(x) + Number(dx)) * 10) / 10} `)
  })
  return first.map((t, k) => {
    const h = (first[k + 1]?.y ?? H) - t.y
    return { alt: lines[k]!, src: head.replace(/height="[\d.]+"/, `height="${h}"`).replace(/viewBox="0 0 ([\d.]+) [\d.]+"/, `viewBox="0 0 $1 ${h}"`) + lead + own(t.body) + '</svg>' }
  })
}

/** Every Svg node of the drawn tree, a merged picture cut into its rows (see cutRows): `props` with the row's alt and source. */
export async function svgRows(ui: any): Promise<{ props: any; n: any }[]> {
  const out: { props: any; n: any }[] = []
  for (const n of await ui.findAll({ type: 'Svg' })) {
    const src = dq(String(n.props?.source ?? ''))
    if (!altLines(n.props?.alt).filter(Boolean).length || altLines(n.props?.alt).length < 2) { out.push({ props: { ...n.props, source: src }, n }); continue }
    for (const c of cutRows(n.props?.alt, src)) out.push({ props: { ...n.props, alt: c.alt, source: c.src }, n })
  }
  return out
}

/** The bar pictures (strips and tracks) with their alt, the markup's own width and height, the Svg's width prop
 *  (absent on a grid picture: the desktop fits it to its slot) and source. */
export async function bars(ui: any) {
  return (await svgRows(ui)).map((s: any) => {
    const src = dq(String(s.props?.source ?? ''))
    const own = (k: string) => Number(new RegExp(`^<svg[^>]* ${k}="([0-9.]+)"`).exec(src)?.[1])
    return { alt: String(s.props?.alt ?? ''), width: own('width'), height: own('height'), prop: s.props?.width, src }
  })
}

/** `$.ui.mount(a)` whose `ui.press` reaches the ghost links (#837 b8) */
export const mountG = async (api: any, a: any) => ghostPress(a.surface === 'desktop', await api.ui.mount(a))

/** the number of no-break spaces in a ghost link's Markdown text `[...](https://a.invalid)`; -1 when the text is anything else */
export const ghostCells = (text: unknown): number => {
  const t = String(text ?? '')
  const pre = '[', post = '](' + GHOST_HREF + ')'
  if (!t.startsWith(pre) || !t.endsWith(post)) return -1
  const mid = t.slice(1, t.length - post.length)
  return mid.length > 0 && [...mid].every(c => c.charCodeAt(0) === 160) ? mid.length : -1
}

/** #837 b9a: `n` presses of one key, ALL resolved from the tree drawn NOW (started together, before the pane redraws): the host that keeps the handler a
 *  link first got calls the closure of an OLD render for the 2nd, 3rd press. The mock's `ui.press` redraws before it answers and always calls the newest handler, so
 *  a one-by-one press cannot show such a closure; this one can. Rejects when a press fails. */
export const pressStale = async (ui: any, key: string, n = 2) => { await Promise.all(Array.from({ length: n }, () => ui.press({ key }))) }

// ---- #972: the pointer element's place. pressEl = an absolute Box (top 0, `left` cells) holding [a Text of `lead` no-break spaces,] a plain Button; blankSpan (register.tsx) puts the
// Button's start at `left * PX_PER_COL + lead * NBSP_PX` screen px and its label is em spaces (U+2003, BLANK_PX each) + no-break spaces (U+00A0, NBSP_PX each).
const NB = String.fromCharCode(160), EMSP = String.fromCharCode(0x2003)
/** a Text of only no-break spaces: the lead of a pressEl (never a note line, never a cell text) */
export const isLeadText = (n: any): boolean => {
  if (n?.type !== 'Text') return false
  const t = (n.children ?? []).map((c: any) => (typeof c === 'string' ? c : '')).join('')
  return t.length > 0 && [...t].every(c => c === NB)
}
/** the no-break spaces of the lead Text before the Button inside an absolute Box (0 when there is none) */
export const leadOfBox = (box: any): number => {
  let lead = 0
  for (const c of box?.children ?? []) { if (c?.type === 'Button') break; if (isLeadText(c)) lead += String(c.children?.[0] ?? '').length }
  return lead
}
/** a label of only U+2003 / U+00A0 (a blank face): its width in screen px; null when the label is anything else */
export const blankPx = (label: unknown): number | null => {
  const t = String(label ?? '')
  if (!t.length || [...t].some(c => c !== NB && c !== EMSP)) return null
  // #994: as the real pane lights it (kit LABEL_*): an em space LABEL_EM, a no-break space LABEL_NB, and the host's padding
  return [...t].reduce((a, c) => a + (c === EMSP ? LABEL_EM : LABEL_NB), LABEL_PAD)
}
/** the screen px where a pressEl's Button starts: its Box's `left` cells and the lead's no-break spaces */
export const startPx = (left: number, lead: number): number => left * PX_PER_COL + lead * NBSP_PX
/** a Text of only no-break spaces standing before the Button in its parent absolute Box: the lead of a pressEl (a position, not a word: no note line, no cell text) */
export const isLead = (parent: any, n: any): boolean => {
  if (parent?.type !== 'Box' || parent.props?.position !== 'absolute' || !isLeadText(n)) return false
  const kids: any[] = parent.children ?? [], at = kids.indexOf(n), btn = kids.findIndex(c => c?.type === 'Button')
  return at >= 0 && btn > at
}

/** #995 send-back 2: a pager's dim end keeps its Button mounted in a 0 x 0 clipped Box (hooks/register.tsx `pressEl` `hidden`): nothing is drawn there and nothing takes the
 *  pointer. A test of what the pane SHOWS reads the tree with those Boxes left out. */
export const isHiddenBox = (n: any): boolean => n?.type === 'Box' && n.props?.overflow === 'hidden' && n.props?.width === 0 && n.props?.height === 0
export const shown = <T,>(tree: T): T => {
  const go = (n: any): any => {
    if (!n || typeof n !== 'object') return n
    if (Array.isArray(n)) return n.filter(c => !isHiddenBox(c)).map(go)
    const out: any = { ...n }
    if (Array.isArray(n.children)) out.children = n.children.filter((c: any) => !isHiddenBox(c)).map(go)
    if (n.props && Array.isArray(n.props.children)) out.props = { ...n.props, children: n.props.children.filter((c: any) => !isHiddenBox(c)).map(go) }
    else if (n.props && n.props.children && typeof n.props.children === 'object') out.props = { ...n.props, children: isHiddenBox(n.props.children) ? undefined : go(n.props.children) }
    return out
  }
  return go(tree)
}
/** #995 send-back 2 row 3: a table row's keyed Box (absolute, 2 cells in, to the right edge, its span high): since one light rule it draws no light of its own and holds only the row's
 *  own presses (a toggle, a ticket number), or nothing. What a test of a table's rows reads as the row's place. */
export const isRowBox = (b: any): boolean => b?.type === 'Box' && b.props?.position === 'absolute' && b.props?.left === 2 && b.props?.right === 0 && b.props?.height != null
