import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen, bars, svgWords, linkLabel, onTabs } from './kit'

// #683 r4c: the main tab = five cards (Agents, Merge, PoB runs, PC, Laptop: the approved mock's order), no header line
// or legend above them; every row is one picture of one width on one grid; a ticket number only as a native Link
// over its row (never inside a picture); the machine pictures as wide as the rows.
const sess = (name: string, busy: boolean, last: string, subagents: any[] = []) =>
  ({ sid: name, name, kind: 'interactive', busy, issue: null, held: [], model: 'Opus 5.5', ctx: 120_000, age: '10 min', last, subagents })
const AGENTS = [
  sess('MODS', true, 'Edit register.tsx', [
    { name: 'research opencode session api', type: 'opencode', issue: null, model: 'Luna 6', ctx: 200_000, age: '9 min', busy: true, depth: 1, last: 'websearch: opencode session api' },
  ]),
  { ...sess('orch Poe-Junkroan #681', true, 'Bash pytest -q'), held: [{ number: 681, claimed: true, subagents: [] }, { number: 684, claimed: false, subagents: [] }] },
  sess('Brain: PoB', false, 'idle line that must not show'),
]
const MERGE = {
  at: '2026-10-09T19:46:10',
  running: { branches: ['orch-677'], issues: [677], phase: 'suite', started: '2026-10-09T19:38:32', percent: 62,
    tests_done: 2647, tests_total: 4270, failed: 0, eta_s: 140, eta_h: '2 min', elapsed_h: '7 min' },
  waiting: [], landed: [],
}
const LAPTOP = { offline: { lost: '19:02', lost_ago: '1 h 10 min', cores: 8, slots_total: 3, running: [] } }
const fast = JSON.stringify({ ...JSON.parse(FAST), agents: AGENTS, merge: MERGE, laptop: LAPTOP })
// #983: four cards on «Главная», the runs card on the tab «POB» (read after them)
const CARDS = ['Agents', 'Merge', 'PC', 'Laptop', 'PoB runs']

for (const surface of ['terminal', 'desktop'] as const) {
  test(`${surface}: five cards, no header, rows carry the action`, async ($, on) => {
    const ui = await mountPane($, on, surface, { fast }, 123)
    // (the terminal indents a nested row's name: #683 r5)
    const all = (await onTabs(ui, ['main', 'pob'], seen)).map(t => (surface === 'terminal' ? t.trim() : t))
    const need = [...CARDS, 'MODS', 'ORCH', 'research opencode session api']
    const miss = need.filter(n => !all.includes(n))
    if (miss.length) throw new Error('missing: ' + JSON.stringify(miss))
    // #995 row 4 (the owner, 14.10: «Резервы убираем»): no reservation row on PC or Laptop
    if (all.some(t => /резерв|Зарезервировать/i.test(t))) throw new Error('a reservation word is drawn: ' + all.filter(t => /резерв/i.test(t)).join(' | '))
    // The laptop's link state on its title line: the picture's word (desktop) or `· offline` (terminal).
    if (!all.some(t => t === 'offline' || t === '· offline')) throw new Error('no offline word')
    const order = CARDS.map(c => all.indexOf(c))
    if (order.some((v, i) => i && v < order[i - 1]!)) throw new Error('card order ' + JSON.stringify(order))
    // No header line or legend (round 1), no raw last-action row (owner 09.10 20:5x), no words on an idle session.
    if (all.some(t => /JUNKROAN|agents busy|↳ /.test(t))) throw new Error('header or activity row is back')
    if (all.includes('idle line that must not show')) throw new Error('an idle session shows words')
    if (all.some(t => t === 'orch Poe-Junkroan #681')) throw new Error('raw ORCH session name')
    if (surface === 'desktop') {
      const pics = await onTabs(ui, ['main', 'pob'], bars)
      // One grid: at 123 columns the card's content is 960 px (09.10 21:5x, measured live): every picture is drawn
      // 4 px over (963) and placed without a width, so the desktop fits it to the slot and all end on one edge.
      // #683 r5 (0): a picture native Boxes line up with over many lines (a table, a detail head) is drawn 1:1
      // instead: its markup is 959 wide and its Svg carries that very width. #683 r5 (B): the squares of a run are
      // rows of the grid like every other (a label row, a strip per build), so nothing on this tab is 1:1 here.
      // #837 b1: a probe spacer of the PoB runs card (`<rect width='1'` of the tile colour, alt "row", width W) is no picture of the grid
      const exact = pics.filter(p => p.prop != null && !/^<svg[^>]*><rect width="1" height="[\d.]+" fill="#262628"\/><\/svg>$/.test(p.src))
      if (exact.some(p => p.width !== 959 || p.prop !== 959)) throw new Error(`1:1 pictures: ${exact.map(p => `${p.width}/${p.prop}`)}`)
      const sq = pics.filter(p => p.alt.startsWith('Билд'))
      if (sq.length < 2 || sq.some(p => p.prop != null)) throw new Error(`the squares are not rows of the grid: ${sq.map(p => `${p.alt} ${p.prop}`)}`)
      // #837 b15: the mask tier is the natural one, so a row's mask Svg (alt "row", no width prop) is no picture of the grid either
      const widths = new Set(pics.filter(p => p.prop == null && p.alt !== 'row').map(p => p.width))
      if (widths.size !== 1 || [...widths][0] !== 963) throw new Error(`widths at 123 cols: ${[...widths]}`)
      // The ORCH row: how many tickets it has in words (#683 r5: no segment bar, no 0/2), never a #N in a picture.
      const orch = pics.find(p => p.alt.startsWith('ORCH:'))
      if (!orch || !svgWords(orch.src).includes('2 тикета') || svgWords(orch.src).includes('0/2') || orch.src.includes('height="6" rx="1.5"')) throw new Error('ORCH row: ' + (orch && svgWords(orch.src).join(' | ')))
      // (#683 r5 (B): no exception: the squares' label row draws «Билды», its ticket is a native Link after the word)
      // (#972: a card row's ticket number is drawn in its row's picture and a blank Button `lk-<card><row>-#N` lies over it: a number in a picture is held by such a Button)
      const ghosts = new Set((await onTabs(ui, ['main', 'pob'], (u: any) => u.findAll({ type: 'Button' }))).map((b: any) => /^(?:lk|tl)-.*-#?(\d+)$/.exec(String(b.key ?? b.props?.key))?.[1]).filter(Boolean).map(n => `#${n}`))
      const numbered = pics.filter(p => svgWords(p.src).some(w => /#\d/.test(w) && !ghosts.has(w)))
      if (numbered.length) throw new Error('ticket number inside a picture: ' + numbered.map(p => p.alt).join(' | '))
      const lab = pics.find(p => /^Билды #\d+$/.test(p.alt))
      if (!lab || svgWords(lab.src)[0] !== 'Билды') throw new Error('the squares label: ' + (lab && svgWords(lab.src).join(' | ')))
      // The desktop stops redrawing a tree past ~100k characters (#613, #671).
      const sz = JSON.stringify(await (ui as any).drawn()).length
      console.log('SZ main tab', sz)
      if (sz >= 90_000) throw new Error('main tab ' + sz + ' chars')
    }
  })
}
