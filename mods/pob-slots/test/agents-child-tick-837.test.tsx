import { test } from 'claude-code/testing'
import { FAST, TICKETS } from './fixtures'
import { mountPane, bars, dq } from './kit'

// #837 agents-child-tick: an ORCH child (ticket) row draws its #N in the тикет column, at the same x as a parent row's ticket,
// and the name column holds the title only (the baseline picture autopilot-s63-baseline-standing.png).
const sub = (name: string, issue: number | null, busy: boolean) =>
  ({ id: name, name, type: 'worker', issue, model: 'Sonnet 5.5', ctx: 50_000, age: '5 min', busy, digest: busy ? 'Edit file_path=a.py' : undefined })
const ORCH = { sid: 'o', name: 'orch Poe-Junkroan #3', kind: 'background', busy: true, issue: null, model: 'Sonnet 5.5', ctx: 120_000, age: '17 min', last: '',
  held: [{ number: 702, claimed: true, subagents: [] }, { number: 703, claimed: true, subagents: [] }], subagents: [sub('#702 unit 1', 702, true), sub('#703 unit 1', 703, true)] }
const SESSION = { sid: 's', name: 'autopilot', kind: 'interactive', busy: true, issue: 780, model: 'Opus 5.5', ctx: 100_000, age: '2 min', last: '', held: [], subagents: [] }
const tk = JSON.parse(TICKETS)
const like = Object.values(tk.issues)[0] as any
for (const n of [702, 703]) tk.issues[String(n)] = { ...like, n, title: `Title of ${n}`, open: true, state: 'open', kids: [], parent: null, blockers: [] }
const fast = JSON.stringify({ ...JSON.parse(FAST), agents: [SESSION, ORCH] })

test('#837: ORCH child rows draw #N in the тикет column (x of a parent row ticket), the name column has the title only', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { fast, tickets: JSON.stringify(tk) }, 123)
  const all = (await bars(ui)).map((p: any) => dq(String(p.src)))
  const tx = (src: string, re: RegExp) => [...src.matchAll(re)].map(m => Number(m[1]))
  const parent = all.flatMap(s => tx(s, /<text x="([\d.]+)"[^>]*>#780</g))
  if (parent.length !== 1) throw new Error('parent ticket text: ' + JSON.stringify(parent))
  const px = parent[0]!
  for (const n of [702, 703]) {
    const at = all.flatMap(src => tx(src, new RegExp(`<text x="([0-9.]+)"[^>]*>#${n}<`, 'g')))
    const title = all.flatMap(src => tx(src, new RegExp(`<text x="([0-9.]+)"[^>]*>Title of ${n}<`, 'g')))
    console.log(`#${n}: ticket x ${at}, parent x ${px}, title x ${title}`)
    if (at.length !== 1 || Math.abs(at[0]! - px) > 1) throw new Error(`#${n} not in the ticket column: ${at} vs ${px}`)
    if (title.length !== 1 || !(title[0]! < px - 20)) throw new Error(`#${n} title not in the name column: ${title}`)
  }
})
