import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen, svgWords, svgRows, dq, onTabs } from './kit'

// #793 unit 3b: the owner's standing rules R1-R5 on the monitor (findings D3, F01, F04, F05; F03 and F06 are in
// builds.test.tsx). A card is a title and a table, its title keeps a count only, no white-filled control, every
// card's table has muted column heads.
const base = () => JSON.parse(FAST)
const MERGE = { at: '2026-10-09T19:46:10', running: { branches: ['orch-677'], issues: [677], phase: 'suite', started: '2026-10-09T19:38:32', percent: 62,
  tests_done: 2647, tests_total: 4270, failed: 0, eta_s: 140, workers: 6, suite_out: 'x.out', eta_h: '2 min', elapsed_h: '7 min' },
  waiting: [{ branch: 'orch-621', issues: [621], position: 1, queued: '2026-10-09T19:40:01', waited_s: 369, eta_start_s: 140, waited_h: '6 min', eta_start_h: '2 min' }],
  landed: [], queue_end_h: '9 min', queue_until: '01:44' }
const draw = async ($: any, on: any, f: any) => mountPane($, on, 'desktop', { fast: JSON.stringify(f) }, 123)
const walkAll = async (ui: any) => { const out: any[] = []; const w = (n: any) => { if (n && typeof n === 'object') { out.push(n); for (const c of n.children ?? []) w(c) } }; w(await ui.drawn()); return out }

test('D3: the PoB runs card of a run with no builds carries no generated sentence', async ($, on) => {
  const f = base()
  delete f.runs.running[0].progress
  f.runs.running[0].what = 'replay'
  const ui = await draw($, on, f)
  const words = await seen(ui)
  const bad = words.filter(t => /нет билдов|не benchmark|читаю квадраты|не начался|прогон тестов|папка рана/.test(t))
  if (bad.length) throw new Error('a sentence in the PoB runs card: ' + bad.join(' | '))
  await ui.unmount()
})

test('F01: no control is drawn with the white `primary` fill; every control is a plain Button (the host draws its label; no child Text, #972)', async ($, on) => {
  const ui = await draw($, on, base())
  const all = await walkAll(ui)
  const prim = all.filter(n => n.type === 'Button' && n.props?.variant === 'primary')
  if (prim.length) throw new Error('primary buttons: ' + prim.map(b => b.props.label).join(' | '))
  // #995 row 4: the reserve control is gone (the owner, 14.10: «Резервы убираем»); every Button left is plain
  if (all.some(n => n.type === 'Button' && /^res-/.test(String(n.props?.key)))) throw new Error('a reserve control is drawn')
  if (all.some(n => n.type === 'Select')) throw new Error('a Select is drawn (the reserve form)')
  const notPlain = all.filter(n => n.type === 'Button' && !n.props?.plain)
  if (notPlain.length) throw new Error('a Button that is not plain: ' + notPlain.map(b => b.props.key).join(' | '))
  await ui.unmount()
})

test('F04: Agents, Merge, PoB runs, PC and Laptop have muted column heads', async ($, on) => {
  const f = base()
  f.merge = MERGE
  const ui = await draw($, on, f)
  // #771: a run of rows is one picture; svgRows cuts it into its rows, a head row read as its own
  const sources = await onTabs(ui, ['main', 'pob'], async u => (await svgRows(u)).map(r => dq(String(r.props?.source ?? '')))) // #983: the runs card is on «POB»
  const heads = (cells: string[]) => sources.filter(s => svgWords(s).join('|') === cells.join('|') && /class="mu"/.test(s)).length
  const need: [string, string[], number][] = [
    ['Agents', ['сессия', 'тикет', 'модель', 'контекст', 'делает', 'длительность'], 1],
    ['Merge', ['задача', 'тикет', 'статус', 'длительность'], 1], // #995 row 2: no «ветка» column
    ['PoB runs', ['задача', 'тикет', 'приоритет, слоты', 'билды', 'статус', 'начало', 'длительность'], 1], // #995 send-back 1 (defect 5): a finished run's date-time under its own head
  ]
  for (const [card, cells, n] of need) if (heads(cells) < n) throw new Error(`${card}: no muted head row ${cells.join(' | ')}`)
  const machine = sources.filter(s => /ресурс/.test(s) && /занято/.test(s) && /сейчас/.test(s) && /class="mu"/.test(s)).length
  if (machine < 1) throw new Error('the machine cards have no column heads')
  await ui.unmount()
})

test("F05: restored to the baseline by #837 unit 11b (the autopilot's comparison 00:08Z: F05 is an agent finding, not the owner's word): the head line is `очередь: N идёт, M ждёт · вся ~X, до HH:MM`, the `В очереди` row has no total", async ($, on) => {
  const f = base()
  f.merge = MERGE
  f.runs.queue_end_h = '7 min'; f.runs.queue_until = '01:44'
  const ui = await draw($, on, f)
  const words = await onTabs(ui, ['main', 'pob'], seen) // #983: Merge on «Главная», the runs card on «POB»
  const heads = words.filter(t => /^очередь: \d+ идёт, \d+ ждёт/.test(t))
  const total = (h: string) => heads.some(t => / · вся ~/.test(t) && t.includes(h))
  if (heads.length < 2 || !total('вся ~9 мин, до 01:44') || !total('вся ~7 мин, до 01:44')) throw new Error('head lines: ' + heads.join(' | ') + ' // ' + words.filter(t => /вся|очередь/.test(t)).join(' | '))
  const row = words.filter(t => /^вся( ~|\s)/.test(t) || /^вся не меньше/.test(t))
  if (row.length) throw new Error('a total on the `В очереди` row: ' + row.join(' | '))
  await ui.unmount()
})
