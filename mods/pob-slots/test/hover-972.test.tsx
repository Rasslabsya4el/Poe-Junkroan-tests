import { test, mock, expect } from 'claude-code/testing'
// #972: ONE hover look in the whole monitor. This test walks whatever the pane draws: every element a pointer can press
// (a Button, a Link, a Markdown link), in every tab and every state the pane's own opening elements reach (a run picked,
// a build open while it is read and with its stats, every toggle / pager / pick the tree holds, one at a time and all
// together), on the owner's own data of 2026-10-13 (cache-live-20261013.ts) at the pane's width and a narrow one.
// For each element it reads: the host element behind it (Button = the light rectangle, Link / Markdown = an underline),
// where the host puts it against its row (test/grid.ts: a Button at its Box's px top, a Link / Markdown on the nearest
// 19-px line), and which code placed it (the shape of its Boxes, with the file:line of #972's cause table).
// The rule it holds: underline 0, off-text 0, in every state; a new element or state the pane grows is walked without
// editing this file; an element that bypasses the shared mechanism shows up as a second mechanism and fails.
import { CACHE_FAST, CACHE_TICKETS, CACHE_SLOW, CACHE_ORCH } from './cache-live-20261013'
import { BUILD_816 } from './buildpanel-answer'
import { faceReads, ghostPress, seedLinks, shown } from './kit'
import { gridOf, type Placed } from './grid'
import { pressFaces, type FaceRead } from './face'

const PROPS = (cols: number): any => ({ title: 'Junkroan', isFocused: false, bodyColumns: cols, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} })
type El = { tab: string; state: string; cols: number; card: string; key: string; label: string; el: 'Button' | 'Link' | 'Markdown'; look: 'rectangle' | 'underline'; mech: string; kind: string; off: number | null; at: number | null }
const kids = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
const keyOf = (n: any) => String(n?.props?.key ?? '')
const abs = (n: any) => n?.type === 'Box' && n.props?.position === 'absolute'

