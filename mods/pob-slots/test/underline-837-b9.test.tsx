import { test, expect } from 'claude-code/testing'
import { ghostSpan, drawnW, NBSP_PX, BLANK_PX, GHOST_INSET, PX_PER_COL } from '../hooks/kit'
import { seedW } from '../hooks/addon'

// #837 b9 A8 (picture 12_home_hover2, real pane at 123 columns, fit 930 / 963): the ghost link's underline was wider than its text. Measured: "P2-core" is 38.5 px wide, its underline 61 px
// (22 no-break spaces = 2.77 px each, NBSP_PX); the long title 231 px, underline 274 px (99 spaces = 2.77 px each); both starting ~6 px left of the first letter: the underline starts GHOST_INSET
// px left of its Box's cell edge, and the old count came from `textWidth`, which draws "P2-core" 53 px and the title 269 px wide against the 38.5 / 231 the host draws. A Box stands on whole cells
// of 7.8 px, so the start can only be the nearest edge (at most half a cell off); the end is matched by the count.
const FIT = 930 / 963
// #972: the span is a pressEl's blank label (em spaces of BLANK_PX each): the host's light rectangle on it, no underline
const span = (x: number, w: number, e = 3) => { const { L, n } = ghostSpan(x, w, FIT, e); const start = (L + e) * PX_PER_COL - GHOST_INSET; return { n, start, end: start + n * BLANK_PX } }
const CASES = [
  { what: 'P2-core', x: 38, w: drawnW('P2-core'), realW: 38.5 },
  { what: 'the long title', x: 38, w: drawnW('A pinned run the PC moves to the laptop a…'), realW: 231 },
  { what: 'the pager word', x: 905, w: drawnW('старее'), realW: 36.5, e: 0 },
  { what: 'a 1-digit seed cell', x: 300 - 17, w: seedW('6') + 22, realW: (seedW('6') + 22) * FIT },
]
test('#837 b9 A8: the constants of the real pane: 2.77 px a no-break space, the 22 / 99 counts of the old code gave 61 / 274 px', () => {
  expect(Math.abs(NBSP_PX - 2.77)).toBeLessThan(0.01)
  expect(Math.abs(61 / 22 - NBSP_PX)).toBeLessThan(0.02)
  expect(Math.abs(274 / 99 - NBSP_PX)).toBeLessThan(0.02)
})
test('#837 b9 A8 / #972: the blank label starts within half a cell (3.9 px) of the first px and ends no further than one blank (BLANK_PX) past the last px; at least 2 blanks', () => {
  for (const c of CASES) {
    const e = (c as any).e ?? 3
    const t0 = c.x * FIT, t1 = t0 + c.realW
    const s = span(c.x, c.w, e)
    console.log(`A8 ${c.what}: n ${s.n}, underline ${s.start.toFixed(1)}..${s.end.toFixed(1)}, text ${t0.toFixed(1)}..${t1.toFixed(1)}: start ${(s.start - t0).toFixed(1)} px, end ${(s.end - t1).toFixed(1)} px`)
    expect(s.n, c.what).toBeGreaterThanOrEqual(2)
    expect(Math.abs(s.start - t0), `${c.what}: start`).toBeLessThanOrEqual(PX_PER_COL / 2 + 0.7)
    expect(s.end - t1, `${c.what}: the underline does not stop inside the text`).toBeGreaterThanOrEqual(-3)
    expect(s.end - t1, `${c.what}: end residual`).toBeLessThanOrEqual(BLANK_PX)
  }
  expect(ghostSpan(0, 1, FIT, 0).n, 'a one-px span still gets 2 blanks').toBe(2)
})
