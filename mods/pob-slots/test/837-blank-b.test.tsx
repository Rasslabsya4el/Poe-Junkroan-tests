import { test, expect } from 'claude-code/testing'
import { mountPane } from './kit'
import { LIVE_FAST } from './fast-live'
import { kids, isOverlay, isBlank } from './layout'

// #837 variant B (cell rows) was replaced by the b1 probe (837-b1): a card's overlay column holds, per data row (a strip) or label row with a press,
// a keyed row Box `hv-row-<k>-<n>` whose first child is a spacer Svg of the row's own px height (no `height` in cells on the Box), and per run of
// the other rows ONE spacer Svg. Green: no overlay child is a Box with a `height` prop, every row Box starts with a spacer, and the column's total
// px is the card picture's height to the px (probe-837-b1.test.tsx reads the rest: the variants, the fill, the digit).
const walk = (n: any, f: (n: any, parent: any) => void, parent: any = null) => { if (n == null || typeof n !== 'object') return; f(n, parent); for (const c of n.children ?? []) walk(c, f, n) }

test('#837 b1: a press row is a Box holding a px-high spacer, no whole-cell height; the column total is the picture to the px', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
  const tree = await (ui as any).drawn()
  let overlays = 0, rowBoxes = 0
  walk(tree, (n, parent) => {
    if (!isOverlay(n)) return
    overlays++
    const pic = kids(parent).find((c: any) => c.type === 'Svg' && !isBlank(c))
    const picH = Number(/height=["']([\d.]+)["']/.exec(String(pic?.props?.source ?? ''))?.[1] ?? 0)
    let sum = 0
    for (const c of kids(n)) {
      if (c.type === 'Svg') { expect(isBlank(c), 'a spacer between rows').toBe(true); sum += c.props.height; continue }
      rowBoxes++
      expect(c.props?.height, 'a row Box has no height in cells').toBeUndefined()
      const sp = kids(c)[0]
      expect(isBlank(sp), 'a row Box starts with its spacer').toBe(true)
      sum += sp.props.height
    }
    console.log('B837', 'overlay children', kids(n).length, 'column px', sum, 'picture px', picH)
    // #837 b9a (B4): the PoB runs card's picture is padded (blank, bottom) to whole 19-px screen lines; the rows' spacers still sum to the rows, so the picture is taller by that pad (609.9 vs 604), under one line
    expect(picH - sum, 'the picture is the column total plus the B4 pad (0 up to one line)').toBeGreaterThanOrEqual(-0.005)
    expect(picH - sum).toBeLessThan(20)
  })
  expect(overlays).toBeGreaterThan(0)
  expect(rowBoxes).toBeGreaterThan(0)
  await ui.unmount()
})
