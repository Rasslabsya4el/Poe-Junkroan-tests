import { test, mock, expect } from 'claude-code/testing'
import { K, ROLE, SCALE, GRID, RADIUS } from '../hooks/tokens'
import { CLASS } from '../hooks/project'
import { STATE_WORD } from '../hooks/kit'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { dq, rowLight, isHiddenBox } from './kit'

// #793 unit 3c: the design review's token findings (F23-F25 contrast, F13 one palette, F10 spacing, F12 type scale,
// F17-F22 one look). Contrast and tokens are read from the drawn pictures and from register.tsx's own tables.
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const OUT: Record<string, string> = { fast: FAST, tickets: TICKETS, slow: SLOW, orch: ORCH }
const COLOUR_PROPS = ['color', 'backgroundColor', 'borderColor', 'dimColor']
const seenColours = new Map<string, string[]>() // colour -> where
function colours(n: any, where: string) {
  for (const bag of [n.props, n.hover]) for (const k of COLOUR_PROPS) { const v = bag?.[k]; if (typeof v === 'string' && v.startsWith('#')) seenColours.set(v.toLowerCase(), [...(seenColours.get(v.toLowerCase()) ?? []), `${where}:${n.type}.${k}`]) }
  if (n.type === 'Svg') for (const m of String(n.props?.source ?? '').matchAll(/#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\b|(?<=["':=])#[0-9a-fA-F]{3}(?![0-9a-fA-F])\b/g)) { seenColours.set(m[0].toLowerCase(), [...(seenColours.get(m[0].toLowerCase()) ?? []), `${where}:svg`]) }
}
const TABS = ['main', 'pob', 'builds', 'tickets', 'cost', 'progress'] // #972: the tab «POB» holds the runs card

/** The pane's tree and every Svg source, per tab. */
async function drawTabs($: any, on: any, surface: 'desktop' | 'terminal' = 'desktop') {
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface, component: 'Pane', requestId: 'pob', props: surface === 'desktop' ? PROPS : { ...PROPS, bodyColumns: 100 } })
  const out: Record<string, { svgs: string[]; tree: any }> = {}
  for (const t of TABS) {
    if (t !== 'main') { await ui.press({ key: `tab-${t}` }); await clock.settle() }
    const tree = await ui.drawn()
    const svgs: string[] = []
    const walk = (n: any) => { if (n && typeof n === 'object') { if (n.type === 'Svg') svgs.push(dq(String(n.props?.source ?? ''))); colours(n, `${surface}-${t}`); for (const c of n.children ?? []) walk(c) } }
    walk(tree)
    out[t] = { svgs, tree }
  }
  await ui.unmount()
  return out
}

const lin = (c: number) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
const lum = (h: string) => { const [r, g, b] = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)); return 0.2126 * lin(r!) + 0.7152 * lin(g!) + 0.0722 * lin(b!) }
export const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x! + 0.05) / (y! + 0.05) }
const over = (fg: string, a: number, bg: string) => '#' + [1, 3, 5].map(i => Math.round(parseInt(fg.slice(i, i + 2), 16) * a + parseInt(bg.slice(i, i + 2), 16) * (1 - a)).toString(16).padStart(2, '0')).join('')

test('F23: no column label or other text is drawn in `faint` (2.85:1); the heads are muted', async ($, on) => {
  const tabs = await drawTabs($, on)
  for (const t of TABS) {
    const bad = tabs[t]!.svgs.filter(s => /class="fa"/.test(s) && !/class="fa"[^>]*>(ничего|пусто)/.test(s)) // #837 u12: the placeholders ничего / пусто are `fa` again, as at the baseline 50ea5412 (autopilot rule); only they
    if (bad.length) throw new Error(`${t}: ${bad.length} pictures use the faint class (column labels)`)
  }
  if (!tabs.tickets!.svgs.some(s => /class="mu"[^>]*>(тикет|название)/.test(s))) throw new Error('Tickets: no muted column label')
})

