import { test } from 'claude-code/testing'
import { COST } from '../hooks/budget'
import { RUN_COST } from '../hooks/addon'
// every kind the pane charges: the general table plus the runs card's own (addon.tsx)
const KIND = { ...COST, ...RUN_COST }
import { TARGET, ANCHOR_ID, base, ids, openPane, tixWith, costWith, jobNoKids, jobKids, jobGrid, jobQueued, jobHist, session, waiting, landed, merging, reading, laptopOff, count } from './budget-kit'
import type { Ids, Seen } from './budget-kit'

// #983 row 2: for every kind of row in COST (hooks/budget.ts) the charge is at or over what is drawn.
// A FAMILY fills ONE list with N rows of one kind (every other list empty), the rows sharing nothing and their texts at their longest (budget-kit.ts), for several N: from one row
// to far more than fit. In every state the pane's own charge for the draw (`budget.charged` of its state line) must be at or over the characters of the drawn tree, the tree must be
// under the target, and the least of every list must have fitted. Where two neighbouring N are both drawn whole, the summary prints what one more row drew and what it was charged.
type Tab = 'main' | 'pob' | 'builds' | 'tickets' | 'cost'
type Fam = { name: string; kinds: (keyof typeof KIND)[]; tab: Tab; ns: number[]; fast?: (n: number, i: Ids) => any; tix?: (n: number) => string; slow?: (n: number) => string; go?: (n: number) => string[]; rows: RegExp }
const F: Fam[] = []
const fastOf = (mut: (f: any, n: number, i: Ids) => void) => (n: number, i: Ids) => { const f = base(); mut(f, n, i); return f }

// ---- «Главная»
F.push({ name: 'Agents: a session', kinds: ['session', 'agentsExtra', 'pager'], tab: 'main', ns: [0, 1, 2, 3, 10, 60, 150], rows: /"key":"hv-ag\d+"/g, fast: fastOf((f, n, i) => { f.agents = Array.from({ length: n }, () => session(i)) }) })
F.push({ name: 'Agents: a working subagent under a chat', kinds: ['sub', 'calm'], tab: 'main', ns: [0, 1, 2, 3, 10, 60, 150], rows: /"key":"hv-ag\d+"/g, fast: fastOf((f, n, i) => { f.agents = [session(i, { kids: n })] }) })
F.push({ name: 'Agents: a finished subagent under a chat', kinds: ['sub', 'calm'], tab: 'main', ns: [0, 1, 2, 3, 9], rows: /"key":"hv-ag\d+"/g, fast: fastOf((f, n, i) => { f.agents = [session(i, { done: n })] }) })
F.push({ name: 'Agents: a ticket with its worker under an ORCH', kinds: ['ticket', 'sub', 'calm'], tab: 'main', ns: [0, 1, 2, 3, 10, 60], rows: /"key":"hv-ag\d+"/g, fast: fastOf((f, n, i) => { f.agents = [session(i, { orch: true, kids: n })] }) })
F.push({ name: 'Agents: a ticket with no worker under an ORCH', kinds: ['ticket', 'calm'], tab: 'main', ns: [0, 1, 2, 3, 10, 60], rows: /"key":"hv-ag\d+"/g, fast: fastOf((f, n, i) => { f.agents = [session(i, { orch: true, done: n })] }) })
F.push({ name: 'Merge: a waiting entry', kinds: ['mergeWait', 'mergeExtra', 'pager'], tab: 'main', ns: [0, 1, 2, 3, 10, 80, 200], rows: /"key":"hv-mg\d+"/g,
  fast: fastOf((f, n, i) => { f.merge.running = merging(i); f.merge.landed = Array.from({ length: 5 }, () => landed(i)); f.merge.waiting = Array.from({ length: n }, (_, k) => waiting(i, k + 1)) }) })
// #995 row 2: «Готово» of the Merge card is a lane (MERGE_PAGE a page at most, the pager on its label row)
F.push({ name: 'Merge: a landing of «Готово»', kinds: ['mergeDone', 'mergeDoneExtra', 'pager'], tab: 'main', ns: [0, 1, 2, 3, 4, 10, 80, 200], rows: /"key":"hv-mg\d+"/g,
  fast: fastOf((f, n, i) => { f.merge.running = merging(i); f.merge.waiting = []; f.merge.landed = Array.from({ length: n }, () => landed(i)) }) })
