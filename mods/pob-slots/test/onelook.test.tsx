import { test, mock } from 'claude-code/testing'
import { K, GRID } from '../hooks/tokens'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { seen, svgWords, dq, isLead, rowLight, isRowBox } from './kit'
import { CELL_PX, thousands } from '../hooks/kit'

// #683 r5 (E) (owner 10.10: «должны ВСЕ таблицы быть одного вида/стиля»; «Если что то не умещается и многоточит,
// значит оно там быть не должно»): on the desktop the Tickets, Cost and Progress tabs draw every table as THE table
// of the pane (tableSvg: one plain picture on the 20-px line grid, drawn 1:1, a keyed hover Box a data row), no word
// is cut with «…», a ticket's number is a native Link over its row, and every fact the tabs showed before is shown.
const COLS = 123
const TW = Math.round(COLS * 7.8) + 4 - 4 // the table's own width: the card's content (W) less 4
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: COLS, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const OUT: Record<string, string> = { fast: FAST, tickets: TICKETS, slow: SLOW, orch: ORCH }
const tk = JSON.parse(TICKETS), slow = JSON.parse(SLOW), orch = JSON.parse(ORCH)
// tableSvg's own mark: the 1-px rule under its column labels, from the band's left edge (16) to the picture's right
const RULE = `<rect x="${GRID.band}" y="${CELL_PX - 1}" width="${TW - GRID.band}" height="1" fill="#38383c"/>`
const usd = (v: number) => `$${v >= 100 ? String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v.toFixed(2)}` // #837 b9b B7: thousands split by the counts' space
const ddmm = (v: string) => { const m = /(\d{4})-(\d{2})-(\d{2})/.exec(v)!; return `${m[3]}.${m[2]}` }
const int = (v: number) => Math.round(v).toLocaleString('en-US')
const squash = (s: string) => s.replace(/\s+/g, '')
/** #994 (a title is ONE line cut with an ellipsis): the title stands whole in the words, or its start does, right before a «…» */
const titleIn = (flat: string, title: string) => {
  if (flat.includes(squash(title))) return true
  const t = squash(title)
  for (const m of flat.matchAll(/…/g)) for (let L = t.length - 1; L >= Math.min(12, t.length - 1); L--) if (m.index! >= L && flat.slice(m.index! - L, m.index!) === t.slice(0, L)) return true
  return false
}
// the collector's «23:50:38» as a footer says it
const fresh = (at: string) => `обновлено ${at.slice(0, 5)}`
// a model id as the tabs name the model (written out here, not computed: the rule is the mod's)
const MODEL: Record<string, string> = {
  'claude-opus-5-5': 'Opus 5.5', 'claude-fable-5-1': 'Fable 5.1', 'claude-sonnet-5-5': 'Sonnet 5.5', 'claude-opus-5': 'Opus 5',
  'claude-sonnet-5': 'Sonnet 5', 'claude-haiku-4-5-20251001': 'Haiku 4.5', 'claude-haiku-5-5': 'Haiku 5.5', 'unslop view (Haiku)': 'мод unslop (Haiku)', '<synthetic>': 'служебные сообщения',
}
const model = (id: string) => MODEL[id] ?? id

const mount = async ($: any, on: any, cols = COLS) => {
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: { ...PROPS, bodyColumns: cols } })
  const go = async (key: string) => { await ui.press({ key }); await clock.settle() }
  return { ui, go }
}

// The drawn tab, read once: its pictures by sort, the native labels, and each table with its hover Boxes.
type Table = { alt: string; src: string; words: string[]; lines: number; hov: { key: string; top: number; height: number; links: { label: string; left: number; card: boolean }[]; buttons: { key: string; label: string; left: number }[] }[] }
const read = async (ui: any) => {
  const tree = await ui.drawn()
  const pics: any[] = [], tables: Table[] = [], texts: string[] = [], buttons: any[] = [], links: string[] = [], oldRows: any[] = [], cards: any[] = []
  const textOf = (n: any): string => (typeof n === 'string' ? n : (n?.children ?? []).map(textOf).join(''))
  const natives = (n: any, left: number, acc: Table['hov'][number], card = false) => {
    for (const c of n.children ?? []) {
      if (!c || typeof c !== 'object') continue
      const at = c.type === 'Box' && c.props?.position === 'absolute' && c.props?.display !== 'none' ? Number(c.props.left) : left
      if (c.type === 'Link') acc.links.push({ label: String(c.props.label), left: at, card: (n.children ?? []).some((s: any) => s?.type === 'Box' && s.props?.display === 'none' && s.hover?.display === 'flex') })
      // #972: a ticket number is drawn in the picture and a blank Button `tl-<table>-<row>-<N>` lies over it: read as the row's ticket press (label `#N`, from the key's tail)
      const tl = c.type === 'Button' ? /^tl-.*-#?(\d+)$/.exec(String(c.props.key)) : null
      if (tl) { if (!/^\s+$/.test(String(c.props.label))) throw new Error(`the ticket press ${c.props.key} is not blank`); acc.links.push({ label: `#${tl[1]}`, left: at, card: false }) }
      else if (c.type === 'Button') acc.buttons.push({ key: String(c.props.key), label: String(c.props.label), left: at })
      if (c.type === 'Box' && c.props?.display === 'none') continue // the hover card's own words are not the row's
      natives(c, at, acc, card)
    }
  }
  const walk = (n: any) => {
    if (!n || typeof n !== 'object') return
    // a ticket's hover card is no part of the tab's own look (its state mark is a small picture of its own): kept apart
    if (n.type === 'Box' && n.props?.display === 'none') { cards.push(n); return }
    if (n.type === 'Text') { texts.push(textOf(n)); return }
    if (n.type === 'Link') links.push(String(n.props?.label ?? ''))
    if (n.type === 'Button') buttons.push(n.props)
    if (n.type === 'Svg') pics.push(n.props)
    if (n.type === 'Box' && n.hover?.backgroundColor === K.hover && !/^(hv|st|mt)-/.test(String(n.props?.key))) oldRows.push(n.props?.key)
    const kids = n.children ?? []
    const first = kids[0]
    // #994: a switch line (`sw-…`) and a corner pager (`pg-…`) are a 1:1 picture with blank Buttons over it, not a table
    if (n.type === 'Box' && first?.type === 'Svg' && first.props?.width != null && !/^(sw|pg)-/.test(String(n.props?.key ?? ''))) {
      const src = dq(String(first.props.source))
      const t: Table = { alt: String(first.props.alt), src, words: svgWords(src), lines: Number(first.props.height) / CELL_PX, hov: [] }
      // #771 B2: the Cost cards' rows may stand in ONE absolute column (left 2, right 0): each child is a hover Box whose
      // top is the sum of the heights and marginTops before it; flattened here into the same rows as the one-Box-a-row form
      const flat: { c: any; top: number }[] = []
      for (const c of kids.slice(1)) {
        if (c?.type === 'Box' && c.props?.position === 'absolute' && !c.hover && c.props?.left === 2 && c.props?.right === 0 && c.props?.flexDirection === 'column') {
          let at = Number(c.props.top ?? 0)
          for (const r of c.children ?? []) { at += Number(r.props?.marginTop ?? 0); flat.push({ c: r, top: at }); at += Number(r.props?.height) }
        } else flat.push({ c, top: Number(c?.props?.top) })
      }
      for (const { c, top } of flat) {
        const inCol = c?.props?.position !== 'absolute'
        if (c?.type !== 'Box' || (!inCol && c.props?.position !== 'absolute') || !(rowLight(c) || isRowBox(c))) throw new Error(`${t.alt}: over a table lies something that is no hover Box: ${JSON.stringify(c).slice(0, 200)}`)
        // #671 u4: top / height are the engine's cells (CELL_PX px); the picture's grid line = what they round to
        const h = { key: String(c.props.key), top: Math.round(top * CELL_PX / CELL_PX), height: Math.max(1, Math.round(Number(c.props.height) * CELL_PX / CELL_PX)), links: [], buttons: [] }
        if (!inCol && (c.props.left !== 2 || c.props.right !== 0)) throw new Error(`${t.alt}: hover Box ${h.key} at left ${c.props.left} right ${c.props.right}`)
        natives(c, 0, h)
        t.hov.push(h)
      }
      tables.push(t)
    }
    for (const c of kids) walk(c)
  }
  walk(tree)
  return { tree, pics, tables, texts, buttons, links, oldRows, cards }
}

// (1a) of #683 r5, the owner 10.10 13:0x: nothing on these tabs is drawn with a text character. A state, a toggle
// and a mark are icons of the pane's set inside the picture, told here by their path; `line` = the table line an
// icon stands on, `turned` = a chevron pointing down.
const ICON: [string, string][] = [['chevron', 'M6.22 3.22'], ['work', 'M8 9.5a1.5'], ['owner', 'cy="7.5"'], ['ready', 'M0 8a8 8 0 0 1 16 0v5.25'],
  ['blocked', 'M2.75 1h10.5'], ['triage', 'stroke-dasharray'], ['open', 'M0 8a8 8 0 1 1 16 0A8'], ['closed', 'M11.28 6.78'], ['dropped', 'M5.3 5.3']]
