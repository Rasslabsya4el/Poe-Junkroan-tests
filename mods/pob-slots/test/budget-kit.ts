import { mock } from 'claude-code/testing'
import { PROPS, mountG } from './kit'
import { SLOW, ORCH } from './fixtures'
import { LIVE_FAST } from './fast-live'
import { LIVE as TIX_LIVE } from './tickets-live-20261011'
import { COST_SLOW_20261011 } from './cost-live-20261011'
import { BUILD_816 } from './buildpanel-answer'
import { MOD_DIR } from '../hooks/project'
import { PRESS_STAMP } from '../hooks/budget'
import { PROGRESS_LINES } from '../hooks/kit'

// #983: the worst-case rig of the budget tests (worst-case-972.test.tsx, budget-kinds-983.test.tsx). It mounts the pane on the desktop at 123 columns with
//   - the ascendancy faces at the size of the LARGEST file of assets/asc: 16 px = 858 bytes = 1,144 base64 characters, 64 px = 4,579 bytes = 6,108 (a distinct face a name);
//   - the pane's own state record captured (hooks/staterec.ts): the line of the draw holds `budget {fixed, charged, fits}`;
//   - payloads whose rows share nothing: every id, number, title, name, branch, tag and face differs from row to row, and every free text is LONG (256 characters, GitHub's
//     limit for a title) and made of narrow letters and of characters a picture escapes (`"`, `&`, `<`), so a cell fitted to its px width holds the most characters it can.
export const TARGET = 95_000
export const FACE16 = 1_144, FACE64 = 6_108
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const b64 = (name: string, n: number) => {
  let x = 2166136261
  for (const ch of name) x = Math.imul(x ^ ch.charCodeAt(0), 16777619) >>> 0
  let s = ''
  for (let i = 0; i < n; i++) { x = (Math.imul(x, 1664525) + 1013904223) >>> 0; s += B64[x >>> 26] }
  return s
}
export const copy = <T,>(x: T): T => JSON.parse(JSON.stringify(x))
export const h = (k: number, m: number) => (Math.imul(k, 2654435761) >>> 0) % m
const NARROW = ['il', 'fit', '"it"', 'till', 'j.l', 'i&l', '<li>', 'lit', 'jill', "it's", 'f.i.l', 'tilt']
/** a text of `n` characters, distinct by `k`: narrow letters and escaped characters, words of 2-5 letters */
export const long = (k: number, n = 256) => {
  let s = `${k} `
  for (let i = 0; s.length < n; i++) s += NARROW[h(k * 31 + i, NARROW.length)] + ' '
  return s.slice(0, n)
}

export const fast0 = JSON.parse(LIVE_FAST)
export const tix0 = JSON.parse(TIX_LIVE)
export const cost0 = JSON.parse(COST_SLOW_20261011)
export const ANCHOR_ID = 'j-20261011-0430-e070'
const live = fast0.runs.running as any[]
const ANCHOR = live.find((j: any) => j.id === ANCHOR_ID)
const REPLAY = live.find((j: any) => j.id === 'j-20261011-0419-7609')
const HIST_TPL = (fast0.runs.history as any[]).filter(j => j.rows_total).sort((a, b) => JSON.stringify(b).length - JSON.stringify(a).length)[0]
const LANDED_TPL = fast0.merge.landed[0]
const agentsLive = fast0.agents as any[]
const BUSY_SUB = agentsLive[1].subagents[0]
const SESSION_TPL = agentsLive[0]
const RUN_CELL = ANCHOR.progress.cells.find((c: any) => c.state === 'running')
const DONE_CELL = ANCHOR.progress.cells.find((c: any) => c.state === 'done')
const CLASSES = ['Witch', 'Templar', 'Duelist', 'Marauder', 'Ranger', 'Shadow', 'Scion']
const MODELS = ['Opus 5.5', 'Sonnet 5.5', 'Haiku 5.5', 'Fable 5.1']
const WHAT = ['replay', 'benchmark', 'request', 'tests']
const DIGESTS: string[] = agentsLive.flatMap(a => [a.digest, ...a.subagents.map((s: any) => s.digest)]).filter((d: any) => d)