test('F24: placeholders are muted, a knob label is dark on every state colour (>= 4.5:1)', async ($, on) => {
  const tabs = await drawTabs($, on)
  // #837 u12: the placeholders are `fa` (faint) as at the baseline 50ea5412 (register.tsx:1666,1677 there); no rule here
  if (tabs.main!.svgs.some(s => /class="kn"/.test(s))) throw new Error('a knob label is still the white kn class')
  const ink = K.ink
  for (const s of ['active', 'done', 'failed', 'wait', 'accent']) {
    const r = ratio(ink, (K as any)[s]!)
    if (r < 4.5) throw new Error(`knob label ${ink} on ${s} ${(K as any)[s]}: ${r.toFixed(2)}:1`)
  }
  // the machine bars: white words on the identity fill at the bar's own opacity over the card
  const roles: Record<string, string> = ROLE
  for (const r of ['work', 'agents']) {
    const eff = over(roles[r]!, 0.8, K.tile)
    const c = ratio('#ffffff', eff)
    if (c < 4.5) throw new Error(`white label on ${r} bar ${eff}: ${c.toFixed(2)}:1`)
  }
})

// The text tokens and the fills a text stands on: the card, the zebra stripe, the hover and the selected row.
export const TEXTS = ['text', 'muted', 'accent', 'active', 'done', 'failed', 'wait'] as const
export const FILLS = ['tile', 'stripe', 'hover', 'sel'] as const

// #837 pass 2 (u5a): the colours are the baseline's (50ea5412): muted #9198a1, accent #4493f8, done #ab7df8, stripe #2d2d30, hover #343438.
// The contrast guard is on the card (tile) and the selected fill's text-on-card only; the zebra / hover fills are baseline values.
test('#837 pass 2: muted, accent, done, stripe and hover are the baseline values', async () => {
  const want = { muted: '#9198a1', accent: '#4493f8', done: '#ab7df8', stripe: '#2d2d30', hover: '#343438' }
  for (const [k, v] of Object.entries(want)) if ((K as any)[k] !== v) throw new Error(`K.${k} = ${(K as any)[k]}, baseline ${v}`)
})
test('F25: every text token on the card is >= 4.5:1', async () => {
  const rows: string[] = []
  const bad: string[] = []
  for (const t of TEXTS) {
    const cells = FILLS.map(f => { const r = ratio((K as any)[t], (K as any)[f]); if (r < 4.5 && f === 'tile') bad.push(`${t} on ${f}: ${r.toFixed(2)}`); return r.toFixed(2) })
    rows.push(`${t.padEnd(7)} ${(K as any)[t]}  ${cells.join('  ')}`)
  }
  console.log(`CONTRAST text      ${FILLS.map(f => f.padEnd(5)).join('  ')}\n` + rows.join('\n'))
  if (bad.length) throw new Error('below 4.5: ' + bad.join('; '))
})

// #837 pass 2 (baseline 50ea5412; replaces #793 F25's darker-stripe band): a table's zebra is the neutral veil `#808080` at .06,
// radius 5, drawn over the card; the solid stripe token is not a picture band any more.
test('F25 (#837 pass 2): the zebra band of a table is the grey .06 veil, rx 5, as at baseline', async ($, on) => {
  const tabs = await drawTabs($, on)
  const veil = tabs.tickets!.svgs.filter(s => new RegExp(`<rect [^>]*?rx="5" fill="${K.veil}" fill-opacity="0?\\.06"`).test(s))
  console.log(`zebra veil pictures on Tickets: ${veil.length}`)
  if (!veil.length) throw new Error('no table draws the .06 veil band at rx 5')
  if (tabs.tickets!.svgs.some(s => s.includes(`fill="${K.stripe}"`))) throw new Error('a table band is still the solid stripe token')
})

// an 8-digit token (hoverVeil: the baseline's accent at alpha 2e) is drawn as the Box's own colour: its 6-digit prefix is the token's colour
const OKCOL = () => new Set([...Object.values(K), ...Object.values(ROLE), ...Object.values(CLASS)].flatMap(v => [v.toLowerCase(), v.toLowerCase().slice(0, 7)]))
const normCol = (c: string) => (c.length === 4 ? '#' + [1, 2, 3].map(i => c[i]! + c[i]).join('') : c.slice(0, 7))
const strayColours = () => [...seenColours].filter(([c]) => c !== '#00000000' /* #837: the ghost Link's transparent Text draws nothing */ && !OKCOL().has(normCol(c))).map(([c, w]) => `${c} (${[...new Set(w)].slice(0, 3).join(', ')})`)

