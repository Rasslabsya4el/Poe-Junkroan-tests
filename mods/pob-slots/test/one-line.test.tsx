import { test, mock, expect } from 'claude-code/testing'
// #837 pass 2 (P5), unit 4b: no strip cell and no table cell is higher than one line, except the table columns that wrap in the baseline
// (50ea5412: Tickets «название», Cost «название» and «По чатам», the reading's «результат»). Fixture: the u3 test's waiting jobs
// (rule 4: a job that waits for a job, one for a slot, one for RAM) on the 2026-10-11 FAST payload, 123 columns.
import { FAST, SLOW, ORCH } from './fixtures'
import { LIVE as TODAY } from './tickets-live-20261011'
import { COST_SLOW_20261011, COST_TICKETS_20261011 } from './cost-live-20261011'
import { LIVE_FAST } from './fast-live'
import { CELL_PX, rowsSvg, rowSvg, tableSvg } from '../hooks/kit'
import { CARD_PITCH } from '../hooks/tokens'
import { dq, mountPane, svgRows, mountG, rowLight, isRowBox } from './kit'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const waiting = () => {
  const f = JSON.parse(FAST)
  const [a, b] = f.runs.queued
  a.wait = { kind: 'after', text: 'ждёт P1-#814-2' }; a.host_fixed = true; a.start_s = 6960; a.start_h = '1 h 56 min'; a.takes_h = '36 min'
  b.wait = { kind: 'slots', text: 'слоты: свободно 1 из 5' }; b.takes_h = ''; delete b.start_h
  f.runs.queued.push({ ...b, id: 'j-ram', tag: 'P2-#2-1', issue: 2, wait: { kind: 'ram', text: 'RAM: свободно 4.4 из 8 GB' } })
  f.runs.queued.length = 3
  f.laptop = { runs: { ...f.runs, running: [], queued: [], daemon: { host: 'laptop', age_s: 3, slots_total: 6, slots_in_use: 0, reserved: 0, reserved_until: null } } }
  return f
}
const ysOf = (src: string) => [...new Set([...dq(src).matchAll(/<(?:text|tspan)\b[^>]*? y="([\d.]+)"/g)].map(m => Number(m[1])))].sort((x, y) => x - y)
const TABS: [string, string[]][] = [['main', []], ['pob', ['tab-pob']], ['pob, run picked', ['tab-pob', 'run-pick-' + waiting().runs.running[0].id]], ['tickets', ['tab-tickets', 'tg-670']], ['cost week', ['tab-cost', 'cost-week']], ['cost month', ['tab-cost', 'cost-month']], ['cost day', ['tab-cost', 'cost-day']], ['progress', ['tab-progress']], ['builds', ['tab-builds']]]
const open = async ($: any, on: any, name: string, keys: string[]) => {
  const cost = name.startsWith('cost')
  const out: Record<string, string> = { fast: /^(main|pob)/.test(name) ? JSON.stringify(waiting()) : cost ? '{}' : FAST, tickets: cost ? COST_TICKETS_20261011 : TODAY, slow: cost ? COST_SLOW_20261011 : SLOW, orch: ORCH }
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: out[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.write', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await mountG($, { plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  for (const k of keys) { await ui.press({ key: k }); await clock.settle() }
  return ui
}

// ---- strips: every row picture (a card's row, a Builds row) is one line: one text baseline, at most 30 px high (the Cost tabs hold tables only: the tables test below) ----
// #995 row 5: the Progress tab holds two tables and no row picture: read by «P5 tables» below
for (const [name, keys] of TABS.filter(([n]) => !n.startsWith('cost') && n !== 'progress')) {
  test(`P5 strips: ${name} tab: every row picture is one line (one text baseline, at most 30 px high), three waiting jobs`, { timeoutMs: 60_000 }, async ($, on) => {
    const ui = await open($, on, name, keys)
    const rows = (await svgRows(ui)).map((r: any) => { const src = dq(String(r.props.source)); return { alt: String(r.props.alt), H: Number(/^<svg[^>]* height="([\d.]+)"/.exec(src)?.[1]), ys: ysOf(src) } }).filter(r => r.H <= 60 && r.ys.length)
    const worst = rows.reduce((m, r) => Math.max(m, r.ys[r.ys.length - 1]! - r.ys[0]!), 0), tall = Math.max(0, ...rows.map(r => r.H))
    console.log(`P5STRIP ${name}: ${rows.length} row pictures, tallest ${tall} px, widest spread of text baselines ${worst.toFixed(1)} px`)
    expect(rows.length, 'row pictures read').toBeGreaterThan(0)
    // #837 b9a (B4): a picture of the run card is padded (blank, bottom) to whole 19-px screen lines, up to one line (19.25 px) more than its rows
    expect(rows.filter(r => r.H > 30 + 19.25).map(r => `${r.alt} ${r.H}`), 'a row higher than 30 px (+ the B4 pad of under one line)').toEqual([])
    expect(rows.filter(r => r.ys[r.ys.length - 1]! - r.ys[0]! > 1).map(r => `${r.alt} ${JSON.stringify(r.ys)}`), 'a row with two baselines').toEqual([])
  })
}

// ---- tables: a hover Box as many cells high as its row's lines; the lines under the first one belong to a wrap column only ----
const kids = (n: any): any[] => (n?.children ?? []).filter((c: any) => c && typeof c === 'object')
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
const words = (src: string) => [...dq(src).matchAll(/<(?:text|tspan)\b[^>]*? x="([\d.]+)"[^>]*? y="([\d.]+)"|<(?:text|tspan)\b[^>]*? y="([\d.]+)"[^>]*? x="([\d.]+)"/g)].map(m => ({ x: Number(m[1] ?? m[4]), y: Number(m[2] ?? m[3]) }))
/** per table picture of the tree: its rows (hover Boxes) and, for a row of more than one line, the x of every word below its first line */
const tablesOf = (tree: any) => {
  const out: { rows: number; wrapped: number; maxSpan: number; below: number[] }[] = []
  walk(tree, (n) => {
    const ks = kids(n)
    ks.forEach((svg, i) => {
      if (svg.type !== 'Svg') return
      const src = String(svg.props?.source ?? '')
      const boxes = ks.slice(i + 1).filter(c => c.type === 'Box' && c.props?.position === 'absolute' && (c.hover || rowLight(c) || isRowBox(c)) && Number.isInteger(c.props.top)) // #972: a row's Box carries its light
      if (!boxes.length) return
      const w = words(src), below = new Set<number>()
      let wrapped = 0, maxSpan = 1
      for (const b of boxes) {
        const top = b.props.top * CELL_PX, span = Math.round(Number(b.props.height ?? 1))
        maxSpan = Math.max(maxSpan, span)
        if (span > 1) { wrapped++; for (const x of w) if (x.y >= top + CELL_PX && x.y < top + span * CELL_PX) below.add(x.x) }
      }
      out.push({ rows: boxes.length, wrapped, maxSpan, below: [...below].sort((a, b) => a - b) })
    })
  })
  return out
}
for (const [name, keys] of TABS) {
  test(`P5 tables: ${name} tab: every table row is one line but a wrap column's, which is ONE column of its table`, { timeoutMs: 60_000 }, async ($, on) => {
    const ui = await open($, on, name, keys)
    const ts = tablesOf(await (ui as any).drawn())
    console.log(`P5TAB ${name}: ${ts.length} tables, rows ${ts.reduce((s, t) => s + t.rows, 0)}, rows of 2+ lines ${ts.reduce((s, t) => s + t.wrapped, 0)}, max lines ${Math.max(1, ...ts.map(t => t.maxSpan))}, x below the first line ${JSON.stringify(ts.map(t => t.below))}`)
    if (/tickets|cost/.test(name)) expect(ts.length, 'tables read').toBeGreaterThan(0)
    // #995 send-back 1 (defect 4): a Progress count row opens nothing, so it has no row Box (its lines are one line each by its spec: no wrap column)
    if (name === 'progress') expect(ts.length, 'a Progress table with row Boxes').toBe(0)
    expect(ts.filter(t => t.below.length > 1).map(t => JSON.stringify(t.below)), 'a table with more than one wrapped column').toEqual([])
    expect(ts.filter(t => t.wrapped > 0 && t.below.length === 0).length, 'a taller row with no words under its first line').toBe(0)
  })
}

// ---- rail: the strip-row code (rowBody, through rowSvg and rowsSvg) never evaluates `wrap` ----
// Object.prototype is sealed in the test engine, so the counter is a deep Proxy on what the strip code is given (the columns, the rows,
// their cells): every `get` / `in` of `wrap` anywhere in it is counted. Control: tableSvg, given a column with `wrap` and `whole`, reads it.
// (rowsOne / queueRows live in register.tsx's closure and hand their rows to rowsSvg; the two-tab drawing is read by the P5 tests above.)
test('P5 rail: `wrap` is evaluated 0 times by the strip-row code (rowBody via rowSvg and rowsSvg) on the main-grid and queue-grid rows; tableSvg reads it > 0 times', () => {
  let reads = 0
  const spy = <T extends object>(o: T): T => new Proxy(o, {
    get(t: any, k) { if (k === 'wrap') reads++; const v = t[k]; return v && typeof v === 'object' ? spy(v) : v },
    has(t, k) { if (k === 'wrap') reads++; return k in t },
  })
  const W = 960
  const grid = [
    { key: 'name', x: 38, w: 300 }, { key: 'tick', x: 352, w: 66 }, { key: 'meta', x: 428, w: 120 },
    { key: 'num', x: 552, w: 66, align: 'end', num: true }, { key: 'act', x: 622, w: 200 }, { key: 'time', x: W - 96, w: 84, align: 'end', num: true },
  ] as any[]
  const long = 'a very long status that waits for a job, for a slot and for RAM: ждёт P1-#814-2 · ~1 ч 56 мин · слоты: свободно 1 из 5'
  const rows: any[] = [
    { kind: 'head', cells: { name: 'задача', tick: 'тикет', act: 'статус', time: 'длительность' } },
    { kind: 'strip', state: 'queued', cells: { name: { t: long }, tick: { t: '#814', href: 'https://x/814' }, meta: { t: long }, num: '1', act: { t: long }, time: '2 min' }, ticket: { n: 814, href: 'https://x/814' } },
    { kind: 'strip', state: 'running', lvl: 1, child: true, cells: { name: long, act: long, time: '1 h' } },
    { kind: 'label', text: 'В очереди', right: long }, { kind: 'gap' }, { kind: 'track', frac: 0.4, knob: 'x' },
  ]
  const spied = spy({ rows, grid })
  const many = rowsSvg(spied.rows.map((r: any, i: number) => ({ r, i })), spied.grid, W)
  const one = spied.rows.map((r: any, i: number) => rowSvg(r, i, spied.grid, W))
  const stripReads = reads
  console.log(`P5RAIL strip-row code: ${many.hs.length} + ${one.length} rows drawn, wrap reads ${stripReads}`)
  expect(many.hs.length + one.length, 'rows drawn').toBe(12)
  reads = 0
  const col: any = spy({ label: 'название', x: 100, wrap: true, w: 200 })
  tableSvg([spy({ label: 'a', x: 20 }) as any, col], [{ rows: [['x', { t: long }]] }], 700, true)
  console.log(`P5RAIL control: tableSvg wrap reads ${reads}`)
  expect(reads, 'control: tableSvg reads wrap').toBeGreaterThan(0)
  expect(stripReads, 'strip-row code reads wrap').toBe(0)
})