// (#671: a table's icons are drawn once in <defs> and placed by <use>: each use is read as the icon it places)
const expandUses = (src: string) => {
  const defs = new Map([...src.matchAll(/<g id="(i\d+)" transform="translate\(-6 -6\)( scale\([\d.]+\)" .*?<\/g><\/g>)/g)].map(m => [m[1]!, m[2]!] as const))
  return src.replace(/<use href="#(i\d+)" x="([\d.]+)" y="([\d.]+)"\/>/g, (_m, id, x, y) => `<g transform="translate(${Number(x) - 6} ${Number(y) - 6})${defs.get(id)}`)
}
const icons = (src0: string, src = expandUses(src0)) =>
  [...src.matchAll(/<g transform="translate\(([\d.]+) ([\d.]+)\) scale\([\d.]+\)" (?:fill="(#\w+)"|fill="none" stroke="(#\w+)"[^>]*)><g ([^>]*)>(.*?)<\/g><\/g>/g)].map(m => ({
    kind: ICON.find(([, p]) => m[6]!.includes(p))?.[0] ?? '?', color: (m[3] ?? m[4])!, x: Number(m[1]), line: (Number(m[2]) - (CELL_PX / 2 - 6)) / CELL_PX, turned: m[5]!.includes('rotate(90'),
  }))
const GLYPH = /[▸▾▶◀▴○●◦◆◉⧗⏳✓✔✕✖⊘◷■□•←↑↓]/
const noGlyphs = async (ui: any, tab: string) => {
  const bad = (await seen(ui)).filter(w => GLYPH.test(w))
  if (bad.length) throw new Error(`${tab}: a text character stands for an icon: ${JSON.stringify(bad.slice(0, 8))}`)
}

