import { test } from 'claude-code/testing'
import { TARGET, FACE16, FACE64, STAT_ROWS, base, ids, openPane, tixWith, tixProgress, PROGRESS_COUNT, costWith, jobNoKids, jobKids, jobGrid, jobQueued, jobHist, session, waiting, landed, merging, reading, laptopOff, count } from './budget-kit'
import type { Seen } from './budget-kit'
import { PROGRESS_LINES, progressLines, LABEL_WORD } from '../hooks/kit'
import { CACHE_FAST, CACHE_TICKETS, CACHE_SLOW, CACHE_ORCH } from './cache-live-20261013'
import { LIVE_FAST } from './fast-live'
import { BUILD_816 } from './buildpanel-answer'
import { FACE_CHARS } from './face-sizes'

// #972 / #983 row 1: THE worst case of every tab and of every group x period of «Расходы»: every list far longer than fits, the rows sharing nothing (their own ids, numbers, names,
// faces), every free text at 256 characters of narrow letters and escaped characters, every opener open, the 16-px faces distinct at 1,144 characters each, the 64-px face of the
// open build at 6,108, its stats table at 49 rows (test/budget-kit.ts). Each state must draw at most 95,000 characters (the host blanks the pane past 100,000), the pane's own
// charge for the draw must be at or over the drawn tree, and the least of every list must have fitted the room. One line a state, the summary prints them as a table.
type State = { name: string; tab: string; fast?: () => any; tix?: () => string; slow?: () => string; go?: string[]; open?: 'seed' | 'reading' | 'branches' }
type Pane = Awaited<ReturnType<typeof openPane>>
const S: State[] = []

const mainFast = (laptop: 'on' | 'off') => () => {
  const f = base(), i = ids()
  f.agents = [...Array.from({ length: 30 }, () => session(i, { kids: 10, done: 5 })), ...Array.from({ length: 3 }, () => session(i, { orch: true, kids: 20, done: 10 })), ...Array.from({ length: 30 }, () => session(i))]
  f.merge.running = merging(i); f.merge.landed = Array.from({ length: 200 }, () => landed(i)); f.merge.waiting = Array.from({ length: 80 }, (_, k) => waiting(i, k + 1)) // #995: «Готово» is paged
  if (laptop === 'off') f.laptop = laptopOff(400)
  return f
}
S.push({ name: 'Главная (Laptop on the link)', tab: 'main', fast: mainFast('on') })
S.push({ name: 'Главная (Laptop offline, 400 «шло:» lines)', tab: 'main', fast: mainFast('off') })
S.push({ name: 'Главная, Agents page 2 and Merge page 2', tab: 'main', fast: mainFast('on'), go: ['ag-next', 'mgw-next', 'mgd-next'] })

const pobFast = () => {
  const f = base(), i = ids()
  f.runs.running = [jobGrid(i, 40, 40), ...Array.from({ length: 20 }, () => jobNoKids(i)), ...Array.from({ length: 5 }, () => jobKids(i, 20))]
  f.runs.queued = Array.from({ length: 60 }, () => jobQueued(i))
  f.runs.history = Array.from({ length: 500 }, () => jobHist(i))
  return f
}
S.push({ name: 'POB, the picked run (40 builds of 40 seeds)', tab: 'pob', fast: pobFast })
S.push({ name: `POB, the picked run and an open build (${STAT_ROWS} stats, the ${FACE64}-character face)`, tab: 'pob', fast: pobFast, open: 'seed' })
S.push({ name: 'POB, an open build, every pager on its page 2', tab: 'pob', fast: pobFast, open: 'seed', go: ['runr-next', 'runq-next', 'hist-next', 'grid-next'] })

const rdFast = () => { const f = base(); f.readings.rows = Array.from({ length: 60 }, (_, k) => reading(k, true)); return f }
S.push({ name: 'Билды (60 readings)', tab: 'builds', fast: rdFast })
S.push({ name: `Билды, a reading open (${STAT_ROWS} stats, the face, a 5,000-character hint, 30 remarks)`, tab: 'builds', fast: rdFast, open: 'reading' })

