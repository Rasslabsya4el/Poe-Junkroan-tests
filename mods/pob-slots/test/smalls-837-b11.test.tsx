import { test, expect } from 'claude-code/testing'
import { FAST, TICKETS } from './fixtures'
import { dq } from './kit'
import { allPics, readPic, mountTab } from './pics-837-b9b'
import { rowSvg, STATE_WORD, STATE_ICON, LABEL_WORD, LABEL_ICON } from '../hooks/kit'

// #837 round 11, unit 1b: three small items.

// R3: the Agents card's activity text starts at one x, with an icon or without.
const sub = (name: string, issue: number | null, busy: boolean, age = '8 min') =>
  ({ id: name, name, type: 'worker', issue, model: 'Sonnet 5.5', ctx: 50_000, age, busy, digest: undefined })
const ORCH_A = { sid: 'o', name: 'orch Poe-Junkroan #3', kind: 'background', busy: true, issue: null, model: 'Sonnet 5.5', ctx: 120_000, age: '17 min', last: '',
  held: [{ number: 702, claimed: true }, { number: 704 }], subagents: [sub('#703 unit 1', 703, false)] }
const CHAT = { sid: 'c', name: 'Brain', kind: 'chat', busy: true, issue: null, model: 'Opus 5.5', ctx: 100_000, age: '5 min', last: '', held: [], subagents: [], digest: 'Read foo.py' }
const tk = JSON.parse(TICKETS)
const like = Object.values(tk.issues)[0] as any
for (const n of [702, 704]) tk.issues[String(n)] = { ...like, n, title: `Title ${n}`, open: true, state: n === 704 ? 'ready' : 'open', kids: [], parent: null, blockers: [] }

test('#837 b11 R3: an activity text with an icon («читает код») and one without («ещё не взят») start at the same x on the Agents card', { timeoutMs: 60_000 }, async ($, on) => {
  const fast = JSON.stringify({ ...JSON.parse(FAST), agents: [ORCH_A, CHAT] })
  const { ui } = await mountTab($, on, { fast, tickets: JSON.stringify(tk) }, null, 123)
  const pic = allPics(await (ui as any).drawn()).find(n => /ORCH: /.test(String(n.props?.alt)))
  expect(pic, 'the Agents picture').toBeTruthy()
  const items = readPic(pic, 123).items.filter(i => i.kind === 'text')
  const withIcon = items.find(i => i.t === 'читает код')
  const without = items.find(i => i.t === 'ещё не взят')
  console.log(`R3 x with icon ${withIcon?.x0.toFixed(2)} without ${without?.x0.toFixed(2)}`)
  expect(withIcon, 'the text with an icon').toBeTruthy()
  expect(without, 'the text without an icon').toBeTruthy()
  expect(Math.abs(withIcon!.x0 - without!.x0)).toBeLessThanOrEqual(0.5)
  await ui.unmount()
})

test('#837 b11 R3: rowSvg: a cell with `inset` and no icon starts where the cell with an icon does; a plain one still starts at its column', () => {
  const cols = [{ key: 'name', x: 0, w: 200 }, { key: 'act', x: 200, w: 200 }]
  const x = (cell: any) => {
    const svg = dq(rowSvg({ kind: 'strip', state: 'idle', cells: { name: 'n', act: cell } } as any, 0, cols, 420).svg)
    return +(/<text x="([\d.]+)"[^>]*>word<\/text>/.exec(svg)?.[1] ?? NaN)
  }
  const a = x({ t: 'word', icon: 'search.octicons' }), b = x({ t: 'word', inset: true }), c = x({ t: 'word' })
  console.log(`R3 rowSvg x: icon ${a} inset ${b} plain ${c}`)
  expect(Math.abs(a - b)).toBeLessThanOrEqual(0.5)
  expect(c).toBeLessThan(a)
})