// (a) nothing is cut: no word of a picture, no native label and no Text ends with «…»
const noDots = async (ui: any, tab: string) => {
  // (a title that GitHub itself ends with «...» is the ticket's own text, not a cut of the mod's: it may stand whole or on lines)
  const gh = Object.values(tk.issues).map((i: any) => squash(String(i.title))).filter(t => t.endsWith('...'))
  const theirs = (w: string) => gh.some(t => t.includes(squash(w)) || squash(w).includes(t))
  // #994 (the owner's rule: a title is ONE line cut with an ellipsis): a ticket's title cut at its column's end is the one cut allowed
  const titles = Object.values(tk.issues).map((i: any) => squash(String(i.title)))
  const titleCut = (w: string) => /…\s*$/.test(w) && w.replace(/…\s*$/, '').trim().length > 0 && titles.some(t => t.startsWith(squash(w.replace(/…\s*$/, ''))))
  const cut = (await seen(ui)).filter(w => (/…\s*$/.test(w) || /\.\.\.$/.test(w.trim())) && !theirs(w) && !titleCut(w))
  if (cut.length) throw new Error(`${tab}: cut with «…»: ${cut.slice(0, 5).join(' | ')}`)
}
// (b) every picture of the tab is the tab bar, a card's title band, the legend, or THE table: tableSvg's rule under
// the labels, drawn 1:1 at the table's width on the 20-px grid, plain (not interactive); a hover Box a data row, each
// on its own lines, none past the picture; and no table of the older sorts (a hover Row of Cells, a `─` rule of text).
const oneLook = (r: Awaited<ReturnType<typeof read>>, tab: string, want: string[]) => {
  const other = r.pics.filter(p => p.width == null).map(p => String(p.alt))
  const tabsBar = other.filter(a => a.startsWith('Главная'))
  if (tabsBar.length !== 1) throw new Error(`${tab}: ${tabsBar.length} tab bars`)
  const exact = r.pics.filter(p => p.width != null && !/^\[|·.*\[|из \d+$/.test(String(p.alt))) // #994: the switch lines (their chosen word in [ ]) and a corner pager's counter are no tables
  if (exact.length !== r.tables.length) throw new Error(`${tab}: ${exact.length} 1:1 pictures, ${r.tables.length} of them tables`)
  if (r.tables.map(t => t.alt).join('|') !== want.join('|')) throw new Error(`${tab}: tables ${r.tables.map(t => t.alt).join('|')}, want ${want.join('|')}`)
  for (const p of exact) {
    const src = dq(String(p.source))
    const own = (k: string) => Number(new RegExp(`^<svg[^>]* ${k}="([0-9.]+)"`).exec(src)?.[1])
    if (!src.includes(RULE)) throw new Error(`${tab}: «${p.alt}» is not tableSvg's picture`)
    if (p.width !== TW || own('width') !== TW || own('height') !== p.height || p.height % CELL_PX !== 0 || p.isInteractive) throw new Error(`${tab}: «${p.alt}» ${p.width} x ${p.height} (own ${own('width')} x ${own('height')})`)
  }
  for (const t of r.tables) {
    let at = 1
    for (const h of t.hov) {
      if (h.top < at || h.height < 1) throw new Error(`${tab}: «${t.alt}» hover Box ${h.key} at line ${h.top} (${h.height} high), the row before ends at ${at}`)
      at = h.top + h.height
    }
    if (at !== t.lines && t.hov.length) throw new Error(`${tab}: «${t.alt}» is ${t.lines} lines, its rows end at ${at}`)
    if (new Set(t.hov.map(h => h.key)).size !== t.hov.length) throw new Error(`${tab}: «${t.alt}» repeats a hover key`)
  }
  if (r.oldRows.length) throw new Error(`${tab}: a Row of Cells is still drawn: ${r.oldRows.slice(0, 3)}`)
  if (r.texts.some(t => /─{5}/.test(t))) throw new Error(`${tab}: a text rule of an old table head`)
  return other
}
const has = (hay: string[], needles: string[], what: string) => {
  const miss = needles.filter(n => !hay.includes(n))
  if (miss.length) throw new Error(`${what}: missing ${JSON.stringify(miss.slice(0, 8))} among ${JSON.stringify(hay.slice(0, 40))}`)
}
// (c) #683 r5 (E), the owner 10.10 12:1x («хватит сюда нести тупо вериблы из кода», «это UI/UX»): a tab draws no code
// word. Whatever the mod itself writes on it (a native Text, a button, a picture's alt = a card's or a table's name,
// a column label, a legend word, and every word of the tables named in `own`: the ones that hold no ticket title and
// no role name) carries no English word but the names the owner uses himself; the old heads, card names and row
// labels are in no table at all (compared whole: a ticket's title is GitHub's and may hold any word); a model id is
// in no table. A ticket's hover card is not read: it repeats GitHub's own card.
const NAMES = new Set(['POB', 'ORCH', 'autopilot', 'keymaster', 'brain', 'Cost', 'Progress', 'API', 'unslop', 'view', 'Opus', 'Fable', 'Sonnet', 'Haiku'])
// #1079 (the owner, 15.10: a label and a state are drawn by the name GitHub writes): on the Tickets and Progress tabs these names are the mod's
// words (their rows and legends), not English leaks; on every other tab they are English and count as a leak. `parked-on-merge` is not in it:
// no row of the two tabs waits for a merge (it is the main tab's ORCH line, `parkedOn` in register.tsx)
const GH_NAMES = ['ready-for-agent', 'needs-triage', 'needs-info', 'ready-for-human', 'wontfix', 'parked-on-run', 'held', 'blocked', 'folder', 'no label', 'not planned', 'open', 'closed']
const GH_RE = new RegExp(`\\b(${GH_NAMES.join('|')})\\b`, 'g')
const OLD = ['#', 'title', 'done', 'model', 'day', 'turns', 'closed issue', 'label', 'n', 'share', 'agent_type', 'ready',
  'By model', 'By day', 'By issue', 'issues closed', 'context × turns', 'context на turn', 'Open issues by label', 'loading...']
const english = (s: string, gh: boolean) => ((gh ? s.replace(GH_RE, ' ') : s).match(/[A-Za-z_][A-Za-z_-]+/g) ?? []).filter(w => !NAMES.has(w))
const heads = (src: string) => [...src.matchAll(/<text x="[\d.]+" y="13" class="mu"[^>]*>([^<]*)<\/text>/g)].map(m => m[1]!)
const noCode = async (ui: any, tab: string, own: string[] = [], free: string[] = []) => {
  const said: string[] = [], all: string[] = []
  const textOf = (n: any): string => (typeof n === 'string' ? n : (n?.children ?? []).map(textOf).join(''))
  const walk = (n: any) => {
    if (!n || typeof n !== 'object') return
    if (n.type === 'Box' && n.props?.display === 'none') return // a ticket's hover card
    if (n.type === 'Text') { if (!free.some(f => textOf(n).startsWith(f))) said.push(textOf(n)); return } // (`free` = a muted line that names agent types or chat titles)
    if (n.type === 'Button') said.push(String(n.props?.label ?? ''))
    if (n.type === 'Svg') {
      const src = dq(String(n.props?.source ?? '')), alt = String(n.props?.alt ?? '')
      said.push(alt)
      // the tab bar and the legend are the mod's words through; a table: its labels, and all of it when named in `own`
      said.push(...(n.props?.width == null || own.includes(alt) ? svgWords(src) : heads(src)))
      all.push(...svgWords(src))
    }
    for (const c of n.children ?? []) walk(c)
  }
  walk(await ui.drawn())
  const gh = /^(tickets|progress)\b/.test(tab) // #1079: the GitHub names are the words of these two tabs only (`tickets, 60` and `progress, 60` too)
  const bad = said.filter(w => english(w, gh).length)
  if (bad.length) throw new Error(`${tab}: an English word the mod wrote itself: ${JSON.stringify(bad.slice(0, 8))}`)
  const old = [...[...said, ...all].filter(w => OLD.includes(w.trim())), ...said.filter(w => /agent_type|orch_end|events\.jsonl|^updated |claude-(opus|sonnet|haiku|fable)-\d/.test(w))]
  if (old.length) throw new Error(`${tab}: an old code word is still drawn: ${JSON.stringify(old.slice(0, 8))}`)
  if (said.some(w => /\d\d:\d\d:\d\d/.test(w))) throw new Error(`${tab}: a time with seconds: ${said.filter(w => /\d\d:\d\d:\d\d/.test(w))}`)
}

test('desktop, Tickets: both cards are THE table, a tree; nothing cut; every fact still shown', async ($, on) => {
  const { ui, go } = await mount($, on)
  await go('tab-tickets')
  // every parent of the first level and one of the second opened: long titles (they wrap), three levels of the tree
  for (const n of [486, 1, 63]) await go(`tg-${n}`)
  await noDots(ui, 'tickets')
  await noCode(ui, 'tickets')
  await noGlyphs(ui, 'tickets')
  const r = await read(ui)
  const other = oneLook(r, 'tickets', ['Цели', 'Вне целей'])
  const LEGEND = ['work', 'owner', 'ready', 'blocked', 'open', 'triage', 'closed', 'dropped']
  has(other, ['Цели', 'Вне целей'], 'tickets: card heads')
  // the legend: the eight states, each the icon its rows carry, in the legend's order
  const lg = r.pics.find(p => icons(dq(String(p.source))).map(i => i.kind).join() === LEGEND.join())
  if (!lg) throw new Error('no loose legend picture with the eight state icons in order (#837 pass 2: the legend is the baseline picture)')
  if (r.texts.includes('Состояния')) throw new Error('a card «Состояния» is drawn')
  // the rows the tab holds: the goals with the opened branches under their parents, then the loose ones, all of them
  const open = new Set([486, 1, 63])
  const rowsOf = (n: number, depth: number, out: [any, number][]) => { const i = tk.issues[String(n)]; out.push([i, depth]); if (open.has(n)) for (const k of i.kids) if (tk.issues[String(k)]) rowsOf(k, depth + 1, out); return out }
  const goals: [any, number][] = tk.goals.flatMap((n: number) => rowsOf(n, 0, []))
  const loose: [any, number][] = tk.loose.flatMap((n: number) => rowsOf(n, 0, []))
  const shownLoose = loose
  has(r.texts, [fresh(tk.at)], 'tickets: texts')
  if (r.texts.some(w => w.includes('не показан'))) throw new Error('a sentence about rows not shown is drawn')
  const sub = (n: number): any[] => (tk.issues[String(n)]?.kids ?? []).flatMap((k: number) => (tk.issues[String(k)] ? [tk.issues[String(k)], ...sub(k)] : []))
  // the tickets a session, a subagent or a run holds are «в работе» whatever their label says (the mod's `heldIssues`)
  const fast = JSON.parse(FAST)
  const held = new Set<number>([
    ...(fast.agents ?? []).flatMap((a: any) => [a.busy && a.issue, ...(a.held ?? []).map((h: any) => (typeof h === 'number' ? h : h.number)), ...(a.subagents ?? []).map((s: any) => s.issue)]),
    ...(fast.runs?.running ?? []).map((j: any) => j.issue)].filter(Boolean))
  const stateOf = (i: any) => (!i.open && i.reason === 'NOT_PLANNED' ? 'dropped' : i.open && held.has(i.n) ? 'work' : i.state)
  let wrapped = 0, marks = 0
  const kinds = new Set<string>()
  for (const [t, rows] of [[r.tables[0]!, goals], [r.tables[1]!, shownLoose]] as const) {
    if (t.hov.length !== rows.length) throw new Error(`«${t.alt}»: ${t.hov.length} rows drawn, ${rows.length} held`)
    has(heads(t.src), ['тикет', 'название', 'готово'], `«${t.alt}» column labels`)
    const flat = squash(t.words.join(''))
    const drawn = icons(t.src)
    if (drawn.some(d => d.kind === '?')) throw new Error(`«${t.alt}»: an icon the test does not know`)
    rows.forEach(([i, depth], k) => {
      const h = t.hov[k]!
      if (h.key !== `hv-tk-${i.n}`) throw new Error(`row ${k} of «${t.alt}» is ${h.key}, want #${i.n}`)
      // the number: drawn in the picture (#972) with a blank Button over its row, two pane columns right a level
      if (h.links.length !== 1 || h.links[0]!.label !== `#${i.n}` || h.links[0]!.left !== 6 + 2 * depth) throw new Error(`#${i.n}: links ${JSON.stringify(h.links)}`)
      if (!t.words.includes(`#${i.n}`)) throw new Error(`#${i.n} is not drawn inside the picture`)
      // the toggle: a native press on a parent, none on a leaf; its label is blank (two no-break spaces): the chevron
      // of the picture under it is what is seen
      const want = i.kids.length ? [{ key: `tg-${i.n}`, label: '  ', left: 1 + 2 * depth }] : []
      if (JSON.stringify(h.buttons) !== JSON.stringify(want)) throw new Error(`#${i.n}: toggle ${JSON.stringify(h.buttons)}, want ${JSON.stringify(want)}`)
      // the row's icons, left to right on its first line: the chevron of a parent (turned down when open), ONE state
      // icon, and the hourglass at the right edge only on an open ticket that waits for other tickets while its
      // state says something else
      const st = stateOf(i), blockedToo = i.open && i.blockers.length > 0 && st !== 'blocked'
      const mine = drawn.filter(d => d.line === h.top)
      const wantIcons = [...(i.kids.length ? [`chevron${open.has(i.n) ? ':down' : ''}`] : []), st, ...(blockedToo ? ['blocked'] : [])]
      if (mine.map(d => d.kind + (d.turned ? ':down' : '')).join() !== wantIcons.join()) throw new Error(`#${i.n}: icons ${mine.map(d => d.kind + (d.turned ? ':down' : ''))}, want ${wantIcons}`)
      // under the press stands its chevron; a level shifts every icon of the row by the same two pane columns
      const chev = mine.find(d => d.kind === 'chevron'), state = mine[i.kids.length ? 1 : 0]!
      // (the press: `left` pane columns inside the hover Box, itself 2 columns in; its blank label is 2 columns wide)
      const pressAt = (2 + 1 + 2 * depth) * 7.8
      if (chev && (chev.x + 6 < pressAt || chev.x + 6 > pressAt + 2 * 7.8 + 4)) throw new Error(`#${i.n}: the chevron's centre at ${chev.x + 6}, its press from ${pressAt}`)
      if (state.x >= (6 + 2 * depth) * 7.8 || (chev && state.x < chev.x + 12)) throw new Error(`#${i.n}: the state icon at ${state.x} (chevron ${chev?.x}, the number at column ${6 + 2 * depth})`)
      if (st === 'closed' && state.color !== '#ab7df8') throw new Error(`#${i.n}: a closed ticket's icon is ${state.color}`)
      kinds.add(st)
      if (blockedToo) marks++
      // the title whole, on as many lines as its hover Box is high
      if (!titleIn(flat, i.title)) throw new Error(`#${i.n}: its title is neither whole nor cut once with «…» in the picture: ${i.title}`)
      if (h.height > 1) wrapped++
      const all = sub(i.n)
      if (all.length && !t.words.includes(`${all.filter(x => !x.open).length}/${all.length}`)) throw new Error(`#${i.n}: no done count ${all.filter(x => !x.open).length}/${all.length}`)
    })
  }
  // #994 (the owner's rule: a title is ONE line cut with an ellipsis): no title wraps any more
  if (wrapped) throw new Error(`${wrapped} titles wrapped onto more than one line`)
  // the fixture rows still hold the mark's one case (#3 waits for you AND for #2) and the common states
  if (marks !== 1) throw new Error(`${marks} rows with the waits-for-tickets mark: the fixture no longer holds #3's case`)
  for (const st of ['work', 'owner', 'open', 'triage', 'closed']) if (!kinds.has(st)) throw new Error(`no row in state «${st}»: the fixture rows changed`)
  // closing a branch takes its rows away: the toggles work
  await go('tg-63')
  const r2 = await read(ui)
  if (r2.tables[0]!.hov.length !== goals.length - tk.issues['63'].kids.length) throw new Error(`#63 closed: ${r2.tables[0]!.hov.length} rows`)
  await ui.unmount()
})

// #683 r5 step 1b: the Cost tab is ONE population (the collector's `cut` of the period) cut ten ways; each cut a card,
// each card THE table, the same trailing columns in all of them (the share bar, % лимита, $, токенов).
const tokH = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(2)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n))
const limPct = (v: number, per: number | null) => { if (per == null) return ''; const p = v / per; return p >= 10 ? `${Math.round(p)} %` : p >= 0.1 ? `${p.toFixed(1)} %` : p > 0 ? '<0.1 %' : '0 %' }
const CUT_NAMES = ['По ролям', 'Роль на разных моделях', 'ORCH: сам и кого запускает', 'ORCH на разных моделях: результат', 'autopilot: сам и кого запускает', 'brain: сам и кого запускает', 'Моды', 'По чатам',
  'По моделям: кто вызывает', 'По виду токенов', 'По дням', 'По тикетам']