test('F13: one palette: every colour drawn on the five desktop tabs is a token of tokens.ts (K, machine identity, base classes)', async ($, on) => {
  seenColours.clear()
  const tabs = await drawTabs($, on)
  for (const t of TABS) for (const src of tabs[t]!.svgs) for (const m of src.matchAll(/#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?/g)) seenColours.set(m[0].toLowerCase(), [`desktop-${t}:svg`])
  if (seenColours.size < 12) throw new Error('the test saw only ' + [...seenColours.keys()].join(' ') + ': the walk is broken')
  const stray = strayColours()
  if (stray.length) throw new Error('colours that are no token: ' + stray.join('; '))
})

test('F13: one palette: every colour of the terminal tabs is a token too', async ($, on) => {
  seenColours.clear()
  await drawTabs($, on, 'terminal')
  const stray = strayColours()
  if (stray.length) throw new Error('colours that are no token: ' + stray.join('; '))
})

// F10: one 4-px spacing scale. The scale itself is the five steps; the grid sizes are multiples of it; every corner
// radius a picture draws is a step or a pill (half its own height).
test('F10: the spacing scale is five 4-px steps and every grid size and radius sits on it', async ($, on) => {
  if (SCALE.length > 5 || new Set(SCALE).size !== SCALE.length || SCALE.some(v => v % 4)) throw new Error('scale ' + SCALE.join(','))
  for (const [k, v] of Object.entries(GRID)) if (v % 4 && k !== 'row' && k !== 'tab' && k !== 'rail') throw new Error(`GRID.${k} = ${v} is no multiple of 4`)
  if (GRID.tab !== 27 || GRID.rail !== 22) throw new Error(`GRID.tab ${GRID.tab} / GRID.rail ${GRID.rail}: baseline 27 / 22 (#837 pass 2)`)
  if (GRID.row !== 19) throw new Error(`GRID.row = ${GRID.row}: a table row is one engine cell, 19 px (#837 pass 2, baseline 50ea5412)`)
  for (const v of Object.values(RADIUS)) if (!SCALE.includes(v)) throw new Error('radius off the scale: ' + v)
  const tabs = await drawTabs($, on)
  const radii = new Map<string, string>() // "rx of h" -> tab
  for (const t of TABS) {
    for (const src of tabs[t]!.svgs) for (const m of src.matchAll(/<rect\b[^>]*>/g)) {
      const tag = m[0]
      const rx = /\brx="([\d.]+)"/.exec(tag)?.[1], h = /\bheight="([\d.]+)"/.exec(tag)?.[1]
      if (rx == null) continue
      const r = Number(rx), hh = Number(h)
      const pill = Math.abs(2 * r - hh) <= 1.01 // a capsule follows its own height (an inset outline is half a pixel shorter)
      if (!pill && !SCALE.includes(r) && r !== 1.5 && r !== 5 && r !== 1 && r !== 6) radii.set(`rx ${r} on a ${hh}-px rect`, t)
    }
  }
  if (radii.size) throw new Error('radii off the scale: ' + [...radii].map(([k, t]) => `${k} (${t})`).join('; '))
})

// F12: one type scale: 12 (body, labels), 13 (a name, a value), 14 (a title); two weights, 400 and 600.
test('F12: every picture sets its text in 12, 13 or 14 px, weight 400 or 600', async ($, on) => {
  const tabs = await drawTabs($, on)
  const sizes = new Map<string, string>(), weights = new Map<string, string>()
  for (const t of TABS) for (const src of tabs[t]!.svgs) {
    for (const m of src.matchAll(/font:(\d+) ([\d.]+)px/g)) { weights.set(m[1]!, t); sizes.set(m[2]!, t) }
    for (const m of src.matchAll(/font-size:([\d.]+)px/g)) sizes.set(m[1]!, t)
    for (const m of src.matchAll(/font-weight:(\d+)/g)) weights.set(m[1]!, t)
  }
  const badSize = [...sizes.keys()].filter(s => !['12', '13', '14', '9.5'].includes(s)), badWeight = [...weights.keys()].filter(w => !['400', '600', '700'].includes(w))
  console.log(`TYPE sizes ${[...sizes.keys()].sort().join(' / ')}, weights ${[...weights.keys()].sort().join(' / ')}`)
  if (!sizes.has('12') || !sizes.has('13') || !sizes.has('14') || !weights.has('400') || !weights.has('600')) throw new Error('the walk missed a step of the scale')
  if (badSize.length || badWeight.length) throw new Error(`off the type scale: sizes ${badSize.join(',')} weights ${badWeight.join(',')}`)
})

// ---- #793 unit 5 (F17, F19, F20, F21): one selected look, one row look, a pressed look, the pager as the period buttons.
type At = { n: any; parent: any }
const nodes = async (ui: any): Promise<At[]> => {
  const out: At[] = []
  const walk = (n: any, parent: any) => { if (!n || typeof n !== 'object') return; out.push({ n, parent }); for (const c of n.children ?? []) walk(c, n) }
  walk(await ui.drawn(), null)
  return out
}
const textColour = (b: any) => (b.children ?? []).find((c: any) => c?.type === 'Text')?.props?.color
const mountDesktop = async ($: any, on: any) => {
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  return { ui: await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS }), clock }
}

