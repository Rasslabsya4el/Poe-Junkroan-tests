import { test, expect } from 'claude-code/testing'
import { mountPane, dq } from './kit'
import { K } from '../hooks/tokens'
import { LIVE_FAST } from './fast-live'
import { LIVE as TODAY } from './tickets-live-20261011'

// #837 unit 12 (autopilot rule: a value that differs from the baseline 50ea5412 and is asked for by no quoted night-ticket row goes back).
// Kept on purpose: K.press, K.titleText, K.titleDim (new tokens, titles are the baseline's measured RGB), K.hoverVeil #4493f82e (the baseline's own
// table HOVER, register.tsx:1452 at 50ea5412; the 1f one at :2919 was the Builds callout Box, which no longer exists).
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
const texts = (src: string) => [...dq(src).matchAll(/<text [^>]*?x="([\d.]+)"[^>]*? y="([\d.]+)"([^>]*)>([^<]*)<\/text>/g)].map(m => ({ x: +m[1]!, y: +m[2]!, attrs: m[3]!, t: m[4]! }))
const sources = (root: any) => { const out: string[] = []; walk(root, n => { if (n.type === 'Svg') out.push(dq(String(n.props?.source ?? ''))) }); return out }
const mount = async ($: any, on: any, fast = LIVE_FAST) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast, tickets: TODAY }, 123)
  return { ui, root: await (ui as any).drawn() }
}

test('#837 u12 (1): a drawn `#N` is the host Link look: class lk, colour 108,165,233 (#6ca5e9), 14 px, weight 400 (u13: measured baseline glyph height 10, mean run 2.11 = 14 px 400)', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui, root } = await mount($, on)
  const srcs = sources(root)
  const tick = srcs.filter(s => texts(s).some(t => /^#\d+$/.test(t.t) && /class="lk"/.test(t.attrs)))
  console.log(`LINK pictures with a drawn #N: ${tick.length}`)
  expect(tick.length).toBeGreaterThan(0)
  for (const s of tick) expect(s).toContain('.lk{fill:#6ca5e9;font-size:14px;font-weight:400}')
  for (const s of srcs) for (const t of texts(s)) if (/^#\d+$/.test(t.t)) expect(t.attrs, '#N text not in the accent').not.toContain('#4493f8')
  await ui.unmount()
})

test('#837 u12 (2): a picture error is #f85149 (baseline .er), the native error text and Muted stay the baseline C.failed / C.muted', { timeoutMs: 60_000 }, async ($, on) => {
  const d = JSON.parse(LIVE_FAST)
  d.merge = { at: '2026-10-09T19:46:10', running: { branches: ['orch-677'], issues: [677], phase: 'suite', started: '2026-10-09T19:38:32', percent: 62, tests_done: 2647, tests_total: 4270, failed: 2, waiting: [], landed: [] } }
  const { ui, root } = await mount($, on, JSON.stringify(d))
  expect(K.failed).toBe('#f85149')
  expect(K.nfailed).toBe('#ff6961')
  expect(K.nmuted).toBe('#98989f')
  const srcs = sources(root)
  expect(srcs.some(s => /class="er"/.test(s) && s.includes('.er{fill:#f85149}')), 'an er text drawn').toBe(true)
  for (const s of srcs) expect(s, 'no picture carries the native error red').not.toContain('#ff6961')
  const cols = new Set<string>()
  walk(root, n => { if (n.type === 'Text' && typeof n.props?.color === 'string') cols.add(n.props.color.toLowerCase()) })
  expect(cols.has('#98989f'), 'native muted text').toBe(true)
  expect(cols.has('#9198a1'), 'no native text in the picture muted').toBe(false)
  await ui.unmount()
})

test('#837 u12 (3): empty-section placeholders are class fa', { timeoutMs: 60_000 }, async ($, on) => {
  const d = JSON.parse(LIVE_FAST)
  d.runs.running = []; d.runs.queued = []
  const { ui, root } = await mount($, on, JSON.stringify(d))
  const ts = sources(root).flatMap(texts)
  for (const w of ['ничего', 'пусто']) expect(ts.some(t => t.t === w && /class="fa"/.test(t.attrs)), `${w} drawn as fa`).toBe(true)
  for (const t of ts) if (t.t === 'ничего' || t.t === 'пусто') expect(t.attrs).not.toContain('class="mu"')
  await ui.unmount()
})

test('#837 u12 (4, 5) (b17): the Готово label and its count stand at y 15; the pager words are host Buttons, the picture draws none', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui: ui2, root: root2 } = await mount($, on)
  const lab = sources(root2).flatMap(texts)
  const g = lab.find(t => t.t === 'Готово'), cnt = lab.find(t => /\sиз\s/.test(t.t)), prev = lab.find(t => t.t === 'новее'), next = lab.find(t => t.t === 'старее')
  console.log(`LABELROW Готово y ${g?.y}, count y ${cnt?.y}, picture новее ${prev?.y}, picture старее ${next?.y}`)
  for (const t of [g, cnt]) { expect(t, 'drawn').toBeTruthy(); expect(t!.y).toBe(15) }
  expect(prev, 'no pager word in the picture').toBeUndefined(); expect(next, 'no pager word in the picture').toBeUndefined()
  await ui2.unmount()
})
