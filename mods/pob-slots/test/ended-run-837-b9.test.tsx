import { test, expect, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { PROPS, ghostPress, dq } from './kit'
import { ICONS } from '../hooks/kit'

// #837 round 9a (A3): a run that is NOT live computes nothing, yet its section said «2 считаются · 40 ждут», drew the spinner, the clock and the working
// texture, and a pressed seed read «считается» and «идёт 7 ч 52…» (r8/13_run1_open_z.png, r8/14_cell_open_z.png, the run P2-core stopped a day earlier).
// Wanted: a seed it never finished says the run's own end word («остановлен», as the «Готово» row writes it), carries the row's pause mark, no spinner, no clock,
// no texture, no «идёт»; the section's right text counts in those words; the finished seeds and a LIVE run are unchanged.
const now = Math.round(Date.now() / 1000)
const CELLS = [
  { ref: 'smite', name: 'Smite', seed: 4, state: 'done', took: '52 min', class: 'Duelist', asc: 'Slayer' },
  { ref: 'spark', name: 'Spark', seed: 4, state: 'running', took: '10:42', started: now - 28320, class: 'Witch', asc: 'Elementalist' },
  { ref: 'spark', name: 'Spark', seed: 5, state: 'waiting', class: 'Witch', asc: 'Elementalist' },
  { ref: 'spark', name: 'Spark', seed: 6, state: 'queued', class: 'Witch', asc: 'Elementalist' },
  { ref: 'wand', name: 'Wand', seed: 4, state: 'running', started: now - 28320, class: 'Shadow', asc: 'Trickster' },
]
const progress = { done: 1, total: 5, total_open: false, eta: null, cells: CELLS }
const BAD = /считается|считаются|ждут|ждёт|идёт/
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }

async function section($: any, on: any, state: string | null) {
  const v = JSON.parse(FAST)
  const live = v.runs.running[0]
  live.issue = 889
  let pressKey: string | null = null
  if (state) {
    live.progress = undefined
    const stopped = { ...live, id: 'j-stop-1', tag: 'P2-core', issue: null, state, progress: undefined, what: 'benchmark', rows_done: 1, rows_total: 5 }
    v.runs.history = [stopped, ...(v.runs.history ?? v.runs.recent ?? [])]
    pressKey = 'run-hist-j-stop-1'
  } else live.progress = progress
  const OUT: Record<string, string> = { fast: JSON.stringify(v), tickets: TICKETS, slow: SLOW, orch: ORCH, cells: JSON.stringify({ progress }) }
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = ghostPress(true, await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) }))
  await ui.press({ key: 'tab-pob' }) // #983: the runs card lives on the tab «POB»
  if (pressKey) { await ui.press({ key: pressKey }); await clock.settle() }
  const rows = async () => {
    const tree: any = await (ui as any).drawn()
    const svg: any[] = []
    walk(tree, n => { if (n.type === 'Svg' && /^Билды/m.test(String(n.props?.alt ?? ''))) svg.push(n) })
    expect(svg.length, 'the queue picture with the section').toBe(1)
    const src = dq(String(svg[0].props.source))
    const all = src.split('<g transform="translate(0 ').slice(1)
    const at = all.findIndex(r => /class="lb">Билды/.test(r))
    expect(at, 'the label row').toBeGreaterThanOrEqual(0)
    return { label: all[at]!, strips: all.slice(at + 1), defs: src.split('<g transform="translate(0 ')[0]!, src }
  }
  return { ui, rows, clock }
}

test('#837 b9a A3: a stopped run: no spinner / clock / texture / «идёт» in its section, the seeds say «остановлен», the counts say «остановлены»', async ($, on) => {
  const { ui, rows, clock } = await section($, on, 'stopped')
  const s = await rows()
  const text = (src: string) => [...src.matchAll(/<text [^>]*>([^<]*)<\/text>/g)].map(m => m[1]!)
  const labelWords = text(s.label)
  const wordsAll = s.strips.flatMap(text)
  console.log('label: ' + labelWords.join(' | '))
  console.log('strips: ' + wordsAll.join(' | '))
  const bad = [...labelWords, ...wordsAll].filter(w => BAD.test(w))
  expect(bad, 'no live word in the section').toEqual([])
  expect(s.strips.filter(r => /class="sp"/.test(r)).length, 'no spinner').toBe(0)
  const clockPath = ICONS['waiting.octicons']![1].match(/d="([^"]+)"/)![1]!.slice(0, 24)
  expect(s.src.includes(clockPath) && s.strips.some(r => r.includes(clockPath)), 'no clock icon in a strip').toBe(false)
  expect(s.strips.filter(r => /url\(#d\d*\)/.test(r)).length, 'no working texture').toBe(0)
  expect(labelWords.join(' '), 'the counts').toMatch(/1 готово/)
  expect(labelWords.join(' '), 'the counts').toMatch(/4 остановлены/)
  expect(wordsAll.filter(w => w === 'остановлен').length, 'the one-seed line says the run\'s end word').toBe(1)
  expect(wordsAll.some(w => /^3 остановлены/.test(w) || /3 остановлены/.test(w)), 'the 3-seed line counts in the end word').toBe(true)
  // a pressed seed: the end word, no «идёт»
  await ui.press({ key: 'cell-j-stop-1-wand-4' }); await clock.settle()
  const p = await rows()
  const pw = p.strips.flatMap(text)
  console.log('pressed: ' + pw.join(' | '))
  expect(pw.filter(w => BAD.test(w)), 'no live word after a press').toEqual([])
  expect(pw.includes('остановлен'), 'the pressed seed says the end word').toBe(true)
  await ui.unmount()
})

test('#837 b9a A3: a LIVE run is unchanged: it counts «считаются», «ждут», draws the spinner and «идёт»', async ($, on) => {
  const { ui, rows } = await section($, on, null)
  const s = await rows()
  const text = (src: string) => [...src.matchAll(/<text [^>]*>([^<]*)<\/text>/g)].map(m => m[1]!)
  const all = [...text(s.label), ...s.strips.flatMap(text)].join(' | ')
  console.log('live: ' + all)
  expect(all).toMatch(/считаются/)
  expect(all).toMatch(/2 ждут/)
  expect(all).not.toMatch(/остановлен/)
  expect(s.strips.filter(r => /class="sp"/.test(r)).length, 'the spinner').toBeGreaterThan(0)
  await ui.unmount()
})
