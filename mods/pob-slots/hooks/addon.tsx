import { K } from './tokens'
import { SCRIPT, REPO, GH, CLASS } from './project'
import { PX, textWidth, fit, besc } from './draw'

import type { BuildPanel, Cell, Job, Machine, Progress, Reading, Runs, Fast, CpuSample, RunPick } from '../types'
import type { Addon } from './register'
import { P0, words, GRID_GAP, PX_PER_COL, dur, fitGrid, icon, num, pctCol, queueEnd, ru, ruForm, slots, slotsRu, whole, emptyRow, drawnW, PG_W, PICTURE_PASSES, n1, n1r } from './kit'
import type { CellKind, CellV, Hot, Press, RowCol, RowCtx, RowSpec, SlotMark, TCellV, TCol, QRun, QDone } from './kit'
import type { LanePlan, Unit } from './budget'

/** #837 b17f (size guard): an ascendancy face (`<image href='data:..' x y width height style/>`, ~1,070 characters of base64) a picture draws twice or more is ONE `<image id='fN' href='data:..' width height style/>` in the
 *  picture's <defs> and a `<use href='#fN' x='..' y='..'/>` where it stood (the runs card of the real payload drew 18 faces of 9 ascendancies: 18 -> 9 copies, -9.6k). THE ONE PLACE that decides how a repeated face is
 *  written: whether the host draws a `<use>` of an `<image>` was not measured in the real pane when this was written (the host is not run by the tests), so if it does not, `return svg` here puts the faces back.
 *  Only a copy that saves characters is made. `flat` (test/kit.ts) writes every use out again. */
const FACE_TAG = /<image href='(data:[^']*)' x='([^']*)' y='([^']*)' width='(\d+)' height='(\d+)' style='image-rendering:pixelated'\/>/g
const shareFaces = (svg: string) => {
  const count = new Map<string, number>()
  for (const m of svg.matchAll(FACE_TAG)) count.set(m[1]! + '|' + m[4] + '|' + m[5], (count.get(m[1]! + '|' + m[4] + '|' + m[5]) ?? 0) + 1)
  const ids = new Map<string, string>()
  let defs = ''
  for (const [k, n] of count) {
    if (n < 2) continue
    const [href, w, h] = k.split('|')
    const id = `f${ids.size}`, def = `<image id='${id}' href='${href}' width='${w}' height='${h}' style='image-rendering:pixelated'/>`
    // a copy as it stood is the tag with its own x and y; a use has `<use href='#fN' x='' y=''/>` (at least 25 characters, the x and y it keeps)
    if (n * (def.length - 40) - def.length <= 0) continue
    ids.set(k, id)
    defs += def
  }
  if (!ids.size) return svg
  const out = svg.replace(FACE_TAG, (t, href, x, y, w, h) => { const id = ids.get(href + '|' + w + '|' + h); return id ? `<use href='#${id}' x='${x}' y='${y}'/>` : t })
  const at = out.indexOf('</defs>')
  if (at >= 0) return out.slice(0, at) + defs + out.slice(at)
  const st = out.indexOf('</style>')
  return st >= 0 ? out.slice(0, st + 8) + `<defs>${defs}</defs>` + out.slice(st + 8) : svg
}
PICTURE_PASSES.push(shareFaces) // #1094 unit 3b: the picture's passes; a pane with no add-on draws no shared face

// The runs card's row costs (#983 / #972): what one row of each kind adds to the drawn tree, upper bounds (test/budget-kinds-983.test.tsx holds them).
// The general budget (budget.ts) does not know these rows; `lane` takes them as the unit costs. A build row and a grid line pay their ascendancy face on top: the face's own length.
export const RUN_COST = {
  run: 2_050, runBuild: 2_650, runMore: 1_150, runExtra: 1_800,
  queued: 1_950, queuedExtra: 1_000,
  done: 2_100, doneExtra: 1_300,
  gridLine: 1_750, seed: 760, gridStrip: 900, gridMore: 1_150, gridExtra: 2_600,
} as const

// «done / total билдов»: the noun agrees with the total (1 / 1 билд, 2 / 3 билда, 6 / 6 билдов)
export const buildsRu = (done: number, total: number, open = false) => `${done} / ${total}${open ? '+' : ''} ${ruForm(total, 'билд', 'билда', 'билдов')}`
// #995 (the owner, 14.10: «Мне не нужна шкала с квадратиками отображающая колво билдов, х/у достаточно»): a run's builds are the text `done / total` in the
// «билды» column (an open total «3 / 5+»), no bar; the row's alt keeps the words («3 / 5 билдов»). runs.py's priorities are P0 > P1 > P2 (store.py PRIORITIES): 3, 2, 1 bars lit.
export const buildsCount = (done: number, total: number, cls: string, open = false): CellV => ({ t: `${done} / ${total}${open ? '+' : ''}`, cls })
export const PRIO_LIT: Record<string, number> = { P0: 3, P1: 2, P2: 1 }
export const metaPics = (j: { priority?: string | null; host?: string | null }, held: number | null | undefined, words: string, tail = ''): CellV => ({
  t: words, cls: 'mu', pics: { lit: PRIO_LIT[j.priority ?? ''] ?? 0, host: j.host ?? '', slots: held ?? 0, tail },
})
// One glyph per build cell: a plain Button whose label is a coloured square (one code point each).
// #683 r4c: GitHub colours (done purple, running green, failed red, waiting / queued black).
export const GLYPH: Record<Cell['state'], string> = { done: '\u{1F7EA}', failed: '\u{1F7E5}', running: '\u{1F7E9}', waiting: '\u2B1B', queued: '\u2B1B' }
export const CELL_COL: Record<Cell['state'], string> = { done: K.done, failed: K.nfailed, running: K.active, waiting: K.nmuted, queued: K.nmuted }

// This project's own add-on of the pane (#796 u4c): the PoB runs card, the Laptop card, the reservation rows and the slot squares of
// the PC card. The pane (register.tsx) imports it statically and draws only what its registry lists; with no add-on it draws the
// generic cards. Its six atoms stay in register.tsx (the loader wants an atom and every read / update of it in one file) and arrive in the context.


// The 16-px (rows) and 64-px (build panel) ascendancy faces, read once per name and size as data URIs ('' = none).
export const faces = new Map<string, string>()
/** #837 b9a: the ids of a picture are one document's: the x a still mark first stands at is kept for the whole picture, not for one row */
const seen = new WeakMap<object, Record<string, number>>()
// An entry's state as a mark: the palette's icon and colour (DESIGN-SYSTEM.md, tokens).
export const SEED_MARK: Record<Cell['state'] | 'ended', [string, string]> = {
  ended: ['pause.octicons', K.idle], done: ['done.octicons', K.done], failed: ['failed.octicons', K.failed], running: ['running', K.active],
  waiting: ['waiting.octicons', K.wait], queued: ['waiting.octicons', K.wait],
}
/** The width a seed's native press takes after its column (a plain Button's label at 13 px and its padding). */
export const seedW = (label: string) => textWidth(label, 14) + 10
type Seed = { col: number; state: Cell['state'] | 'ended'; label: string; picked: boolean; press: Press }
// a line's seeds (#837 b8): a state mark an entry, its native press (the seed) right of the mark at pane column `col`; the kit draws them only through their cell kind
const seedKind = (seeds: Seed[]): CellKind => ({
  end: () => { const l = seeds[seeds.length - 1]; return l ? l.col * PX_PER_COL + seedW(l.label) + 5 : 0 },
  start: () => (seeds[0]?.col ?? 0) * PX_PER_COL - 17,
  draw: (ctx, cy, parts, hot) => {
      // A still mark is drawn once a picture and reused (an Octicon is ~330 chars, the tree budget: three done
      // entries of a line = one path and two <use>); `at` = the x its first drawing stands at.
      const at = (seen.get(ctx) ?? seen.set(ctx, {}).get(ctx))!
      for (const sd of seeds) {
        const bx = sd.col * PX_PER_COL
        const [ic, paint] = SEED_MARK[sd.state]
        const mx = n1r(bx - 7)
        if (sd.picked) parts.push(`<rect x="${n1(bx - 17)}" y="${cy - 9}" width="${n1(seedW(sd.label) + 22)}" height="18" rx="9" fill="${K.accent}" fill-opacity=".22" stroke="${K.accent}"/>`)
        if (sd.state === 'running') parts.push(ctx.icon(ic, mx, cy, 13, paint, 'class="sp"'))
        else if (at[ic] != null) parts.push(`<use href="#m${ic[0]}" x="${n1(mx - at[ic]!)}"/>`)
        else { at[ic] = mx; parts.push(ctx.icon(ic, mx, cy, 13, paint, '', `m${ic[0]}`)) }
        hot.push({ x: bx, w: seedW(sd.label), label: sd.label, press: sd.press, drawn: { x: bx - 17, w: seedW(sd.label) + 22 } })
        // #837 b8: the seed's number is drawn here (a ghost Markdown link over the capsule carries no text of its own); the dim ones as the host drew a dim Button
        parts.push(`<text x="${n1(bx + 3)}" y="${cy + 4.4}" class="tx"${sd.press.dim ? ` style="fill:${K.muted}"` : ''}>${besc(sd.label)}</text>`)
      }
  },
})

// #972: the two design caps of the runs card. They only narrow what the budget allows (hooks/budget.ts `layout`, a lane's `max`): a page never holds more, and holds fewer when the tab is full.
const HIST_PAGE = 6 // History rows a page at most (#683 r3)
const TROW_PX = 19 // #994: one line of the pane in px (a blank picture's height for a gap)
const GRID_PAGER_GAP = 24 // markup px between the grid's counts text and its pager's counter (the picture is fitted to at most 1:1, so this is 12 screen px at a fit of 0.5)
const GRID_PAGE = 8 // #837 b12: builds a page of a run's grid at most (a weekly run keeps adding builds)
// #983: what an open reading says of its build is cut by construction: the brain's hint to NOTE_MAX characters, the check's remarks to SAID_MAX rows of SAID_LINE_MAX characters and one row that counts the rest
const NOTE_MAX = 600, SAID_MAX = 8, SAID_LINE_MAX = 300
// a line = the builds of one (reference, variant): a reference's plain build first, then its variants
export const buildLines = (cells: Cell[]): Cell[][] => {
  const refs: string[] = []
  for (const c of cells) if (!refs.includes(c.ref)) refs.push(c.ref)
  const lines: Cell[][] = []
  for (const ref of refs) {
    const own = cells.filter(c => c.ref === ref)
    const vars: string[] = []
    for (const c of own) if (c.variant && !vars.includes(c.variant)) vars.push(c.variant)
    for (const v of [undefined, ...vars]) {
      const line = own.filter(c => (c.variant || undefined) === v)
      if (line.length) lines.push(line)
    }
  }
  return lines
}
const loadingRuns = new Set<string>() // job ids whose squares `collect.py cells` is reading now
const lateLoads = new Set<string>() // squares whose build was loaded when their folder came after the press

