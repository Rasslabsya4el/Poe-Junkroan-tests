import { test } from 'claude-code/testing'
import { FAST, TICKETS } from './fixtures'
import { mountPane, seen, bars, onTabs } from './kit'
import { GRID } from '../hooks/tokens'

// #683 r5 (owner 10.10): (1) a nested row is shifted right, 24 px a level: its pill and its name move, the other
// columns stay on the grid; (2) an ORCH's tickets are rows under it (ORCH -> ticket -> its working subagents), each
// saying its state in plain words and how many subagents finished on it; a finished subagent is a count, not a row.
const P0 = GRID.rail + 4, INDENT = GRID.indent
// a nested row's name: the name column's x (register.tsx COLS, 38) + the 18-px inset a row with no role icon takes
// (#837 b11 R3: kit.tsx inset, and since b1f23e1f the no-role subagent row register.tsx:1014 takes it too)
const NAME0 = 38 + 18
const sub = (name: string, issue: number | null, busy: boolean, age = '5 min') =>
  ({ id: name, name, type: 'worker', issue, model: 'Sonnet 5.5', ctx: 50_000, age, busy, digest: busy ? 'Edit file_path=a.py' : undefined })
const sess = (name: string, extra: any = {}) =>
  ({ sid: name, name, kind: 'background', busy: true, issue: null, held: [], model: 'Sonnet 5.5', ctx: 120_000, age: '17 min', last: '', subagents: [], ...extra })
const FIN = ['#711 unit 1 stage catalog', '#711 unit 4 stage shares', '#711 unit 3 loop lines', 'Places for #711 stage lines']
// the ORCH as it was live 10.10 02:53: #632 held and not claimed, #711 claimed with 4 finished subagents
const ORCH_IDLE = sess('orch Poe-Junkroan #3', {
  held: [{ number: 632, claimed: false, subagents: [] }, { number: 711, claimed: true, subagents: [] }],
  subagents: FIN.map((n, i) => sub(n, 711, false, `${70 + i} s`)),
})
// one more ticket: claimed, two subagents working on it; and a closed one it finished
const ORCH_BUSY = sess('orch Poe-Junkroan #3', {
  held: [...ORCH_IDLE.held, { number: 702, claimed: true, subagents: [] }],
  subagents: [...ORCH_IDLE.subagents, sub('#702 unit 1 ailment sources', 702, true), sub('#702 unit 2 config rail', 702, true, '2 min'), sub('#703 threshold test', 703, false, '30 min')],
})
const CHAT = sess('MODS', { kind: 'interactive', subagents: [sub('look up the pane grid', null, true)] })
const tk = JSON.parse(TICKETS)
const like = Object.values(tk.issues)[0] as any
for (const [n, title, open] of [[632, 'Rage on Hit title', true], [711, 'Monitor step title', true], [702, 'Ailments title', true], [703, 'Threshold test title', false]] as const)
  tk.issues[String(n)] = { ...like, n, title, open, state: open ? 'open' : 'closed', kids: [], parent: null, blockers: [] }
const tickets = JSON.stringify(tk)
const fastWith = (agents: any[]) => JSON.stringify({ ...JSON.parse(FAST), agents })
/** The x of a strip's pill: the first rounded 17-px (#837) rect of its picture. */
const pillX = (src: string) => Number(/<rect x="([\d.]+)" width="[\d.]+" height="20" rx="10"/.exec(src)?.[1])
const nameX = (src: string, name: string) => Number(new RegExp(`<text x="([\\d.]+)"[^>]*>${name}<`).exec(src)?.[1])

