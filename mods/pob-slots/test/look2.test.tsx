import { test } from 'claude-code/testing'
import { FAST, TICKETS } from './fixtures'
import { mountPane, bars, linkLabel } from './kit'

// #793 unit 6 (F14, F16): a ticket on Главная is drawn as on Тикеты (state icon, number, name); a state is icon + word.
const sub = (name: string, issue: number | null, busy: boolean, age = '5 min') =>
  ({ id: name, name, type: 'worker', issue, model: 'Sonnet 5.5', ctx: 50_000, age, busy, digest: busy ? 'Edit file_path=a.py' : undefined })
const ORCH_BUSY = { sid: 'o', name: 'orch Poe-Junkroan #3', kind: 'background', busy: true, issue: null, model: 'Sonnet 5.5', ctx: 120_000, age: '17 min', last: '',
  held: [{ number: 702, claimed: true, subagents: [] }], subagents: [sub('#702 unit 1', 702, true)] }
const tk = JSON.parse(TICKETS)
const like = Object.values(tk.issues)[0] as any
tk.issues['702'] = { ...like, n: 702, title: 'Ailments title', open: true, state: 'open', kids: [], parent: null, blockers: [] }
const fast = JSON.stringify({ ...JSON.parse(FAST), agents: [ORCH_BUSY] })

test('F14 + F16: an ORCH ticket row is state icon, then the number (drawn in the picture, a blank Button over it, #972), then the name; its state word is plain text (no icon, #837)', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { fast, tickets: JSON.stringify(tk) }, 123)
  const pic = (await bars(ui)).find((p: any) => p.alt.startsWith('#702 '))
  if (!pic) throw new Error('no ticket row')
  if ((pic.src.match(/>#702</g) ?? []).length !== 1) throw new Error('the number is drawn once inside the picture (#972: the Button over it is blank)')
  const nameX = Number(/<text x="([\d.]+)"[^>]*>Ailments title</.exec(pic.src)?.[1])
  const link = (await ui.findAll({ type: 'Button' })).find((l: any) => /^lk-ag\d+-#702$/.test(String(l.key ?? l.props?.key)))
  if (!link) throw new Error('no #702 Button lk-ag<n>-#702')
  if (!/^\s+$/.test(String((link as any).label ?? (link as any).props?.label))) throw new Error('the #702 Button is not blank')
  const issueIcon = (pic.src.match(/<g transform="translate\([^"]*\) scale\([^"]*\)" fill="/g) ?? []).length + (pic.src.match(/<use href="#i\d+"/g) ?? []).length // #771 A7: an icon drawn twice in the card is one def and a <use> each
  console.log(`name x ${nameX}, icons ${issueIcon}`)
  if (nameX !== 62) throw new Error('the name stands alone in the name column (#837 agents-child-tick: the number is in the тикет column): ' + nameX)
  if (!(Number(/<text x="([\d.]+)"[^>]*>#702</.exec(pic.src)?.[1]) > 300)) throw new Error('the number is not in the тикет column')
  if (issueIcon !== 1) throw new Error('state icon in the rail only, the state word is plain text as the baseline (#837 comparison 6116270633 row 4): ' + issueIcon)
})

test('F16: Progress tells a label state as icon + word (the Tickets legend icons)', async ($, on) => {
  // #927: a line with no ticket is not drawn, so the fixture gets one «не делаем» and one blocked ticket for the lines that carry an icon
  const tk2 = { ...tk, issues: { ...tk.issues, '703': { ...like, n: 703, open: true, state: 'open', labels: ['wontfix'], kids: [], parent: null, blockers: [] },
    '704': { ...like, n: 704, open: true, state: 'blocked', labels: [], kids: [], parent: null, blockers: [99999] } } }
  const ui = await mountPane($, on, 'desktop', { tickets: JSON.stringify(tk2) }, 123)
  await ui.press({ key: 'tab-progress' })
  const pic = (await bars(ui)).find((p: any) => /needs-triage/.test(p.src))
  if (!pic) throw new Error('no progress table')
  const icons = (pic.src.match(/<g transform="translate\([^"]*\) scale\([^"]*\)" (?:fill|stroke)/g) ?? []).length
  console.log(`progress icons ${icons}`)
  if (icons < 5) throw new Error('state words without icon: ' + icons)
})
