import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen, bars } from './kit'

// #683 r5 (owner 10.10 02:5x): when the laptop drops off, its running run stays in PoB runs, drawn faded, and says
// since when the data is; collect.py marks such rows `stale` (merge_laptop). A fresh row is not faded.
test('desktop: a stale laptop run stays, faded, with the time of its last reading', async ($, on) => {
  const f = JSON.parse(FAST)
  const base = f.runs.queued[0]
  f.runs.running = [{ ...base, id: 'j-lap', tag: 'P1-#701-1', issue: 701, host: 'laptop', state: 'running', left_h: '14 min', stale: true, stale_since: '02:31' }]
  f.runs.queued = [{ ...base, id: 'j-pc', tag: 'P1-#553-9', issue: 553 }]
  f.laptop = { error: 'ssh timeout', offline: { seen: '02:31' } }
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 160)
  const all = (await seen(ui)).join(' | ')
  if (!all.includes('нет связи с ноутом, данные от 02:31')) throw new Error('no stale words: ' + all)
  if (all.includes('ещё ~14')) throw new Error('a stale row still shows a live estimate')
  const pics = await bars(ui)
  const stale = pics.find((p: any) => p.alt.startsWith('P1-#701-1 stale'))
  const fresh = pics.find((p: any) => p.alt.startsWith('P1-#553-9 queued'))
  if (!stale || !stale.src.includes('<g opacity=".45">')) throw new Error('the stale row is not faded')
  if (!fresh || fresh.src.includes('<g opacity=".45">')) throw new Error('a fresh row is faded')
})