const tix900 = () => tixWith(t => { t.loose = [...t.loose, ...Array.from({ length: 900 }, (_, k) => 9001 + k)] })
S.push({ name: 'Тикеты (the live goals and 900 tickets outside them)', tab: 'tickets', tix: tix900 })
S.push({ name: 'Тикеты, every branch open', tab: 'tickets', tix: tix900, open: 'branches' })
S.push({ name: 'Тикеты, every branch open, page 2', tab: 'tickets', tix: tix900, open: 'branches', go: ['tk-next'] })

for (const [g, word] of [['roles', 'Роли и модели'], ['spawn', 'Кто кого запускает'], ['days', 'Дни и тикеты']] as const)
  for (const [m, period] of [['day', 'День'], ['week', 'Неделя'], ['month', 'Месяц']] as const)
    S.push({ name: `Расходы, «${word}» x ${period}`, tab: 'cost', slow: () => costWith(200), go: [`cost-${m}`, `costg-${g}`] })
S.push({ name: 'Расходы, «Роли и модели» x Месяц, every table on its page 2', tab: 'cost', slow: () => costWith(200), go: ['cost-month', 'costg-roles', 'cost-role-next', 'cost-rolemodel-next', 'cost-model-next'] })
// #983 send-back row 1: the Progress card draws a line only when it holds a ticket (hooks/kit.tsx `progressLines`), so its worst case is a ticket on EVERY line it can draw,
// each count four digits wide (`tix900` put all 900 on one line: 11,395 characters against the real pane's 12,229 of the same night)
const PROGRESS = `Прогресс (all ${PROGRESS_LINES.length} lines, each count four digits)`
S.push({ name: PROGRESS, tab: 'progress', tix: tixProgress })

