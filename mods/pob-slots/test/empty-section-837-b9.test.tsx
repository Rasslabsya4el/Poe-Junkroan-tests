import { test, expect } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, dq } from './kit'

// #837 round 9a (A5): a selected run with no builds drew the label «Билды #889» and nothing under it (r8/17_run2_open_z.png),
// and the `#889` stood about 1.5 px lower than the word «Билды». Wanted: under the label ONE placeholder row «пусто», the very
// placeholder row the card draws under «В очереди» when the queue is empty; the number's baseline is the word's baseline.
const v = JSON.parse(FAST)
const job = v.runs.running[0]
job.issue = 889
job.progress = { done: 0, total: 0, total_open: false, eta: null, cells: [] }
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }

test('#837 b9a A5: a selected run with zero builds draws the «пусто» row under its label; the number stands on the word\'s baseline', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(v) }, 123)
  const tree: any = await (ui as any).drawn()
  const svg: any[] = []
  walk(tree, n => { if (n.type === 'Svg' && /Билды #889/.test(String(n.props?.alt ?? ''))) svg.push(n) })
  expect(svg.length, 'the queue picture with the section').toBe(1)
  const src = dq(String(svg[0].props.source))
  const rows = src.split('<g transform="translate(0 ').slice(1)
  const at = rows.findIndex(r => /class="lb">Билды<\/text>/.test(r))
  expect(at, 'the label row').toBeGreaterThanOrEqual(0)
  // the row right under the label: the placeholder pill (a dot in the rail, the word «пусто» in the muted-faint class)
  const under = rows[at + 1] ?? ''
  console.log('under the label: ' + under.slice(0, 300))
  expect(/<text [^>]*class="fa">пусто<\/text>/.test(under), 'the row under the label says «пусто»').toBe(true)
  // the same placeholder as under «В очереди» (here the queue holds entries, so compare with an empty queue's: same cells, same shape)
  const label = rows[at]!
  const word = /<text x="[\d.]+" y="([\d.]+)" class="lb">Билды<\/text>/.exec(label)
  const num = /<text x="[\d.]+" y="([\d.]+)" class="lk">#889<\/text>/.exec(label)
  expect(word && num, 'the word and the number are drawn in the label row').toBeTruthy()
  console.log(`label baselines: word y ${word![1]}, number y ${num![1]}`)
  expect(Math.abs(+num![1]! - +word![1]!), 'the number stands on the word\'s baseline (picture px)').toBeLessThanOrEqual(0.5)
  await ui.unmount()
})
