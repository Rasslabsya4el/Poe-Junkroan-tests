import { test } from 'claude-code/testing'
import { TICKETS } from './fixtures'
import { mountPane, seen, dq } from './kit'
import { allPics, readPic } from './pics-837-b9b'
import { ICONS, STATE_ICON } from '../hooks/kit'

// #1079 (the owner, 15.10: «в табке Progress и Tickets каждая метка и статус пишутся как GitHub / Pocock пишет, не переводятся»): the Tickets and
// Progress tabs draw every label and ticket state by its GitHub name (`ready-for-agent`, `needs-triage`, `closed`, `not planned` ...), never by a
// Russian word; the layer-added states are `held`, `parked-on-run`. A pane dump of each tab: the names are drawn as written, every row is drawn
// by its own state, and no word of the old table is.

// the words the two tabs drew before #1079 (acceptance row 1); none may stand on the tab or in its legend (whole words, any case)
const OLD = ['готов агенту', 'не разобран', 'ждёт тикеты', 'ждёт тебя', 'ждёт ответа', 'не делаем', 'открыт', 'закрыт', 'в работе', 'нужны уточнения', 'без метки', 'в работе у автопилота', 'ждёт прогон', 'папки (тикеты с подтикетами)']
// a whole word: not a part of a longer word (`open` is not in `opened`, `открыт` is not in `открытые`)
const whole = (s: string, w: string, flags: string) => new RegExp(`(?<![\\p{L}\\d_-])${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\p{L}\\d_-])`, flags).test(s)

// one ticket per label of the Rule (16), one closed row, one not-planned closed row, plus the layer's own states (blocked, parked-on-run) and an autopilot
const issue = (n: number, o: Record<string, unknown>) => ({
  n, title: `Row ${n}`, open: true, reason: null, labels: [] as string[], parent: null, blockers: [] as number[], kids: [] as number[],
  state: 'open', created: '2026-10-14T10:00:00Z', author: 'mod', parked_on_run: false, ...o,
})
const base = JSON.parse(TICKETS)
const ISSUES: Record<string, any> = {
  101: issue(101, { labels: ['needs-triage'], state: 'triage' }),
  102: issue(102, { labels: ['needs-info'], state: 'owner' }),
  103: issue(103, { labels: ['ready-for-agent'], state: 'ready' }),
  104: issue(104, { labels: ['ready-for-human'], state: 'owner' }),
  105: issue(105, { labels: ['wontfix'] }),
  106: issue(106, { labels: ['parked'] }),
  107: issue(107, { labels: ['wayfinder:map'] }),
  108: issue(108, { labels: ['wayfinder:task'] }),
  109: issue(109, { labels: ['wayfinder:grilling'] }),
  110: issue(110, { labels: ['wayfinder:research'] }),
  111: issue(111, { labels: ['wayfinder:prototype'] }),
  112: issue(112, { labels: ['core-issue'] }),
  113: issue(113, { labels: ['core-epic'] }),
  114: issue(114, { labels: ['area:monitor'] }),
  115: issue(115, { labels: ['bug'] }),
  116: issue(116, { labels: ['enhancement'] }),
  117: issue(117, { labels: ['bug'], open: false, reason: 'COMPLETED', state: 'closed' }),
  118: issue(118, { labels: ['wontfix'], open: false, reason: 'NOT_PLANNED', state: 'closed' }),
  119: issue(119, { labels: ['autopilot'] }),
  120: issue(120, { blockers: [101], state: 'blocked' }),
  121: issue(121, { parked_on_run: true }),
}
const TK = { ...base, goals: Object.keys(ISSUES).filter(n => n !== '120').map(Number), loose: [120], issues: ISSUES }

// the state icon each row must draw (the Tickets tab draws no label word: its rows are icons, the legend names them)
const EXPECT: Record<string, keyof typeof STATE_ICON> = {
  101: 'triage', 102: 'owner', 103: 'ready', 104: 'owner', 105: 'open', 106: 'open', 107: 'open', 108: 'open', 109: 'open', 110: 'open', 111: 'open',
  112: 'open', 113: 'open', 114: 'open', 115: 'open', 116: 'open', 117: 'closed', 118: 'dropped', 119: 'open', 120: 'blocked', 121: 'open',
}
// the Progress lines and their counts by hand: 19 open tickets (117 and 118 are closed)
const WANT: [string, number][] = [['needs-triage', 1], ['needs-info', 1], ['ready-for-agent', 1], ['ready-for-human', 1], ['wontfix', 1], ['autopilot', 1],
  ['folder', 2], ['blocked', 1], ['parked-on-run', 1], ['no label', 9]]