export const ids = () => { let n = 9000; return { next: () => ++n } }
export type Ids = ReturnType<typeof ids>
const ISSUE_TPL: any = { n: 0, title: '', open: true, reason: null, labels: ['enhancement', 'area:monitor'], parent: null, blockers: [], kids: [], state: 'open', created: '2026-10-11T01:00:00Z', author: 'Rasslabsya4el' }
/** the tickets payload: the live one plus tickets #9001..#9999, each with its own 256-character title (in no goal, not in `loose`) */
export const tixWith = (mut: (t: any) => void = () => {}) => {
  const t = copy(tix0)
  for (let n = 9001; n <= 9999; n++) t.issues[String(n)] = { ...ISSUE_TPL, n, title: long(n) }
  mut(t)
  return JSON.stringify(t)
}

/** #983 send-back row 1: the tickets payload of the Progress tab's worst case: open tickets on EVERY line the card can draw (hooks/kit.tsx PROGRESS_LINES), each line's count
 *  its own and four digits wide (1,111 … 1,984; the repo holds under 1,000 tickets in all), the total five digits. `lineOf` = how one ticket lands on its line (`progressLines`' rule). */
const lineOf: Record<string, any> = { autopilot: { labels: ['autopilot'] }, folder: { labels: ['wayfinder:map'] }, blocked: { labels: [], blockers: [1] }, 'parked-on-run': { labels: [], parked_on_run: true }, 'no label': { labels: [] } }
export const PROGRESS_COUNT = (k: number) => 1_111 + 97 * k
export const tixProgress = () => {
  const t = copy(tix0)
  let n = 20_000
  PROGRESS_LINES.forEach((line, k) => {
    for (let c = 0; c < PROGRESS_COUNT(k); c++, n++) t.issues[String(n)] = { ...ISSUE_TPL, n, title: `p${n}`, labels: [line], ...(lineOf[line] ?? {}) }
  })
  return JSON.stringify(t)
}

