import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen, bars, svgWords, linkLabel } from './kit'

// #680 / #683 r4c: the Merge card, drawn from `agentops merge-status --json` (the collector adds the *_h human
// durations), as one queue: Идёт (the entry under test: its row with the failures and time left, a track whose knob
// counts the tests a / b) / В очереди (an amber numbered row: when it starts, how long it waits) / Готово (the last
// landings, one row per branch). Times in Russian.
const BUSY = {
  at: '2026-10-09T19:46:10',
  running: { branches: ['orch-677'], issues: [677], phase: 'suite', started: '2026-10-09T19:38:32', percent: 62,
    tests_done: 2647, tests_total: 4270, failed: 3, eta_s: 140, workers: 6, suite_out: 'x.out', eta_h: '2 min', elapsed_h: '7 min' },
  waiting: [{ branch: 'orch-621', issues: [621], position: 1, queued: '2026-10-09T19:40:01', waited_s: 369, eta_start_s: 140,
    waited_h: '6 min', eta_start_h: '2 min' }],
  landed: [{ branch: 'orch-674', issues: [674], queued_to_land_s: 302, rc: 0, took_h: '5 min' },
    { branch: 'orch-674', issues: [674], queued_to_land_s: 302, rc: 1, took_h: '4 min' }],
}
const fastWith = (merge: any) => JSON.stringify({ ...JSON.parse(FAST), merge })
// Owner 09.10 20:2x: no sentence in the card when the line is empty or the command is missing.
const PROSE = /пуста|ждёт repo|не в main|последний/
// The Merge card's words: from its title to the next card's.
const card = (all: string[]) => all.slice(all.indexOf('Merge'), all.indexOf('PoB runs'))

for (const surface of ['terminal', 'desktop'] as const) {
  test(`${surface}: merge card, a suite running, one waiter, one landing`, async ($, on) => {
    const ui = await mountPane($, on, surface, { fast: fastWith(BUSY) }, 123)
    const all = card(await seen(ui))
    const need = ['Merge', 'очередь: 1 идёт, 1 ждёт', '#677', '#621', '#674', 'упало 3, ещё ~2 мин', '2,647 / 4,270', '7 мин',
      'старт через ~2 мин', 'ждёт 6 мин', 'влит, с 2-й попытки', '5 мин']
    const miss = need.filter(n => !all.includes(n))
    if (miss.length) throw new Error('missing: ' + JSON.stringify(miss) + ' in ' + JSON.stringify(all))
    const i = (x: string) => all.indexOf(x)
    if (!(i('Идёт') < i('упало 3, ещё ~2 мин') && i('упало 3, ещё ~2 мин') < i('старт через ~2 мин') && i('старт через ~2 мин') < i('влит, с 2-й попытки'))) throw new Error('order')
    // One row per branch: the retried landing of orch-674 is an attempt, not a second row.
    if (all.filter(x => x === '#674').length !== 1) throw new Error('orch-674 twice')
    if (all.some(t => PROSE.test(t))) throw new Error('a sentence in the card')
    // One place per fact: #972: the ticket number is drawn in the row's picture and a blank Button `lk-mg<n>-#N` lies over it.
    if (surface === 'desktop') {
      const inPics = (await bars(ui)).filter(b => b.alt.startsWith('merge') || b.alt.includes('landed'))
      if (inPics.length !== 4) throw new Error('merge pictures: ' + inPics.map(b => b.alt).join(' | '))
      // #972: every ticket number drawn in a merge picture has its blank Button `lk-mg<n>-#N`
      const held = new Set((await ui.findAll({ type: 'Button' })).map((b: any) => /^lk-mg\d+-(#\d+)$/.exec(String(b.key ?? b.props?.key))?.[1]).filter(Boolean))
      const drawn = inPics.flatMap(b => svgWords(b.src).filter(w => /^#\d+$/.test(w)))
      if (!drawn.length || drawn.some(w => !held.has(w))) throw new Error('a ticket number inside a merge bar that no Button holds: ' + JSON.stringify([drawn, [...held]]))
    }
  })

  for (const [name, merge] of [['empty line', { at: 'x', running: null, waiting: [], landed: [] }], ['command missing', { missing: true }]] as const) {
    test(`${surface}: merge card, ${name}: nothing going, no rows`, async ($, on) => {
      const all = card(await seen(await mountPane($, on, surface, { fast: fastWith(merge) }, 123)))
      if (!all.includes('очередь: 0 идёт, 0 ждёт')) throw new Error('no empty count: ' + all.slice(0, 3).join(' | '))
      if (!all.includes('ничего') || !all.includes('пусто')) throw new Error('empty sections: ' + JSON.stringify(all))
      if (all.some(t => PROSE.test(t))) throw new Error('a sentence in the card')
      const rows = all.filter(t => /^влит|^упало|в очереди$/.test(t))
      if (rows.length) throw new Error('rows in an empty card: ' + JSON.stringify(rows))
    })
  }
}