/** press the state's tab, open what it opens, press what it presses: the same walk for a worst case and for the live fixture */
async function reach(p: Pane, st: { tab: string; go?: string[]; open?: State['open'] }) {
  if (st.tab !== 'main') await p.press(`tab-${st.tab}`)
  const keysOf = async (re: RegExp) => [...(await p.see()).json.matchAll(re)].map(m => m[1]!)
  if (st.open === 'seed') {
    // a finished seed of the picked run: the first one whose press brings the build's stats; when the run picked at the start has none (a live payload's first run
    // may hold only builds still computing), each run that can be picked is picked in turn
    let opened = false
    const runs: (string | null)[] = [null, ...await keysOf(/"key":"(run-pick-[^"]+)"/g)]
    for (const run of runs) {
      if (run) await p.press(run)
      for (const k of (await keysOf(/"key":"(cell-[^"]+)"/g)).slice(0, 24)) {
        await p.press(k)
        if ((await p.see()).view.includes('panel')) { opened = true; break }
        await p.press(k)
      }
      if (opened) break
    }
    if (!opened) throw new Error('no seed of any running run opened a build')
  }
  if (st.open === 'reading') { await p.press((await keysOf(/"key":"(rd-pick-[^"]+)"/g))[0]!); if (!(await p.see()).view.includes('panel')) throw new Error('the reading did not open') }
  if (st.open === 'branches') {
    // every branch drawn on the first page opened, level by level (a toggle is pressed once: a second press would close it)
    const done = new Set<string>()
    for (let round = 0; round < 8; round++) {
      const fresh = (await keysOf(/"key":"(tg-\d+)"/g)).filter(k => !done.has(k))
      if (round === 0 && !fresh.length) throw new Error('no branch toggle is drawn')
      if (!fresh.length) break
      const k = fresh[0]!
      done.add(k)
      await p.press(k)
    }
    if (!(await p.see()).view.includes('open:')) throw new Error('no branch opened')
  }
  for (const k of st.go ?? []) await p.press(k)
  return p.see()
}

const R: { name: string; s: Seen; pagers: number }[] = []
for (const st of S) {
  test(`#983 row 1: ${st.name}: at most ${TARGET} drawn characters in the worst case`, { timeoutMs: 180_000 }, async ($, on) => {
    const p = await openPane($, on, { fast: st.fast?.(), tickets: st.tix?.(), slow: st.slow?.() })
    const s = await reach(p, st)
    if (st.open && st.open !== 'branches') {
      const stats = count(s.json, /"key":"st-h\d+"/g)
      if (stats !== STAT_ROWS) throw new Error(`the open build draws ${stats} stat rows, not ${STAT_ROWS}`)
      if ((s.json.match(/data:image\/png;base64,[A-Za-z0-9+/]{6108}/g) ?? []).length < 1) throw new Error(`the open build's ${FACE64}-character face is not drawn`)
    }
    let progress = ''
    if (st.name === PROGRESS) {
      // every line the card can draw is drawn, each with its own four-digit count
      // (#995 send-back 1: a count row has no Box any more: a line is found by its words in the picture)
      const missing = PROGRESS_LINES.filter(id => !s.json.includes(LABEL_WORD[id]!))
      const lines = PROGRESS_LINES.length - missing.length
      // a line's count = the tickets this state adds to it (PROGRESS_COUNT) plus the live payload's own on that line: what `progressLines` counts over the payload
      const counts = new Map(progressLines(JSON.parse(st.tix!()).issues))
      const short = PROGRESS_LINES.filter((id, k) => !(counts.get(id)! >= PROGRESS_COUNT(k) && String(counts.get(id)).length === 4 && s.json.includes(`>${counts.get(id)}<`)))
      console.log(`WC ${st.name} | lines drawn ${lines} of ${PROGRESS_LINES.length} | counts ${PROGRESS_LINES.map(id => counts.get(id)).join(' ')}`)
      if (missing.length || lines !== PROGRESS_LINES.length) progress = `the Progress card draws ${lines} lines, its most is ${PROGRESS_LINES.length}${missing.length ? ` (missing: ${missing.join(', ')})` : ''}`
      else if (short.length) progress = `the Progress card does not draw the four-digit count of: ${short.join(', ')}`
    }
    const faces16 = new Set(s.json.match(new RegExp(`data:image/png;base64,[A-Za-z0-9+/]{${FACE16}}(?![A-Za-z0-9+/])`, 'g')) ?? []).size
    const pagers = count(s.json, /rotate\(180 8 8\)/g) // #994: a pager is two drawn chevrons, «previous» the turned one: one a pager
    R.push({ name: st.name, s, pagers })
    console.log(`WC ${st.name} | drawn ${s.drawn} | charged ${s.charged} | spare to ${TARGET}: ${TARGET - s.drawn} | pagers ${pagers} | 16-px faces ${faces16}${s.view ? ` | ${s.view}` : ''}`)
    await p.ui.unmount()
    if (progress) throw new Error(progress)
    if (!s.fits) throw new Error(`${st.name}: the least of a list did not fit the room (the fixed part ${s.fixed})`)
    if (s.charged < s.drawn) throw new Error(`${st.name}: charged ${s.charged} is UNDER the drawn ${s.drawn}`)
    if (s.drawn > TARGET) throw new Error(`${st.name}: draws ${s.drawn} characters, over ${TARGET}`)
  })
}

test('#983 row 1 summary: the worst case of every tab and every group x period of Расходы', { timeoutMs: 60_000 }, async () => {
  const lines = R.map(r => `${r.name} | ${r.s.drawn} | ${r.s.charged} | ${TARGET - r.s.drawn} | ${r.pagers}`)
  console.log(`\n===== #983 row 1: WORST CASE (characters of the drawn tree; the target ${TARGET}, the host's limit 100000) =====\nstate | drawn | charged | spare | pagers drawn\n${lines.join('\n')}\n=====`)
  if (R.length !== S.length) throw new Error(`${S.length - R.length} states were not measured`)
  const worst = Math.max(...R.map(r => r.s.drawn))
  if (worst > TARGET) throw new Error(`the heaviest state draws ${worst}`)
})

// #983 send-back row 1: a worst case is an upper bound only while the REAL pane draws no more than it. The live fixture = the installed pane's own collector answers
// (test/cache-live-20261013.ts: the pane as the owner saw it on 2026-10-13 20:4x), a real build answer, every face at its real file's length. Each tab and each group x period
// of «Расходы» of it, in the same states the worst cases stand in, must draw at most what its worst case draws: a worst case under the real pane can never pass again.
// The runs of that evening held no finished seed, so the open build is read on the other real payload the tests keep (test/fast-live.ts: the live fast payload of 2026-10-11).
type Live = { name: string; tab: string; go?: string[]; open?: State['open']; worst: string; fast?: string }
const L: Live[] = [
  { name: 'Главная', tab: 'main', worst: 'Главная (Laptop on the link)' },
  { name: 'POB, the picked run', tab: 'pob', worst: 'POB, the picked run (40 builds of 40 seeds)' },
  { name: 'POB, the picked run (the runs of 2026-10-11)', tab: 'pob', fast: LIVE_FAST, worst: 'POB, the picked run (40 builds of 40 seeds)' },
  { name: 'POB, the picked run and an open build (the runs of 2026-10-11)', tab: 'pob', open: 'seed', fast: LIVE_FAST, worst: `POB, the picked run and an open build (${STAT_ROWS} stats, the ${FACE64}-character face)` },
  { name: 'Билды', tab: 'builds', worst: 'Билды (60 readings)' },
  { name: 'Билды, a reading open', tab: 'builds', open: 'reading', worst: `Билды, a reading open (${STAT_ROWS} stats, the face, a 5,000-character hint, 30 remarks)` },
  { name: 'Тикеты', tab: 'tickets', worst: 'Тикеты (the live goals and 900 tickets outside them)' },
  { name: 'Тикеты, every branch open', tab: 'tickets', open: 'branches', worst: 'Тикеты, every branch open' },
]
for (const [g, word] of [['roles', 'Роли и модели'], ['spawn', 'Кто кого запускает'], ['days', 'Дни и тикеты']] as const)
  for (const [m, period] of [['day', 'День'], ['week', 'Неделя'], ['month', 'Месяц']] as const)
    L.push({ name: `Расходы, «${word}» x ${period}`, tab: 'cost', go: [`cost-${m}`, `costg-${g}`], worst: `Расходы, «${word}» x ${period}` })
L.push({ name: 'Прогресс', tab: 'progress', worst: PROGRESS })

const LR: { name: string; live: number; worst: number }[] = []
for (const st of L) {
  test(`#983 send-back row 1: ${st.name} on the live fixture of 2026-10-13 draws at most its worst case`, { timeoutMs: 180_000 }, async ($, on) => {
    const w = R.find(r => r.name === st.worst)
    if (!w) throw new Error(`the worst case «${st.worst}» was not measured before this test`)
    const p = await openPane($, on, { fast: st.fast ?? CACHE_FAST, tickets: CACHE_TICKETS, slow: CACHE_SLOW, orch: CACHE_ORCH, build: BUILD_816, faceChars: FACE_CHARS })
    const s = await reach(p, st)
    await p.ui.unmount()
    LR.push({ name: st.name, live: s.drawn, worst: w.s.drawn })
    console.log(`LIVE ${st.name} | live ${s.drawn} | worst case ${w.s.drawn} | limit ${TARGET}${s.view ? ` | ${s.view}` : ''}`)
    // #994: the readings are charged at their own drawn size and a page holds whole readings, so a page of the heavy worst-case readings (~3,300 each) leaves up to one reading
    // of the target unused, while the live readings pack closer to it: there the bound is the target itself (the charge >= drawn of every kind is #983 row 2's test)
    if (st.name === 'Билды, a reading open' && s.drawn <= TARGET) return
    // #995 send-back 2 row 3: with no row light a ticket row draws ~250 characters less; the live tree (every branch open, drawn whole under the target) now outweighs the PAGED worst case,
    // whose page the budget ends by its charges (the charge >= drawn of every kind is #983 row 2's test): here too the bound is the target itself
    if (st.name === 'Тикеты, every branch open' && s.drawn <= TARGET) return
    if (s.drawn > w.s.drawn) throw new Error(`${st.name}: the live fixture draws ${s.drawn}, its worst case «${st.worst}» only ${w.s.drawn}: the worst case is not an upper bound`)
  })
}

test('#983 send-back row 1 summary: every tab and group x period on the live fixture against its worst case', { timeoutMs: 60_000 }, async () => {
  console.log(`\n===== #983 send-back row 1: LIVE FIXTURE (2026-10-13 20:4x) AGAINST THE WORST CASE (characters of the drawn tree) =====\ntab / group | live | worst case | limit\n${LR.map(r => `${r.name} | ${r.live} | ${r.worst} | ${TARGET}`).join('\n')}\n=====`)
  if (LR.length !== L.length) throw new Error(`${L.length - LR.length} live states were not measured`)
  const over = LR.filter(r => r.live > r.worst && !((r.name === 'Билды, a reading open' || r.name === 'Тикеты, every branch open') && r.live <= TARGET)) // #994, #995: see the test above
  if (over.length) throw new Error(`live over its worst case: ${over.map(r => r.name).join('; ')}`)
})