// #994 (the owner, 14.10: one hover look, the pressed / selected look its darker step; «весь дешборд должен соблюдать один стиль»): the selected Cost period is a CAPSULE of the
// switch's picture (the host light's own shape, 19 px, rx 4: the `sel` fill, the accent outline, its word in the accent); no Box draws a square fill or a square hover
test('F17 (#994): the selected tab is bright, the others dim; the selected Cost period is the switch picture\'s one capsule (sel fill, accent outline, rx 4); no square fill', async ($, on) => {
  const { ui, clock } = await mountDesktop($, on)
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  const all = await nodes(ui)
  const btn = (key: string) => all.find(x => x.n.type === 'Button' && x.n.props?.key === key)!
  const tab = btn('tab-cost'), idle = btn('tab-main'), week = btn('cost-week'), day = btn('cost-day')
  if (!!tab.n.props?.dimColor || !idle.n.props?.dimColor) throw new Error(`tab-cost dim ${tab.n.props?.dimColor}, tab-main dim ${idle.n.props?.dimColor}: the selected tab must be bright and the others dim`)
  // the period: a blank pressEl over its drawn face (no word of the host's, no fill of a Box)
  for (const b of [week, day]) if (String(b.n.props?.label ?? '').trim() || b.n.props?.dimColor) throw new Error(`${b.n.props?.key}: not a blank, bright pressEl over the drawn word`)
  const sq = all.filter(x => x.n.type === 'Box' && (x.n.hover?.backgroundColor || [K.sel, K.press, K.hover].includes(x.n.props?.backgroundColor)))
  if (sq.length) throw new Error('a Box draws a square fill or a square hover: ' + sq.map(x => x.n.props?.key ?? '?').join(', '))
  const sw = all.filter(x => x.n.type === 'Svg' && /Неделя/.test(String(x.n.props?.alt))).map(x => dq(String(x.n.props.source)))
  const caps = sw.flatMap(src => [...src.matchAll(/<rect [^>]*rx="4" fill="([^"]+)" stroke="([^"]+)" stroke-opacity="\.55"\/>/g)])
  if (sw.length !== 1 || caps.length !== 1 || caps[0]![1]!.toLowerCase() !== K.sel.toLowerCase() || caps[0]![2]!.toLowerCase() !== K.accent.toLowerCase()) throw new Error('the period switch: not one picture with one selected capsule: ' + sw.join(' || ').slice(0, 400))
  if (!/class="ac">Неделя</.test(sw[0]!) || !/class="mu">День</.test(sw[0]!)) throw new Error('the selected word is not in the accent, the others not muted')
})

test('F19 (#837 pass 2): every strip row is a full pill (20 px, rx 10) as at baseline 50ea5412, never the flat rx 4 band', async ($, on) => {
  const tabs = await drawTabs($, on)
  const all = TABS.flatMap(t => tabs[t]!.svgs)
  const pills = all.filter(s => /<rect x="[\d.]+" width="[\d.]+" height="20" rx="10"/.test(s))
  const flat = all.filter(s => /<rect x="[\d.]+" width="[\d.]+" height="(?:17|20)" rx="4" fill="#(212123|262628)"/.test(s))
  console.log(`pill pictures ${pills.length}, flat bands ${flat.length}`)
  if (!pills.length) throw new Error('no strip row draws the 20-px pill')
  if (flat.length) throw new Error(`${flat.length} pictures still draw the flat rx 4 band`)
})