test('desktop: a nested row is shifted right by 24 px a level, its parent is not', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { fast: fastWith([CHAT, ORCH_BUSY]), tickets }, 123)
  const pics = await onTabs(ui, ['main', 'pob'], bars) // #983: the sessions on «Главная», the run and its builds on «POB»
  const pic = (alt: string) => pics.find((p: any) => p.alt.startsWith(alt))?.src ?? ''
  const got = {
    chat: pillX(pic('MODS:')), sub: pillX(pic('look up the pane grid:')),
    orch: pillX(pic('ORCH:')), ticket: pillX(pic('#702 ')), worker: pillX(pic('unit 1 ailment sources:')),
    subName: nameX(pic('look up the pane grid:'), 'look up the pane grid'), workerName: nameX(pic('unit 1 ailment sources:'), 'unit 1 ailment sources'),
  }
  // a running run's build rows (the fixture's run has builds being computed) are its children too
  const job = JSON.parse(FAST).runs.running[0]
  const build = job.progress.cells.find((c: any) => c.state === 'running')
  const buildX = pillX(pic(`${build.name}:`)), runX = pillX(pic(`${job.tag} running`))
  console.log(`pill x: ${JSON.stringify(got)} | run ${runX}, its build ${buildX}`)
  if (got.chat !== P0 || got.orch !== P0 || runX !== P0) throw new Error('a parent row moved')
  if (got.sub !== P0 + INDENT || got.ticket !== P0 + INDENT || buildX !== P0 + INDENT) throw new Error('a level-1 row is not at P0 + 24')
  if (got.worker !== P0 + 2 * INDENT) throw new Error('a level-2 row is not at P0 + 48')
  if (got.subName !== NAME0 + INDENT || got.workerName !== NAME0 + 2 * INDENT) throw new Error('a nested name did not move with its pill')
  // the other columns stay on the grid: the model sits at the meta column's x on every level
  const metaX = (src: string) => Number(/<text x="([\d.]+)"[^>]*>Sonnet 5\.5</.exec(src)?.[1])
  if (new Set([metaX(pic('ORCH:')), metaX(pic('look up the pane grid:')), metaX(pic('unit 1 ailment sources:'))]).size !== 1) throw new Error('the meta column moved')
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`${surface}: an ORCH's tickets are rows: waiting, claimed, the finished subagents as a count`, async ($, on) => {
    const ui = await mountPane($, on, surface, { fast: fastWith([ORCH_IDLE]), tickets }, 123)
    const all = await seen(ui)
    const txt = all.join(' | ')
    for (const w of ['2 тикета', 'ещё не взят', 'у ORCH в работе · 4 отработали', 'Rage on Hit title', 'Monitor step title'])
      if (!all.some(t => t.trim() === w)) throw new Error(`missing «${w}»: ${txt.slice(0, 600)}`)
    const names = FIN.map(n => n.replace(/^#\d+\s*/, ''))
    const shown = names.filter(n => txt.includes(n))
    console.log(`${surface}: words «2 тикета», «ещё не взят», «у ORCH в работе · 4 отработали» shown; finished subagent names shown ${shown.length} of ${names.length}`)
    if (shown.length) throw new Error('a finished subagent has a row: ' + shown.join(', '))
    if (all.includes('0/2')) throw new Error('the old closed/all count is back')
  })

  test(`${surface}: a ticket in work names its workers; order = in work, claimed, waiting, closed`, async ($, on) => {
    const ui = await mountPane($, on, surface, { fast: fastWith([ORCH_BUSY]), tickets }, 123)
    const all = (await seen(ui)).map(t => t.trim())
    for (const w of ['4 тикета', 'в работе: 2 воркера', 'unit 1 ailment sources', 'unit 2 config rail', 'закрыт · 1 отработал'])
      if (!all.includes(w)) throw new Error(`missing «${w}»: ${all.join(' | ').slice(0, 800)}`)
    const at = ['в работе: 2 воркера', 'у ORCH в работе · 4 отработали', 'ещё не взят', 'закрыт · 1 отработал'].map(w => all.indexOf(w))
    console.log(`${surface}: act words at ${JSON.stringify(at)}`)
    if (at.some((v, i) => v < 0 || (i > 0 && v < at[i - 1]!))) throw new Error('ticket order ' + JSON.stringify(at))
    // the workers stand right under their ticket, before the next ticket's row
    const w1 = all.indexOf('unit 1 ailment sources'), w2 = all.indexOf('unit 2 config rail')
    if (!(at[0]! < w1 && w1 < w2 && w2 < at[1]!)) throw new Error('workers not under their ticket: ' + JSON.stringify([at, w1, w2]))
    if (all.includes('threshold test')) throw new Error('a finished subagent has a row')
  })
}

// 10.10 (live #720: merged, its ORCH said «ждёт merge», the row read «ждёт очереди у ORCH»): a ticket its ORCH holds
// but no longer claims was parked by it; the row says what it waits for, read from the Merge card's / PoB runs' data.
test('desktop: a parked ticket says what it waits for; one never worked on is not taken yet', async ($, on) => {
  const orch = sess('orch Poe-Junkroan #4', {
    held: [632, 711, 702, 703].map(number => ({ number, claimed: false, subagents: [] })),
    subagents: [sub('#711 unit 1', 711, false), sub('#702 unit 1', 702, false), sub('#703 unit 1', 703, false)],
  })
  const tk2 = JSON.parse(tickets)
  tk2.issues['703'] = { ...tk2.issues['703'], open: true, state: 'open' }
  const v = JSON.parse(FAST)
  v.agents = [orch]
  v.merge = { waiting: [{ branch: 'orch-711', issues: [711], position: 1, queued: '', waited_s: 5, eta_start_s: 60 }], landed: [] }
  v.runs.running[0].issue = 702
  const ui = await mountPane($, on, 'desktop', { fast: JSON.stringify(v), tickets: JSON.stringify(tk2) }, 123)
  const all = (await seen(ui)).map(t => t.trim())
  const want = ['ждёт мерджа · 1 отработал', 'ждёт PoB ран · 1 отработал', 'отложен ORCH · 1 отработал', 'ещё не взят']
  console.log(`parked words shown: ${want.filter(w => all.includes(w)).length} of ${want.length}; «ждёт очереди у ORCH» shown: ${all.some(t => t.includes('ждёт очереди у ORCH'))}`)
  for (const w of want) if (!all.includes(w)) throw new Error(`missing «${w}»: ${all.join(' | ').slice(0, 900)}`)
  if (all.some(t => t.includes('ждёт очереди у ORCH'))) throw new Error('the old words are back')
})
