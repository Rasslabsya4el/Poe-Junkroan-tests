import { test, expect } from 'claude-code/testing'
import { rowSvg } from '../hooks/kit'
import type { RowCol, RowSpec } from '../hooks/kit'
import { textWidth, PX } from '../hooks/draw'
import { dq } from './kit'

// #837 round 9 merge: two rules of rowBody share the free room between a plain text cell and the end-aligned text after it.
//   b9a A4: an end-aligned text may extend LEFT to the end of the cell drawn before it + 12 screen px (picture px x 1 / 0.9657).
//   b9b B3b: a plain text may extend RIGHT, past its column, up to 12 screen px (picture px x W / (W - 33.4)) before the end-aligned text.
// Wanted: the two together never overlap, whatever the two texts; the earlier cell's real end wins and the end-aligned text is fitted to what is left of it.
const W = 800
const COLS: RowCol[] = [
  { key: 'name', x: 40, w: 150 },
  { key: 'status', x: 190, w: 200 },
  { key: 'time', x: 390, w: 100, align: 'end' },
]
const texts = (svg: string) => [...dq(svg).matchAll(/<text x="([\d.]+)"([^>]*)class="([^"]*)"[^>]*>([^<]*)<\/text>/g)].map(m => ({ x: +m[1]!, end: /text-anchor="end"/.test(m[2]!), t: m[4]!.replace(/&amp;/g, '&') }))

test('#837 b9 merge: A4 (end text extends left) and B3b (plain text extends right) never overlap and keep 12 screen px apart wherever both could apply', () => {
  const stati = ['готово', 'группа «улучшения» 12 шаг', 'группа «улучшения» 12 шаг, проход 3, сборка снаряжения, ещё много слов', 'x'.repeat(120)]
  const times = ['3 мин', 'идёт 7 ч 52 мин', 'идёт 7 ч 52 мин, ещё слова', 'идёт 7 ч 52 мин, ещё слова, ещё слова, ещё слова, ещё слова']
  let pairs = 0, ext = 0, left = 0, tight = 0
  for (const status of stati) for (const time of times) {
    const r: RowSpec = { kind: 'strip', state: 'running', cells: { name: 'Build', status: status, time } }
    const { svg } = rowSvg(r, 0, COLS, W)
    const ts = texts(svg)
    const s = ts.find(x => !x.end && x.t.length > 0 && x.t !== 'Build')!
    const e = ts.find(x => x.end)!
    expect(s, `status drawn for «${status.slice(0, 20)}» / «${time.slice(0, 20)}»`).toBeTruthy()
    expect(e, `time drawn for «${status.slice(0, 20)}» / «${time.slice(0, 20)}»`).toBeTruthy()
    const sEnd = s.x + textWidth(s.t, PX)
    const eStart = e.x - textWidth(e.t, PX)
    pairs++
    if (sEnd > COLS[1]!.x + COLS[1]!.w + 0.5) ext++            // B3b ran the plain text past its column
    if (eStart < COLS[2]!.x - 0.5) left++                      // A4 ran the end text left of its column
    // never overlap; when the plain text runs past its column (B3b) the gap is >= 12 screen px, when the end text runs left of its column (A4) too
    expect(eStart - sEnd, `${pairs}: «${s.t}» ends ${sEnd.toFixed(1)}, «${e.t}» starts ${eStart.toFixed(1)}`).toBeGreaterThanOrEqual(0)
    if (sEnd > COLS[1]!.x + COLS[1]!.w + 0.5 || eStart < COLS[2]!.x - 0.5) {
      tight++
      expect(eStart - sEnd, `${pairs}: gap in screen px`).toBeGreaterThanOrEqual(11.5 / 0.9657 - 0.7)
    }
    // both rules at once never happen on one pair: a text that extends takes only the room the other one does not use
    expect(sEnd > COLS[1]!.x + COLS[1]!.w + 0.5 && eStart < COLS[2]!.x - 0.5, `${pairs}: both extended`).toBe(false)
  }
  console.log(`overlap sweep: ${pairs} pairs, B3b extended the plain text in ${ext}, A4 extended the end text in ${left}, ${tight} with a rule applied`)
  expect(ext, 'B3b is exercised').toBeGreaterThan(0)
  expect(left, 'A4 is exercised').toBeGreaterThan(0)
})

test('#837 b9 merge: the real end of the plain text (B3b) is what the end-aligned text (A4) is fitted to when a column lies between them', () => {
  // a middle column of a short text between the plain cell and the end-aligned one: A4 looks at the end of every earlier cell
  const cols: RowCol[] = [
    { key: 'name', x: 40, w: 120 },
    { key: 'status', x: 160, w: 120 },
    { key: 'gap', x: 280, w: 60 },
    { key: 'time', x: 340, w: 90, align: 'end' },
  ]
  for (const time of ['3 мин', 'идёт 7 ч 52 мин', 'идёт 7 ч 52 мин, ещё слова, ещё слова']) {
    const r: RowSpec = { kind: 'strip', state: 'running', cells: { name: 'Build', status: 'группа «улучшения» 12 шаг, проход 3', gap: '', time } }
    const ts = texts(rowSvg(r, 0, cols, W).svg)
    const s = ts.find(x => !x.end && x.t !== 'Build')!
    const e = ts.find(x => x.end)!
    expect(e.x - textWidth(e.t, PX) - (s.x + textWidth(s.t, PX)), `«${time}» after «${s.t}»`).toBeGreaterThanOrEqual(0)
  }
})