/** #972: the twelve cards of the cost tab stand in three groups behind a second switch. The three groups are drawn one after another and read as ONE reading: the tables in the
 *  order they had on the one page (CUT_NAMES), the pictures and texts of the groups joined (the tab bar, the period line and the limit line once), the trees side by side. */
const GROUPS = ['roles', 'spawn', 'days']
const readCost = async (ui: any, go: (key: string) => Promise<void>): Promise<Awaited<ReturnType<typeof read>>> => {
  const parts: Awaited<ReturnType<typeof read>>[] = []
  for (const g of GROUPS) { await go(`costg-${g}`); parts.push(await read(ui)) }
  const once = <X,>(xs: X[], key: (x: X) => string) => { const seenK = new Set<string>(); return xs.filter(x => { const k = key(x); if (seenK.has(k)) return false; seenK.add(k); return true }) }
  const tables = parts.flatMap(x => x.tables)
  return {
    tree: { type: 'Box', props: {}, children: parts.map(x => x.tree) },
    pics: once(parts.flatMap(x => x.pics), x => (x.width == null && String(x.alt).startsWith('Главная') ? 'tabs' : JSON.stringify([x.alt, x.source]))),
    tables: [...CUT_NAMES.map(n => tables.find(t => t.alt === n)).filter((t): t is Table => !!t), ...tables.filter(t => !CUT_NAMES.includes(t.alt))],
    texts: once(parts.flatMap(x => x.texts), x => x),
    buttons: once(parts.flatMap(x => x.buttons), x => JSON.stringify(x)), links: parts.flatMap(x => x.links), oldRows: parts.flatMap(x => x.oldRows), cards: parts.flatMap(x => x.cards),
  }
}
// a table's data rows from its picture: the words of each line, left to right, with their x
const rowsOf = (src: string) => {
  const by = new Map<number, { x: number; w: string }[]>()
  for (const m of src.matchAll(/<tspan x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]*)<\/tspan>/g)) {
    const y = Number(m[2])
    const k = Math.round(y)
    by.set(k, [...(by.get(k) ?? []), { x: Number(m[1]), w: m[3]!.replace(/&amp;/g, '&') }])
  }
  return [...by.entries()].sort((a, b) => a[0] - b[0]).map(([, ws]) => ws.sort((a, b) => a.x - b.x))
}
const sumOf = (xs: any[], k = 'cost_usd') => xs.reduce((a, x) => a + x[k], 0)
const near = (a: number, b: number, what: string) => { if (Math.abs(a - b) >= 1e-6) throw new Error(`${what}: ${a} vs ${b}`) }
// the bold line of the head, from the formula (written out here: the rule is the mod's)
const headOf = (cut: any) => {
  const p = cut.total.limit_pct
  const all = sumOf([cut.total.tokens].map(x => ({ v: x.input + x.cache_write + x.cache_read + x.output })), 'v')
  const unit = (cut.total.limit_days ?? 7) > 7 ? 'месячного' : 'недельного' // #1018 A: the month is against a month's limit
  return `${usd(cut.total.cost_usd)} · ≈ ${thousands(Math.round(p))} % ${unit} лимита · ${tokH(all)} токенов` // #995 row 6: always in its unit, the percent
}
const periodOf = (cut: any) => (ddmm(cut.since) === ddmm(cut.until) ? ddmm(cut.since) : `${ddmm(cut.since)} – ${ddmm(cut.until)}`)
const BANNED = ['ходов', 'контекст', 'в среднем на сессию']
// the rules of the three counts, written out (the spec's, not the mod's code)
const pluralOf = (n: number, a: string, b: string, c: string) => {
  const m100 = n % 100, m10 = n % 10
  return m100 >= 11 && m100 <= 14 ? c : m10 === 1 ? a : m10 >= 2 && m10 <= 4 ? b : c
}
const spaced = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
const rateOf = (v: number) => (v >= 10 ? spaced(Math.round(v)) : /* #837 b8 (E): a rate of 1000 or more is grouped like every count */ v >= 0.05 ? v.toFixed(1) : v > 0 ? '<0.1' : '0')
const ROLE_WORD: Record<string, string> = { orch: 'ORCH', other_sub: 'другие субагенты', other_chat: 'другие чаты', mod: 'моды' }
const roleWord = (k: string) => ROLE_WORD[k] ?? k
const MODE_WORD: Record<string, string> = { monitor: 'монитор', unslop: 'unslop' }
const sessWord = (n: number) => `${spaced(n)} ${pluralOf(n, 'сессия', 'сессии', 'сессий')}`
const SUB_WORD: Record<string, [string, string, string]> = { main: ['сессия', 'сессии', 'сессий'], sub: ['субагент', 'субагента', 'субагентов'], mod: ['вызов', 'вызова', 'вызовов'] }
// #774: the tab's one muted line, at its very end
const COST_END = (at: unknown, per: number | null) => [per == null ? '' : `1 % недельного лимита ≈ $${per} по ценам API`, fresh(String(at))].filter(Boolean).join(' · ')
const TYPE_KEYS = ['effort-high', 'effort-medium', 'web-fetch', 'general-purpose']

// #771: the Cost cards draw no hover Box over a row (size guard): a table's rows are its picture's lines less the head line;
// the tickets table keeps its Boxes (a native Link lies in each row), so its own count stands.
const rowsIn = (t: Table) => t.hov.length || Math.max(0, t.lines - 1)