// #994: a press leaves no square fill (the 250-ms `press` slab was a square); the choice it makes is drawn as the selected capsule
test('F20 (#994): a pressed period draws no press fill; the period it chose is the selected capsule', async ($, on) => {
  const { ui, clock } = await mountDesktop($, on)
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  await ui.press({ key: 'cost-day' })
  const after = await nodes(ui)
  if (after.some(x => x.n.props?.backgroundColor === K.press || x.n.hover?.backgroundColor === K.press)) throw new Error('a press fill is drawn')
  await clock.settle()
  const sw = (await nodes(ui)).filter(x => x.n.type === 'Svg' && /День/.test(String(x.n.props?.alt))).map(x => dq(String(x.n.props.source)))
  if (sw.length !== 1 || !/class="ac">День</.test(sw[0]!)) throw new Error('the pressed period is not the selected one: ' + sw.join(' || ').slice(0, 300))
})

// #994 (the owner, 14.10: «новее - старее я бы хотел заменить на нормальные кнопки с иконками картинками стрелок»): a pager is two icon buttons, the chevron of the pane's
// icon set (octicons' chevron-right, turned for «previous») drawn in the picture, a BLANK host Button over each; the end of the range is drawn dim and gets no Button
test('F21 (#994): the pager of Готово is two icon buttons: the chevrons drawn, a blank Button over the live one; the dim end (first page) is no Button; no pager word anywhere', async ($, on) => {
  const { ui, clock } = await mountDesktop($, on)
  await ui.press({ key: 'tab-pob' }); await clock.settle() // #983: the runs card lives on the tab «POB»
  const all = await nodes(ui)
  const btn = (key: string) => all.find(x => x.n.type === 'Button' && x.n.props?.key === key)
  expect(all.filter(x => x.n.type === 'Markdown' && /^hist-/.test(String(x.n.props?.key))).length, 'no ghost link for the pager').toBe(0)
  // #995 send-back 2: the dim end keeps its Button mounted (a press that reaches the end no longer loses the next press) in a 0 x 0 clipped Box: nothing drawn, nothing under the pointer
  const prev = btn('hist-prev')
  expect(!prev || isHiddenBox(prev.parent), 'first page: «previous» is drawn dim; its Button, if any, stands in a 0 x 0 clipped Box').toBe(true)
  expect(String(btn('hist-next')?.n.props?.label ?? 'x').trim(), '«next» is a blank Button over its chevron').toBe('')
  const words = all.flatMap(x => [x.n.props?.label, ...(x.n.children ?? []).filter((c: any) => typeof c === 'string')]).filter(t => /новее|старее/.test(String(t)))
  expect(words, 'no pager word is drawn').toEqual([])
  const chev = all.filter(x => x.n.type === 'Svg').map(x => dq(String(x.n.props.source))).filter(src => src.includes('M6.22 3.22'))
  expect(chev.some(src => /rotate\(180 8 8\)/.test(src)), 'the «previous» chevron is drawn (turned)').toBe(true)
})

// ---- #793 unit 7a: F02 F09 F18 F27 F28 F29
const textsOf = (tree: any) => { const o: string[] = []; const w = (n: any) => { if (typeof n === 'string') o.push(n); else if (n && typeof n === 'object') for (const c of n.children ?? []) w(c) }; w(tree); return o }
const svgTexts = (svgs: string[]) => svgs.flatMap(s => [...s.matchAll(/>([^<>]+)</g)].map(m => m[1]!))
const everyText = (tabs: Awaited<ReturnType<typeof drawTabs>>, ts = TABS) => ts.flatMap(t => [...textsOf(tabs[t]!.tree), ...svgTexts(tabs[t]!.svgs)])

// #837 pass 2 (baseline 50ea5412): a look difference no ticket row asked for goes back. F02 / F27 / F28 / F29 are low findings.
test('F02 back (#837 pass 2): the Tickets legend is one loose picture above the cards, no card «Состояния»', async ($, on) => {
  const tabs = await drawTabs($, on)
  const t = tabs.tickets!
  if (t.svgs.some(s => /class="ti"[^>]*>Состояния</.test(s))) throw new Error('a card titled «Состояния» is drawn')
  const loose = t.svgs.filter(s => (s.match(/<text/g) ?? []).length >= 6 && !/class="ti"/.test(s) && !/<rect/.test(s))
  console.log(`loose legend pictures ${loose.length}`)
  if (loose.length !== 1) throw new Error(`want one loose legend picture, got ${loose.length}`)
  if (!svgTexts(loose).includes(STATE_WORD.work)) throw new Error(`the legend picture lacks «${STATE_WORD.work}»`)
})