export const signature = (v: Fast) => [
  v.status, v.runs_error,
  v.runs?.running.map(j => [j.id, j.locks, j.progress?.done, j.progress?.total, j.progress?.cells.map(c => c.state[0]).join('')]),
  v.runs?.queued.map(j => j.id), v.runs?.history?.length ?? v.runs?.recent.length, v.runs?.slots.length, v.runs?.waiting,
  v.runs?.daemon && [v.runs.daemon.slots_total, v.runs.daemon.reserved, v.runs.daemon.reserved_until, v.runs.daemon.age_s > 120],
  v.laptop && [v.laptop.error, v.laptop.offline?.lost, v.laptop.runs?.running.map(j => [j.id, j.progress?.done]),
    v.laptop.runs?.queued.length, v.laptop.runs?.slots.length, v.laptop.runs?.daemon?.slots_total, v.laptop.runs?.daemon?.reserved],
  v.readings?.rows.length, v.readings?.error,
]

/** Loads the ascendancy faces the next draw needs (the render calls it before drawing; `X` = what the pane reads and the file reader). */
export const prepare = async (X: Record<string, any>) => {
  const $ = { fs: { read: X.readBytes }, plugin: { root: X.root } }
  const { f, runPick, bp, bpRd } = X
  {
    // #683 r4c: the ascendancy faces this draw needs (16 px on a running build's row, 64 px on an open build panel),
    // read once each from the mod's assets/asc as data URIs; a face that is not there is '' (the row draws a dot).
    // The open build's class reads "Marauder / Chieftain": its head takes the ascendancy's face, else its base
    // class's (an ascendancy with no asset of its own), so both are asked for.
    const panelFaces = [bp, bpRd].flatMap(b => (b?.data?.class ? [...new Set(String(b.data.class).split(' / ').reverse())].filter(Boolean).map(n => `${n}_64`) : []))
    const wantFaces = [
      // (B): a run's squares draw a face a line, whatever its builds' states: the running runs' cells and the picked run's
      ...[...(f?.runs?.running ?? []).flatMap(j => j.progress?.cells ?? []), ...(runPick?.progress?.cells ?? [])].filter(c => c.asc || c.class).map(c => `${c.asc ?? c.class}_16`),
      // the Builds tab: a reading's row draws its build's face too
      ...(f?.readings?.rows ?? []).filter(r => r.asc || r.class).map(r => `${r.asc ?? r.class}_16`),
      ...panelFaces,
    ]
    for (const k of wantFaces) {
      if (faces.has(k)) continue
      const cut = k.lastIndexOf('_')
      const [n, px] = [k.slice(0, cut), k.slice(cut + 1)]
      try {
        faces.set(k, `data:image/png;base64,${(await $.fs.read(`${$.plugin.root}/assets/asc/${n.toLowerCase()}_${px}x${px}.png`, { as: 'bytes' })).base64}`)
      } catch {
        faces.set(k, '')
      }
    }
  }
}

type TRow = { cells: any[]; odd?: boolean }

