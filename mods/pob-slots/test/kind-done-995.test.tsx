import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen } from './kit'

// #995 send-back 1, defect 5 (the brain's pass of 14.10 on the installed 4adfc90f): the «Готово» row of #980 said only «готово» and its «билды» was
// empty. #980's two runs, as the store holds them: P1-#980 = `python scripts/legal_supports_stored_vs_fresh.py` (a command run_kind does not know:
// what '', kind_name «прочий прогон», no builds) and P1-#980-2 = `python scripts/search.py "Shrapnel Ballista" ...` (now what 'request', its `.out`
// counted by addon.py search_cells: 1 full build planned, 1 done). Each finished row names its kind; a run with builds shows `x / y`.
test('desktop: every «Готово» row names its kind; the search run of #980 shows 1 / 1 билд', async ($, on) => {
  const f = JSON.parse(FAST)
  const base = { ...f.runs.queued[0], state: 'done', host: 'pc', priority: 'P1', issue: 980, workers: 1 }
  f.runs.running = []; f.runs.queued = []
  f.runs.history = [
    { ...base, id: 'j-20261014-0049-37a3', tag: 'P1-#980-2', what: 'request', kind_name: 'билд по запросу', date: '14.10', start: '01:00', dur: '4 h 25 min', rows_done: 1, rows_total: 1 },
    { ...base, id: 'j-20261014-0049-6649', tag: 'P1-#980', what: '', kind_name: 'прочий прогон', date: '14.10', start: '00:49', dur: '32 min' },
  ]
  const words = await seen(await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 160))
  const all = words.join(' | ')
  console.log('#980 rows: ' + words.filter(w => /прогон|запросу|билд|готово|\d \/ \d/.test(w)).map(w => `«${w}»`).join(' '))
  for (const need of ['билд по запросу · готово', 'прочий прогон · готово', '1 / 1 билд'])
    if (!all.includes(need)) throw new Error(`missing «${need}» in ${all}`)
  // the drawn «билды» cell of the search run (not only its alt): exactly one `x / y` text, `1 / 1`; the run without builds draws none
  const counts = words.filter(w => /^\d+ \/ \d+\+?$/.test(w.trim()))
  if (counts.length !== 1 || counts[0]!.trim() !== '1 / 1') throw new Error('drawn build counts: ' + JSON.stringify(counts))
  if (words.some(w => w.trim() === 'готово')) throw new Error('a «Готово» row says only «готово»: ' + all)
})