// The twelve tables of one period, checked against its `cut`; `days` = the period's calendar days.
const checkCost = (r: Awaited<ReturnType<typeof read>>, cut: any, what: string) => {
  const total = cut.total.cost_usd
  const days: number = cut.days
  const [tRole, tRoleModel, tOrch, tOrchModel, tAuto, tBrain, tMod, tWho, tModel, tKind, tDay, tIssue] = r.tables as Table[]
  const rowOf = (t: Table, x: { cost_usd: number; tokens?: number }, tokens?: number) =>
    has(t.words, [usd(x.cost_usd), limPct(x.cost_usd, cut.total.limit_usd_per_pct), tokH(tokens ?? x.tokens ?? 0)], `${what}: ${t.alt}`)
  const tail = (heads: string[]) => [...heads, 'доля', '% лимита', '$', 'токенов'] // #837 b10 S5: the bar column is named
  // По ролям: as ranked, the rows sum to the total, each with its count in words
  if (rowsIn(tRole!) !== cut.by_role.length) throw new Error(`${what}: roles ${rowsIn(tRole!)} rows`)
  near(sumOf(cut.by_role), total, `${what}: roles sum to the total`)
  cut.by_role.forEach((x: any) => {
    rowOf(tRole!, x)
    const w = SUB_WORD[x.group]!
    has(tRole!.words, [roleWord(x.key), `${spaced(x.n)} ${pluralOf(x.n, ...w)}`], `${what}: role ${x.key}`)
  })
  if (heads(tRole!.src).join() !== tail(['роль', 'сколько']).join()) throw new Error(`${what}: roles heads ${heads(tRole!.src)}`)
  const roleKeys = tRole!.words.filter(w => ['brain', 'ORCH', 'autopilot', 'keymaster', 'worker', 'worker-strong', 'researcher-find', 'researcher-how'].includes(w))
  if (cut.by_role.some((x: any) => x.key === 'keymaster') && !roleKeys.includes('keymaster')) throw new Error(`${what}: no keymaster row among the roles`)
  // an agent type is no role: it stands in no table, only in the muted line
  const tableWords = r.tables.flatMap(t => t.words)
  for (const k of TYPE_KEYS) if (tableWords.includes(k) || r.tables.some(t => t.alt === k)) throw new Error(`${what}: the agent type ${k} is a table word`)
  const oSub = cut.by_role.find((x: any) => x.key === 'other_sub')
  // the three spawner cards
  const spawners: [Table, string][] = [[tOrch!, 'orch'], [tAuto!, 'autopilot'], [tBrain!, 'brain']]
  for (const [t, key] of spawners) {
    const sp = cut.by_spawner.find((x: any) => x.key === key)
    const want = days > 1 ? ['кто', 'субагентов', 'за сессию', 'в день'] : ['кто', 'субагентов', 'за сессию']
    if (heads(t.src).join() !== tail(want).join()) throw new Error(`${what}: ${t.alt} heads ${heads(t.src)}`)
    if (!sp) { if (rowsIn(t) || t.words.some(w => w === 'сам')) throw new Error(`${what}: ${t.alt} has rows with no turn of ${key}`); continue }
    if (rowsIn(t) !== 1 + sp.roles.length) throw new Error(`${what}: ${t.alt} ${rowsIn(t)} rows`)
    rowOf(t, sp.own)
    has(t.words, ['сам'], `${what}: ${t.alt}`)
    near(sp.own.cost_usd + sp.sub.cost_usd, sp.cost_usd, `${what}: ${key} own + sub`)
    near(sumOf(sp.roles), sp.sub.cost_usd, `${what}: ${key} roles sum to sub`)
    sp.roles.forEach((x: any) => {
      rowOf(t, x)
      has(t.words, [roleWord(x.key), String(x.agents), rateOf(x.agents / sp.sessions), ...(days > 1 ? [rateOf(x.agents / days)] : [])], `${what}: ${t.alt} role ${x.key}`)
    })
    const sub = r.pics.find(p => p.width == null && String(p.alt).startsWith(t.alt))
    if (!sub || sub.alt !== `${t.alt} · ${sessWord(sp.sessions)} · всего ${usd(sp.own.cost_usd + sp.sub.cost_usd)}`) throw new Error(`${what}: ${t.alt} sub: ${sub?.alt}`)
  }
  if (r.tables.some(t => /^keymaster/.test(t.alt)) || r.pics.some(p => /^keymaster/.test(String(p.alt)))) throw new Error(`${what}: a card is titled keymaster`)
  // Моды
  const mods = cut.by_mod as any[]
  const wantMod = days > 1 ? ['мод', 'модель', 'вызовов', 'в день'] : ['мод', 'модель', 'вызовов']
  if (heads(tMod!.src).join() !== tail(wantMod).join()) throw new Error(`${what}: mods heads ${heads(tMod!.src)}`)
  if (rowsIn(tMod!) !== mods.length) throw new Error(`${what}: mods ${rowsIn(tMod!)} rows`)
  mods.forEach(x => {
    rowOf(tMod!, x)
    has(tMod!.words, [MODE_WORD[x.key]!, model(x.model), spaced(x.calls), ...(days > 1 ? [rateOf(x.calls / days)] : [])], `${what}: mod ${x.key}`)
  })
  if (tMod!.words.some(w => /^claude-/.test(w))) throw new Error(`${what}: a model id in the mods table`)
  const modSum = sumOf(mods)
  near(modSum, cut.by_role.find((x: any) => x.key === 'mod').cost_usd, `${what}: mods = the mod role`)
  const modSub = r.pics.find(p => p.width == null && String(p.alt).startsWith('Моды'))
  if (!modSub || modSub.alt !== `Моды · ${usd(modSum)} из ${usd(total)}`) throw new Error(`${what}: mods sub: ${modSub?.alt}`)
  // По чатам: only chats and the untitled; ORCH / autopilot / keymaster / mods are in По ролям
  const who = cut.by_who as any[]
  const chats = who.filter(x => x.kind === 'chat' || x.kind === 'untitled')
  const top = chats.slice(0, 10), rest = chats.slice(10)
  if (rowsIn(tWho!) !== top.length + (rest.length ? 1 : 0)) throw new Error(`${what}: chats ${rowsIn(tWho!)} rows`)
  const flat = squash(tWho!.words.join(''))
  top.forEach(x => {
    rowOf(tWho!, x)
    if (!flat.includes(squash(x.kind === 'untitled' ? 'чаты без названия' : x.key))) throw new Error(`${what}: chat «${x.key}» is not drawn`)
  })
  if (rest.length) { rowOf(tWho!, { cost_usd: sumOf(rest) }, sumOf(rest, 'tokens')); has(tWho!.words, [`остальные (${rest.length})`], `${what}: chats rest`) }
  for (const w of ['ORCH', 'autopilot', 'keymaster', 'мод unslop', 'мод монитора', 'моды']) if (tWho!.words.includes(w)) throw new Error(`${what}: По чатам holds ${w}`)
  near(sumOf(top) + sumOf(rest), sumOf(chats), `${what}: chats sum`)
  near(sumOf(chats) + sumOf(who.filter(x => x.kind !== 'chat' && x.kind !== 'untitled')), total, `${what}: chats + the rest of by_who = the total`)
  if (top[0] && top[0].sub_usd >= 0.005 && !tWho!.words.includes(`субагенты ${usd(top[0].sub_usd)}`)) throw new Error(`${what}: chats, the subagents note`)
  const chatSub = r.pics.find(p => p.width == null && String(p.alt).startsWith('По чатам'))
  if (!chatSub || chatSub.alt !== `По чатам · ${usd(sumOf(chats))} из ${usd(total)}`) throw new Error(`${what}: chats sub: ${chatSub?.alt}`)
  // По моделям: кто вызывает: a model, under it its role x model rows with their count
  const kept: any[] = cut.by_role_model.filter((x: any) => x.tokens > 0 || x.cost_usd > 0)
  const rmWord = (x: any) => (x.group === 'mod' ? MODE_WORD[x.role]! : roleWord(x.role))
  const models = cut.by_model.filter((x: any) => x.tokens > 0 || x.cost_usd > 0)
  near(sumOf(cut.by_role_model), total, `${what}: role x model rows sum to the total`)
  if (heads(tModel!.src).join() !== tail(['модель / роль', 'сколько']).join()) throw new Error(`${what}: models heads ${heads(tModel!.src)}`)
  if (rowsIn(tModel!) !== models.length + kept.length) throw new Error(`${what}: models ${rowsIn(tModel!)} rows of ${models.length} + ${kept.length}`)
  const mrows = rowsOf(tModel!.src)
  let at = 0
  models.forEach((x: any) => {
    rowOf(tModel!, x)
    const row = mrows[at++]!
    if (row[0]!.w !== model(x.key) || row.some(w => /^\d+ (сесси|субагент|вызов)/.test(w.w))) throw new Error(`${what}: model row ${model(x.key)}: ${JSON.stringify(row)}`)
    const kids = kept.filter(k => k.model === x.key)
    for (const k of kids) {
      const kr = mrows[at++]!
      const cnt = `${spaced(k.n)} ${pluralOf(k.n, ...SUB_WORD[k.group]!)}`
      if (kr[0]!.w !== rmWord(k) || kr[0]!.x <= row[0]!.x || !kr.some(w => w.w === cnt) || !kr.some(w => w.w === usd(k.cost_usd)))
        throw new Error(`${what}: ${model(x.key)} / ${k.role}: ${JSON.stringify(kr)}`)
    }
    near(sumOf(kids), x.cost_usd, `${what}: ${model(x.key)} roles sum to the model`)
  })
  near(sumOf(cut.by_model), total, `${what}: models sum to the total`)
  // Роль на разных моделях: one row per kept pair, the role named once per group, no bar, no % лимита
  const ORDER = ['brain', 'orch', 'autopilot', 'keymaster', 'worker', 'worker-strong', 'researcher-find', 'researcher-how', 'other_sub', 'other_chat', 'unslop', 'monitor']
  const rank = (r: string) => (ORDER.indexOf(r) < 0 ? 99 : ORDER.indexOf(r))
  const want = [...kept].sort((a, b) => rank(a.role) - rank(b.role) || (rank(a.role) === 99 ? a.role.localeCompare(b.role) : 0) ||
    (a.first == null ? 1 : 0) - (b.first == null ? 1 : 0) || String(a.first).localeCompare(String(b.first)) || a.model.localeCompare(b.model))
  const spanOf = (x: any) => (x.first == null ? '' : x.first === x.last ? ddmm(x.first) : `${ddmm(x.first)} – ${ddmm(x.last)}`)
  const nDays = (x: any) => Math.round((Date.parse(x.last) - Date.parse(x.first)) / 86400000) + 1
  const per = (v: number) => (v < 0.1 ? `$${v.toFixed(3)}` : usd(v))
  if (/stroke-width="6"/.test(tRoleModel!.src) || heads(tRoleModel!.src).includes('% лимита')) throw new Error(`${what}: role x model has a bar or % лимита`)
  if (rowsIn(tRoleModel!) !== want.length) throw new Error(`${what}: role x model ${rowsIn(tRoleModel!)} rows of ${want.length}`)
  const need = ['роль', 'модель', 'запусков', '$ за запуск', '$']
  has(heads(tRoleModel!.src), need, `${what}: role x model heads`)
  const rrows = rowsOf(tRoleModel!.src)
  want.forEach((x, i) => {
    const row = rrows[i]!.map(w => w.w)
    const firstOfGroup = i === 0 || want[i - 1]!.role !== x.role
    const name = rmWord(x)
    if (firstOfGroup ? row[0] !== name : row.includes(name) && x.role !== x.model) throw new Error(`${what}: role x model row ${i} ${x.role}: ${JSON.stringify(row)}`)
    const cells = [model(x.model), ...(x.first ? [spanOf(x)] : []), spaced(x.n), usd(x.cost_usd),
      ...(x.n > 0 ? [per(x.cost_usd / x.n), tokH(Math.round(x.tokens / x.n)), rateOf(x.n / nDays(x))] : [])]
    const miss = cells.filter(c => !row.includes(c))
    if (miss.length) throw new Error(`${what}: role x model row ${i} ${x.role}/${x.model}: missing ${JSON.stringify(miss)} in ${JSON.stringify(row)}`)
  })
  // the groups' names appear once each, in the fixed order
  const groupNames = rrows.map(r => r[0]!.w).filter((w, i) => want[i] && (i === 0 || want[i - 1]!.role !== want[i]!.role) && w === rmWord(want[i]!))
  if (groupNames.length !== new Set(want.map(x => x.role)).size) throw new Error(`${what}: role names ${groupNames}`)
  const orchPairs = want.filter(x => x.role === 'orch')
  if (orchPairs.some((x, i) => i > 0 && String(orchPairs[i - 1]!.first) > String(x.first))) throw new Error(`${what}: ORCH pairs not in first order`)
  // ORCH на разных моделях: результат
  const oRows = kept.filter(x => x.role === 'orch' && x.led > 0).sort((a, b) => String(a.first).localeCompare(String(b.first)))
  if (rowsIn(tOrchModel!) !== oRows.length) throw new Error(`${what}: ORCH result ${rowsIn(tOrchModel!)} rows of ${oRows.length}`)
  const orows = rowsOf(tOrchModel!.src)
  oRows.forEach((x, i) => {
    const row = orows[i]!.map(w => w.w)
    const c = x.cost_usd + x.spawned.cost_usd
    const cells = [model(x.model), spanOf(x), spaced(x.led), rateOf(x.spawned.agents / x.led), usd(c / x.led), ...(x.closed == null ? [] : [String(x.closed)]), ...(x.closed ? [usd(c / x.closed)] : [])]
    const miss = cells.filter(w => !row.includes(w))
    if (miss.length) throw new Error(`${what}: ORCH result ${x.model}: missing ${JSON.stringify(miss)} in ${JSON.stringify(row)}`)
  })
  // По виду токенов, По дням, По тикетам: unchanged
  const KW: Record<string, string> = { input: 'ввод', cache_write: 'запись в кэш', cache_read: 'чтение из кэша', output: 'вывод' }
  const kinds = [...cut.by_kind].sort((a: any, b: any) => b.cost_usd - a.cost_usd)
  if (rowsIn(tKind!) !== 4) throw new Error(`${what}: kinds ${rowsIn(tKind!)} rows`)
  kinds.forEach((x: any) => { rowOf(tKind!, x); has(tKind!.words, [KW[x.key]!], `${what}: kinds`) })
  const kw = tKind!.words.filter(w => Object.values(KW).includes(w))
  if (kw.join() !== kinds.map((x: any) => KW[x.key]).join()) throw new Error(`${what}: kinds order ${kw}`)
  near(sumOf(cut.by_kind), total, `${what}: kinds sum to the total`)
  // #995 row 6: every day of the period, newest first, in every period (the month's 30 rows too): no «остальные (n)» row, a share bar on every day
  const shown: any[] = [...cut.by_day].sort((a: any, b: any) => (a.key < b.key ? 1 : a.key > b.key ? -1 : 0))
  if (rowsIn(tDay!) !== shown.length) throw new Error(`${what}: days ${rowsIn(tDay!)} rows, want ${shown.length}`)
  shown.forEach((x: any) => { rowOf(tDay!, x); has(tDay!.words, [ddmm(x.key)], `${what}: days`) })
  if (tDay!.words.some(w => w.startsWith('остальные'))) throw new Error(`${what}: days: a rest row`)
  if (tDay!.words.filter(w => /^[0-9][0-9][.][0-9][0-9]$/.test(w)).join() !== shown.map((x: any) => ddmm(x.key)).join()) throw new Error(`${what}: days order`)
  const track = /<path d="([^"]*)" fill="none" stroke="#808080" stroke-opacity="[.]16" stroke-width="6"/.exec(tDay!.src)?.[1] ?? ''
  if ((track.match(/M/g) ?? []).length !== shown.length) throw new Error(`${what}: days: ${(track.match(/M/g) ?? []).length} bars for ${shown.length} days`)
  near(sumOf(cut.by_day), total, `${what}: days sum to the total`)
  // #774: the month keeps its 10 dearest tickets (a hover Box a row would take it past the size guard); the others join the rest row
  // #972 (the owner, 13.10): every period keeps every ticket the collector sends (its twenty dearest); the month's cut to ten is gone, the budget pages the card when it must
  const keepT = cut.by_issue.length
  const cutT = cut.by_issue.slice(keepT)
  rowOf(tIssue!, { cost_usd: cut.issue_rest.cost_usd + sumOf(cutT) }, cut.issue_rest.tokens + sumOf(cutT, 'tokens')); rowOf(tIssue!, cut.no_issue)
  has(tIssue!.words, [`остальные тикеты (${cut.issue_rest.n + cutT.length})`], `${what}: tickets rest`)
  if (tIssue!.hov.length !== keepT + 2) throw new Error(`${what}: tickets ${tIssue!.hov.length} rows, want ${keepT + 2}`)
  near(sumOf(cut.by_issue) + cut.issue_rest.cost_usd + cut.no_issue.cost_usd, total, `${what}: tickets sum to the total`)
  // the share bars: a track a row in nine cards (the tickets card has none)
  for (const t of r.tables.slice(0, 11)) if (rowsIn(t) && t !== tRoleModel && t !== tOrchModel && !/stroke-width="6"/.test(t.src)) throw new Error(`${what}: ${t.alt}: no share bar`)
  if (/stroke-width="6"/.test(tIssue!.src)) throw new Error(`${what}: tickets: a share bar`)
  // the hover keys run on across the tables of a drawn group without a gap (#972: a group is a draw of its own; `r.tree` of the three groups read together holds one tree a group)
  for (const part of ((r.tree as any).children ?? []) as any[]) {
    const keys = [...JSON.stringify(part).matchAll(/"key":"(hv-cost-\d+)"/g)].map(m => m[1]!)
    if (keys.join() !== keys.map((_, i) => `hv-cost-${i}`).join()) throw new Error(`${what}: hover keys ` + keys.slice(0, 12))
  }
}