/** the code that placed a pointer element, read from the Boxes around it (register.tsx / addon.tsx of main at 306e14c2) */
const mechOf = (el: any, anc: any[]): string => {
  const ks = anc.map(keyOf)
  const pb = ks.find(k => k.startsWith('hv-pb-'))
  const row = ks.find(k => /^hv-(ag|mg|run|grid)\d+$/.test(k) || /^(ag|mg|run|grid)-[rg]\d+$/.test(k))
  const tabb = ks.find(k => k.startsWith('hv-tabb-'))
  // a table row: the keyed absolute Box at `cellTop(line)` / `cellH(span)` (the mock's drawn tree carries no `hover` prop, so it is not read)
  const tableRow = anc.find(a => abs(a) && typeof a.props.top === 'number' && typeof a.props.height === 'number' && /^hv-|-h\d+$/.test(keyOf(a)))
  if (tabb) return 'tab bar: Box hover + plain Button (register.tsx:1742-1743)'
  if (el.type === 'Markdown') return /\]\(.*\) *\[/.test(String(el.props?.text ?? '')) || (String(el.props?.text ?? '').match(/\]\(/g) ?? []).length > 1
    ? 'ghostSeeds: one Markdown of nbsp links over the seeds (register.tsx:743-758)'
    : 'ghostLink: a Markdown nbsp link over the drawn word (register.tsx:733-739)'
  if (el.type === 'Link') {
    if (tableRow) return 'tableEl native Link inside the row hover Box (register.tsx:871,883)'
    if (row) return kids(el).some((c: any) => c.type === 'Text' && c.props?.color === '#00000000')
      ? 'pressAt ghost Link (transparent Text) centred on the picture number (register.tsx:777-781, nativeHot0 :549)'
      : 'rowsOne Link with a label (register.tsx:549)'
    return 'rowOf Link / IssueLink (register.tsx:666,427)'
  }
  // a Button
  const lbl = String(el.props?.label ?? '')
  const parent = anc[anc.length - 1]
  // #972: THE pointer element: a plain Button in an absolute Box at the top of its row (`pressEl`, register.tsx); a control outside a row (Ctl) is the same Button in its PressBox
  if (parent && abs(parent) && parent.props.top === 0 && el.props?.plain) return 'pressEl'
  if (tableRow) return 'tableEl native plain Button, blank label over the picture icon (register.tsx:871,883)'
  if (row && pb) return (row.startsWith('hv-') || /-r\d+$/.test(row)) && /^\s+$/.test(lbl) || lbl === ''
    ? 'pressAt ghost Button, blank label (register.tsx:781, nativeHot0 :553)'
    : 'visibleAt: host Button with its label in a PressBox at the row top (register.tsx:767-770, :535-554)'
  if (pb) return el.props?.plain ? 'Ctl: the plain Button in its PressBox (register.tsx)' : 'Ctl / PressBox outside a row (register.tsx:535-537, :920-926)'
  if (ks.some(k => k.startsWith('card-')) && anc.some(a => abs(a) && a.props.top === 0)) return 'rowOf: Button in an absolute Box at the row top (register.tsx:655-669)'
  return 'other: ' + ks.filter(Boolean).slice(-3).join(' > ')
}
const kindOf = (key: string, label: string, el: string): string => {
  if (/^run-(pick|q|hist)-/.test(key)) return 'run title'
  if (/^(hist|grid|tk)-(prev|next)$/.test(key)) return 'pager word'
  if (/^cell-/.test(key)) return 'seed cell'
  if (/^tab-/.test(key)) return 'tab head'
  if (/^tg-/.test(key)) return 'tree toggle'
  if (/^rd-pick-/.test(key)) return 'reading row'
  if (/^open-(pob|author)-/.test(key)) return 'open PoB button'
  if (/^res-/.test(key)) return 'reserve button'
  if (/^cost-/.test(key)) return 'cost period'
  if (el === 'Link' || /^#\d+$/.test(label)) return 'ticket link'
  return 'other: ' + (key || label)
}
/** every pointer element of a drawn tree, with its offset from test/grid.ts where the grid reader placed it */
const elementsOf = (tree: any, tab: string, state: string, cols: number): El[] => {
  const g = gridOf(tree, cols)
  const placed = [...g.placed]
  const out: El[] = []
  const walk = (n: any, anc: any[], card: string) => {
    if (!n || typeof n !== 'object') return
    const k = keyOf(n)
    if (k.startsWith('card-')) card = k.slice(5)
    if (k.startsWith('hv-tabb-')) card = 'tabs'
    if (n.type === 'Button' || n.type === 'Link' || n.type === 'Markdown') {
      const label = String(n.props?.label ?? kids(n).map((c: any) => (typeof c === 'string' ? c : c.props?.children ?? c.children?.join?.('') ?? '')).join('') ?? n.props?.text ?? '')
      const i = placed.findIndex(p => p.el === n.type && (k ? p.key === k : p.key === ''))
      const p: Placed | undefined = i >= 0 ? placed.splice(i, 1)[0] : undefined
      out.push({ tab, state, cols, card, key: k, label: label.slice(0, 50), el: n.type, look: n.type === 'Button' ? 'rectangle' : 'underline', mech: mechOf(n, anc), kind: kindOf(k, label, n.type), off: p ? Math.round(p.off * 10) / 10 : null, at: p ? p.at : null })
      return
    }
    for (const c of kids(n)) walk(c, [...anc, n], card)
  }
  walk(tree, [], '')
  return out
}

/** the hooks beneath the pane, registered ONCE per test (before the first `$` call); `cfg.buildAnswers` is read at each build read */
const cfg = { buildAnswers: true }
function setup(on: any) {
  faceReads(on)
  const clock = mock.clock(on)
  const all: Record<string, string> = { fast: CACHE_FAST, tickets: CACHE_TICKETS, slow: CACHE_SLOW, orch: CACHE_ORCH }
  on('process.run', async (_$: any, e: any) => {
    if (e.argv[2] === 'build') return cfg.buildAnswers ? { value: { exitCode: 0, stdout: BUILD_816, stderr: '', isStdoutTruncated: false } } as any : new Promise(() => {}) as any
    return { value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.write', async () => ({ value: undefined }) as any)
  on('fs.exists', async () => ({ value: false }) as any)
  started = false
  return clock
}
let started = false
async function mount($: any, clock: any, cols: number, buildAnswers: boolean) {
  cfg.buildAnswers = buildAnswers
  if (!started) { started = true; void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {}) }
  await clock.settle()
  const ui = ghostPress(true, await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(cols) }))
  await clock.settle()
  return { ui, clock }
}
/** the keys of the elements that open or push rows apart, read from the drawn tree (never a list of today's) */
const OPENERS = /^(tg-|hist-next$|grid-next$|tk-next$|rd-pick-|run-pick-|run-q-|run-hist-|cell-)/
const openersOf = async (ui: any): Promise<string[]> => {
  const ks: string[] = []
  const walk = (n: any) => {
    if (!n || typeof n !== 'object') return
    if (n.type === 'Button' && OPENERS.test(keyOf(n))) ks.push(keyOf(n))
    if (n.type === 'Markdown') for (const l of seedLinks(n)) if (OPENERS.test(l.key)) ks.push(l.key)
    for (const c of kids(n)) walk(c)
  }
  walk(await ui.drawn())
  return [...new Set(ks)]
}
/** #972: the card rows' keyed Boxes `hv-<card><n>` and how many carry a `hover` prop (a card row lights nothing of its own; a table row `hv-cost-<n>` / `hv-tk-<n>` keeps its veil and is not counted) */
const rowBoxes = (tree: any): { rows: number; hover: number } => {
  let rows = 0, hover = 0
  const walk = (n: any) => {
    if (!n || typeof n !== 'object') return
    if (n.type === 'Box' && /^hv-[a-z]+\d+$/.test(keyOf(n)) && !/^hv-tabb/.test(keyOf(n))) { rows++; if (n.hover != null || n.props?.hover != null) hover++ }
    for (const c of kids(n)) walk(c)
  }
  walk(tree)
  return { rows, hover }
}
const worstOf = (fs: FaceRead[]) => {
  const f = fs.filter(r => r.face && r.dStart != null)
  const ds = f.map(r => Math.abs(r.dStart!)), dw = f.map(r => Math.abs(r.dWidth ?? 0))
  const top = (a: number[]) => (a.length ? Math.max(...a) : 0)
  return { n: f.length, start: top(ds), width: top(dw) }
}
const summary = (els: El[]) => {
  const by = (f: (e: El) => string) => { const m = new Map<string, number>(); for (const e of els) m.set(f(e), (m.get(f(e)) ?? 0) + 1); return [...m].map(([k, v]) => `${k} ${v}`).join(', ') }
  const off = els.filter(e => e.off != null && Math.abs(e.off) >= 0.5)
  const worst = off.length ? Math.max(...off.map(e => Math.abs(e.off!))) : 0
  return `elements ${els.length}; by look: ${by(e => e.look)}; off-text ${off.length} (worst ${worst} px; ${by.call(null, (e: El) => e.kind) && off.map(e => `${e.kind} ${e.off}`).slice(0, 6).join(', ')}); mechanisms ${new Set(els.map(e => e.mech)).size}`
}

const ALL: El[] = []
const FACES: (FaceRead & { tab: string; state: string; cols: number })[] = []
const ROWS = { rows: 0, hover: 0 }
const lines: string[] = []
const record = async (ui: any, tab: string, state: string, cols: number) => {
  const tree = shown(await ui.drawn())
  const els = elementsOf(tree, tab, state, cols)
  ALL.push(...els)
  const fs = pressFaces(tree, cols)
  FACES.push(...fs.map(f => ({ ...f, tab, state, cols })))
  const rb = rowBoxes(tree)
  ROWS.rows += rb.rows; ROWS.hover += rb.hover
  const w = worstOf(fs)
  lines.push(`${tab} | ${state} | ${cols} cols | ${summary(els)}; faces read ${w.n} of ${fs.length} pressEl (worst start ${w.start.toFixed(2)} px, worst width ${w.width.toFixed(2)} px); card row Boxes ${rb.rows}, with a hover prop ${rb.hover}`)
}

for (const cols of [120, 80]) {
  // #983: the cards stand on two tabs: «Главная» (Agents, Merge, the machines) and «POB» (the runs card, the picked run's builds, the open build)
  for (const home of ['main', 'pob']) test(`#972 walk: ${home} tab, ${cols} cols`, { timeoutMs: 180_000 }, async ($, on) => {
    const clock0 = setup(on)
    const mountAt = async (stats: boolean) => { const r = await mount($, clock0, cols, stats); if (home !== 'main') { await r.ui.press({ key: `tab-${home}` }); await r.clock.settle() } return r }
    for (const build of ['reading', 'stats'] as const) {
      let { ui, clock } = await mountAt(build === 'stats')
      await record(ui, home, 'nothing picked', cols)
      const openers = (await openersOf(ui)).filter(k => !k.startsWith('tg-'))
      const name = (k: string) => k.replace(/-j-\d{8}-\d{4}-\w+$/, '-<job>').replace(/^cell-.*$/, 'cell (build open, ' + build + ')')
      // one at a time, each on a fresh pane (a pick is not undone by a second press)
      for (const k of openers) {
        await ui.unmount(); ({ ui, clock } = await mountAt(build === 'stats'))
        // a cell lives under its run's picked square: the run is picked first (the atoms of a pick and a page live on across mounts)
        const job = /^cell-(j-\d{8}-\d{4}-\w+)-/.exec(k)?.[1]
        if (job) { await ui.press({ key: `run-pick-${job}` }).catch(() => {}); await clock.settle() }
        const ok = await ui.press({ key: k }).then(() => true, (e: any) => { lines.push(`${home} | ${name(k)} open | ${cols} cols | not reached: ${String(e).slice(0, 80)}`); return false })
        await clock.settle()
        if (ok) await record(ui, home, `${name(k)} open`, cols)
        if (/^(hist|grid)-next$/.test(k)) { await ui.press({ key: k.replace('next', 'prev') }).catch(() => {}); await clock.settle() }
      }
      // all together: the first running run picked, its first cell open (read from the tree after the pick), both pagers on page 2
      await ui.unmount(); ({ ui, clock } = await mountAt(build === 'stats'))
      const pick = openers.find(k => k.startsWith('run-pick-'))
      if (pick) { await ui.press({ key: pick }).catch(() => {}); await clock.settle() }
      const after = await openersOf(ui)
      for (const k of [...after.filter(k => k.startsWith('cell-')).slice(0, 1), ...after.filter(k => /^(hist|grid)-next$/.test(k))]) { await ui.press({ key: k }).catch(() => {}); await clock.settle() }
      await record(ui, home, `all open (build ${build})`, cols)
      await ui.unmount()
    }
  })
  for (const tab of ['tickets', 'cost', 'progress', 'builds']) {
    test(`#972 walk: ${tab} tab, ${cols} cols`, { timeoutMs: 180_000 }, async ($, on) => {
      const { ui, clock } = await mount($, setup(on), cols, true)
      await ui.press({ key: `tab-${tab}` }); await clock.settle()
      await record(ui, tab, 'closed', cols)
      const openers = await openersOf(ui)
      for (const k of openers) {
        await ui.press({ key: k }); await clock.settle()
        await record(ui, tab, `${k} open`, cols)
        if (/^(hist|grid|tk)-next$/.test(k)) { await ui.press({ key: k.replace('next', 'prev') }).catch(() => {}); await clock.settle() } else { await ui.press({ key: k }).catch(() => {}); await clock.settle() }
      }
      for (const k of openers) { await ui.press({ key: k }).catch(() => {}); await clock.settle() }
      await record(ui, tab, 'all open', cols)
      await ui.unmount()
    })
  }
}

test('#972 the rule: one look, every element on its own text', { timeoutMs: 60_000 }, async () => {
  console.log('HOVER972_TABLE_BEGIN\n' + lines.join('\n') + '\nHOVER972_TABLE_END')
  console.log('HOVER972_JSON_BEGIN' + JSON.stringify(ALL) + 'HOVER972_JSON_END')
  const underline = ALL.filter(e => e.look === 'underline')
  // the model's zero for a Button (grid.ts BETA, calibrated on the b11 probes) leaves 0.8 px on a 26-px row; the real pane is the judge of the px (#972 checkpoint 4)
  const off = ALL.filter(e => e.off != null && Math.abs(e.off) >= 1)
  const inRows = ALL.filter(e => e.card !== 'tabs' && e.at != null)
  const mechs = new Set(inRows.map(e => e.mech))
  expect(ALL.length, 'pointer elements walked').toBeGreaterThan(0)
  expect(underline.length, `elements with an underline on hover: ${underline.slice(0, 5).map(e => `${e.tab}/${e.state}/${e.kind}`).join(', ')}`).toBe(0)
  expect(off.length, `elements off their drawn text: ${off.slice(0, 5).map(e => `${e.tab}/${e.state}/${e.kind} ${e.off} px`).join(', ')}`).toBe(0)
  // #972: the light of every pointer element is EXACT on its face: its start (Box left cells + the lead's no-break spaces) within 1.5 px of the drawn face's first px, its width (em spaces + no-break spaces) within 3 px of the face's
  const read = FACES.filter(f => f.face && f.dStart != null)
  const kinds = [...new Set(read.map(f => f.where + '/' + f.kind))].sort()
  const badStart = read.filter(f => Math.abs(f.dStart!) > 1.5), badWidth = read.filter(f => Math.abs(f.dWidth ?? 0) > 3)
  const worst = (k: string, key: 'dStart' | 'dWidth') => Math.max(0, ...read.filter(f => f.where + '/' + f.kind === k).map(f => Math.abs(f[key] ?? 0)))
  console.log('HOVER972_FACES ' + kinds.map(k => `${k}: n ${read.filter(f => f.where + '/' + f.kind === k).length}, worst start ${worst(k, 'dStart').toFixed(2)} px, worst width ${worst(k, 'dWidth').toFixed(2)} px`).join(' | ') + `; unread by kind: ${[...new Set(FACES.filter(f => !f.face).map(f => f.where + '/' + f.kind))].sort().map(k => `${k} ${FACES.filter(f => !f.face && f.where + '/' + f.kind === k).length} e.g. ${FACES.find(f => !f.face && f.where + '/' + f.kind === k)!.key}`).join(', ')}; pressEl read ${read.length} of ${FACES.length} (the rest: a visible-label Button the host draws itself, or a chevron / icon face)`)
  expect(read.length, 'pressEl read against a drawn face').toBeGreaterThan(0)
  for (const k of ['card/ticket', 'card/title', 'card/seed', 'table/ticket']) expect(kinds, `kinds of pressEl read: ${kinds.join(', ')}`).toContain(k)
  expect(badStart.length, `pressEl starting off their face by more than 1.5 px: ${badStart.slice(0, 5).map(f => `${f.tab}/${f.state}/${f.key} ${f.dStart!.toFixed(2)}`).join(', ')}`).toBe(0)
  expect(badWidth.length, `pressEl wider / narrower than their face by more than 3 px: ${badWidth.slice(0, 5).map(f => `${f.tab}/${f.state}/${f.key} ${f.dWidth!.toFixed(2)}`).join(', ')}`).toBe(0)
  expect(ROWS.rows, 'card row Boxes walked').toBeGreaterThan(0)
  expect(ROWS.hover, 'card row Boxes with a hover prop').toBe(0)
  expect([...mechs], `placement mechanisms of the elements in rows and tables: ${[...mechs].join(' | ')}`).toEqual(['pressEl'])
  expect(ALL.filter(e => e.mech !== 'pressEl' && !e.mech.startsWith('Ctl:')).length, `elements neither pressEl nor a Ctl: ${ALL.filter(e => e.mech !== 'pressEl' && !e.mech.startsWith('Ctl:')).slice(0, 5).map(e => `${e.tab}/${e.kind}: ${e.mech}`).join(', ')}`).toBe(0)
})