/** the fast payload with every growing list emptied */
export const base = (): any => {
  const f = copy(fast0)
  f.runs.running = []; f.runs.queued = []; f.runs.history = []; f.runs.recent = []
  f.agents = []
  f.merge = { ...f.merge, running: null, waiting: [], landed: [] }
  f.readings = { ...f.readings, rows: [] }
  return f
}
export const jobNoKids = (i: Ids) => {
  const k = i.next(), total = 6 + h(k, 20)
  return { ...copy(REPLAY), id: `j-cl-${k}`, tag: `cl-${k}-${long(k, 60)}`, issue: k, priority: `P${h(k, 3)}`, workers: 1 + h(k + 1, 9), locks: 1 + h(k + 1, 9), host: h(k, 2) ? 'pc' : 'laptop', what: WHAT[h(k, 4)],
    left_h: `${1 + h(k, 9)} h ${10 + h(k, 49)} min`, dur: `${1 + h(k, 9)} h ${10 + h(k, 49)} min`, age: `${1 + h(k, 9)} h ${10 + h(k, 49)} min`, progress: { done: 1 + h(k, total - 2), total, total_open: true, eta: '07:39', cells: [] } }
}
const runCell = (k: number, j: number) => {
  const w1 = 0.2 + h(k + j, 50) / 100, w2 = 0.9 - w1 * 0.8
  return { ...copy(RUN_CELL), ref: `r${k}x${j}`, seed: 1 + j, variant: `v${k}x${j}`, name: `${long(k * 100 + j, 80)}`, class: CLASSES[h(k + j, 7)], asc: `Asc${k}x${j}`, stage: long(k * 77 + j, 120),
    started: RUN_CELL.started - 60 * (j + 1) * (1 + h(k, 9)), took: `${1 + h(k + j, 9)}:${10 + h(k + j, 49)}`,
    bar: { w: [w1, w2, Math.max(0.0014, 1 - w1 - w2)], fill: [h(k + j, 100) / 100, h(k + j + 1, 100) / 200, 0], at: h(k + j, 3) } }
}
/** a running run with `kids` builds being computed (each its own face, name, stage, bar) */
export const jobKids = (i: Ids, kids: number) => {
  const k = i.next()
  return { ...jobNoKids(i), id: `j-ck-${k}`, tag: `ck-${k}-${long(k, 60)}`, issue: k, progress: { done: 1, total: kids + 1, total_open: true, eta: null, cells: Array.from({ length: kids }, (_, j) => runCell(k, j)) } }
}
/** a running run whose grid has `lines` builds of `seeds` seeds each (states mixed, each line its own face and name); `id` = the run's id */
export const jobGrid = (i: Ids, lines: number, seeds: number, id = ANCHOR_ID) => {
  const k = i.next()
  const ST = ['done', 'failed', 'running', 'waiting', 'done', 'done']
  const cells = Array.from({ length: lines }, (_, l) => Array.from({ length: seeds }, (_, s) => {
    const st = ST[h(k + l * 7 + s, ST.length)]!
    return { ...copy(st === 'running' ? RUN_CELL : DONE_CELL), ref: `g${k}x${l}`, variant: '', seed: 1000 + s * (1 + h(l, 7)), name: long(k * 50 + l, 80), class: CLASSES[h(k + l, 7)], asc: `Gsc${k}x${l}`, state: st,
      took: `${1 + h(l + s, 50)} min`, stage: long(k + l * 3 + s, 100), metrics: [['Full DPS', 1000 + h(l * 9 + s, 900000), 1000 + h(l * 5 + s, 900000)]] }
  })).flat()
  return { ...copy(ANCHOR), id, tag: `cg-${k}-${long(k, 60)}`, issue: k, progress: { ...copy(ANCHOR.progress), done: 1, total: lines * seeds, total_open: true, cells } }
}
export const jobQueued = (i: Ids) => {
  const k = i.next()
  return { id: `j-cq-${k}`, tag: `cq-${k}-${long(k, 60)}`, name: `P1 #${k}`, issue: k, priority: `P${h(k, 3)}`, host: h(k, 2) ? 'pc' : 'laptop', workers: 1 + h(k, 9), state: 'queued', age: '78 min', date: '11.10', start: '', bench: false, dur: `${1 + h(k, 9)} h ${10 + h(k, 49)} min`,
    start_s: 3600 + h(k, 9000), start_h: `${1 + h(k, 9)} h ${10 + h(k, 49)} min`, takes_s: 3000, takes_h: '50 min', est: 'rate', wait: { kind: 'after', text: `ждёт ${long(k, 90)}` }, what: WHAT[h(k, 4)], host_fixed: true }
}
export const jobHist = (i: Ids) => {
  const k = i.next(), total = 3 + h(k, 30)
  return { ...copy(HIST_TPL), id: `j-ch-${k}`, tag: `ch-${k}-${long(k, 60)}`, issue: k, state: ['done', 'failed', 'stopped', 'cancelled'][h(k, 4)], rows_total: total, rows_done: h(k, total + 1), priority: `P${h(k, 3)}`, workers: 1 + h(k, 9),
    host: h(k, 2) ? 'pc' : 'laptop', what: WHAT[h(k, 4)], date: `${10 + h(k, 19)}.10`, start: `${10 + h(k, 13)}:${10 + h(k, 49)}`, dur: `${1 + h(k, 9)} h ${10 + h(k, 49)} min` }
}
export const sub = (i: Ids, issue: number | null, busy = true) => {
  const k = i.next()
  return { ...copy(BUSY_SUB), id: `sub-cl-${k}`, name: long(k, 120), issue, busy, model: MODELS[h(k, 4)], ctx: 20_000 + h(k, 160_000), age: `${1 + h(k, 9)} h ${10 + h(k, 49)} min`, digest: DIGESTS[h(k, DIGESTS.length)], dk: `dk${k}` }
}
/** a busy session: a chat (its `kids` busy and `done` finished subagents) or an ORCH (each busy subagent on a ticket of its own, `closed` more tickets held) */
export const session = (i: Ids, o: { orch?: boolean; kids?: number; done?: number } = {}) => {
  const k = i.next()
  const a = copy(SESSION_TPL)
  a.sid = `sess-cl-${k}`; a.busy = true
  a.name = o.orch ? `orch Poe-Junkroan #${k} ~${k}` : long(k, 120)
  a.kind = o.orch ? 'background' : 'interactive'
  a.issue = o.orch ? null : k
  a.model = MODELS[h(k, 4)]; a.ctx = 20_000 + h(k, 160_000); a.age = `${1 + h(k, 9)} h ${10 + h(k, 49)} min`; a.digest = DIGESTS[h(k, DIGESTS.length)]; a.dk = `dk${k}`
  a.subagents = [...Array.from({ length: o.kids ?? 0 }, () => sub(i, i.next())), ...Array.from({ length: o.done ?? 0 }, () => sub(i, o.orch ? i.next() : null, false))]
  a.held = o.orch ? a.subagents.map((s: any) => ({ number: s.issue, claimed: true })) : []
  return a
}
export const waiting = (i: Ids, pos: number) => {
  const k = i.next()
  return { branch: `orch-${k}-${long(k, 80).replace(/ /g, '-')}`, issues: [k], position: pos, queued: '2026-10-11T07:02:48', waited_s: 600, eta_start_s: 900 + h(k, 3000), waited_h: `${1 + h(k, 9)} h ${10 + h(k, 49)} min`, eta_start_h: `${1 + h(k, 9)} h ${10 + h(k, 49)} min`, takes_h: `${1 + h(k, 9)} h ${10 + h(k, 49)} min` }
}
export const landed = (i: Ids) => {
  const k = i.next()
  return { ...copy(LANDED_TPL), branch: `orch-${k}-${long(k, 80).replace(/ /g, '-')}`, issues: [k], rc: h(k, 5) ? 0 : 1, took_h: `${1 + h(k, 9)} h ${10 + h(k, 49)} min`, landed: `2026-10-11T0${h(k, 9)}:${10 + h(k, 49)}:20` }
}
/** a merge under test (its track, its counts) */
export const merging = (i: Ids) => {
  const k = i.next()
  return { branches: [`orch-${k}-${long(k, 80).replace(/ /g, '-')}`], issues: [k], phase: 'suite', tests_done: 1234, tests_total: 5678, percent: 21, failed: 3, eta_h: '1 h 12 min', elapsed_h: '2 h 34 min' }
}
const READING = fast0.readings.rows[0]
/** a reading: its own face, name and numbers; `notes` = the open build's facts at their longest (a 5,000-character hint, 30 remarks of 1,000 characters) */
export const reading = (k: number, notes = false) => ({ ...copy(READING), seed: 100 + k, ref: `${String(k).padStart(2, '0')} ${long(k, 60).replace(/ /g, '_')}`, pobbin_id: `cl${k}`, name: long(k, 90), var: long(k + 500, 40), class: CLASSES[h(k, 7)], asc: `Rsc${k}`,
  ours: 100_000 + h(k, 9_000_000), life: 3000 + h(k, 5000), errors: h(k, 3), warnings: h(k, 5), rank: 1 + k, run_name: long(k + 900, 80), stop: h(k, 2) ? 'time' : null,
  note: notes ? long(k, 5000) : long(k, 300), said: notes ? Array.from({ length: 30 }, (_, n) => [n % 2 === 0, long(k * 40 + n, 1000)]) : [] })
