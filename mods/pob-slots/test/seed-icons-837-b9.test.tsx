import { test, expect } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, dq } from './kit'
import { textWidth } from '../hooks/draw'

// #837 round 9a (A2): in the «Билды <run>» section of an open run, the seed cells of rows whose seeds all wait were drawn
// «clock 4, bare 5, clock 6, lone clock»: the 2nd and 3rd icons stood one cell too far right (r8/13_run1_open_z.png).
// Every seed cell is its icon immediately left of its own number: the icon's x lies inside the cell
// (right of the previous number's end, left of its own number).
const v = JSON.parse(FAST)
const job = v.runs.running[0]
job.issue = 889
const cell = (ref: string, name: string, seed: number, state: string) => ({ ref, name, seed, state, class: 'Duelist', asc: 'Slayer', ...(state === 'done' ? { took: '52 min' } : {}) })
job.progress = { done: 0, total: 8, total_open: false, eta: null, cells: [
  cell('a', 'Aaa', 4, 'running'), cell('a', 'Aaa', 5, 'waiting'), cell('a', 'Aaa', 6, 'waiting'),
  cell('b', 'Bbb', 4, 'running'), cell('b', 'Bbb', 5, 'waiting'), cell('b', 'Bbb', 6, 'waiting'),
  cell('c', 'Ccc', 4, 'waiting'), cell('c', 'Ccc', 5, 'waiting'), cell('c', 'Ccc', 6, 'waiting'),
  cell('d', 'Ddd', 4, 'waiting'), cell('d', 'Ddd', 5, 'waiting'), cell('d', 'Ddd', 6, 'waiting'),
  cell('e', 'Eee', 4, 'waiting'),
] }
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }

test('#837 b9a A2: every seed cell stands its icon immediately left of its own number, in every row kind', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(v) }, 123)
  const tree: any = await (ui as any).drawn()
  const svg: any[] = []
  walk(tree, n => { if (n.type === 'Svg' && /Билд «/.test(String(n.props?.alt ?? ''))) svg.push(n) })
  expect(svg.length, 'one picture of the queue').toBe(1)
  const src = dq(String(svg[0].props.source))
  // SVG semantics: a <use href="#id"> reads the FIRST element of the document with that id; a row is a <g transform="translate(0 y)">
  const first = new Map<string, number>() // id -> the x its first element translates to
  for (const m of src.matchAll(/<(?:g|path) id="([^"]+)" transform="translate\(([-\d.]+) /g)) if (!first.has(m[1]!)) first.set(m[1]!, +m[2]!)
  const rows = src.split('<g transform="translate(0 ').slice(1).filter(r => />(?:Aaa|Bbb|Ccc|Ddd|Eee)<\/text>/.test(r) && /class="tx"[^>]*>\d+</.test(r))
  expect(rows.length, 'the strip rows').toBe(5)
  const seen: string[] = []
  rows.forEach((row, ri) => {
    const nums = [...row.matchAll(/<text x="([\d.]+)" y="[\d.]+" class="tx"(?: style="[^"]*")?>(\d+)<\/text>/g)].map(m => ({ x: +m[1]!, t: m[2]! }))
    // the icons of the seeds: an element with its own id, a <use> of one, or the running spinner (class "sp")
    const icons: number[] = []
    for (const m of row.matchAll(/<(?:g|path) (?:id="(m\w)" )?transform="translate\(([-\d.]+) [-\d.]+\) scale\((?:0\.8125|0\.5417)\)"[^>]*>(?:<g class="sp">)?|<use href="#(m\w)" x="([-\d.]+)"\/>/g)) {
      icons.push(m[3] ? first.get(m[3])! + +m[4]! : +m[2]!)
    }
    seen.push(`row ${ri}: numbers at ${nums.map(n => n.x).join(',')}, icons at ${icons.map(x => x.toFixed(1)).join(',')}`)
    expect(icons.length, `row ${ri}: one icon a seed`).toBe(nums.length)
    nums.forEach((n, k) => {
      const left = icons[k]!, right = left + 13
      const prevEnd = k ? nums[k - 1]!.x + textWidth(nums[k - 1]!.t, 14) : -Infinity
      expect(left, `row ${ri} seed ${n.t}: the icon starts right of the previous number`).toBeGreaterThanOrEqual(prevEnd)
      expect(right, `row ${ri} seed ${n.t}: the icon ends left of its own number`).toBeLessThanOrEqual(n.x + 0.01)
    })
  })
  console.log(seen.join(' | '))
  await ui.unmount()
})