// #774: a Cost card is a title and a table. No note line inside a card (a Text under or beside the table), a sub beside the
// title only a count or a sum, every row of all twelve tables under a hover Box, and ONE muted line at the tab's very end.
const cardLook = (r: Awaited<ReturnType<typeof read>>, at: unknown, what: string, per: number | null) => {
  const cardsOf: any[] = []
  const walk = (n: any) => {
    if (!n || typeof n !== 'object') return
    if (n.type === 'Box' && String(n.props?.key ?? '').startsWith('card-cost-')) { cardsOf.push(n); return }
    for (const c of n.children ?? []) walk(c)
  }
  walk(r.tree)
  if (cardsOf.length !== 12) throw new Error(`${what}: ${cardsOf.length} cards`)
  const notes: string[] = []
  // #972: a Text of only no-break spaces before the Button in an absolute Box is the lead of a pointer element (its sub-cell start), not a note line
  const textsIn = (n: any, parent: any = null) => { if (!n || typeof n !== 'object') return; if (n.type === 'Text' && !isLead(parent, n)) notes.push(String(n.children?.[0] ?? '')); for (const c of n.children ?? []) textsIn(c, n) }
  cardsOf.forEach(c => textsIn(c))
  if (notes.length) throw new Error(`${what}: note lines inside the cards: ${JSON.stringify(notes.slice(0, 4))}`)
  for (const p of r.pics.filter(p => p.width == null && !String(p.alt).startsWith('Главная'))) {
    const sub = String(p.alt).split(' · ').slice(1).join(' · ')
    if (sub && !/^\d[\d ]* \p{L}+ · всего \$|^\$[\d., ]+ из \$/u.test(sub)) throw new Error(`${what}: «${p.alt}» holds a sub that is no count or sum`)
  }
  const bare = r.tables.filter(t => t.lines > 1 && (!t.hov.length || t.hov[0]!.top !== 1 || t.hov.at(-1)!.top + t.hov.at(-1)!.height !== t.lines))
  if (r.tables.length !== 12 || bare.length) throw new Error(`${what}: cards whose rows carry no hover: ${bare.map(t => t.alt)}`)
  // one muted line, last of the tab's native Texts (the others: the period and the bold head line)
  const texts = r.texts.filter(t => t.trim() && !['День', 'Неделя', 'Месяц', 'Расходы'].includes(t)) // (the period's plain presses and the selected tab carry their label as a Text, #793 F01, F17)
  const lines = texts.filter(t => t.startsWith('1 % недельного лимита'))
  if (lines.length !== 1 || texts.at(-1) !== lines[0] || lines[0] !== COST_END(at, per)) throw new Error(`${what}: the end of the tab: ${JSON.stringify(texts.slice(-3))}`)
  if (texts.length !== 3) throw new Error(`${what}: ${texts.length} native texts: ${JSON.stringify(texts)}`)
}

