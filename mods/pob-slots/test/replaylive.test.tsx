import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen, bars } from './kit'

// #683 r5 (owner 10.10 02:1x): a RUNNING replay run. Its build being computed draws a bar of time so far against the
// run's median build time; a done square shows its main stat before -> after and says the full stats come at the end.
const v = JSON.parse(FAST)
const job = v.runs.running[0]
const now = Math.round(Date.now() / 1000)
job.progress = {
  done: 1, total: 2, total_open: false, eta: null, kind: 'replay', cells: [
    { ref: 'smite', name: 'Smite', seed: 4, state: 'done', took: '5.3 min', delta: '1,288,274 -> 1,381,385 (+7.23 %)' },
    { ref: 'spark', name: 'Spark', seed: 4, state: 'running', class: 'Witch', asc: 'Elementalist', started_est: now - 240, expect_s: 318 },
  ],
}
const fast = JSON.stringify(v)

test('desktop: running replay = a time bar on the build row, before -> after on a done square', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast }, 123)
  const words = (await seen(ui)).join(' | ')
  if (!/считается, обычно ~5\.3 min|считается, обычно ~5 мин/.test(words) && !words.includes('считается, обычно')) throw new Error('no time bar text: ' + words.slice(0, 400))
  await ui.press({ key: `cell-${job.id}-smite-4` })
  const after = (await seen(ui)).join(' | ')
  // #837 pass 2: the row says one word; the numbers stand in the picked build's panel only
  const strip = (await bars(ui)).find((x: any) => String(x.alt).startsWith('Билд «Smite»'))
  if (!strip || String(strip.alt).includes('->') || String(strip.alt).includes('%') || strip.src.includes('->')) throw new Error('row: ' + (strip && strip.alt))
  if (!after.includes('1,288,274 -> 1,381,385 (+7.23 %)') || !after.includes('когда ран закончится')) throw new Error('panel: ' + after.slice(-400))
})