/** The render-time part: gets the pane's drawing context, returns this add-on's cards (the body keeps its render-scope indentation: a block). */
export const make = (X: Record<string, any>) => {
  // The engine's `$` never crosses a file: the pane hands in what the moved code asks of it, and `$`, `update`, `logError` are rebuilt here with the same call shapes (an atom arrives as `{ set }`: the loader wants every update of an atom spelled in the file that declares it).
  const $ = { process: { run: X.run }, clock: { after: X.after }, ui: { copy: X.copy } }
  const update = (_$: unknown, a: { set: (fn: (v: any) => any) => Promise<any> }, fn: (v: any) => any): Promise<any> => a.set(fn)
  const read = (_$: unknown, a: { get: () => Promise<any> }): Promise<any> => a.get()
  const logError = (_$: unknown, kind: 'pull' | 'render', err: unknown): Promise<void> => X.logError(kind, err)
  const { fastAtom, runPickAtom, runSelAtom, histPageAtom, gridPageAtom, gridPage, Box, Text, Button, Svg, f, t, W, sc, Ctl, Muted, rowEl, rowsOne, tableEl, detailHead, tick, queueRows, refreshFast, Cell, Head, Row, bp, runSel, runPick, histPage, selected, press, tableOf, hm, hmDay, fresh, panelAtom, selectedAtom, selectedRd, bpRd, readPanelAtom, readSelAtom, Tile, Title, ColTable, tv, pctCell, titleOf, Card, hostCard, cpuHist, labelPager, cardPager, pg, PAGER_PAD, counterOf, pageFill, COLS, sizeOf, COST, pagesNow, clipLine, unpage, listPage } = X
  const TW = W - 4
    // The versus columns of every table: what | наш | наш / автор (bar + %) | автор; with no author: what | наш.
    const versusCols = (what: string, author: boolean): TCol[] => author
      // #1018 B: the author's head says the numbers are the prepared author's (the pane's; the button opens the raw one): «автор (адапт.)», 83 px at 12 px,
      // from TW - 95 to TW - 12, 27 px clear of «наш / автор» (TW - 190 to TW - 122); at 13 px 14 px clear. `автор адапт.` is the fallback if it ever does not fit.
      ? [{ label: what, x: P0 }, { label: 'наш', x: TW - 206, end: true }, { label: 'наш / автор', x: TW - 190, kind: 'ratio' }, { label: 'автор (адапт.)', x: TW - 12, end: true }]
      : [{ label: what, x: P0 }, { label: 'наш', x: TW - 12, end: true }]
  const bpPob = bp // #994: the POB tab's open build (the Builds tab's is bpRd)
  // #972: every list of this add-on that grows with the data asks the pane's `lane` what to draw of it (hooks/budget.ts)
  const lane: (key: string, units: Unit[], opt?: { extra?: number; max?: number; at?: number }) => LanePlan = X.lane
  {
    // #995 (the owner, 14.10: «Резервы убираем нахуй, бесполезные»): the reservation row (two selects and «Зарезервировать») is gone from the PC and Laptop cards;
    // the daemon's reserved slots still show as the owner's squares (the data path is not the cards').
    // The slot squares of a host: busy from the left (queue first, then agents), free after; the owner's reserved
    // slots (#622, the daemon's `reserved`) last, in the owner's colour. `avail` is the daemon's effective total
    // (its `slots_total`, the mode total minus the reservation). The caption: in use / avail · до HH:MM.
    const slotMarks = (r: Runs | undefined, shape?: { slots_total?: number }): [SlotMark[], string] => {
      if (!r) return [Array.from({ length: shape?.slots_total ?? 0 }, () => 'free' as const), '—']
      const d = r.daemon
      const has = d != null && d.slots_total != null
      const reserved = has ? d!.reserved ?? 0 : 0
      const avail = has ? d!.slots_total! : r.total
      // The slot locks held now are the truth: the daemon's `slots_in_use` counts a job's submitted workers, not the
      // locks of a lone job it widened (#570; owner 10.10 01:5x: «5 слотов» on the run, 1 square lit here).
      const inUse = Math.max(has && d!.slots_in_use != null ? d!.slots_in_use : 0, r.slots.length)
      const busy = [...r.slots].sort((a, b) => (a.role === 'queue' ? 0 : 1) - (b.role === 'queue' ? 0 : 1))
      const n = avail + reserved
      // a queue lock = a PoB run; any other lock (an agent's PobSession, role other / agents) = agents
      const marks = Array.from({ length: n }, (_, i): SlotMark => (i >= n - reserved ? 'you' : i < inUse ? (busy[i] && busy[i].role !== 'queue' ? 'agents' : 'run') : 'free'))
      return [marks, `${inUse} / ${avail}` + (r.queue_until ? ` · до ${r.queue_until}` : '')] // #995: no «резерв» word on the cards
    }

    const laptopCard = () => {
      const m = f?.laptop?.machine
      const r = f?.laptop?.runs
      const err = f?.laptop?.error
      const o = f?.laptop?.offline
      const name = 'Laptop'
      const iconName = 'laptop'
      const state = m ? { t: 'на связи', cls: 'ok' } : o ? { t: 'offline', cls: 'er' } : undefined
      const cores = m?.cores ?? o?.cores
      const sub = [cores != null ? `${cores} ядер` : '', m ? `${Math.round(m.ram_total)} GB` : ''].filter(Boolean).join(', ')
      const [marks, cap] = slotMarks(m ? r : undefined, o)
      const since = o ? o.lost ?? o.seen : undefined
      const ago = o ? (o.lost ? o.lost_ago : o.seen_ago) : undefined
      // #983: the runs an offline laptop was computing are a list that grows: as many lines as the budget gives (a row with child rows), the others ONE line that counts them
      const was = !m && o ? o.running ?? [] : []
      const wasPlan = lane('lapw', was.length ? [{ own: 0, kids: was.map(() => COST.note), more: COST.note }] : [])
      const wasN = wasPlan.shown[0]?.kids ?? 0
      const below = [
        !m && o && <Text color={K.nfailed}>{since ? `нет связи с ${since}${ago ? ` · ${ago}` : ''}` : 'нет связи'}</Text>,
        was.slice(0, wasN).map(j => (
          <Muted>{clipLine(`шло: ${j.tag}${j.workers ? ` · ${slots(j.workers)}` : ''}${j.total != null ? ` · ${j.done}/${j.total}` : ''}`, 120)}</Muted>
        )),
        wasPlan.shown.length > 0 && was.length > wasN && <Muted>{`шло: ещё ${was.length - wasN}`}</Muted>,
        m && r && r.waiting > 0 && <Text color={K.owner}>{r.waiting} waiting for a slot</Text>,
      ]
      return hostCard({
        id: 'laptop', name, iconName, sub, m, loaded: !!(m || o), err, state, marks, cap, hist: cpuHist['laptop'], slotsNote: !!r, below,
        headState: err ? { t: 'offline', cls: 'er' } : undefined,
      })
    }
    // The PC card's slot squares and waiting line: the runs of this project, drawn into the generic PC card.
    const pcSlots = (m: Machine | undefined) => {
      const r = f?.runs
      const [marks, cap] = slotMarks(m ? r : undefined)
      const below = [
        m && r && r.waiting > 0 && <Text color={K.owner}>{r.waiting} waiting for a slot</Text>,
      ]
      return { marks, cap, below, slotsNote: !!r }
    }
    const runsCard = () => <Card k="runs" iconName="cpu.octicons" name="PoB runs" sub={`очередь: ${f?.runs?.running.length ?? 0} идёт, ${f?.runs?.queued.length ?? 0} ждёт` + queueEnd(f?.runs?.queue_end_h, f?.runs?.queue_until, f?.runs?.queue_end_partial)}>{runsBlock()}</Card>

    const runsBlock = () => {
      // no payload yet (or an error): the card's table is drawn all the same, its sections empty (a card is a title and a table, never a note line)
      const r: Runs = f?.runs ?? ({ running: [], queued: [], recent: [], history: [] } as unknown as Runs)
      const cellId = (j: Job, c: Cell) => `${j.id}|${c.ref}|${c.seed}${c.variant ? '|' + c.variant : ''}`

      // A press selects (or, pressed again, closes) a cell; a finished one also gets its build decoded.
      const pick = async (j: Job, c: Cell) => {
        const opening = await toggleSel(cellId(j, c))
        const dir = j.progress?.dir
        if (opening && dir && (c.state === 'done' || c.state === 'failed')) await loadBuild(cellId(j, c), dir, c.ref, c.seed, c.variant ?? '')
      }
      const buildPanel = (j: Job, c: Cell, facts?: string[], title?: string) => {
        const dir = j.progress?.dir
        if (!dir) return null // a replay run still running (its folder comes at its end) or a run whose folder is gone
        // A square opened before its folder came (a replay ending): load it now, once (owner 10.10 02:4x: «читаю
        // build…» forever, the load ran only on the press, when there was no folder yet).
        const key = cellId(j, c)
        if (bp?.key !== key && !lateLoads.has(key)) { lateLoads.add(key); void loadBuild(key, dir, c.ref, c.seed, c.variant ?? '') }
        return buildPanelAt(cellId(j, c), (surface, who) => { if (dir) void openPobAt(cellId(j, c), dir, c.ref, c.seed, c.variant ?? '', surface, who) }, facts, title)
      }

      // #587: Running, Queued and History are rows of one queue; a press on a run's title picks it and its squares are
      // drawn under the queue (none picked = the first running run). A run that is not running gets its squares from
      // `collect.py cells <id>`, once per pick.
      const history = r.history ?? r.recent
      const shownId = runSel ?? r.running[0]?.id ?? null
      const live = r.running.find(j => j.id === shownId)
      const other = live ? undefined : [...r.queued, ...history].find(j => j.id === shownId)
      const loadRun = async (id: string) => {
        if (loadingRuns.has(id)) return
        loadingRuns.add(id)
        await update($, runPickAtom, () => ({ id, loading: true }))
        let next: RunPick
        try {
          const ran = await $.process.run(['python', SCRIPT, 'cells', id], { cwd: REPO, timeoutMs: 30_000 })
          const v = JSON.parse(ran.stdout)
          next = v.error ? { id, error: String(v.error) } : v.progress ? { id, progress: v.progress as Progress } : { id, gone: !!v.gone }
        } catch (err) {
          void logError($, 'render', err)
          next = { id, error: String(err).slice(0, 160) }
        } finally {
          loadingRuns.delete(id)
        }
        await update($, runPickAtom, p => (p?.id === id ? next : p))
      }
      // A picked run that left Running since (or a pane drawn anew) loads its squares by itself.
      if (other && other.state !== 'queued' && runPick?.id !== other.id && !loadingRuns.has(other.id)) {
        const id = other.id
        $.clock.after(0, () => void loadRun(id))
      }
      // #837 b9a: decided at PRESS time. The host may call the handler of an OLDER render, so nothing here is read from this render's `shownId`: the selection is the
      // atom's value inside the update, the designed fallback (no selection = the first running run) and the run's state are read from the live answer when the press lands.
      let histShown = 0 // the page «Готово» draws in this render
      const pickRun = async (j: Job) => {
        const now = (await fastAtom.get())?.runs
        const first: string | null = (now ?? r).running[0]?.id ?? null
        const jn: Job = [...(now ?? r).running, ...(now ?? r).queued, ...((now ?? r).history ?? (now ?? r).recent ?? [])].find((x: Job) => x.id === j.id) ?? j
        let again = false
        await update($, runSelAtom, (cur: string | null) => { again = j.id === (cur ?? first); return again ? null : j.id })
        // #994 (defect 2): «Готово» follows the picked run (-1: the page that holds it, also after newer runs push it to the next page) until the pager is stepped; unpicked, it stays on the page shown
        // (set only when it changes: an atom set is a redraw, and a press that lands during a redraw may be lost; #994 row 5)
        if (histPage !== (again ? histShown : -1)) await update($, histPageAtom, () => (again ? histShown : -1))
        if (!again && jn.state !== 'running' && jn.state !== 'queued') await loadRun(j.id)
      }
      const runTitle = (j: Job) => titleOf(j.issue) ?? j.tag

      // A running run: its strip (title = the press that picks its squares, ticket, priority / host / slots it holds,
      // the finish time, run time), its track (builds done / total), then ONE ROW PER BUILD BEING COMPUTED: the
      // ascendancy's pixel face in the rail, the name in its base class's colour, the pipeline as a bar of its three
      // groups (#711: each as wide as its measured share of build time, filled in the class colour, the one the build
      // is in pulses), then the group and the step its log last STARTED, in the log's own words (in the loop: the
      // pass and the move); a log with no start line yet reads «запускается», never a guessed step. Minutes on it.
      const nowS = Date.now() / 1000
      // #995 row 3 (the owner, 14.10: «У каждого билда шкала с этапами реальная или там от балды колво пунктов»): the old bar (the three groups' measured shares, the
      // loop filled by a time guess) marked no real stage and is gone. What stands in the «билды» column of a build is its REAL stage: the place of the step its log last
      // started among the catalog's steps (addon.py build_stage `stage_index` / `stage_count`, #985 c: only from a `step start:` line), as the text «этап N / M»
      const stageCell = (c: Cell): CellV => {
        const x = c as Cell & { stage_index?: number; stage_count?: number }
        return c.started && x.stage_index && x.stage_count ? { t: `этап ${x.stage_index} / ${x.stage_count}`, cls: 'mu' } : ''
      }
      const buildRow = (c: Cell): RowSpec => {
        const col = (c.class && CLASS[c.class]) || K.text
        const said = c.stage ?? (c.after ? `после шага ${c.after}` : 'запускается')
        const ascN = c.asc ?? c.class ?? ''
        const img = faces.get(`${ascN}_16`)
        // #683 r5: a replay build logs no stages. #995: its old bar (12 segments of time against the run's median build time) marked no stage: gone
        if (!c.started && c.started_est) {
          const el = Math.max(0, nowS - c.started_est)
          return {
            kind: 'strip', color: col, child: true, alt: `${c.name}: считается`,
            rail: img ? { img } : { dot: true, color: col },
            cells: {
              name: { t: c.name, cls: 'nm', color: col }, tick: '',
              meta: ascN, num: '',
              act: { t: c.expect_s ? `считается, обычно ~${dur(c.expect_s)}` : 'считается', cls: 'tx', icon: 'running', spin: true, iconColor: col },
              time: `~${dur(el)}`,
            },
          }
        }
        return {
          kind: 'strip', color: col, child: true, alt: `${c.name}: ${c.started ? said : ''}`,
          rail: img ? { img } : { dot: true, color: col },
          cells: {
            // a replay build (collect.py replay_cells) has no log of steps and no start: neither is drawn
            name: { t: c.name, cls: 'nm', color: col }, tick: '',
            meta: ascN, num: stageCell(c),
            // #1004 u1: the act is the build's status word (addon.py `status`, the data's own Russian words); the raw stage stays in the alt above; a cell with no status keeps `said`
            act: c.started ? { t: c.status || said, cls: c.stage ? 'tx' : 'mu', icon: 'running', spin: true, iconColor: col } : '',
            time: c.started ? dur(nowS - c.started) : c.took ? `с ${c.took}` : '',
          },
        }
      }
      // #837 pass 2 (owner 11.10, point 4): a build's stage segments stand in the «билды» column (where the job row has its build
      // squares), directly left of that build's status.
      // #683 r5: the laptop out of reach: its rows stay as last read, faded, and say since when the data is
      const staleTxt = (j: Job) => `нет связи с ноутом, данные от ${j.stale_since ?? '?'}`
      // #683 r5 (owner 10.10 02:3x): a row says what its run executes (collect.py run_kind), the scripts' own words:
      // a benchmark builds from scratch and logs its steps, a replay repeats one move on finished builds (no step log)
      const KIND_WORD: Record<string, string> = { benchmark: 'benchmark', replay: 'replay', tests: 'тесты', request: 'билд по запросу' }
      const kinded = (j: Job, t: string) => [KIND_WORD[j.what ?? ''], t].filter(Boolean).join(' · ')
      const faceLen = (c: Cell) => (faces.get(`${c.asc ?? c.class ?? ''}_16`) ?? '').length // a build's row pays its face on top of the row (the picture holds a face once: charged every time, the dear side)
      const runAll: (QRun & { kidCosts: number[] })[] = r.running.map(j => {
        const p = j.progress
        const held = j.locks != null ? j.locks : j.workers
        const live = (p?.cells ?? []).filter(c => c.state === 'running')
        return {
          icon: 'cpu.octicons', sel: j.id === shownId, alt: `${j.tag} ${j.stale ? 'stale' : 'running'}${p?.total ? `: ${buildsRu(p.done, p.total, p.total_open)}` : ''}, ${[j.priority, j.host, slotsRu(held)].filter(Boolean).join(', ')}`, stale: !!j.stale,
          cells: {
            name: { t: runTitle(j), cls: 'nm', press: { key: `run-pick-${j.id}`, on: () => void pickRun(j), dim: j.id !== shownId } },
            tick: tick(j.issue), meta: metaPics(j, held, [j.priority, j.host, slotsRu(held)].filter(Boolean).join(', ')),
            num: p?.total ? buildsCount(p.done, p.total, j.stale ? 'mu' : 'tx', p.total_open) : '',
            // #699: the time still to go, from what is measured; none -> said, never guessed
            act: j.stale ? { t: staleTxt(j), cls: 'tx' } : j.left_h ? { t: kinded(j, `ещё ~${ru(j.left_h)}`), cls: 'tx', icon: 'hourglass.octicons' } : { t: kinded(j, 'оценки нет'), cls: 'mu' },
            time: j.stale ? '' : ru(j.dur ?? j.age),
          },
          kids: live.map(buildRow), kidCosts: live.map(c => RUN_COST.runBuild + faceLen(c)),
        }
      })
      // #972: the running runs through the budget: a page of them (the pager on the «Идёт» row); of a run's builds as many as fit, the others ONE calm row that counts them
      const runPlan = lane('runr', runAll.map((x): Unit => ({ own: RUN_COST.run, kids: x.kidCosts, more: RUN_COST.runMore })), { extra: RUN_COST.runExtra })
      const running: QRun[] = runPlan.shown.map(sh => {
        const { kidCosts: _c, ...x } = runAll[sh.i]!
        const all = x.kids ?? [], cutN = all.length - sh.kids
        return { ...x, kids: cutN > 0 ? [...all.slice(0, sh.kids), { kind: 'strip', state: 'idle', calm: true, child: true, alt: `${cutN} more builds running`, rail: { dot: true, color: K.idle },
          cells: { name: { t: `ещё ${cutN} ${ruForm(cutN, 'считается', 'считаются', 'считается')}`, cls: 'mu' } } } as RowSpec] : all }
      })
      // #706: a queued row says what the daemon really waits for (`wait.kind`: another run, RAM, slots, a reservation,
      // the host's mode) and, when the slot simulation knows it (#699), how long: «ждёт #814 · ~1 ч 56 мин», «ждёт слот».
      // #837 pass 2 (owner 11.10, point 6): nothing else is drawn in the row: no «привязан к ...», no «на Laptop свободно N»,
      // no «слоты: свободно ...», no «оценки нет», no «займёт ~...».
      const waitTxt = (j: Job) => {
        const w = j.wait
        const left = !w || w.kind === 'slots' || w.kind === 'after' ? ((j.start_s ?? 0) >= 60 && j.start_h ? ` · ~${ru(j.start_h)}` : '') : ''
        // #793 F08: a run tag in the daemon's words (`P1-#795-2`) is a run id: the ticket stands there, as everywhere
        // #1106: a job that waits for an `--after` predecessor still running or queued names it by tag, verbatim (no rewrite)
        const what = j.waits_for && !j.held_by ? `ждёт ${j.waits_for.tag}` : !w || w.kind === 'slots' ? 'ждёт слот' : w.kind === 'ram' ? 'ждёт RAM' : w.text.replace(/\bP\d-#(\d+)(?:-\d+)?/g, '#$1')
        return what + left
      }
      // #863: a job whose `--after` predecessor failed never starts: the row says so, in the failure colour, no estimate
      const heldTxt = (j: Job) => j.held_by ? `держит упавший ${String(j.held_by.tag).replace(/\bP\d-#(\d+)(?:-\d+)?/g, '#$1')}` : ''
      const waitAll = r.queued.map(j => ({ sel: j.id === shownId, alt: `${j.tag} queued, ${[j.priority, j.host, slotsRu(j.workers)].filter(Boolean).join(', ')}`, stale: !!j.stale, cells: {
        name: { t: runTitle(j), cls: 'tx', press: { key: `run-q-${j.id}`, on: () => void pickRun(j), dim: j.id !== shownId } },
        tick: tick(j.issue), meta: metaPics(j, j.workers, [j.priority, j.host, slotsRu(j.workers)].filter(Boolean).join(', ')),
        act: j.stale ? { t: staleTxt(j), cls: 'tx' } : { t: heldTxt(j) || waitTxt(j),
          cls: j.held_by ? 'er' : 'wt', icon: 'waiting.octicons' }, time: j.stale ? '' : `ждёт ${ru(j.dur ?? j.age)}` } as Record<string, CellV> }))
      // #972: the queued runs through the budget: a page of them, the pager on the «В очереди» row
      const waitPlan = lane('runq', waitAll.map(() => RUN_COST.queued), { extra: RUN_COST.queuedExtra })
      const waiting = waitPlan.shown.map(s => waitAll[s.i]!)

      // #995 send-back 1 (defect 5: the date-time of a finished run stood in the «приоритет, слоты» column with no head of its own): the runs card's grid is the pane's
      // with one column more, «начало» (a finished run's date and start), right-aligned just before «длительность»; the status column ends before it. A running or
      // queued row has nothing there, so its status runs on to the time as before (kit rowBody: a text runs on to the next drawn cell). The meta column holds the pictures only.
      const timeX = COLS.find((c: RowCol) => c.key === 'time')!.x
      const WHEN_W = 80
      const RUN_COLS: RowCol[] = [...COLS.map((c: RowCol) => (c.key === 'act' ? { ...c, w: Math.max(40, timeX - 16 - WHEN_W - c.x) } : c)),
        { key: 'when', x: timeX - 16 - WHEN_W, w: WHEN_W, align: 'end', num: true }].sort((a, b) => a.x - b.x)
      // History (Готово), HIST_PAGE rows a page: the picked one highlighted; pager «новее» / «старее» on its label line.
      const RUN_WORD: Record<string, string> = { done: 'готово', failed: 'упал', stopped: 'остановлен', cancelled: 'отменён' }
      // #972: the finished runs through the budget: HIST_PAGE a page at most
      const pinAt = histPage < 0 && runSel != null ? history.findIndex((j: Job) => j.id === runSel) : -1
      const histPlan = lane('hist', history.map(() => RUN_COST.done), { extra: RUN_COST.doneExtra, max: HIST_PAGE, at: Math.max(0, histPage), pin: pinAt >= 0 ? pinAt : undefined })
      histShown = histPlan.page
      const pages = histPlan.pages.length
      // #837 b9a: a step from the atom's value at PRESS time (the host may call the handler of an older render)
      const setPage = (d: number) => async () => {
        await update($, histPageAtom, (x: number) => { const m = pagesNow('hist', pages); return Math.max(0, Math.min(m - 1, (x < 0 ? histShown : Math.min(x, m - 1)) + d)) })
      }
      // #837 b17: the pager word is a host Button with its visible label on the label row (the picture draws none; as the old build's `Hot` entries); a word at the end of the range is dim and takes no press
      const histPager = labelPager('hist', histPlan, setPage)
      const doneRows: QDone[] = histPlan.shown.map(s => history[s.i]!).map(j => {
        const sel = runSel != null && j.id === runSel
        return { state: j.state === 'done' ? 'done' : j.state === 'failed' ? 'failed' : 'idle', sel, alt: `${j.tag} ${j.state}, ${[j.priority, j.host, j.rows_total ? buildsRu(j.rows_done ?? 0, j.rows_total) : ''].filter(Boolean).join(', ')}`, cells: {
          name: { t: runTitle(j), cls: sel ? 'tx' : 'mu', press: { key: `run-hist-${j.id}`, on: () => void pickRun(j), dim: !sel } },
          tick: tick(j.issue), meta: metaPics(j, j.workers, [j.priority, j.host, [j.date, j.start].filter(Boolean).join(' ')].filter(Boolean).join(', ')),
          when: { t: [j.date, j.start].filter(Boolean).join(' '), cls: sel ? 'tx' : 'mu' },
          num: j.rows_total ? buildsCount(j.rows_done ?? 0, j.rows_total, sel ? 'tx' : 'mu') : '',
          // #683 r5 pt 2: a run with builds says so in its row (owner: finding the run that HAS squares meant pressing every row)
          // #995 send-back 1 (defect 5: #980's row said only «готово»): a finished run always names its kind; a command run_kind does not know
          // takes the collector's own plain name of it (addon.py kind_name: «прочий прогон»)
          act: { t: [KIND_WORD[j.what ?? ''] ?? j.kind_name, RUN_WORD[j.state] ?? j.state].filter(Boolean).join(' · '),
            cls: j.state === 'failed' ? 'er' : j.rows_total ? 'tx' : 'mu' }, time: ru(j.dur) } }
      })
      const rows = queueRows({ heads: { name: 'задача', tick: 'тикет', meta: 'приоритет, слоты', num: 'билды', act: 'статус', when: 'начало', time: 'длительность' }, running, waiting,
        runLabel: labelPager('runr', runPlan), waitLabel: labelPager('runq', waitPlan), waitFrom: Math.max(0, waitPlan.from - 1), waitFill: pageFill(waitPlan), done: {
          rows: doneRows, pager: histPager.hot ?? [], fill: pageFill(histPlan),
          right: history.length ? (histPlan.paged ? counterOf(histPlan) : String(history.length)) : '',
        } })

      // The picked run's squares: a live run from the fast pull, another from its loaded pick. One native press per
      // (reference, seed, variant), GitHub colours; a press shows that build under them.
      const shown: Job | undefined = live ?? (other && runPick?.id === other.id && runPick.progress
        ? { ...other, progress: runPick.progress } : other)
      const squares = () => {
        if (!shown) return null
        const p = shown.progress
        let why: string | null = null
        if (!p) {
          if (shown.state === 'queued') why = 'ещё не начался: квадратов пока нет'
          else if (runPick?.id === shown.id && runPick.loading) why = 'читаю квадраты…'
          else if (runPick?.id === shown.id && runPick.error) why = runPick.error
          else if (shown.gone || (runPick?.id === shown.id && runPick.gone)) why = 'папка рана удалена: квадратов нет'
          else if (shown.state === 'running' || runPick?.id === shown.id) why = shown.what === 'tests' ? 'это прогон тестов (pytest): билдов в нём нет' : 'у этого рана нет билдов (не benchmark, не replay и не билд по запросу)'
          else why = 'читаю квадраты…'
        }
        const cells = p?.cells ?? []
        const refs: string[] = []
        for (const c of cells) if (!refs.includes(c.ref)) refs.push(c.ref)
        const order = refs.flatMap(ref => cells.filter(c => c.ref === ref))
        const sel = cells.find(c => cellId(shown, c) === selected)
        // #683 r5 (B) (owner 10.10: «Квадраты получились уебищными, как это сочетается со стилем?»), desktop: the block
        // is rows of the pane like every other: a label row (the run's ticket as a native Link, the counts by state in
        // words), then ONE STRIP PER NAMED BUILD (a reference, and each of its variants) on the block's own grid: the
        // face in the rail, the name in its base class's colour, the ascendancy, a state mark and a native press (the
        // seed) per build, what the line's build came to, its time. The picked build's detail under the strips: the
        // one head (it repeats nothing its strip says) and the one table.
        if (Svg) {
          // #837 b9a A3: a run that is not live (stopped / cancelled / failed / done) computes nothing: a seed it never finished is 'ended' and says the run's own end word (the «Готово» row's RUN_WORD)
          const ended = shown.state !== 'running' && shown.state !== 'queued'
          type St = Cell['state'] | 'ended'
          const stOf = (c: Cell): St => (ended && (c.state === 'running' || c.state === 'waiting' || c.state === 'queued') ? 'ended' : c.state)
          const END: [string, string, string] = shown.state === 'stopped' ? ['остановлен', 'остановлены', 'остановлено'] : shown.state === 'cancelled' ? ['отменён', 'отменены', 'отменено']
            : shown.state === 'failed' ? ['упал', 'упали', 'упало'] : ['не досчитан', 'не досчитаны', 'не досчитано']
          const STATE_RU: Record<St, string> = { done: 'готово', failed: 'упал', running: 'считается', waiting: 'ждёт', queued: 'ждёт', ended: END[0] }
          const countsOf = (cs: Cell[]) => {
            const count = (...st: St[]) => cs.filter(c => st.includes(stOf(c))).length
            const nDone = count('done'), nRun = count('running'), nWait = count('waiting', 'queued'), nEnd = count('ended')
            const nFail = count('failed') + (shown.state === 'failed' ? nEnd : 0) // a failed run's end word is «упал» already
            return [
              nDone ? `${nDone} готово` : '', nRun ? `${nRun} ${ruForm(nRun, 'считается', 'считаются', 'считается')}` : '',
              nWait ? `${nWait} ${ruForm(nWait, 'ждёт', 'ждут', 'ждут')}` : '', nFail ? `${nFail} ${ruForm(nFail, 'упал', 'упали', 'упало')}` : '',
              nEnd && shown.state !== 'failed' ? `${nEnd} ${ruForm(nEnd, ...END)}` : '',
            ]
          }
          const counts = [...countsOf(cells), p?.total_open ? 'варианты ещё добавляются' : ''].filter(Boolean).join(' · ')
          const runName = shown.issue ? `#${shown.issue}` : shown.tag
          const sqGrid0: RowCol[] = [
            { key: 'name', x: 38, w: Math.round(196 * sc) },
            { key: 'meta', x: Math.round(244 * sc), w: Math.round(98 * sc) },
            { key: 'tick', x: Math.round(352 * sc), w: Math.round(220 * sc) },
            { key: 'act', x: Math.round(584 * sc), w: Math.max(40, W - Math.round(584 * sc) - 96) },
            { key: 'time', x: W - 96, w: 84, align: 'end', num: true },
          ]
          const wide = new Set<RowSpec>()
          const lines = buildLines(cells)
          // ours against the author's on a build's first metric, in percent
          const ratioOf = (c: Cell) => { const m = c.metrics?.[0]; return m && m[1] != null && m[2] ? Math.round((m[1] / m[2]) * 100) : null }
          const ratioCls = (pc: number) => (pc >= 100 ? 'ok' : pc >= 80 ? 'tx' : 'er')
          // a running build's `took` is the clock time it started at (collect.py), so its time is counted from its start
          const timeOf = (c: Cell) => c.state === 'done' || c.state === 'failed' ? ru(c.took) : stOf(c) !== 'running' ? ''
            : c.started ? `идёт ${dur(nowS - c.started)}` : c.started_est ? `идёт ~${dur(nowS - c.started_est)}` : c.took ? `идёт с ${c.took}` : ''
          const actOf = (line: Cell[], one: Cell | undefined): { t: string; cls: string } => {
            if (one) {
              // #837 pass 2 (owner 11.10, point 7): a build row's status is one word of the legend; the numbers (the ratio,
              // the metric, before -> after) are in the detail panel of the picked build
              const pc = ratioOf(one)
              return { t: STATE_RU[stOf(one)],
                cls: one.state === 'failed' ? 'er' : pc != null ? ratioCls(pc) : one.state === 'done' || stOf(one) === 'running' ? 'tx' : 'mu' }
            }
            const best = line.filter(c => c.state === 'done').map(ratioOf).filter((x): x is number => x != null).sort((a, b) => b - a)[0]
            return { t: countsOf(line).filter(Boolean).join(' · '),
              cls: best != null ? ratioCls(best) : line.some(c => c.state === 'done' || stOf(c) === 'running') ? 'tx' : 'mu' }
          }
          const told = lines.map(line => {
            const lead = line[0]!
            const picked = line.find(c => cellId(shown, c) === selected)
            const one = picked ?? (line.length === 1 ? lead : undefined)
            return { line, lead, picked, act: actOf(line, one), time: one ? timeOf(one) : '', meta: lead.asc ?? lead.class ?? '' }
          })
          // The grid from the lines' own words (the owner's rule, fitGrid): a long name pushes the later columns right,
          // the ascendancy (its face says it) leaves when they no longer fit; a strip with no time (several builds,
          // none picked) lets its words run to the pill's end, so it asks the act column for that much less.
          const seedStep = (label: string) => Math.ceil((12.5 + seedW(label) + 14) / PX_PER_COL)
          const needTime = Math.max(0, ...told.map(x => textWidth(x.time)))
          const sqGrid = fitGrid(sqGrid0, {
            name: Math.max(0, ...told.map(x => textWidth(x.lead.name, PX, true))),
            meta: Math.max(0, ...told.map(x => textWidth(x.meta))),
            // the seeds wrap inside their column, so it never asks for more than the design gave it
            tick: Math.min(sqGrid0[2]!.w, Math.max(0, ...told.map(x => (2 + x.line.reduce((s, c) => s + seedStep(String(c.seed)), 0)) * PX_PER_COL - 14))),
            act: Math.max(0, ...told.map(x => textWidth(x.act.t) - (x.time ? 0 : needTime + GRID_GAP))),
            time: needTime,
          }, ['meta'], W - 12).map(c => (c.key === 'act' ? { ...c, w: Math.max(40, W - 12 - (needTime ? needTime + GRID_GAP : 0) - c.x) } : c))
          const sqWide = sqGrid.map(c => (c.key === 'act' ? { ...c, w: W - c.x - 12 } : c))
          const tickX = sqGrid.find(c => c.key === 'tick')!.x
          const actC = sqGrid.find(c => c.key === 'act')!
          const col0 = Math.round(tickX / PX_PER_COL) + 2
          const edge = actC.x - 8 // a seed's press ends left of the act column
          // #837 b12: more than GRID_PAGE builds are shown a page at a time, the ones happening now first: a build with a seed being computed, then one with a finished seed (done / failed),
          // then the waiting ones, each group in the run's own order; a run of GRID_PAGE builds or fewer is drawn whole, in the run's order, with no pager
          const rank = (x: (typeof told)[number]) => (x.line.some(c => stOf(c) === 'running') ? 0 : x.line.some(c => c.state === 'done' || c.state === 'failed') ? 1 : 2)
          const order = told.length > GRID_PAGE ? told.map((x, n) => ({ x, n })).sort((a, b) => rank(a.x) - rank(b.x) || a.n - b.n).map(y => y.x) : told
          // #972: the builds through the budget: GRID_PAGE lines a page at most. A line pays its row, its face, a press a seed, and a strip more for every wrap of its seeds
          // #983: a line's seeds are its child rows: as many as the budget gives are drawn, the others ONE calm row «ещё N сидов» under the line (a line of a hundred seeds is cut, never the page's limit passed)
          const seedCosts = (line: Cell[]) => {
            let col = col0, k = 0
            return line.map(c => { const label = String(c.seed); let wrap = 0; if (k && col * PX_PER_COL + seedW(label) > edge) { wrap = RUN_COST.gridStrip; col = col0; k = 0 } k++; col += seedStep(label); return RUN_COST.seed + wrap })
          }
          const gridPlan = lane('grid', order.map((x): Unit => ({ own: RUN_COST.gridLine + faceLen(x.lead), kids: seedCosts(x.line), more: RUN_COST.gridMore })), { extra: RUN_COST.gridExtra, max: GRID_PAGE, at: gridPage?.run === shown.id ? gridPage.page : 0 })
          const paged = gridPlan.paged
          const gpages = gridPlan.pages.length
          const gpage = gridPlan.page
          const onPage = gridPlan.shown.map(s => ({ ...order[s.i]!, seedsShown: s.kids }))
          // the step is decided inside the atom update from the atom's value at PRESS time (the host may call an older render's handler)
          const shownRun = shown
          const stepGrid = (d: number) => async () => {
            await update($, gridPageAtom, (x: { run: string | null; page: number }) => { const m = pagesNow('grid', gpages); return { run: shownRun.id, page: Math.max(0, Math.min(m - 1, Math.min(x.run === shownRun.id ? x.page : 0, m - 1) + d)) } })
          }
          const strips: RowSpec[] = []
          for (const { line: lineAll, lead, picked, act: said0, time, meta, seedsShown } of onPage) {
            const line = lineAll.slice(0, seedsShown), cutSeeds = lineAll.length - line.length
            const color = (lead.class && CLASS[lead.class]) || K.text
            const img = faces.get(`${lead.asc ?? lead.class}_16`)
            // what the line came to, as many of its parts as fit whole (a part with no room goes, none is cut)
            const act = { ...said0, t: whole(said0.t, time ? actC.w : W - 12 - actC.x) }
            const base: RowSpec = { kind: 'strip', color, child: true, calm: !line.some(c => stOf(c) === 'running'), sel: !!picked }
            // seeds past the act column wrap to a strip of their own: no name, no rail mark, the line's tint
            const parts: Seed[][] = [[]]
            let col = col0
            for (const c of line) {
              const label = String(c.seed)
              if (parts[parts.length - 1]!.length && col * PX_PER_COL + seedW(label) > edge) { parts.push([]); col = col0 }
              parts[parts.length - 1]!.push({ col, state: stOf(c), label, picked: c === picked, press: {
                key: `cell-${shown.id}-${c.ref}-${c.seed}${c.variant ? '-' + c.variant : ''}`, on: () => void pick(shown, c), dim: sel != null && c !== sel } })
              col += seedStep(label)
            }
            const said = (cs: Cell[]) => cs.map(c => `seed ${c.seed} ${STATE_RU[stOf(c)]}`).join(', ')
            let at = 0
            parts.forEach((seeds, pi) => {
              const own = line.slice(at, at + seeds.length)
              at += seeds.length
              const strip: RowSpec = pi
                ? { ...base, alt: `Билд «${lead.name}», ещё: ${said(own)}`, cells: { tick: { kind: seedKind(seeds) } } }
                : { ...base, alt: [`Билд «${lead.name}»: ${said(own)}`, said0.t, time].filter(Boolean).join(' · '),
                  rail: img ? { img } : { dot: true, color },
                  cells: { name: { t: lead.name, cls: 'nm', color }, meta: { t: meta, cls: 'mu' }, tick: { kind: seedKind(seeds) }, act, time } }
              if (!time) wide.add(strip)
              strips.push(strip)
            })
            if (cutSeeds > 0) strips.push({ kind: 'strip', state: 'idle', calm: true, child: true, alt: `Билд «${lead.name}»: ещё ${cutSeeds} seed`, rail: { dot: true, color: K.idle },
              cells: { name: { t: `ещё ${cutSeeds} ${ruForm(cutSeeds, 'сид', 'сида', 'сидов')}`, cls: 'mu' } } })
          }
          if (!strips.length) strips.push(emptyRow())
          const detail = () => {
            if (!sel) return null
            const id = cellId(shown, sel)
            const dir = shown.progress?.dir
            const panel = sel.state === 'done' || sel.state === 'failed' ? buildPanel(shown, sel, undefined, sel.name) : null
            // #994 (defect 11): the gap above the open build is a blank picture of one 19-px line (the host drew `marginTop={1}` as half a line, the rows under it off their tree)
            return (
              <Box flexDirection="column">
                <Svg source={`<svg xmlns='http://www.w3.org/2000/svg' width='${W}' height='${TROW_PX}'/>`} alt="row" height={TROW_PX} />
                {panel ?? detailHead(sel.name, [
                  [sel.class, sel.asc].filter(Boolean).join(' / '),
                  // #837 pass 2: the main stat before -> after left the strip's row (one word there); it stands here
                  sel.delta && !dir ? `main stat ${sel.delta}` : '',
                  sel.state === 'done' && !dir && shown.state === 'running' ? 'полные статы и PoB — когда ран закончится: replay пишет их только в конце' : '',
                ])}
                {sel.metrics?.some(([, ours, author]) => ours != null || author != null) && !(bp?.key === id && bp.data) && tableEl('mt', versusCols('показатель', true), [{ rows: sel.metrics.map(([name, ours, author]): TCellV[] =>
                  [{ t: name, cls: 'mu' }, num(ours), pctCell(ours != null && author ? (ours / author) * 100 : null), { t: num(author), cls: 'mu' }]) }], `${sel.name} metrics`)}
              </Box>
            )
          }
          // #771 A6: the label and the strips are rows of the queue's one picture (the press of each lies over its own row)
          // #837 b12: the pager (counter + «новее» / «старее», the history's own words and places) stands at the row's right end; the counts text is left of it, at least GRID_PAGER_GAP px away from the counter and
          // from the row's own left text: when both do not fit, the counts text loses its tail parts (whole parts, never a cut word)
          const counter = paged ? counterOf(gridPlan) : ''
          const leftEnd = shown.issue ? 38 + textWidth('Билды', 12, true) + 8 + textWidth(runName, 13) + 4 : P0 + 12 + textWidth(`Билды ${runName}`, 12, true)
          const leadEnd = W - 12 - PAGER_PAD - textWidth(counter) - GRID_PAGER_GAP
          const leadT = paged ? whole(counts, leadEnd - leftEnd - 12) : ''
          const label: RowSpec = {
            kind: 'label', text: shown.issue ? 'Билды' : `Билды ${runName}`, right: paged ? counter : counts || (!p && runPick?.id === shown.id ? runPick.error ?? '' : ''), alt: `Билды ${runName}`,
            ...(paged ? { rightPad: PAGER_PAD, lead: leadT ? { t: leadT, end: leadEnd } : undefined } : {}),
            // the ticket is a native Link right after the word, never inside the picture
            hot: [...(shown.issue ? [{ x: 38 + textWidth('Билды', 12, true) + 8, w: 60, label: runName, href: `${GH}${shown.issue}` }] : []),
              ...(paged ? [pg(W - 12 - 2 * PG_W - 4, 'prev', { key: 'grid-prev', on: stepGrid(-1), dim: gpage === 0 }), pg(W - 12 - PG_W, 'next', { key: 'grid-next', on: stepGrid(1), dim: gpage === gpages - 1 })] : [])],
          }
          // #837 b10 S3: one muted head row under the label (as the card's own head), not over the placeholder, nothing over the time
          const head: RowSpec = { kind: 'head', cells: { name: 'билд', meta: 'ascendancy', tick: 'сиды', act: 'статус' } }
          return { rows: [{ r: label, i: 0 }, ...(told.length ? [{ r: head, i: 0, cols: sqGrid }] : []), ...strips.map((r, n) => ({ r, i: n, cols: wide.has(r) ? sqWide : sqGrid }))], below: detail() }
        }
        let k = 0
        return { rows: [], below: (
          <Box flexDirection="column">
            <Box flexDirection="row" flexWrap="wrap" alignItems="center">
              <Box width={17} paddingLeft={5} flexShrink={0}><Text bold color={K.nmuted}>{`Билды ${shown.issue ? `#${shown.issue}` : shown.tag}`}</Text></Box>
              {order.map(c => (
                <Button key={`cell-${shown.id}-${c.ref}-${c.seed}${c.variant ? '-' + c.variant : ''}`} plain label={GLYPH[c.state]}
                  dimColor={sel != null && cellId(shown, c) !== selected} onPress={() => void pick(shown, c)} />
              ))}
              {why && <Muted>{why}</Muted>}
            </Box>
            {p?.total_open && <Muted>варианты ещё добавляются</Muted>}
            {sel && (
              <Box flexDirection="column" marginTop={1}>
                <Head>
                  <Cell grow><Text bold color={K.text}>{sel.name}</Text></Cell>
                  <Cell w={10}><Muted>seed {sel.seed}</Muted></Cell>
                </Head>
                <Row i={k} k={`hv-sel-${k++}`}>
                  <Cell w={14}><Muted>состояние</Muted></Cell>
                  <Cell grow><Text color={CELL_COL[sel.state]}>{sel.state}</Text></Cell>
                </Row>
                <Row i={k} k={`hv-sel-${k++}`}>
                  <Cell w={14}><Muted>время</Muted></Cell>
                  <Cell grow><Text color={K.text}>{sel.took ? (sel.state === 'running' ? `started ${sel.took}` : sel.took) : '-'}</Text></Cell>
                </Row>
                {sel.delta && !shown.progress?.dir && (
                  <Row i={k} k={`hv-sel-${k++}`}>
                    <Cell w={14}><Muted>main stat</Muted></Cell>
                    <Cell grow><Text color={K.text}>{sel.delta}</Text></Cell>
                  </Row>
                )}
                {sel.state === 'done' && !shown.progress?.dir && shown.state === 'running' && (
                  <Muted>полные статы и PoB — когда ран закончится: replay пишет их только в конце</Muted>
                )}
                {(sel.state === 'done' || sel.state === 'failed') && buildPanel(shown, sel)}
                {sel.metrics && !(bp?.key === cellId(shown, sel) && bp.data) && (
                  <Box flexDirection="column" marginTop={1}>
                    <Head>
                      <Cell grow><Muted>metric</Muted></Cell>
                      <Cell w={14}><Muted>ours</Muted></Cell>
                      <Cell w={14}><Muted>author</Muted></Cell>
                      <Cell w={6}><Muted>%</Muted></Cell>
                    </Head>
                    {sel.metrics.map(([name, ours, author], mi) => {
                      const pc = ours != null && author ? (ours / author) * 100 : null
                      return (
                        <Row i={mi} k={`hv-metric-${mi}`}>
                          <Cell grow><Text color={K.text} wrap="truncate-end">{name}</Text></Cell>
                          <Cell w={14}><Text color={K.text}>{num(ours)}</Text></Cell>
                          <Cell w={14}><Text color={K.nmuted}>{num(author)}</Text></Cell>
                          <Cell w={6}><Text color={pc == null ? K.nmuted : pctCol(pc)}>{pc == null ? '-' : `${Math.round(pc)} %`}</Text></Cell>
                        </Row>
                      )
                    })}
                  </Box>
                )}
              </Box>
            )}
          </Box>
        ) }
      }
      const sq = squares()
      return (
        <Box flexDirection="column">
          {/* #995 send-back 2 (the running P2-core row's status was cut to «нет связи с ноутом,...»): a queue strip with no «начало» (a running or queued run) keeps the
              pane's grid, its status as wide as on 4adfc90f; the head, a finished run and the squares keep the grid with that column */}
          {rowsOne('run', [...rows.map((r, i) => (r.kind === 'strip' && !r.cells?.when ? { r, i, cols: COLS } : { r, i })), ...(sq?.rows ?? [])], RUN_COLS)}
          {f?.runs_error && <Text color={K.nfailed} wrap="truncate-end">{clipLine(f.runs_error)}</Text>}
          {sq?.below}
        </Box>
      )
    }


    // The 64-px faces of the open build's class (its ascendancy first, else its base class).
    const facesOf = (b: BuildPanel | null | undefined) => (b?.data?.class ? [...new Set(String(b.data.class).split(' / ').reverse())].filter(Boolean).map(n => `${n}_64`) : [])
    // #994 (defect 6): a reading's key ('rd|…') lives in the Builds tab's own atoms, a square's in POB's: the two tabs never close each other's open build
    const isRd = (key: string) => key.startsWith('rd|')
    const selAtomOf = (key: string) => (isRd(key) ? readSelAtom : selectedAtom)
    const panelAtomOf = (key: string) => (isRd(key) ? readPanelAtom : panelAtom)
    // ---------------------------------------------------------- one build: decode, open, compare
    // Shared by the runs card's squares and the Builds tab; `key` names the build in selectedAtom / panelAtom.
    const toggleSel = async (key: string) => {
      let opening = false
      await update($, selAtomOf(key), (x: string | null) => { opening = x !== key; return opening ? key : null })
      return opening
    }
    // The collector decodes the build (`collect.py build`): PoB's own saved PlayerStat, ours and the author's.
    const loadBuild = async (key: string, dir: string, ref: string, seed: number, variant: string) => {
      await update($, panelAtomOf(key), () => ({ key, loading: true }))
      let next: BuildPanel
      try {
        const ran = await $.process.run(['python', SCRIPT, 'build', dir, ref, String(seed), variant], { cwd: REPO, timeoutMs: 60_000 }) // a laptop run: ssh
        const v = JSON.parse(ran.stdout)
        next = v.error ? { key, error: String(v.error) } : { key, data: v }
      } catch (err) {
        void logError($, 'render', err)
        next = { key, error: String(err).slice(0, 160) }
      }
      await update($, panelAtomOf(key), (b: BuildPanel | null) => (b?.key === key ? next : b))
    }
    // "Open in PoB": PoB's command line takes only a pob://<site>/<id> link it downloads, never a
    // local file or code: a build with a pobb.in id (#572) opens by pob://pobbin/<id>, else the
    // collector starts PoB with the build in its Builds folder; the import code goes to the clipboard too.
    const openPobAt = async (key: string, dir: string, ref: string, seed: number, variant: string, surface: any, who: 'ours' | 'author') => {
      const b = await read($, panelAtomOf(key))
      let copied = false
      if (who === 'ours' && b?.key === key && b.data?.code) copied = (await $.ui.copy({ text: b.data.code, surface })).isCopied
      let note: string
      try {
        const ran = await $.process.run(['python', SCRIPT, 'openpob', dir, ref, String(seed), who, variant], { cwd: REPO, timeoutMs: 60_000 })
        const v = JSON.parse(ran.stdout)
        const whose = who === 'author' ? 'PoB автора' : 'наш PoB'
        note = v.error ? `${whose} не открылся: ${v.error}` : v.link ? `${whose} запущен: ${v.where}` : `${whose} запущен: Builds › ${v.where}`
      } catch (err) {
        note = `не открылся: ${String(err).slice(0, 120)}`
      }
      if (copied) note += ' · import code скопирован'
      await update($, panelAtomOf(key), (x: BuildPanel | null) => (x?.key === key ? { ...x, opened: note } : x))
    }
    // `facts` = the opener's own words about the build that its row does not say (none since #683 r5: a strip of the
    // squares and a row of Builds say them), `title` = the opener's name for it (a square's); `rowSaysNote` (the
    // Builds tab) = the opener's row already carries rank, audit and floors, so the collector's note made of exactly
    // those (collect.py _request_build) is not drawn again; a replay's before -> after note is. `under` = what the
    // opener says of the OPEN build only (the Builds tab: the brain's hint, the check's sentences, why it stopped),
    // drawn native under the head, where it wraps whole; while the build is read, or failed to read, it is drawn
    // all the same. The terminal keeps its text panel.
    const ROW_NOTE = /^(?:rank \S+)?(?: · )?(?:audit: .*?)?(?: · )?(?:floors: .*)?$/
    const buildPanelAt = (key: string, open: (surface: any, who: 'ours' | 'author') => void, facts?: string[], title?: string, rowSaysNote = false, under: any = null) => {
      const factsLine = (facts ?? []).filter(Boolean).join(' · ')
      // a square's head is drawn while its build is read (or failed to read): its name and facts live nowhere else
      const bare = (state: any) => (Svg && (title || under) ? <Box flexDirection="column">{title && detailHead(title, [factsLine])}{state}{under}</Box> : state)
      const bp = isRd(key) ? bpRd : bpPob
      const panelFaces = facesOf(bp)
      if (bp?.key !== key || bp.loading) return bare(<Muted>читаю билд…</Muted>)
      if (bp.error || !bp.data) return bare(<Text color={K.nfailed}>{bp.error ?? 'нет данных'}</Text>)
      const d = bp.data
      const okey = key.replace(/[^A-Za-z0-9_|-]/g, "_")
      if (Svg) {
        const tt = title ?? d.skill ?? '-'
        const face = panelFaces.map(k => faces.get(k)).find(Boolean)
        return (
          <Box flexDirection="column">
            {detailHead(tt, [
              [d.skill && d.skill !== tt ? d.skill : '', d.class ?? '', d.level ? `Level ${d.level}` : ''].filter(Boolean).join(' · '),
              factsLine, d.note && !(rowSaysNote && ROW_NOTE.test(d.note)) ? clipLine(d.note) : '',
            ], face, [
              { key: `open-pob-${okey}`, label: 'Открыть наш PoB', primary: true, on: (press: any) => open(press?.surface, 'ours') },
              ...(d.author_pobbin_url ? [{ key: `open-author-${okey}`, label: 'Открыть PoB автора', on: (press: any) => open(press?.surface, 'author') }] : []),
            ])}
            {under}
            {bp.opened && <Muted>{clipLine(bp.opened)}</Muted>}
            {tableEl('st', versusCols('показатель', d.author), d.groups.map(g => ({ title: g.title, rows: g.rows.map(([stat, ours, author, p]): TCellV[] => d.author
              ? [{ t: stat, cls: 'mu' }, String(ours), pctCell(p, true), { t: String(author), cls: 'mu' }]
              : [{ t: stat, cls: 'mu' }, String(ours)]) })), `${d.skill ?? ''} stats`)}
          </Box>
        )
      }
      const STAT_COLS = [{ grow: true }, { w: 9 }, { w: 9 }, { w: 6 }]
      return (
        <Box flexDirection="column" marginTop={1}>
          <Box flexDirection="row" gap={1} alignItems="center">
            <Box flexDirection="column" flexGrow={1}>
              <Text bold color={K.text}>{d.skill ?? '-'}</Text>
              <Muted>{d.class ?? ''}{d.level ? ` · Level ${d.level}` : ''}</Muted>
              {d.note && <Muted>{d.note}</Muted>}
            </Box>
            <Ctl k={`open-pob-${okey}`} label="Открыть наш PoB" main go={(press: any) => open(press?.surface, 'ours')} />
            {d.author_pobbin_url && (
              <Button key={`open-author-${okey}`} label="Открыть PoB автора"
                onPress={(press: any) => open(press?.surface, 'author')} />
            )}
          </Box>
          {bp.opened && <Muted>{bp.opened}</Muted>}
          <Box flexDirection="column" marginTop={1}>
            <Head>
              <Cell grow><Muted>stat</Muted></Cell>
              <Cell w={9}><Muted>ours</Muted></Cell>
              <Cell w={9}><Muted>{d.author ? 'author' : ''}</Muted></Cell>
              <Cell w={6}><Muted>{d.author ? '%' : ''}</Muted></Cell>
            </Head>
            <ColTable cols={STAT_COLS} rows={d.groups.flatMap((g, gi): TRow[] => [
              ...(gi ? [{ cells: [] }] : []),
              { cells: [{ t: g.title, b: true }] },
              ...g.rows.map(([stat, ours, author, p], ri): TRow => ({ odd: ri % 2 === 1, cells: [
                { t: stat, c: K.nmuted }, { t: String(ours) }, { t: d.author ? String(author) : '', c: K.nmuted },
                { t: p == null ? '' : `${p} %`, c: p == null ? K.nmuted : pctCol(p) }] })),
            ])} />
          </Box>
        </Box>
      )
    }
    // ---------------------------------------------------------- builds tab (#591)
    // The builds the brain queued for the owner to read (artifacts/readings/queue.json), read-only:
    // the brain removes a row once the owner's word on it has come. A press on a build opens the
    // same panel as a square of the runs card: Open PoB ours / author and the stat comparison.
    const buildsTab = () => {
      const q = f?.readings
      if (!q) return <Muted>loading...</Muted>
      const names = [...new Set(q.rows.map(r => r.run_name).filter(Boolean))].join(', ')
      const keyOf = (r: Reading) => `rd|${r.run_dir}|${r.ref}|${r.seed}|${r.variant ?? ''}`
      const pickReading = async (r: Reading) => {
        // #994 (defect 9): an opened reading stays on the drawn page (its panel takes room and re-cuts the pages): the lane pins it until the next step of the pager
        if (await toggleSel(keyOf(r))) { if (listPage?.rd != null) await unpage('rd'); await loadBuild(keyOf(r), r.run_dir, r.ref, r.seed, r.variant ?? '') }
      }
      const nameOf = (r: Reading) => [r.name ?? words(r.ref.replace(/^\d+\s+/, '')), r.var ?? ''].filter(Boolean).join(' · ')
      // #683 r5 (0), desktop: the tab duplicates an opened square of PoB runs in the pane's own style: a card, one
      // strip per reading on the tab's own grid (the name is the press), and under the open one the same detail panel.
      // #683 r5 (C) (owner 10.10: «убрать весь этот текстовый мусор»; on the mock: «Если что то не умещается и
      // многоточит, значит оно там быть не должно»; on the live tab 12:1x: «нахуя подсказка куда смотреть не под
      // спойлером билда?» and «хватит сюда нести тупо вериблы из кода»): a row is a strip of the squares: the
      // ascendancy's face, the build's name in a reader's words (the main skill, what a variant lacks: the
      // collector's `name` / `var`, never a slug), the ascendancy, the main number under PoB's own UI label, Life,
      // and the build's check as ONE mark and a plain word. Nothing of the code's vocabulary stands in it (no `seed`
      // unless two rows differ only by it, no output's code name, no `audit` / `floors`). The brain's note
      // («Куда смотреть») and the check's sentences belong to the OPEN build: native lines under its head, where
      // they wrap whole. The grid is fitted to the rows' own words (fitGrid): with no room left the ascendancy goes
      // first (the face says it), then the mark, then Life.
      if (Svg) {
        const n = q.rows.length
        const sub = n ? [`${n} ${ruForm(n, 'билд', 'билда', 'билдов')}`, names].filter(Boolean).join(' · ') : 'пусто'
        const anyOpen = q.rows.some(r => keyOf(r) === selectedRd)
        const okMark = (t: string) => ({ icon: 'done.octicons', color: K.done, t, cls: 'mu' })
        const badMark = (t: string) => ({ icon: 'failed.octicons', color: K.failed, t, cls: 'er' })
        const sameBuild = (a: Reading, b: Reading) => a.run_dir === b.run_dir && a.ref === b.ref && (a.variant ?? '') === (b.variant ?? '')
        // F15: the main number and Life are two right-aligned numeric columns with a head; the head names the number
        // (PoB's own label) when every row's is the same, else the rows keep their label in the cell
        const labels = [...new Set(q.rows.filter(r => r.ratio_pct == null && r.ours != null).map(r => r.metric_label ?? ''))]
        // #994 (defect 5): a column whose cells say «% автора» is not headed by a metric's name: the head names the metric only when NO row is a ratio, else «результат» and a row
        // with its own number keeps its label in the cell
        const oneLabel = labels.length === 1 && labels[0] && !q.rows.some(r => r.ratio_pct != null) ? labels[0] : ''
        const told = q.rows.map(r => {
          const errs = r.errors ?? 0
          const warns = r.warnings ?? 0
          const errsT = `${errs} ${ruForm(errs, 'ошибка', 'ошибки', 'ошибок')}`
          // the seed is said only where two rows are one build but for it
          const name = [r.name ?? words(r.ref.replace(/^\d+\s+/, '')), r.var ?? '', q.rows.some(x => x !== r && sameBuild(x, r)) ? `seed ${r.seed}` : ''].filter(Boolean).join(' · ')
          // #730: a build made from a request has no author: its own main number stands in the ratio's place
          const main: CellV = r.ratio_pct != null
            ? { t: `${r.ratio_pct} % автора`, cls: r.ratio_pct >= 100 ? 'ok' : r.ratio_pct >= 80 ? 'tx' : 'er' }
            : { t: r.ours != null ? `${oneLabel ? '' : r.metric_label ?? ''} ${r.ours_h ?? num(r.ours)}`.trim() : '', cls: 'tx' }
          return {
            r, name, main, asc: r.asc ?? r.class ?? '', life: r.life != null ? num(r.life) : '',
            marks: [
              // #962: the column «рейлы» says the number of errors and nothing else (a null count: an empty cell)
              ...(r.errors == null ? [] : errs ? [badMark(String(errs))] : [okMark('0')]),
            ],
            // the open build's own facts as the rows of one table (#793 F03, F06): its place in the request, the check's
            // verdict and sentences, why it stopped; the brain's hint first. Never a note line, never a bullet character.
            lines: [
              r.note ? ['Куда смотреть', { t: clipLine(r.note, NOTE_MAX), cls: 'tx' }] : null,
              r.rank != null ? ['Место', `${r.rank}-е в запросе${r.run_name ? ` «${r.run_name}»` : ''}`] : null,
              r.errors != null ? ['Проверка билда', { t: `${errs ? errsT : 'ошибок нет'}${warns ? `, ${warns} ${ruForm(warns, 'замечание', 'замечания', 'замечаний')}` : ''}`, cls: errs ? 'er' : 'mu' }] : null,
              ...(r.said ?? []).slice(0, SAID_MAX).map(([bad, t]): [string, TCellV] => ['Замечание', { t: clipLine(t, SAID_LINE_MAX), cls: bad ? 'er' : 'mu' }]),
              (r.said ?? []).length > SAID_MAX ? ['Замечание', { t: `ещё ${(r.said ?? []).length - SAID_MAX}`, cls: 'mu' }] : null,
              r.stop === 'time' ? ['Поиск', 'остановлен по времени: билд не досчитан'] : r.stop && r.stop !== 'converged' ? ['Поиск', r.stop] : null,
            ].filter((x): x is [string, TCellV] => !!x),
          }
        })
        const needTick = Math.max(textWidth(oneLabel || 'результат'), ...told.map(x => textWidth(tv(x.main))))
        const needLife = Math.max(textWidth('Life'), ...told.map(x => textWidth(x.life)))
        const grid = fitGrid([
          { key: 'name', x: 38, w: Math.round(330 * sc) },
          { key: 'meta', x: Math.round(380 * sc), w: Math.round(96 * sc) },
          { key: 'tick', x: Math.round(486 * sc), w: Math.round(160 * sc), cls: 'tx' },
          { key: 'life', x: Math.round(660 * sc), w: Math.round(86 * sc), cls: 'tx' },
          { key: 'act', x: Math.round(760 * sc), w: Math.max(40, W - 12 - Math.round(760 * sc)) },
        ], {
          name: Math.max(0, ...told.map(x => textWidth(x.name, 14) + 10)), // a native press: 13 px and its padding (rowSvg)
          meta: Math.max(0, ...told.map(x => textWidth(x.asc))),
          tick: needTick,
          life: needLife,
          act: Math.max(0, ...told.map(x => x.marks.reduce((w, m) => w + 17 + textWidth(m.t) + 14, -14))),
        }, ['meta', 'act', 'life'], W - 12).map(c => (c.key === 'tick' || c.key === 'life' ? { ...c, align: 'end' as const, num: true } : c)) // the numbers right-aligned in the columns fitGrid fitted
        // #972: the readings through the budget. A reading is a picture of its own (and, open, its panel under it), so its cost is its own drawn size, measured: every reading is
        // built, the page's are drawn; the pager stands in the card's corner when the queue does not fit whole
        const readEls = told.map(({ r, name, main, asc, life, marks, lines }, i) => {
                const key = keyOf(r)
                const isOpen = selectedRd === key
                const color = (r.class && CLASS[r.class]) || undefined
                const img = faces.get(`${r.asc ?? r.class}_16`)
                const row: RowSpec = {
                  kind: 'strip', sel: isOpen, calm: true, child: true, color, // #837 b9 A7: a build is never working (the kit takes a coloured, not calm row for a running one: dots), opened = the outline only
                  rail: img ? { img } : { dot: true, color: isOpen ? K.accent : color ?? K.idle },
                  // the alt says the row whole
                  alt: [name, asc, `${r.ratio_pct == null ? oneLabel : ''} ${tv(main)}`.trim(), life ? `Life ${life}` : '', ...(r.errors == null ? [] : [`рейлы ${r.errors}`])].filter(Boolean).join(' · '),
                  cells: {
                    name: { t: name, cls: isOpen ? 'tx' : 'mu', press: { key: `rd-pick-${key.replace(/[^A-Za-z0-9_-]/g, "_")}`, on: () => void pickReading(r), dim: anyOpen && !isOpen } },
                    meta: asc ? { t: asc, cls: 'mu' } : '', tick: main, life, act: marks.length ? { marks } : '',
                  },
                }
                // the open build's facts: a table (check | result), the brain's hint its first row
                const under = lines.length ? (
                  <Box flexDirection="column">
                    {tableOf(`rd-facts-${i}`, [{ key: 'what', label: 'рейлы', x: P0 }, { key: 'res', label: 'результат', x: 18 * PX_PER_COL, wrap: true }],
                      lines.map(([what, res]): TCellV[] => [{ t: what, cls: 'mu' }, res]), [], `${name}: ${lines.map(l => `${l[0]} ${typeof l[1] === 'string' ? l[1] : l[1].t}`).join(', ')}`)}
                  </Box>
                ) : null
                return (
                  <Box key={`rd-${key.replace(/[^A-Za-z0-9_-]/g, "_")}`} flexDirection="column" marginBottom={isOpen && i < n - 1 ? 1 : 0}>
                    {rowEl(`rdr-${i}`, row, i, grid)}
                    {isOpen && buildPanelAt(key, (surface, who) => void openPobAt(key, r.run_dir, r.ref, r.seed, r.variant ?? '', surface, who), undefined, undefined, true, under)}
                  </Box>
                )
        })
        const openAt = q.rows.findIndex(r => keyOf(r) === selectedRd)
        const readPlan = lane('rd', readEls.map((el: unknown) => sizeOf(el)), { pin: openAt >= 0 && listPage?.rd == null ? openAt : undefined })
        return (
          <Box flexDirection="column">
            <Card k="readings" iconName="book.octicons" name="Билды на чтение" sub={whole(sub, W - P0 - textWidth('Билды на чтение', 14, true) - 24)}>
              {cardPager('rd', readPlan)}
              {q.error && <Text color={K.nfailed}>{clipLine(q.error)}</Text>}
              {/* #994 (defect 5): the name is drawn in the picture at its column (#972), so the head word «билд» stands at the column too (the 5.5 px of the old host label are gone) */}
              {rowEl('rdh', { kind: 'head', cells: { name: 'билд', meta: 'ascendancy', tick: oneLabel || 'результат', life: 'Life', act: 'рейлы' } }, 0, grid)}
              {readPlan.shown.map(s => readEls[s.i])}
            </Card>
            <Muted>{fresh(hmDay(q.updated) || '-')}</Muted>
          </Box>
        )
      }
      return (
        <Box flexDirection="column">
          <Tile>
            <Title>Билды на чтение</Title>
            {q.error && <Text color={K.nfailed}>{q.error}</Text>}
            {q.rows.length === 0 && <Muted>очередь пуста</Muted>}
            {q.rows.map((r, i) => {
              const key = keyOf(r)
              const isOpen = selectedRd === key
              return (
                <Box key={`rd-${key.replace(/[^A-Za-z0-9_-]/g, "_")}`} flexDirection="column" marginBottom={i < q.rows.length - 1 ? 1 : 0}>
                  <Box flexDirection="row" gap={1} flexWrap="wrap">
                    <Button key={`rd-pick-${key.replace(/[^A-Za-z0-9_-]/g, "_")}`} plain label={`${isOpen ? '▾' : '▸'} ${nameOf(r)}`} onPress={() => void pickReading(r)} />
                    {/* #730: a build made from a request has no author: its own metric and audit stand in the ratio's place */}
                    {r.ratio_pct != null ? <Text color={pctCol(r.ratio_pct)}>{`${r.ratio_pct} %`}</Text>
                      : r.ours != null ? <Text color={K.text}>{`${r.metric_label ?? ''} ${r.ours_h ?? num(r.ours)}`.trim()}</Text> : <Muted>-</Muted>}
                    {r.life != null && <Text color={K.text}>{`Life ${num(r.life)}`}</Text>}
                    {!!r.errors && <Text color={K.nfailed}>{`${r.errors} ${ruForm(r.errors, 'ошибка', 'ошибки', 'ошибок')}`}</Text>}
                    {r.floors_bad && <Text color={K.nfailed}>ниже порога</Text>}
                  </Box>
                  {r.note && <Text color={K.nmuted} wrap="wrap">{r.note}</Text>}
                  {isOpen && buildPanelAt(key, (surface, who) => void openPobAt(key, r.run_dir, r.ref, r.seed, r.variant ?? '', surface, who))}
                </Box>
              )
            })}
          </Tile>
          <Muted>{`${names || '-'} · ${fresh(hmDay(q.updated) || '-')}`}</Muted>
        </Box>
      )
    }
    // #972 (the owner, 13.10: «на главной должно быть все что не связано с пое … Добавить вкладку POB в которой будет карточка поб ранс»): the tab «POB» = the runs card, with the picked
    // run's «Билды #N» block and the open build under it; the main tab keeps the machines' cards only
    const pobTab = () => (
      <Box flexDirection="column">
        {runsCard()}
        <Muted>{fresh(f?.at)}</Muted>
      </Box>
    )
    return { laptopCard, pcSlots, runsCard, buildsTab, pobTab }
  }
}

export const ADDON: Addon = {
  cards: [
    { id: 'laptop', order: 50, name: 'Laptop', draw: c => c.addon.laptopCard() },
  ],
  tabs: [
    { id: 'pob', order: 10, label: 'POB', draw: c => c.addon.pobTab() },
    { id: 'builds', order: 20, label: 'Билды', draw: c => c.addon.buildsTab(), ownOpen: true },
  ],
  signature, make, prepare,
  roleOrder: ['brain', 'orch', 'autopilot', 'keymaster', 'worker', 'worker-strong', 'researcher-find', 'researcher-how', 'other_sub', 'other_chat', 'unslop', 'monitor'],
}