test('desktop, Cost: twelve cards, one population cut twelve ways; each THE table; nothing cut', async ($, on) => {
  const { ui, go } = await mount($, on)
  await go('tab-cost')
  await noDots(ui, 'cost')
  const r = await readCost(ui, go)
  // the tables that hold no ticket title, no role name and no chat name: every word of them is the mod's own
  const OWN = ['По виду токенов', 'По дням']
  // (the muted lines under a table name agent types and chat titles: GitHub's and Claude Code's own words)
  const FREE: string[] = []
  await noCode(ui, 'cost', OWN, FREE)
  const c = slow.cost_week.cut
  const total = c.total.cost_usd
  const other = oneLook(r, 'cost', CUT_NAMES)
  const sp = (k: string) => c.by_spawner.find((x: any) => x.key === k)
  const SPN: Record<string, string> = { orch: 'ORCH: сам и кого запускает', autopilot: 'autopilot: сам и кого запускает', brain: 'brain: сам и кого запускает' }
  const spSub = (k: string) => (sp(k) ? `${SPN[k]} · ${sessWord(sp(k).sessions)} · всего ${usd(sp(k).cost_usd)}` : SPN[k]!)
  const chatSum = sumOf(c.by_who.filter((x: any) => x.kind === 'chat' || x.kind === 'untitled'))
  has(other, ['По ролям', spSub('orch'), spSub('autopilot'), spSub('brain'), `Моды · ${usd(sumOf(c.by_mod))} из ${usd(total)}`, `По чатам · ${usd(chatSum)} из ${usd(total)}`, 'Роль на разных моделях', 'ORCH на разных моделях: результат', 'По моделям: кто вызывает', 'По виду токенов', 'По дням', 'По тикетам'], 'cost: card heads')
  if (other.some(a => /^keymaster/.test(a))) throw new Error('a card is named keymaster: ' + other)
  // the period's three plain presses, no white `primary` fill (#793 F01); the selected one is the one not dimmed (the pane opens on the week)
  const sw = r.buttons.filter(b => String(b.key).startsWith('cost-'))
  // #994: the period's words are drawn in the switch picture (the chosen one in its capsule); its three presses are blank Buttons over them
  if (sw.map(b => `${b.key}:${String(b.label).trim()}:${b.variant ?? ''}`).join(' ') !== 'cost-day:: cost-week:: cost-month::') throw new Error('the period switcher: ' + JSON.stringify(sw))
  if (!r.pics.some(p => String(p.alt) === 'День · [Неделя] · Месяц')) throw new Error('the period switcher picture: ' + r.pics.map(p => p.alt).join(' | ').slice(0, 300))
  // the head line: the period at the left, the bold line at the right; the fixture week is the real one
  if (c.days !== 7) throw new Error('the fixture week is not 7 days: ' + c.days)
  has(r.texts, [periodOf(c), headOf(c), COST_END(slow.at, c.total.limit_usd_per_pct)], 'cost: the head line and the one muted line')
  if (!headOf(c).includes('≈ 80 % недельного лимита')) throw new Error('week head: ' + headOf(c))
  // #1018 A: the week is against the weekly limit (limit_days 7): the head says недельного, and the mod draws that line
  if (c.total.limit_days !== 7 || !r.texts.some(t => t.includes('≈ 80 % недельного лимита'))) throw new Error('week: the unit of the head: ' + c.total.limit_days + ' ' + JSON.stringify(r.texts.filter(t => t.includes('лимита'))))
  await noGlyphs(ui, 'cost')
  const words = (await seen(ui)).join('\n')
  for (const b of BANNED) if (words.includes(b)) throw new Error(`the tab draws «${b}»`)
  checkCost(r, c, 'week')
  cardLook(r, slow.at, 'week', c.total.limit_usd_per_pct)
  // the week's fixture: the facts this test relies on
  if (c.by_role.length !== 11 || c.by_spawner.length !== 5 || c.by_mod.length !== 2) throw new Error('the fixture week changed shape')
  const [tRole, , tOrch, , , tBrain, tMod, tWho, , , , tIssue] = r.tables as Table[]
  // the count words of three rows, from the fixture's own numbers (the fixture is refilled from the real week)
  const sp3 = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  const nOf = (k: string) => c.by_role.find((x: any) => x.key === k).n as number
  has(tRole!.words, [`${sp3(nOf('orch'))} ${pluralOf(nOf('orch'), 'сессия', 'сессии', 'сессий')}`,
    `${sp3(nOf('worker'))} ${pluralOf(nOf('worker'), 'субагент', 'субагента', 'субагентов')}`,
    `${sp3(nOf('mod'))} ${pluralOf(nOf('mod'), 'вызов', 'вызова', 'вызовов')}`], 'week: the count words')
  if (rowsIn(tOrch!) !== 6 || rowsIn(tBrain!) !== 4) throw new Error(`week: spawner rows ${rowsIn(tOrch!)} / ${rowsIn(tBrain!)}`)
  if (rowsIn(tWho!) !== 11 || !tWho!.words.includes('остальные (2)')) throw new Error(`week: chats ${rowsIn(tWho!)}`)
  if (rowsIn(tMod!) !== 2) throw new Error('week: mods')
  // По тикетам: 20 tickets (the number a native Link over its row, the title whole), the rest, the ones with no ticket
  const rowsI = tIssue!.hov
  if (rowsI.length !== 22 || c.by_issue.length !== 20) throw new Error(`tickets: ${rowsI.length} rows`)
  has(tIssue!.words, [`остальные тикеты (${c.issue_rest.n})`, 'без тикета'], 'tickets: the rest rows')
  has(heads(tIssue!.src), ['тикет', 'название', '% лимита', '$', 'токенов'], 'tickets: column labels')
  const flat = squash(tIssue!.words.join(''))
  let cards = 0
  c.by_issue.forEach((x: any, k: number) => {
    const h = rowsI[k]!
    const known = tk.issues[String(x.number)]
    if (h.links.length !== 1 || h.links[0]!.label !== `#${x.number}` || h.links[0]!.card) throw new Error(`tickets #${x.number}: ${JSON.stringify(h.links)}`)
    has(tIssue!.words, [usd(x.cost_usd), limPct(x.cost_usd, c.total.limit_usd_per_pct), tokH(x.tokens)], 'tickets')
    if (known && !titleIn(flat, known.title)) throw new Error(`tickets #${x.number}: its title is neither whole nor cut with «…»`)
    if (known) cards++
  })
  if (!cards) throw new Error(`tickets: ${cards} known tickets`) // #771: a plain link now, no hover card (card === false above)
  // a known ticket carries its state icon, nothing else does
  if (icons(tIssue!.src).length !== cards) throw new Error(`tickets: ${icons(tIssue!.src).length} state icons for ${cards} known tickets`)
  if (rowsI.slice(20).some(h => h.links.length)) throw new Error('tickets: a link on the rest rows')
  // day: no «в день» column in the spawner and mods tables, ten tables, autopilot has no turn (a head and no rows)
  await go('cost-day')
  const rd = await readCost(ui, go)
  oneLook(rd, 'cost, day', CUT_NAMES)
  has(rd.texts, [periodOf(slow.cost_day.cut), headOf(slow.cost_day.cut)], 'cost, day: head')
  if (slow.cost_day.cut.days !== 1) throw new Error('the fixture day is not 1 day')
  checkCost(rd, slow.cost_day.cut, 'day')
  cardLook(rd, slow.at, 'day', slow.cost_day.cut.total.limit_usd_per_pct)
  for (const k of [2, 4, 5, 6]) if (heads(rd.tables[k]!.src).includes('в день')) throw new Error(`day: «в день» in ${rd.tables[k]!.alt}`)
  if (slow.cost_day.cut.by_spawner.some((x: any) => x.key === 'autopilot')) throw new Error('the fixture day holds autopilot')
  if (rowsIn(rd.tables[4]!) !== 0) throw new Error('day: autopilot card has rows')
  await noDots(ui, 'cost, day')
  await noCode(ui, 'cost, day', OWN, FREE)
  await go('cost-month')
  const rm = await readCost(ui, go)
  oneLook(rm, 'cost, month', CUT_NAMES)
  has(rm.texts, [periodOf(slow.cost_month.cut), headOf(slow.cost_month.cut)], 'cost, month: head')
  if (!headOf(slow.cost_month.cut).includes('≈ 455 % месячного лимита')) throw new Error('month head: ' + headOf(slow.cost_month.cut))
  // #1018 A: the month is against a month's limit (limit_days 30): the head says месячного лимита, and the mod draws that line, not недельного
  if (slow.cost_month.cut.total.limit_days !== 30 || !rm.texts.some(t => t.includes('≈ 455 % месячного лимита')) || rm.texts.some(t => t.includes('недельного лимита') && !t.startsWith('1 % недельного лимита'))) throw new Error('month: the unit of the head: ' + JSON.stringify(rm.texts.filter(t => t.includes('лимита'))))
  checkCost(rm, slow.cost_month.cut, 'month')
  cardLook(rm, slow.at, 'month', slow.cost_month.cut.total.limit_usd_per_pct)
  const mw = slow.cost_month.cut.by_who.filter((x: any) => x.kind === 'chat' || x.kind === 'untitled').length
  if (rowsIn(rm.tables[7]!) !== 11 || !rm.tables[7]!.words.includes(`остальные (${mw - 10})`)) throw new Error(`month: По чатам ${rowsIn(rm.tables[7]!)} rows`)
  await noDots(ui, 'cost, month')
  await noCode(ui, 'cost, month', OWN, FREE)
  await ui.unmount()
})