/** an offline laptop that was computing `n` runs */
export const laptopOff = (n: number) => ({ error: null, offline: { lost: '11.10 06:12', lost_ago: '1 h 12 min', seen: '11.10 06:10', seen_ago: '1 h 14 min', cores: 16, slots_total: 6,
  running: Array.from({ length: n }, (_, k) => ({ tag: `P1-#${9000 + k}-${long(k, 200)}`, workers: 1 + h(k, 9), total: 10 + h(k, 90), done: h(k, 10) })) } })

/** the answer of `collect.py build` at its largest: the stats table of 49 rows (addon/addon.py GROUPS: 13 + 7 + 21 + 7 stats and the main stat), every name and number its own */
export const BUILD_49 = (() => {
  const b = JSON.parse(BUILD_816)
  const sizes = [14, 7, 21, 7]
  b.groups = b.groups.map((g: any, gi: number) => ({ ...g, rows: Array.from({ length: sizes[gi] ?? g.rows.length }, (_, r) => {
    const src = g.rows[r % g.rows.length]
    return r < g.rows.length ? src : [`${src[0]} ${long(gi * 100 + r, 30)}`, `${(1 + h(gi * 31 + r, 9000)).toLocaleString('en-US')}.${h(r, 90)}M`, `${(1 + h(gi * 17 + r, 9000)).toLocaleString('en-US')}.${h(r, 80)}M`, 50 + h(gi * 7 + r, 120)]
  }) }))
  b.note = long(1, 400); b.name = long(2, 80); b.skill = long(3, 60); b.class = 'Shadow / Saboteur'
  return JSON.stringify(b)
})()
export const STAT_ROWS = 49