// R4 (withdrawn by #995 row 4, the owner 14.10: «Резервы убираем»): there is no reserve row, so no minute Select
test('#837 b11 R4 / #995: no reserve Select on the main tab', { timeoutMs: 60_000 }, async ($, on) => {
  const base = JSON.parse(FAST)
  const daemon = { host: 'pc', age_s: 5, slots_total: 7, slots_in_use: 4, reserved: 0, reserved_until: null }
  const { ui } = await mountTab($, on, { fast: JSON.stringify({ ...base, runs: { ...base.runs, daemon } }) }, null, 123)
  expect(await ui.find({ type: 'Select', key: 'res-m-pc' } as any), 'the minutes Select').toBeFalsy()
  expect(await ui.find({ type: 'Select', key: 'res-n-pc' } as any), 'the slots Select').toBeFalsy()
  await ui.unmount()
})

// R5: one icon = one wording: a Прогресс row that carries an icon of the Тикеты legend says the legend's word.
test('#837 b11 R5: every icon drawn both in the Тикеты legend and in a Прогресс row has the same words', () => {
  const legend: (keyof typeof STATE_ICON)[] = ['work', 'owner', 'ready', 'blocked', 'open', 'triage', 'closed', 'dropped']
  const pairs: string[] = []
  const diff: string[] = []
  for (const [label, [ic]] of Object.entries(LABEL_ICON)) {
    for (const st of legend) {
      if (STATE_ICON[st][0] !== ic) continue
      pairs.push(`${ic}: legend «${STATE_WORD[st]}» / row «${LABEL_WORD[label]}»`)
      if (STATE_WORD[st] !== LABEL_WORD[label]) diff.push(`${label} (${ic}): «${LABEL_WORD[label]}» vs legend «${STATE_WORD[st]}»`)
    }
  }
  console.log('R5 pairs ' + pairs.join(' ; '))
  // the four states asked for agree; wontfix (the label) and not planned (the state) share the skip icon but are written by their GitHub names (#1079), so they are not paired; the other rows are reported, not pinned
  const named = ['needs-triage', 'ready-for-agent', 'ready-for-human', 'blocked']
  expect(diff.filter(d => named.some(n => d.startsWith(n + ' '))), 'wording differs').toEqual([])
  // the one designed difference (#1079): wontfix (the label) and not planned (the state) share the skip icon; the pin names both words
  expect(diff.filter(d => d.startsWith('wontfix ')), 'wontfix vs not planned').toEqual([`wontfix (${STATE_ICON.dropped[0]}): «wontfix» vs legend «not planned»`])
  expect(LABEL_WORD.wontfix).toBe('wontfix')
  expect(STATE_WORD.dropped).toBe('not planned')
  expect(LABEL_WORD.blocked).toBe('blocked')
})

test('#837 b11 R5: on the screen: the Прогресс row of the hourglass says what the Тикеты legend says', { timeoutMs: 60_000 }, async ($, on) => {
  const mk = (n: number, labels: string[], more: object = {}) => ({ n, title: `ticket ${n}`, open: true, reason: null, labels, parent: null, blockers: [], created: '2026-10-01T10:00:00Z', author: 'x', kids: [], state: 'open', ...more })
  const t = JSON.stringify({ ...JSON.parse(TICKETS), goals: [], loose: [],
    issues: Object.fromEntries([mk(1, ['needs-triage']), mk(2, ['ready-for-agent']), mk(3, ['ready-for-human']), mk(6, ['wayfinder:map']), mk(7, [], { blockers: [6] })].map(i => [String(i.n), i])) })
  const { ui: tabP } = await mountTab($, on, { tickets: t }, 'progress', 123)
  const prog = allPics(await (tabP as any).drawn()).find(n => n.props.width && /^По тикетам/.test(String(n.props.alt))) // #995 row 5: the ticket lines' table
  expect(prog, 'the Прогресс table').toBeTruthy()
  const words = readPic(prog, 123).items.filter(i => i.kind === 'text').map(i => i.t)
  for (const st of ['triage', 'ready', 'owner', 'blocked'] as const) expect(words, `Прогресс row of ${st}`).toContain(STATE_WORD[st])
  expect(words).not.toContain('заблокирован')
  await tabP.unmount()
})
