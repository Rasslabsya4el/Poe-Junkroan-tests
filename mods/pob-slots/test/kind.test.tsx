import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen } from './kit'

// #683 r5 (owner 10.10 02:3x): a benchmark run and a replay run must never read as one thing: each running row says
// what its run executes (collect.py `what`), before its estimate; a run of an unknown kind says only the estimate.
test('desktop: a running row names what its run executes', async ($, on) => {
  const f = JSON.parse(FAST)
  const base = f.runs.queued[0]
  f.runs.running = [
    { ...base, id: 'j-a', tag: 'P1-#604-3', issue: 604, state: 'running', what: 'benchmark', left_h: '2 h 29 min' },
    { ...base, id: 'j-b', tag: 'P1-#553-9', issue: 553, state: 'running', what: 'replay', left_h: '14 min' },
    { ...base, id: 'j-c', tag: 'P1-#620-1', issue: 620, state: 'running', what: 'tests' },
    { ...base, id: 'j-d', tag: 'P1-#641-1', issue: 641, state: 'running', what: '', left_h: '5 min' },
  ]
  f.runs.queued = []
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 160)
  const all = await seen(ui)
  for (const w of ['benchmark · ещё ~2 ч 29 мин', 'replay · ещё ~14 мин', 'тесты · оценки нет', 'ещё ~5 мин'])
    if (!all.includes(w)) throw new Error(`no «${w}» among: ${all.filter(x => x.includes('ещё') || x.includes('оценки')).join(' | ')}`)
})