// ---- the cost payload at its largest: every table of every period filled with `n` distinct rows
const KINDS = ['input', 'cache_write', 'cache_read', 'output']
export const costWith = (n0: number, titles = true, only?: string) => {
  const slow = copy(cost0)
  for (const mode of ['cost_day', 'cost_week', 'cost_month']) {
    const cut = slow[mode].cut
    const n = n0, N = (table: string) => (only && only !== table ? 1 : n0)
    const num = (k: number) => ({ tokens: 1_000_000 + h(k, 900_000_000), cost_usd: 1 + h(k, 90_000) / 100, turns: 10 + h(k, 9000) })
    cut.by_role = Array.from({ length: N('role') }, (_, k) => ({ key: `role-${long(k, 40).replace(/ /g, '-')}`, group: ['main', 'sub', 'mod'][h(k, 3)], n: 1 + h(k, 9000), types: [], ...num(k) }))
    const roles = Array.from({ length: Math.max(N('rolemodel'), N('model')) }, (_, k) => `r${k}-${long(k + 50, 30).replace(/ /g, '-')}`)
    const models = Array.from({ length: Math.max(1, Math.ceil(Math.max(N('rolemodel'), N('model'), N('orchmodel')) / 4)) }, (_, k) => `claude-model-${k}-${long(k + 70, 20).replace(/ /g, '-')}`)
    cut.by_model = models.map((m, k) => ({ key: m, unpriced_turns: 0, ...num(k + 300) }))
    cut.by_role_model = roles.flatMap((r, k) => models.slice(0, 4).map((m, j) => ({ role: r, group: ['main', 'sub', 'mod'][h(k, 3)], model: models[(k + j) % models.length], n: 1 + h(k * 9 + j, 9000), led: 1 + h(k + j, 90), unpriced_turns: 0,
      first: `2026-10-${String(1 + h(k + j, 9)).padStart(2, '0')}`, last: `2026-10-${String(10 + h(k * 3 + j, 19)).padStart(2, '0')}`, spawned: { agents: 1 + h(k + j, 900), ...num(k * 5 + j) }, ended: null, closed: 1 + h(k + j, 40), ...num(k * 13 + j) })))
    // the ORCH's own pairs: one a model, so «ORCH на разных моделях» has a row a model
    cut.by_role_model.push(...models.map((m, k) => ({ role: 'orch', group: 'main', model: m, n: 1 + h(k, 900), led: 1 + h(k, 90), unpriced_turns: 0, first: '2026-10-01', last: `2026-10-${String(10 + h(k, 19)).padStart(2, '0')}`,
      spawned: { agents: 1 + h(k, 900), ...num(k + 11) }, ended: null, closed: 1 + h(k, 40), ...num(k + 23) })))
    cut.by_spawner = ['orch', 'autopilot', 'brain'].map((key, s) => ({ key, sessions: 100 + s, chats: [], own: num(s + 1), sub: { agents: 500, ...num(s + 2) }, ...num(s + 3),
      roles: Array.from({ length: N(key === 'autopilot' ? 'auto' : key) }, (_, k) => ({ key: `sp${s}-${long(k + s * 100, 40).replace(/ /g, '-')}`, agents: 1 + h(k + s, 9000), types: [], ...num(k + s * 1000) })) }))
    cut.by_mod = Array.from({ length: N('mod') }, (_, k) => ({ key: `mod-${long(k + 9, 40).replace(/ /g, '-')}`, model: models[k % models.length], calls: 1 + h(k, 90000), unpriced_calls: 0, ...num(k + 700) }))
    cut.by_who = Array.from({ length: N('who') }, (_, k) => ({ key: long(k + 4000, 200), kind: 'chat', sessions: 1 + h(k, 90), sub_usd: 1 + h(k, 9000) / 100, ...num(k + 800) }))
    cut.by_kind = Array.from({ length: Math.max(4, Math.min(N('kind'), 12)) }, (_, k) => ({ key: KINDS[k] ?? `kind-${long(k, 30)}`, ...num(k + 900) }))
    cut.by_day = Array.from({ length: Math.min(N('day'), 31) }, (_, k) => ({ key: `2026-10-${String(1 + k).padStart(2, '0')}`, ...num(k + 950) }))
    cut.days = Math.max(2, cut.by_day.length)
    cut.by_issue = Array.from({ length: Math.min(N('issue'), 20) }, (_, k) => ({ number: 9001 + k, ...(titles ? {} : { title: undefined }), ...num(k + 1000) }))
    cut.issue_rest = { n: 231, tokens: 1409258496, cost_usd: 548.94 }
  }
  return JSON.stringify(slow)
}

