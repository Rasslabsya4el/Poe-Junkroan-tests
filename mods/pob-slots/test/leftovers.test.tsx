import { test } from 'claude-code/testing'
import { FAST, TICKETS } from './fixtures'
import { mountPane, bars } from './kit'
import { textWidth } from '../hooks/draw'

// #793 unit 7b (F07, F08): queued runs of one ticket lead with the field that differs; no run id in a cell.
const job = (id: string, tag: string, workers: number, wait: string) =>
  ({ id, tag, name: tag, issue: 12, priority: 'P1', host: 'pc', workers, state: 'queued', age: '5 min', date: '11.10', start: '', bench: false, dur: '5 min', wait: { kind: 'run', text: wait } })
const base = JSON.parse(FAST)
base.runs.queued = [job('q1', 'P1-#12', 3, 'ждёт P1-#12-2'), job('q2', 'P1-#12-2', 1, 'ждёт P1-#12-5, ещё')]
const fast = JSON.stringify(base)

test('F07 + F08: queued rows of one ticket say only what they wait for; a run tag in the reason is the ticket', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast, tickets: TICKETS }, 123)
  const rows = (await bars(ui)).filter((p: any) => / queued,/.test(p.alt))
  console.log(rows.map((p: any) => p.alt).join(' | '))
  if (rows.length < 2) throw new Error('queued rows: ' + rows.length)
  const text = (s: string) => [...s.replace(/<style>[\s\S]*?<\/style>/g, '').matchAll(/>([^<>]+)</g)].map(m => m[1]).join(' ')
  const t0 = text(rows[0].src), t1 = text(rows[1].src)
  if (!/ждёт #12/.test(t0)) throw new Error('F07 first row: ' + t0)
  if (!/ждёт #12/.test(t1)) throw new Error('F07 second row: ' + t1)
  if (/P\d-#\d+/.test(t0 + t1)) throw new Error('F08 run id left in a cell: ' + t0 + t1)
})

// #793 unit 7c (F26), moved by #837 unit 10 (autopilot's answer 6115205025, option (a): the baseline grid is back, the status text takes
// the room left and ends in an ellipsis; the baseline cut the reason too).
test('F26: a reason longer than the room ends in an ellipsis inside its column and never overlaps the time column', async ($, on) => {
  const one = JSON.parse(FAST)
  one.runs.queued = [{ ...job('q1', 'P1-#795', 2, 'ждёт P1-#795, слоты PC заняты тестами и одним replay'), issue: 795 }]
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(one), tickets: TICKETS }, 123)
  const row = (await bars(ui)).find((p: any) => / queued,/.test(p.alt))
  if (!row) throw new Error('no queued row')
  const words = [...row.src.replace(/<style>[\s\S]*?<\/style>/g, '').matchAll(/>([^<>]+)</g)].map((m: any) => m[1] as string)
  const reason = words.find((w: string) => /^ждёт #795/.test(w))
  const want = 'ждёт #795, слоты PC заняты тестами и одним replay'
  // #837 unit 11, autopilot comparison 00:08Z: the PoB runs card is on the baseline COLS (status x 622 as Merge's and Agents')
  // #837 b9b B3: the status may run on to 12 screen px (12 * 963 / 929.6 picture px) before the time text, which ends at the row's right edge less 12
  const actX = 552 + 70, timeStart = 963 - 12 - textWidth(words.find((w2: string) => /^ждёт \d/.test(w2)) ?? ''), timeX = timeStart - 12 * 963 / 929.6
  const w = Math.ceil(textWidth(want))
  console.log(`reason ${want.length} chars = ${w} px; room ${timeX - actX - 18} px; drawn: ${reason}`)
  if (w <= timeX - actX - 18) throw new Error(`the reason is no test of the width: ${w} px`)
  if (!reason || !reason.endsWith('…') || reason === want) throw new Error('the reason is not cut with an ellipsis: ' + JSON.stringify(reason))
  const x0 = Number(new RegExp(`<text x="([0-9.]+)"[^>]*>${reason.slice(0, 6)}`).exec(row.src)?.[1])
  if (!(x0 >= actX - 1) || x0 + textWidth(reason) > timeX) throw new Error(`the reason overlaps the time column: x ${x0}, width ${textWidth(reason)}`)
})

// #822 unit 1 (N3): a waiting row's ~60-char reason is drawn WHOLE, wrapped onto a second line (the `wrap` columns'
// behaviour); no cell of the PoB runs queue card ends in «…»; the `билды` column stays where it was (x 430, end 496; #837 unit 10: x 622, end 688; #837 unit 11, autopilot comparison 00:08Z: the baseline's x 552, end 618).
// #837 pass 2 (the N3 row of #822 is withdrawn; baseline 50ea5412): a waiting row is ONE line, 26 px, whatever its reason: no
// strip row wraps (the rail side of P5: `RowCol.wrap` is gone from the strip rows' kit), the reason is cut or dropped, never a
// second line; the `билды` column keeps its x (end 496; #837 unit 10: 688; #837 unit 11, autopilot comparison 00:08Z: 618).
test('N3 (#837 pass 2): a 60-char reason of a waiting row stays on ONE 26 px line; the билды column keeps its x', async ($, on) => {
  const one = JSON.parse(FAST)
  one.runs.queued = [{ ...job('q1', 'P1-#795', 2, 'ждёт P1-#795, слоты PC заняты тестами и ещё одним долгим запуском'), issue: 795 }]
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(one), tickets: TICKETS }, 123)
  const all = await bars(ui)
  const row = all.find((p: any) => / queued,/.test(p.alt))
  if (!row) throw new Error('no queued row')
  const ys = new Set([...row.src.replace(/<style>[\s\S]*?<\/style>/g, '').matchAll(/<text [^>]*? y="([\d.]+)"/g)].map((m: any) => m[1] as string))
  const head = all.find((p: any) => /билды/.test(p.src) && /статус/.test(p.src))
  const hx = Number(/<text x="([\d.]+)"[^>]*>билды</.exec(head?.src ?? '')?.[1])
  console.log(`N3: text lines at y ${JSON.stringify([...ys])}; билды x ${hx}; row height ${row.height}`)
  const yv = [...ys].map(Number)
  if (Math.max(...yv) - Math.min(...yv) > 1) throw new Error('the row has more than one text line: ' + JSON.stringify([...ys]))
  if (row.height !== 26) throw new Error('a waiting row is not one 26 px line: ' + row.height)
  // #837 unit 10 (6115205025): the baseline grid; #837 unit 11, autopilot comparison 00:08Z: the билды column x 552, end 618 (the status x 622 is Merge's)
  if (hx !== 618) throw new Error('билды column off the baseline grid: ' + hx)
})