// #841 / #927: every open ticket is counted ONCE on the first line of the rule that fits. The fixture below has one ticket per
// line, a blocked child of a blocked map, a labelled map, a ticket with 11 labels; the counts are written BY HAND (not the card's rule).
const prog = (n: number, o: any = {}) => ({ n, title: `T${n}`, open: true, reason: null, labels: [], parent: null, blockers: [], kids: [], state: 'open', parked_on_run: false, ...o })
const PROG_ISSUES: any[] = [
  prog(1, { labels: ['needs-triage'] }), prog(2, { labels: ['needs-info'] }), prog(3, { labels: ['ready-for-agent'] }),
  prog(4, { labels: ['ready-for-human'] }), prog(5, { labels: ['wontfix'] }),
  prog(6, { labels: ['autopilot'], blockers: [99] }), // autopilot wins over a blocker
  prog(7, { labels: ['wayfinder:map'], blockers: [99] }), // a labelled map, itself blocked: a folder
  prog(8, { labels: ['core-epic'] }),
  prog(9, { kids: [10] }), prog(10, { parent: 9 }), // an open sub-ticket makes a folder; the child itself has no label
  prog(11, { blockers: [99] }),
  prog(12, { labels: ['wayfinder:map'], blockers: [99], kids: [13] }), prog(13, { parent: 12 }), // a blocked child of a blocked map
  prog(14, { parked_on_run: true }),
  prog(15, { parked_on_run: true, blockers: [99] }), // blocked wins over parked
  prog(16),
  prog(17, { labels: [...Array.from({ length: 10 }, (_, k) => `area:a${k}`), 'ready-for-human'] }), // the 11th label is the triage one
  prog(18, { open: false, labels: ['needs-triage'], state: 'closed' }), // closed: nowhere
  prog(19, { kids: [20] }), prog(20, { open: false, parent: 19, state: 'closed' }), // only a closed sub-ticket: no folder
]
test('desktop, Progress: every open ticket on ONE line of the rule; counts by hand; lines sum to the open total', async ($, on) => {
  const was = OUT.tickets
  OUT.tickets = JSON.stringify({ ...tk, issues: Object.fromEntries(PROG_ISSUES.map(i => [String(i.n), i])), goals: [], loose: [] })
  try {
    const { ui, go } = await mount($, on)
    await go('tab-progress')
    await noDots(ui, 'progress')
    const r = await read(ui)
    // by hand: [hover key, words on the line, count]; 18 tickets are open (18 and 20 are closed)
    const want: [string, string, number][] = [
      ['needs-triage', 'needs-triage', 1], ['needs-info', 'needs-info', 1], ['ready-for-agent', 'ready-for-agent', 1],
      ['ready-for-human', 'ready-for-human', 2], ['wontfix', 'wontfix', 1], ['autopilot', 'autopilot', 1],
      ['folder', 'folder', 4], ['blocked', 'blocked', 3], ['parked-on-run', 'parked-on-run', 1], ['no label', 'no label', 3],
    ]
    if (want.reduce((a, [, , n]) => a + n, 0) !== 18) throw new Error('the hand counts do not sum to 18')
    // #995 row 5: two cards in this order: «По тикетам» (every line of a ticket's state, 14 tickets) and «Остальное» (the folder, 4); each a title, its count and a table with a head
    await noCode(ui, 'progress', ['По тикетам', 'Остальное'])
    const other = oneLook(r, 'progress', ['По тикетам', 'Остальное'])
    has(other, ['По тикетам · 14', 'Остальное · 4'], 'progress: the card heads')
    const parts: [typeof want, number][] = [[want.filter(([k]) => k !== 'folder'), 0], [want.filter(([k]) => k === 'folder'), 1]]
    for (const [ws, k] of parts) {
      const t = r.tables[k]!
      has(t.words, ['метка', 'тикетов', 'доля', ...ws.flatMap(([, w, n]) => [w, String(n)])], `progress ${k}`)
      // #995 send-back 1 (defect 4): a count row opens nothing, so it has no row Box and lights nothing; the lines stand in the rule's order
      if (t.hov.length) throw new Error(`progress ${k}: a count row lights under the pointer: ` + t.hov.map(h => h.key))
      const at = ws.map(([, w]) => t.words.indexOf(w))
      if (at.some((x, i) => x < 0 || (i > 0 && x <= at[i - 1]!))) throw new Error(`progress ${k}: lines out of order ` + JSON.stringify(at))
      const paths = [...t.src.matchAll(/<path d="([^"]+)" fill="none" stroke="(#[0-9a-zA-Z]+)"[^>]*stroke-width="6"/g)].map(m => ({ d: m[1]!, n: (m[1]!.match(/M/g) ?? []).length, col: m[2] }))
      if (paths.length !== 2 || paths[0]!.n !== ws.length || paths[1]!.n !== ws.length || paths[1]!.col !== '#4493f8') throw new Error(`progress ${k} bars: ` + JSON.stringify(paths))
      // #995 send-back 1 (defect 2): a bar is the line's share of ITS OWN card's total (the title's number), not of both cards' sum: fill + 6 over track + 6 (kit tableSvg: each is drawn 6 px short for its round caps)
      const hs = (d: string) => [...d.matchAll(/h([\d.]+)/g)].map(m => Number(m[1]))
      const track = hs(paths[0]!.d), fill = hs(paths[1]!.d)
      const own = ws.reduce((a, [, , n]) => a + n, 0)
      ws.forEach(([key, , n], i) => {
        const got = (fill[i]! + 6) / (track[i]! + 6)
        if (Math.abs(got - n / own) > 0.01) throw new Error(`progress ${k} ${key}: bar ${got.toFixed(3)} of the card, want ${n} / ${own} = ${(n / own).toFixed(3)}`)
      })
    }
    has(r.texts, [fresh(tk.at)], 'progress: texts')
    await ui.unmount()
  } finally { OUT.tickets = was! }
})

// a line with no ticket is not drawn, except needs-triage and no label (#1079: the names as written)
test('desktop, Progress: an empty line is not drawn, only needs-triage and no label stay', async ($, on) => {
  const was = OUT.tickets
  OUT.tickets = JSON.stringify({ ...tk, issues: { '1': prog(1, { labels: ['ready-for-agent'] }) }, goals: [], loose: [] })
  try {
    const { ui, go } = await mount($, on)
    await go('tab-progress')
    const r = await read(ui)
    const t = r.tables[0]!
    // the lines drawn, read from the picture's words (a count row has no Box since #995 send-back 1)
    const drawn = ['needs-triage', 'needs-info', 'ready-for-agent', 'ready-for-human', 'wontfix', 'autopilot', 'blocked', 'parked-on-run', 'no label'].filter(w => t.words.includes(w))
    if (drawn.join() !== 'needs-triage,ready-for-agent,no label' || t.hov.length) throw new Error('progress rows: ' + drawn + ' / boxes ' + t.hov.length)
    if (r.tables[1]?.words.includes('folder')) throw new Error('an empty folder line is drawn')
    await ui.unmount()
  } finally { OUT.tickets = was! }
})

// A pane half as wide: still no «…»: a title wraps onto more lines, and a column with no room leaves its table whole
// (By model's note of a model), its words in no row.
test('desktop, 60 columns: titles stay one line (cut with an ellipsis), a column with no room leaves the table (#994)', async ($, on) => {
  const NARROW = 60
  const tw = Math.round(NARROW * 7.8)
  const { ui, go } = await mount($, on, NARROW)
  await go('tab-tickets')
  await go('tg-63')
  await noDots(ui, 'tickets, 60')
  const r = await read(ui)
  if (r.tables.length !== 2 || r.pics.filter(p => p.width != null).some(p => p.width !== tw)) throw new Error('tickets, 60: tables ' + r.pics.map(p => p.width))
  const flat = squash(r.tables[0]!.words.join(''))
  const rows = [...tk.goals, ...tk.issues['63'].kids].map((n: number) => tk.issues[String(n)]).filter(Boolean)
  const cutTitle = rows.filter((i: any) => !titleIn(flat, i.title))
  if (cutTitle.length) throw new Error('tickets, 60: a title is neither whole nor cut with «…»: ' + cutTitle[0].title)
  // #994: a title is ONE line (cut with «…» at its column), never wrapped
  if (r.tables[0]!.hov.some(h => h.height > 1)) throw new Error('tickets, 60: a title wrapped')
  has(heads(r.tables[0]!.src), ['тикет', 'название', 'готово'], 'tickets, 60: the done column stays')
  await noCode(ui, 'tickets, 60')
  await go('tab-cost')
  await noDots(ui, 'cost, 60')
  await noCode(ui, 'cost, 60', ['По виду токенов', 'По дням'], ['другие субагенты:', 'чаты:'])
  const c = await readCost(ui, go)
  if (c.tables.length !== 12) throw new Error(`cost, 60: ${c.tables.length} tables`)
  if (c.tables.map(x => x.alt).join('|') !== CUT_NAMES.join('|') || c.tables.some(x => rowsIn(x) === 0)) throw new Error('cost, 60: tables ' + c.tables.map(x => x.alt))
  // the pane too narrow: the note of a row leaves its table, the numbers that are left stay whole
  const byModel = c.tables[8]!
  has(byModel.words, ['модель / роль', '$', 'Haiku 5.5'], 'By model, 60')
  if (c.tables[11]!.hov.some(h => h.height > 1)) throw new Error('cost, 60: a ticket title wrapped (#994: one line, cut with an ellipsis)')
  if (byModel.words.includes('нет цены')) throw new Error('By model, 60: the note column is still drawn: ' + byModel.words.join(' | '))
  await go('tab-progress')
  await noDots(ui, 'progress, 60')
  await noCode(ui, 'progress, 60', ['По тикетам', 'Остальное'])
  await ui.unmount()
})