// the shape of the icon a table row draws: the table places it as `<use href="#iK" x y/>` on the row's line, the shape itself in <defs> as `id="iK"`
const iconDef = (d: string, id: string) => {
  const i = d.indexOf(` id="${id}"`)
  if (i < 0) return ''
  const ends = [d.indexOf(' id="i', i + 5), d.indexOf('</defs>', i)].filter(x => x >= 0)
  return d.slice(i, ends.length ? Math.min(...ends) : d.length)
}
// the path data of an icon of the set (its first `d`, or the whole shape for a circle)
const shapeOf = (name: string) => { const s = ICONS[name]?.[1] ?? ''; return / d="([^"]+)"/.exec(s)?.[1] ?? s }
// the icon drawn on the line of the row whose title is `title` (the use nearest to the title's baseline), '' when none
const drawnShape = (src: string, title: string) => {
  const d = dq(src)
  const ty = +(new RegExp(`<tspan [^>]*y="([\\d.]+)"[^>]*>${title}</tspan>`).exec(d)?.[1] ?? NaN)
  const uses = [...d.matchAll(/<use href="#(i\d+)" x="([\d.-]+)" y="([\d.-]+)"\/>/g)].map(m => ({ id: m[1]!, y: +m[3]! }))
  const near = uses.filter(u => Math.abs(u.y - ty) < 12).sort((a, b) => Math.abs(a.y - ty) - Math.abs(b.y - ty))[0]
  return near ? iconDef(d, near.id) : ''
}

test('#1079: the Tickets tab draws its states and legend by GitHub name, every row by its state icon, no old word', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tickets: JSON.stringify(TK), tab: 'tickets' }, 123)
  const words = await seen(ui)
  const all = words.join('\n')
  // the legend's names (the states of the Tickets tab, `not planned` for a not-planned close)
  const names = ['held', 'ready-for-human', 'ready-for-agent', 'blocked', 'open', 'needs-triage', 'closed', 'not planned']
  const missing = names.filter(nm => !whole(all, nm, 'u'))
  const old = OLD.filter(w => whole(all, w, 'iu'))
  // every row of the fixture is drawn: its title stands on the tab
  const titles = Object.values(ISSUES).map((i: any) => i.title).filter(t => !all.includes(t))
  // every row is drawn by the icon of its own state (the path of the icon the state names)
  const tables = allPics(await (ui as any).drawn()).filter(p => /^(Цели|Вне целей)$/.test(String(p.props?.alt))).map(p => String(p.props.source))
  const wrong = Object.entries(EXPECT).filter(([n, st]) => {
    const src = tables.find(s => dq(s).includes(`>Row ${n}<`))
    const shape = shapeOf(STATE_ICON[st][0])
    return !src || !shape || !drawnShape(src, `Row ${n}`).includes(shape)
  }).map(([n, st]) => `Row ${n} is not drawn as ${st}`)
  console.log(`#1079 tickets: names missing ${JSON.stringify(missing)}, old words ${JSON.stringify(old)}, titles missing ${titles.length}, rows wrong ${wrong.length}`)
  await ui.unmount()
  if (missing.length) throw new Error(`Tickets tab does not draw: ${missing.join(', ')}`)
  if (old.length) throw new Error(`Tickets tab draws old words: ${JSON.stringify(old)}`)
  if (titles.length) throw new Error(`Tickets tab misses rows: ${titles.join(', ')}`)
  if (wrong.length) throw new Error(`Tickets tab draws a row with another state: ${wrong.join('; ')}`)
})

test('#1079: the Progress tab draws its label lines by GitHub name, each with its count, no old word', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tickets: JSON.stringify(TK), tab: 'progress' }, 123)
  const words = await seen(ui)
  const all = words.join('\n')
  // the lines of the fixture, by the name the Progress card draws (`parked-on-run`, `no label`, `folder`, `blocked` as the layer names them)
  const names = ['needs-triage', 'needs-info', 'ready-for-agent', 'ready-for-human', 'wontfix', 'autopilot', 'folder', 'blocked', 'parked-on-run', 'no label']
  const missing = names.filter(nm => !whole(all, nm, 'u'))
  const old = OLD.filter(w => whole(all, w, 'iu'))
  // each line's count stands on the line's own row, and its name ends before the count column (no cut, no overlap)
  const pics = allPics(await (ui as any).drawn()).filter(p => /^(По тикетам|Остальное)/.test(String(p.props?.alt)))
  const bad: string[] = [], found: string[] = []
  for (const p of pics) {
    const its = readPic(p, 123).items.filter(i => i.kind === 'text')
    for (const [label, n] of WANT) {
      const L = its.find(i => i.t === label)
      if (!L) continue
      found.push(label)
      const C = its.find(i => i.row === L.row && i.t === String(n))
      if (!C) bad.push(`${label}: ${n} not on its row`)
      else if (L.x1 > C.x0 - 2) bad.push(`${label}: name runs into the count column (${L.x1.toFixed(1)} > ${C.x0.toFixed(1)})`)
    }
  }
  const lines = WANT.map(([l]) => l).filter(l => !found.includes(l))
  console.log(`#1079 progress: names missing ${JSON.stringify(missing)}, old words ${JSON.stringify(old)}, lines not drawn ${JSON.stringify(lines)}, line errors ${bad.length}`)
  await ui.unmount()
  if (missing.length) throw new Error(`Progress tab does not draw: ${missing.join(', ')}`)
  if (old.length) throw new Error(`Progress tab draws old words: ${JSON.stringify(old)}`)
  if (lines.length) throw new Error(`Progress tab does not draw the lines: ${lines.join(', ')}`)
  if (bad.length) throw new Error(`Progress tab: ${bad.join('; ')}`)
})