// ---- the mount
const norm = (p: unknown) => String(p).split('\\').join('/')
const STAMP = /,"press":\{"plugin":"[^"]*","handle":\d+\}/g
export type Seen = { drawn: number; charged: number; fixed: number; fits: boolean; view: string; tree: any; json: string }
/** `fast` as an object or as the collector's own text; `orch` = the orch payload (the fixture's when absent); `faceChars` = the base64 length of each face file by name
 *  (test/face-sizes.ts: the real files); absent, every face is as long as the largest file */
export async function openPane($: any, on: any, o: { fast?: any; tickets?: string; slow?: string; build?: string; cols?: number; orch?: string; faceChars?: Record<string, number> } = {}) {
  const clock = mock.clock(on)
  const all: Record<string, string> = { fast: typeof o.fast === 'string' ? o.fast : JSON.stringify(o.fast ?? base()), tickets: o.tickets ?? tixWith(), slow: o.slow ?? SLOW, orch: o.orch ?? ORCH }
  on('process.run', async (_$: any, e: any) => {
    if (e.argv[2] === 'build') return { value: { exitCode: 0, stdout: o.build ?? BUILD_49, stderr: '', isStdoutTruncated: false } } as any
    return { value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  const files = new Map<string, string>()
  on('fs.exists', async (_$: any, e: any) => ({ value: files.has(norm(e.path)) }) as any)
  on('fs.read', async (_$: any, e: any) => {
    const m = /[\\/]asc[\\/](\w+)_(16|64)x\2\.png$/.exec(String(e.path))
    if (m && e.as === 'bytes' && o.faceChars) { const n = o.faceChars[`${m[1]}_${m[2]}x${m[2]}.png`]; if (n) return { value: { base64: b64(m[1]! + m[2], n) } } as any; throw new Error('ENOENT ' + e.path) }
    if (m && e.as === 'bytes') return { value: { base64: b64(m[1]! + m[2], m[2] === '16' ? FACE16 : FACE64) } } as any
    if (files.has(norm(e.path))) return { value: files.get(norm(e.path)) } as any
    throw new Error('ENOENT ' + e.path)
  })
  on('fs.write', async (_$: any, e: any) => { files.set(norm(e.path), e.text); return { value: undefined } as any })
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui: any = await mountG($, { plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(o.cols ?? 123) })
  const settle = async () => { for (let k = 0; k < 6; k++) await clock.settle() }
  await settle()
  const press = async (key: string) => { await ui.press({ key }); await settle() }
  /** what is drawn now and what the pane charged for it. `drawn` = the characters of the drawn tree as the host holds it (its press stamps in). The state line must be of THIS draw:
   *  its own measure (the hook's tree and a stamp an element with a handler) is recomputed from the drawn tree and must be the same number. */
  const see = async (): Promise<Seen> => {
    await settle()
    const tree = await ui.drawn(), json = JSON.stringify(tree)
    const lines = (files.get(`${MOD_DIR}/bin/.cache/state.jsonl`) ?? '').split('\n').filter(Boolean).map(l => JSON.parse(l))
    const line = lines[lines.length - 1]
    if (!line?.budget) throw new Error('the pane wrote no state line with a budget')
    const own = json.replace(STAMP, '').length + (json.match(STAMP) ?? []).length * PRESS_STAMP
    if (line.guard.measure !== own) throw new Error(`the last state line (tab ${line.tab}, view ${line.view ?? ''}, measure ${line.guard.measure}) is not of the draw on the screen (${own})`)
    return { drawn: json.length, charged: line.budget.charged, fixed: line.budget.fixed, fits: line.budget.fits, view: line.view ?? '', tree, json }
  }
  return { ui, clock, press, see, settle, files }
}
/** the keyed row Boxes of a card's rows (`hv-<k><n>`) and the keyed table rows whose key starts with `prefix` */
export const count = (json: string, re: RegExp) => (json.match(re) ?? []).length
