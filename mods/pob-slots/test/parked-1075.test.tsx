import { test } from 'claude-code/testing'
import { TICKETS } from './fixtures'
import { mountPane, dq } from './kit'
import { allPics, readPic } from './pics-837-b9b'
import { ICONS, progressLines } from '../hooks/kit'

// #1075 (the owner, 15.10: «в табке Тикеты и Прогресс паркед пишется ... в названии»): a ticket labelled `parked` (the collector's
// row field `parked`) draws the parked mark (`pause.octicons`) where the held / blocked mark stands on the Tickets tab, and it is
// one line of the Progress tab that is never counted in the in-work line. Titles are drawn as GitHub holds them: no word «parked».

const PARKED = 'pause.octicons'
// the path data of an icon of the set (its first `d`, or the whole shape)
const shapeOf = (name: string) => { const s = ICONS[name]?.[1] ?? ''; return / d="([^"]+)"/.exec(s)?.[1] ?? s }
// the shape an icon `<use href="#iK">` names, from its `<defs>` entry `id="iK"`
const iconDef = (d: string, id: string) => {
  const i = d.indexOf(` id="${id}"`)
  if (i < 0) return ''
  const ends = [d.indexOf(' id="i', i + 5), d.indexOf('</defs>', i)].filter(x => x >= 0)
  return d.slice(i, ends.length ? Math.min(...ends) : d.length)
}
// the shapes of every icon a table draws on the line whose text is `label`: a `<use href="#iN" x y/>` within the line's band (the
// Tickets table), or an inline `<g transform="translate(X Y) scale(S)">` whose centre (Y + 8 S) is in the band (the Progress table)
const shapesOnLine = (src: string, label: string) => {
  const d = dq(src)
  const ty = +(new RegExp(`<tspan [^>]*y="([\\d.]+)"[^>]*>${label}</tspan>`).exec(d)?.[1] ?? NaN)
  if (Number.isNaN(ty)) return null
  const uses = [...d.matchAll(/<use href="#(i\d+)" x="([\d.-]+)" y="([\d.-]+)"\/>/g)].map(m => ({ id: m[1]!, y: +m[3]! }))
  const useShapes = uses.filter(u => Math.abs(u.y - ty) < 12).map(u => iconDef(d, u.id))
  const inline = [...d.matchAll(/<g transform="translate\(([\d.-]+) ([\d.-]+)\) scale\(([\d.]+)\)"[^>]*>([\s\S]*?)(?=<g transform="translate\(|<text|<\/svg>)/g)]
    .filter(m => Math.abs(+m[2]! + 8 * +m[3]! - ty) < 12).map(m => m[4]!)
  return [...useShapes, ...inline]
}

const issue = (n: number, title: string, o: Record<string, unknown>) => ({
  n, title, open: true, reason: null, labels: [] as string[], parent: null, blockers: [] as number[], kids: [] as number[],
  state: 'open', created: '2026-10-14T10:00:00Z', author: 'mod', parked_on_run: false, parked: false, ...o,
})
const base = JSON.parse(TICKETS)

// Tickets: three parked rows (the mark each must draw), one ready row that must not be marked
const TK_ISSUES: Record<string, any> = {
  301: issue(301, 'Ticket one', { labels: ['parked'], parked: true }),
  302: issue(302, 'Ticket two', { labels: ['parked'], parked: true }),
  303: issue(303, 'Ticket three', { labels: ['parked', 'autopilot'], parked: true }),
  304: issue(304, 'Ticket four', { labels: ['ready-for-agent'], state: 'ready' }),
}
const TK = { ...base, goals: Object.keys(TK_ISSUES).map(Number), loose: [], issues: TK_ISSUES }
const PARKED_TITLES = ['Ticket one', 'Ticket two', 'Ticket three']

test('#1075 tickets: three parked rows draw the parked mark, no title holds the word parked', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tickets: JSON.stringify(TK), tab: 'tickets' }, 123)
  const all = JSON.stringify(await (ui as any).drawn())
  const tables = allPics(await (ui as any).drawn()).filter(p => /^(Цели|Вне целей)$/.test(String(p.props?.alt))).map(p => String(p.props.source))
  const pauseShape = shapeOf(PARKED)
  const marked = PARKED_TITLES.filter(t => tables.some(src => dq(src).includes(`>${t}<`) && (shapesOnLine(src, t) ?? []).some(s => s.includes(pauseShape))))
  // the titles stand on the tab as GitHub holds them, none with the word parked
  const titlesParked = PARKED_TITLES.filter(t => !all.includes(t)).length
  const badTitles = [...tables].flatMap(src => [...dq(src).matchAll(/<tspan[^>]*>([^<]*)<\/tspan>/g)].map(m => m[1]!)).filter(t => /parked/i.test(t))
  console.log(`#1075 tickets: parked marks on ${marked.length} of ${PARKED_TITLES.length} parked rows, titles with «parked» ${badTitles.length}, titles missing ${titlesParked}`)
  await ui.unmount()
  if (titlesParked) throw new Error(`Tickets tab misses rows: ${titlesParked}`)
  if (badTitles.length) throw new Error(`titles drawn with «parked»: ${JSON.stringify(badTitles)}`)
  if (marked.length !== PARKED_TITLES.length) throw new Error(`parked mark on ${marked.length} of ${PARKED_TITLES.length} rows`)
})