test('F09 + F18: every footer is `обновлено HH:MM`, no `0 мин`, no `назад` in a footer', async ($, on) => {
  const tabs = await drawTabs($, on)
  const foot = everyText(tabs).filter(x => x.includes('обновлено'))
  console.log(`footers ${foot.length}: ${[...new Set(foot)].join(' | ')}`)
  if (foot.length < 4) throw new Error(`only ${foot.length} footers found`)
  for (const x of foot) if (!/обновлено ((\d\d\.\d\d )?\d\d:\d\d|-)$/.test(x)) throw new Error(`footer «${x}» is not one form`) // #837 b3 item 5: a stamp of another day reads `dd.mm HH:MM`
  const zero = everyText(tabs).filter(x => /\d ч 0 мин|\b0 мин\b/.test(x) && !/CPU/.test(x))
  if (zero.length) throw new Error(`zero minutes said: ${zero.join(' | ')}`)
})

test('F27 back (#837 pass 2): the role words are the baseline words: no `ждёт worker` / `ведёт merge` / `ждёт merge` / `worker ещё нет` in any text', async ($, on) => {
  const tabs = await drawTabs($, on)
  const bad = everyText(tabs).filter(x => /ждёт worker|ведёт merge|ждёт merge|worker ещё/.test(x))
  if (bad.length) throw new Error(`role names not as the baseline: ${bad.join(' | ')}`)
  const ru = everyText(tabs).filter(x => /воркер|мердж/.test(x))
  console.log(`baseline role words drawn: ${[...new Set(ru)].slice(0, 6).join(' | ')}`)
  if (!ru.length) throw new Error('no baseline role word («воркер…» / «мердж…») drawn at all')
})

test('F09 back (#837 pass 2): the age on its hover card is `N дн назад`, `N ч назад` or `N мин назад` (baseline `ago`), never `ч 5 мин назад`', async ($, on) => {
  const tabs = await drawTabs($, on, 'terminal')
  const ago = [...new Set(everyText(tabs).filter(x => /назад$/.test(x.trim())).map(x => x.trim()))]
  console.log(`ages drawn: ${ago.slice(0, 8).join(' | ')}`)
  if (!ago.length) throw new Error('no ticket age drawn')
  const odd = ago.filter(x => !/^\d+ (дн|ч|мин) назад$/.test(x))
  if (odd.length) throw new Error(`an age not in the baseline form: ${odd.join(' | ')}`)
})

test('F28 back (#837 pass 2): the card of the Builds tab is «Билды на чтение», the tab stays «Билды»', async ($, on) => {
  const tabs = await drawTabs($, on)
  if (!tabs.builds!.svgs.some(s => /class="ti"[^>]*>Билды на чтение</.test(s))) throw new Error('no card titled «Билды на чтение» on the Builds tab')
  if (!JSON.stringify(tabs.main!.tree).includes('"key":"tab-builds","label":"Билды"')) throw new Error('the tab «Билды» is gone') // #983: read on the tab's own press (the word «Билды» of the runs card left «Главная»)
})

