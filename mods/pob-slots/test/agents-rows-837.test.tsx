import { test } from 'claude-code/testing'
import { FAST, TICKETS } from './fixtures'
import { mountPane, dq, altLines } from './kit'
import { STATE_ICON } from '../hooks/kit'
import { K } from '../hooks/tokens'

// #837 unit 14 (autopilot comparison 6116270633, rows 3 and 4): the Agents card at the baseline 50ea5412.
//  row 3: session strips stand 26 px apart (the baseline's 4-px gap row is 0 cells in the host's layout: no gap row between sessions);
//  row 4: an ORCH ticket row's status is plain text (class tx / mu, no colour of its own), the row is not tinted by the ticket's state colour.
const sub = (name: string, issue: number | null, busy: boolean, age = '8 min') =>
  ({ id: name, name, type: 'worker', issue, model: 'Sonnet 5.5', ctx: 50_000, age, busy, digest: undefined })
const chat = (name: string) => ({ sid: name, name, kind: 'chat', busy: false, issue: null, model: 'Opus 5.5', ctx: 100_000, age: '5 min', last: '', held: [], subagents: [] })
const ORCH_A = { sid: 'o', name: 'orch Poe-Junkroan #3', kind: 'background', busy: true, issue: null, model: 'Sonnet 5.5', ctx: 120_000, age: '17 min', last: '',
  held: [{ number: 702, claimed: true }, { number: 703, claimed: true }, { number: 704 }], subagents: [sub('#703 unit 1', 703, false)] }
const tk = JSON.parse(TICKETS)
const like = Object.values(tk.issues)[0] as any
for (const n of [702, 703, 704]) tk.issues[String(n)] = { ...like, n, title: `Title ${n}`, open: true, state: n === 704 ? 'ready' : 'open', kids: [], parent: null, blockers: [] }
const fast = JSON.stringify({ ...JSON.parse(FAST), agents: [ORCH_A, chat('Brain: PoB'), chat('MODS')] })

const card = async (ui: any) => {
  const n = (await ui.findAll({ type: 'Svg' })).find((x: any) => /ORCH: /.test(String(x.props?.alt)))
  if (!n) throw new Error('no Agents picture')
  return { src: dq(String(n.props.source)), alt: altLines(n.props.alt) }
}

test('#837 u14 row 3: the Agents card is head + one 26-px pitch per row, no 4-px gap row between sessions', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { fast, tickets: JSON.stringify(tk) }, 123)
  const { src, alt } = await card(ui)
  const h = Number(/^<svg[^>]* height="([0-9.]+)"/.exec(src)?.[1])
  const rows = alt.filter(Boolean).length // ORCH, 2 ticket rows, 2 chats
  console.log(`agents picture h=${h}, rows ${rows}`)
  // #995 row 1: the head (22 px) and the two section labels «Чаты», «Фоновые сессии» (a queue's label row, 22 px each), then 26 px a session row
  const labels = (src.match(/class="lb">(Чаты|Фоновые сессии)</g) ?? []).length
  if (labels !== 2) throw new Error(`section labels: ${labels}`)
  if ((h - 22 - 2 * 22) % 26 !== 0) throw new Error(`pitch is not 26 px a row: h ${h}, rows ${rows}: (h - 66) mod 26 = ${(h - 66) % 26}`)
})

test('#837 u14 row 4: a ticket row status is plain text with no colour of its own and no state tint; a finished subagent gives the time cell', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { fast, tickets: JSON.stringify(tk) }, 123)
  const { src } = await card(ui)
  for (const w of ['взят, воркера пока нет', 'ещё не взят']) {
    const said = new RegExp(`<text[^>]*>${w}</text>`).exec(src)?.[0] ?? ''
    if (!said) throw new Error('no status text ' + w)
    if (/style=/.test(said)) throw new Error('status text carries its own colour: ' + said)
  }
  if (!/<text[^>]*>8 мин<\/text>/.test(src)) throw new Error('no time cell 8 мин on the ticket row with a finished subagent')
  const tint = STATE_ICON.ready[1]
  const n = src.split(`fill="${tint}" fill-opacity=".09"`).length - 1
  console.log(`pills tinted ${tint}: ${n}, K.idle ${K.idle}`)
  if (n) throw new Error('a waiting ticket row is tinted by the ticket state colour (baseline: K.idle)')
})