// Progress: three parked tickets (one of them also autopilot) and one autopilot ticket of its own
const PG_ISSUES: Record<string, any> = {
  201: issue(201, 'Progress one', { labels: ['parked'], parked: true }),
  202: issue(202, 'Progress two', { labels: ['parked'], parked: true }),
  203: issue(203, 'Progress three', { labels: ['parked', 'autopilot'], parked: true }),
  204: issue(204, 'Progress four', { labels: ['autopilot'] }),
}
const PG = { ...base, goals: Object.keys(PG_ISSUES).map(Number), loose: [], issues: PG_ISSUES }

test('#1075 progress: the parked line draws the parked mark for its three tickets and is not counted in the autopilot (in work) line', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tickets: JSON.stringify(PG), tab: 'progress' }, 123)
  const pics = allPics(await (ui as any).drawn()).filter(p => /^(По тикетам|Остальное)/.test(String(p.props?.alt)))
  const pauseShape = shapeOf(PARKED)
  let parkedCount = -1, parkedMarked = false, autopilotCount = -1
  for (const p of pics) {
    const src = String(p.props.source)
    const its = readPic(p, 123).items.filter(i => i.kind === 'text')
    const P = its.find(i => i.t === 'parked')
    // a line's count stands on the line's own baseline (the card draws its lines in one row group, so the row index does not tell them apart)
    const countOn = (L: { y: number }) => its.find(i => Math.abs(i.y - L.y) < 1 && /^\d+$/.test(i.t))
    if (P) {
      const C = countOn(P)
      parkedCount = C ? +C.t : -1
      parkedMarked = (shapesOnLine(src, 'parked') ?? []).some(s => s.includes(pauseShape))
    }
    const A = its.find(i => i.t === 'autopilot')
    if (A) {
      const C = countOn(A)
      autopilotCount = C ? +C.t : -1
    }
  }
  // the three parked tickets: the parked line counts them, draws the mark, and the in-work (autopilot) line keeps only its own one
  // the tab draws one line for the parked tickets (no row per ticket): the mark stands on that line and the line counts the three
  console.log(`#1075 progress: parked line counts ${parkedCount} tickets, mark on the line: ${parkedMarked ? 'yes' : 'no'}, in-work (autopilot) line ${autopilotCount} (the one in-work ticket is Progress four, so 0 parked ones are in it)`)
  await ui.unmount()
  if (parkedCount !== 3) throw new Error(`parked line counts ${parkedCount}, want 3`)
  if (!parkedMarked) throw new Error('parked line draws no parked mark')
  if (autopilotCount !== 1) throw new Error(`in-work (autopilot) line counts ${autopilotCount}, want 1 (only Progress four)`)
})

// #1075 send-back (code-review of unit 2): a parked ticket keeps its role label, so `parked` is checked before the triage labels:
// the parked line counts every parked ticket whatever its other labels, and a triage line counts only the unparked ones.
test('#1075 progress: parked tickets carrying a role label are counted on the parked line, not on their triage line', async () => {
  const SB: Record<string, any> = {
    401: issue(401, 'Parked ready', { labels: ['ready-for-agent', 'parked'], parked: true }),
    402: issue(402, 'Parked info', { labels: ['needs-info', 'parked'], parked: true }),
    403: issue(403, 'Parked owner', { labels: ['ready-for-human', 'parked'], parked: true }),
    404: issue(404, 'Plain ready', { labels: ['ready-for-agent'], state: 'ready' }),
  }
  const lines = new Map(progressLines(SB))
  const parkedCount = lines.get('parked') ?? 0
  const readyCount = lines.get('ready-for-agent') ?? 0
  const infoCount = lines.get('needs-info') ?? 0
  const ownerCount = lines.get('ready-for-human') ?? 0
  console.log(`#1075 progress send-back: parked ${parkedCount}, ready-for-agent ${readyCount}, needs-info ${infoCount}, ready-for-human ${ownerCount}`)
  if (parkedCount !== 3) throw new Error(`parked line counts ${parkedCount}, want 3`)
  if (readyCount !== 1) throw new Error(`ready-for-agent line counts ${readyCount}, want 1 (only Plain ready)`)
  if (infoCount !== 0) throw new Error(`needs-info line counts ${infoCount}, want 0`)
  if (ownerCount !== 0) throw new Error(`ready-for-human line counts ${ownerCount}, want 0`)
})