F.push({ name: 'Laptop offline: a «шло:» line', kinds: ['note'], tab: 'main', ns: [0, 1, 2, 3, 20, 400], rows: /шло: /g, fast: fastOf((f, n) => { f.laptop = laptopOff(n) }) })
// ---- «POB»
F.push({ name: 'PoB runs: a running run', kinds: ['run', 'runExtra', 'pager'], tab: 'pob', ns: [0, 1, 2, 3, 10, 60, 150], rows: /"key":"hv-run\d+"/g, fast: fastOf((f, n, i) => { f.runs.running = Array.from({ length: n }, () => jobNoKids(i)) }) })
F.push({ name: 'PoB runs: a build being computed under a run', kinds: ['runBuild', 'runMore', 'gridLine'], tab: 'pob', ns: [0, 1, 2, 3, 10, 60], rows: /"key":"hv-run\d+"/g, fast: fastOf((f, n, i) => { f.runs.running = [jobKids(i, n)] }) })
F.push({ name: 'PoB runs: a queued run', kinds: ['queued', 'queuedExtra', 'pager'], tab: 'pob', ns: [0, 1, 2, 3, 10, 60, 150], rows: /"key":"hv-run\d+"/g, fast: fastOf((f, n, i) => { f.runs.queued = Array.from({ length: n }, () => jobQueued(i)) }) })
F.push({ name: 'PoB runs: a finished run', kinds: ['done', 'doneExtra', 'pager'], tab: 'pob', ns: [0, 1, 2, 3, 6, 7, 13, 500], rows: /"key":"hv-run\d+"/g, fast: fastOf((f, n, i) => { f.runs.history = Array.from({ length: n }, () => jobHist(i)) }) })
F.push({ name: 'the picked run: a build line of one seed', kinds: ['gridLine', 'gridExtra', 'pager'], tab: 'pob', ns: [1, 2, 3, 8, 9, 40], rows: /"key":"hv-run\d+"/g, fast: fastOf((f, n, i) => { f.runs.running = [jobGrid(i, n, 1)] }) })
F.push({ name: 'the picked run: a seed of one build line', kinds: ['seed', 'gridStrip', 'gridMore'], tab: 'pob', ns: [1, 2, 3, 10, 40, 300], rows: /"key":"cell-/g, fast: fastOf((f, n, i) => { f.runs.running = [jobGrid(i, 1, n)] }) })
F.push({ name: 'the picked run: a seed of each of eight build lines', kinds: ['seed', 'gridStrip', 'gridMore'], tab: 'pob', ns: [1, 2, 3, 10, 40, 300], rows: /"key":"cell-/g, fast: fastOf((f, n, i) => { f.runs.running = [jobGrid(i, 8, n)] }) })
F.push({ name: 'PoB runs: a build being computed under a run that is not the picked one', kinds: ['runBuild', 'runMore'], tab: 'pob', ns: [0, 1, 2, 3, 10, 60], rows: /"key":"hv-run\d+"/g, fast: fastOf((f, n, i) => { f.runs.running = [jobNoKids(i), jobKids(i, n)] }) })
// ---- «Билды»
F.push({ name: 'Билды: a reading', kinds: ['pager'], tab: 'builds', ns: [0, 1, 2, 3, 10, 60, 150], rows: /"key":"rd-pick-/g, fast: fastOf((f, n) => { f.readings.rows = Array.from({ length: n }, (_, k) => reading(k)) }) })
F.push({ name: 'Билды: readings, the first open with its facts at their longest', kinds: ['pager'], tab: 'builds', ns: [1, 3, 60], rows: /"key":"rd-pick-/g,
  fast: fastOf((f, n) => { f.readings.rows = Array.from({ length: n }, (_, k) => reading(k, true)) }), go: () => ['rd-pick-FIRST'] })
// ---- «Тикеты»
F.push({ name: 'Тикеты: a ticket outside the goals', kinds: ['ticketSlack', 'pager'], tab: 'tickets', ns: [0, 1, 2, 3, 30, 300, 900], rows: /"key":"hv-tk-\d+"/g, fast: () => base(),
  tix: n => tixWith(t => { t.goals = []; t.loose = Array.from({ length: n }, (_, k) => 9001 + k) }) })
F.push({ name: 'Тикеты: the live goals, every branch open, and tickets outside them', kinds: ['ticketSlack', 'pager'], tab: 'tickets', ns: [0, 300], rows: /"key":"hv-tk-\d+"/g, fast: () => base(),
  tix: n => tixWith(t => { t.loose = [...t.loose, ...Array.from({ length: n }, (_, k) => 9001 + k)] }), go: () => ['OPEN-ALL'] })
// ---- «Расходы» (the week): every table of a group at N rows
for (const [g, word] of [['roles', 'Роли и модели'], ['spawn', 'Кто кого запускает'], ['days', 'Дни и тикеты']] as const)
  F.push({ name: `Расходы, «${word}»: a row in every table`, kinds: ['tableRow', 'tableCell', 'tableBar', 'tableChar', 'tablePress', 'tableExtra', 'pager'], tab: 'cost', ns: [1, 2, 3, 12, 45, 200], rows: /"key":"hv-cost-\d+"/g,
    fast: () => base(), slow: n => costWith(n), go: () => ['cost-week', `costg-${g}`] })

// one table at N rows, the others of its group at one: what a row of THAT table draws
const TABLES: [string, string, string][] = [['roles', 'role', 'По ролям'], ['roles', 'rolemodel', 'Роль на разных моделях'], ['roles', 'model', 'По моделям: кто вызывает'], ['roles', 'kind', 'По виду токенов'],
  ['spawn', 'orch', 'ORCH: сам и кого запускает'], ['spawn', 'orchmodel', 'ORCH на разных моделях: результат'], ['spawn', 'mod', 'Моды'], ['spawn', 'who', 'По чатам'], ['days', 'day', 'По дням'], ['days', 'issue', 'По тикетам']]
for (const [g, table, word] of TABLES)
  F.push({ name: `Расходы, the table «${word}» alone`, kinds: ['tableRow', 'tableCell', 'tableBar', 'tableChar', 'tablePress', 'tableExtra'], tab: 'cost', ns: [1, 2, 3, 12, 60, 400], rows: /"key":"hv-cost-\d+"/g, fast: () => base(), slow: n => costWith(n, true, table), go: () => ['cost-week', `costg-${g}`] })

type Got = Seen & { rows: number }
const R = new Map<string, Got>()
for (const fam of F) for (const n of fam.ns) {
  test(`#983 row 2: ${fam.name}, N=${n}: the charge is at or over the drawn tree, under ${TARGET}`, { timeoutMs: 120_000 }, async ($, on) => {
    const p = await openPane($, on, { fast: fam.fast?.(n, ids()), tickets: fam.tix?.(n), slow: fam.slow?.(n) })
    if (fam.tab !== 'main') await p.press(`tab-${fam.tab}`)
    for (const key of fam.go?.(n) ?? []) {
      if (key === 'rd-pick-FIRST') { const m = /"key":"(rd-pick-[^"]+)"/.exec((await p.see()).json); if (m) await p.press(m[1]!) }
      else if (key === 'OPEN-ALL') {
        // branches of the first page opened one by one (a toggle is pressed once: a second press would close it)
        const done = new Set<string>()
        for (let round = 0; round < 8; round++) {
          const fresh = [...(await p.see()).json.matchAll(/"key":"(tg-\d+)"/g)].map(m => m[1]!).filter(k => !done.has(k))
          if (!fresh.length) break
          done.add(fresh[0]!)
          await p.press(fresh[0]!)
        }
      } else await p.press(key)
    }
    const s = await p.see()
    const got: Got = { ...s, rows: count(s.json, fam.rows) }
    R.set(`${fam.name}|${n}`, got)
    console.log(`BK ${fam.name} | N=${n} | rows drawn ${got.rows} | drawn ${s.drawn} | charged ${s.charged} | spare ${s.charged - s.drawn} | fixed ${s.fixed} | fits ${s.fits}${s.view ? ` | ${s.view}` : ''}`)
    await p.ui.unmount()
    if (!s.fits) throw new Error(`${fam.name} N=${n}: the least of a list did not fit the room (fixed ${s.fixed})`)
    if (s.charged < s.drawn) throw new Error(`${fam.name} N=${n}: charged ${s.charged} is UNDER the drawn ${s.drawn} (by ${s.drawn - s.charged})`)
    if (s.drawn > TARGET) throw new Error(`${fam.name} N=${n}: draws ${s.drawn}, over ${TARGET}`)
  })
}

test('#983 row 2 summary: one more row of each kind, drawn against charged', { timeoutMs: 60_000 }, async () => {
  const out = ['family | N -> N | one more row drew | was charged | COST kinds']
  for (const fam of F) for (let k = 0; k + 1 < fam.ns.length; k++) {
    const a = R.get(`${fam.name}|${fam.ns[k]}`), b = R.get(`${fam.name}|${fam.ns[k + 1]}`)
    if (!a || !b || b.rows <= a.rows) continue
    const per = b.rows - a.rows
    out.push(`${fam.name} | ${fam.ns[k]} -> ${fam.ns[k + 1]} | ${Math.round((b.drawn - a.drawn) / per)} | ${Math.round((b.charged - a.charged) / per)} | ${fam.kinds.map(x => `${x} ${KIND[x]}`).join(', ')}`)
  }
  console.log('\n===== #983 row 2: ONE MORE ROW (characters; rows drawn, not rows in the data) =====\n' + out.join('\n') + '\n=====')
})
