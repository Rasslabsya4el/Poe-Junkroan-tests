import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen } from './kit'

// #1089 unit 2 (the owner, 15.10: the Merge card hid the tickets of a batch and showed a ticket still open as «влит»):
// 1. a running batch of several tickets draws one running row per ticket (same phase, knob, elapsed; name = the ticket's title, tick = its #n);
// 2. a landed row (rc 0) of a ticket still open reads «влит в HH:MM, тикет открыт»; a closed ticket reads as before;
// 3. a ticket with `merge_lost` true (bin/collect.py, unit 1) gets a row in the waiting lane: name = its title, tick, act «merge lost» (class er), empty time.
// Drawn from the pane's words (seen) on both surfaces; the card is the words from its title to the next card's.

const GHOST = JSON.parse(FAST)
const ticket = (n: number, o: Record<string, unknown> = {}) => ({
  n, title: `Ticket title ${n}`, open: true, reason: null, labels: [] as string[], parent: null, blockers: [] as number[], kids: [] as number[],
  state: 'open', created: '2026-10-15T10:00:00Z', author: 'mod', parked_on_run: false, ...o,
})
const TICKETS = (issues: Record<string, any>) => JSON.stringify({ at: '18:00:00', goals: [], loose: [], issues })
const withMerge = (merge: any) => JSON.stringify({ ...GHOST, merge })
const card = (all: string[]) => all.slice(all.indexOf('Merge'), all.indexOf('PoB runs'))
const count = (all: string[], w: string) => all.filter(x => x === w).length

for (const surface of ['terminal', 'desktop'] as const) {
  // 1. one running batch of three tickets: three running rows, each with its own title and tick
  test(`${surface}: #1089 a running batch of three tickets draws one running row per ticket`, async ($, on) => {
    const merge = {
      at: '2026-10-15T18:00:00', waiting: [], landed: [],
      running: { branches: ['o1081', 'o1074e', 'o406'], issues: [1081, 1074, 406], phase: 'suite', started: '2026-10-15T17:30:00', percent: 50,
        tests_done: 2000, tests_total: 4000, failed: 0, eta_s: 300, workers: 2, suite_out: 'x.out', eta_h: '5 min', elapsed_h: '24 min' },
    }
    const ui = await mountPane($, on, surface, { fast: withMerge(merge), tickets: TICKETS({
      1081: ticket(1081), 1074: ticket(1074), 406: ticket(406),
    }) }, 123)
    const all = card(await seen(ui))
    const need = ['Ticket title 1081', 'Ticket title 1074', 'Ticket title 406', '#1081', '#1074', '#406']
    const miss = need.filter(n => !all.includes(n))
    if (miss.length) throw new Error('missing running names/ticks: ' + JSON.stringify(miss) + ' in ' + JSON.stringify(all))
    // same phase, knob and elapsed on every ticket's row: the act of each row reads the same
    if (count(all, 'тесты, ещё ~5 мин') !== 3) throw new Error('running rows not one per ticket: ' + count(all, 'тесты, ещё ~5 мин') + ' in ' + JSON.stringify(all))
    if (count(all, '24 мин') !== 3) throw new Error('elapsed not on every running row: ' + JSON.stringify(all))
  })

  // 2. landed rows: an open ticket says so, a closed ticket reads as before
  test(`${surface}: #1089 a landed row of an open ticket says «тикет открыт», a closed one does not`, async ($, on) => {
    const merge = {
      at: '2026-10-15T18:00:00', running: null, waiting: [],
      landed: [
        { branch: 'o1074', issues: [1074], queued_to_land_s: 302, rc: 0, landed: '2026-10-15T17:18:00', took_h: '5 min' },
        { branch: 'o1000', issues: [1000], queued_to_land_s: 302, rc: 0, landed: '2026-10-15T16:02:00', took_h: '4 min' },
      ],
    }
    const ui = await mountPane($, on, surface, { fast: withMerge(merge), tickets: TICKETS({
      1074: ticket(1074, { open: true }), 1000: ticket(1000, { open: false, state: 'closed', reason: 'COMPLETED' }),
    }) }, 123)
    const all = card(await seen(ui))
    if (!all.includes('влит в 17:18, тикет открыт')) throw new Error('open landed row not marked: ' + JSON.stringify(all))
    if (!all.includes('влит в 16:02')) throw new Error('closed landed row changed: ' + JSON.stringify(all))
    if (all.includes('влит в 16:02, тикет открыт')) throw new Error('closed ticket marked open')
  })

  // 3. a ticket whose merge is lost: a waiting-lane row, act «merge lost», empty time
  test(`${surface}: #1089 a ticket with merge_lost gets a waiting-lane row «merge lost»`, async ($, on) => {
    const merge = {
      at: '2026-10-15T18:00:00', running: null,
      waiting: [{ branch: 'orch-621', issues: [621], position: 1, queued: '2026-10-15T17:40:01', waited_s: 369, eta_start_s: 140, waited_h: '6 min', eta_start_h: '2 min' }],
      landed: [{ branch: 'orch-674', issues: [674], queued_to_land_s: 302, rc: 0, landed: '2026-10-15T17:50:00', took_h: '5 min' }],
    }
    const ui = await mountPane($, on, surface, { fast: withMerge(merge), tickets: TICKETS({
      621: ticket(621), 674: ticket(674),
      1074: ticket(1074, { open: true, merge_lost: true }),
    }) }, 123)
    const all = card(await seen(ui))
    if (!all.includes('merge lost')) throw new Error('no merge lost act: ' + JSON.stringify(all))
    if (!all.includes('Ticket title 1074') || !all.includes('#1074')) throw new Error('merge lost row without title or tick: ' + JSON.stringify(all))
    const i = (x: string) => all.indexOf(x)
    const landed = all.findIndex(x => x.startsWith('влит'))
    // the waiting lane: after the waiting entry, before the landings
    if (!(i('старт через ~2 мин') < i('merge lost') && i('merge lost') < landed)) throw new Error('merge lost not in the waiting lane: ' + JSON.stringify(all))
  })
}
