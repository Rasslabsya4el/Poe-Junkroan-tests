import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, bars } from './kit'
import { GRID } from '../hooks/tokens'

// #678 / #683 r4c: an opencode run is a subagent row of the ORCH that launched it, its sub-sessions one step
// deeper, same row, its own model; no "GPT" group anywhere. #683 r5: a step is an indent of 24 px (the rail mark and
// the pill move right): a subagent's mark is a dot at x 35 (step 1), a sub-session's a ring at x 59 (step 2).
const oc = (name: string, depth: number) => ({ name, type: 'opencode', issue: null, model: 'Terra 5.6', ctx: 230_000, age: '11 min', busy: true, depth, last: '' })
const AGENTS = [{
  sid: 'orch', name: 'orch Poe-Junkroan #621', kind: 'background', busy: true, issue: 621, held: [], model: 'Sonnet 5.5', ctx: 90_000, age: '40 min', last: '',
  subagents: [
    { name: 'worker #621', type: 'worker', issue: null, model: 'Sonnet 5.5', ctx: 50_000, age: '10 min', busy: true },
    oc('research merge pipeline practices', 1), oc('Research queue systems', 2), oc('Research affected tests', 2),
    oc('Research postmerge workflows', 2), oc('Research flaky test practices', 2),
  ],
}]
const fast = JSON.stringify({ ...JSON.parse(FAST), agents: AGENTS })
const NAMES = ['worker #621', 'research merge pipeline practices', 'Research queue systems']

for (const surface of ['terminal', 'desktop'] as const) {
  test(`${surface}: opencode strips under their ORCH`, async ($, on) => {
    const ui = await mountPane($, on, surface, { fast })
    let indent: (name: string) => number
    let models: number
    let all: string[]
    if (surface === 'desktop') {
      const pics = await bars(ui)
      all = pics.flatMap(p => [p.alt, p.src])
      // a row's step = where its rail mark stands: a filled dot one indent right 1, a ring two indents right 2
      indent = name => {
        const src = pics.find(p => p.alt.startsWith(`${name}:`))?.src ?? ''
        const c = (lvl: number) => GRID.rail / 2 + lvl * GRID.indent
        return src.includes(`<circle cx="${c(2)}" cy="10" r="2.8" fill="none"`) ? 2 : src.includes(`<circle cx="${c(1)}" cy="10" r="3.2"`) ? 1 : -1
      }
      models = pics.filter(p => p.src.includes('Terra 5.6')).length
    } else {
      const texts = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text))
      all = texts
      // the name carries two spaces per step
      indent = name => { const t = texts.find(x => x.trim() === name); return t ? (t.length - t.trimStart().length) / 2 : -1 }
      models = texts.filter(t => t === 'Terra 5.6').length
    }
    console.log(surface, JSON.stringify(NAMES.map(n => [n, indent(n)])))
    if (indent(NAMES[0]!) <= 0 || indent(NAMES[0]!) !== indent(NAMES[1]!)) throw new Error('research strip not at the subagent level')
    if (indent(NAMES[2]!) !== 2 * indent(NAMES[0]!)) throw new Error('sub-session not one step deeper')
    if (models !== 5) throw new Error('model: ' + models)
    if (all.some(t => /\bGPT\b/.test(t))) throw new Error('a GPT group appeared')
  })
}