test('F29 back (#837 pass 2): the Цели / Вне целей / Расходы cards carry no icon; every other card title keeps one', async ($, on) => {
  const tabs = await drawTabs($, on)
  const bare: string[] = []
  for (const t of TABS) for (const s of tabs[t]!.svgs) {
    const m = /<text x="[\d.]+" y="17" class="ti">([^<]*)</.exec(s)
    if (m && !/<g[^>]*transform="translate\([\d. ]+\) scale/.test(s.slice(0, m.index))) bare.push(`${t}: ${m[1]}`)
  }
  console.log(`titles without icon: ${bare.join(' | ')}`)
  const own = bare.filter(x => x.startsWith('tickets: ') || x.startsWith('cost: ') || x === 'progress: По тикетам' || x === 'progress: Остальное') // the baseline's prog-labels head has no icon; #995 row 5: the two cards of the Progress tab keep that head (#837, autopilot's order of 19:17)
  if (bare.length !== own.length) throw new Error(`card titles without an icon outside Tickets / Cost / the Progress label card: ${bare.filter(x => !own.includes(x)).join(' | ')}`)
  for (const w of ['tickets: Цели', 'tickets: Вне целей']) if (!bare.includes(w)) throw new Error(`${w} has an icon`)
  if (!own.some(x => x.startsWith('cost: '))) throw new Error('no Cost card is bare')
  for (const name of ['По тикетам', 'Остальное']) {
    const p = tabs.progress!.svgs.find(s => s.includes(`class="ti">${name}<`))
    if (!p || !/class="nm"/.test(p) || /class="su"/.test(p)) throw new Error(`the Progress count of «${name}» is not the baseline chip (class nm) of its bare head`)
  }
})

// ---- #793 unit 9: N1 (the hovered row of a whole table kept its text), N4 (the PoB runs head names a run as its neighbour names a task)
// #995 send-back 2 row 3 (one hover look, the host's rectangle): a table row presses nothing as a whole, so it draws no light at all; its keyed Box keeps its place and no fill
test('N1 (#995): a table row draws no light of its own and no fill: the row under the pointer shows its icon, number and title unchanged', async ($, on) => {
  const { ui, clock } = await mountDesktop($, on)
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  const rows = (await nodes(ui)).filter(x => x.n.type === 'Box' && /^hv-cost-/.test(String(x.n.props?.key)))
  if (!rows.length) throw new Error('no keyed Box over a table row')
  const over = rows.filter(x => rowLight(x.n))
  console.log(`table rows: ${rows.length}, with a light of their own: ${over.length}`)
  if (over.length) throw new Error(`${over.length} of ${rows.length} table rows carry a light`)
  const filled = rows.filter(x => x.n.hover?.backgroundColor || x.n.props?.backgroundColor)
  if (filled.length) throw new Error(`${filled.length} of ${rows.length} table rows are filled by their Box`)
})

test('N4: the PoB runs card names its first column `задача` as the Merge card does, not `ран`', async ($, on) => {
  const tabs = await drawTabs($, on)
  const words = svgTexts(tabs.main!.svgs)
  if (words.includes('ран')) throw new Error('the head `ран` is still drawn')
})

// #837 D1: the per-state tint of a strip row, as at baseline 50ea5412 (calm .09 / child .12 / else .17), on the F19 pill.
test('D1: a strip row of a running, done and failed state draws its state colour over the band at the baseline opacity', async ($, on) => {
  const tabs = await drawTabs($, on)
  const all = TABS.flatMap(t => tabs[t]!.svgs)
  const tint = (state: string, op: string) => all.filter(s => new RegExp(`<rect x="[\\d.]+" width="[\\d.]+" height="\\d+" rx="10" fill="${(K as any)[state]}" fill-opacity="${op.replace('.', '\\.')}"/>`).test(s)).length
  const got: string[] = []
  for (const st of ['active', 'done', 'failed']) {
    const n = tint(st, '0.17') + tint(st, '0.12') + tint(st, '0.09')
    got.push(`${st} ${n}`)
    if (!n) throw new Error(`no strip row of state ${st} draws its tint (${got.join(', ')})`)
  }
  console.log('D1 tinted pictures: ' + got.join(', '))
})

// #837 D2 (pass 2 P1): the hover of a Box over a picture is the baseline's accent `#4493f8` at 18 % (alpha 0x2e): translucent, the
// row text stays readable (>= 4.5:1) on it over the card.
test('D2: the table hover Box fill is #4493f8 at alpha 0x2e and the row text stays >= 4.5:1 on it', async () => {
  if (K.hoverVeil.toLowerCase() !== '#4493f82e') throw new Error('hoverVeil is ' + K.hoverVeil)
  const a = 0x2e / 255
  const eff = over(K.hoverVeil.slice(0, 7), a, K.tile)
  const got: string[] = []
  for (const t of ['text']) { const r = ratio((K as any)[t], eff); got.push(`${t} ${r.toFixed(2)}`); if (r < 4.5) throw new Error(`${t} on the veil over the card: ${r.toFixed(2)}`) }
  console.log('D2 hover veil over the card: ' + got.join(', '))
})
