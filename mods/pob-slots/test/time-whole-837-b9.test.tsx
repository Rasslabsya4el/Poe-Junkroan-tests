import { test, expect, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { PROPS, ghostPress, dq } from './kit'
import { textWidth, PX } from '../hooks/draw'

// #837 round 9a (A4): on a LIVE run a build's row ended in «идёт 7 ч 52…» cut with an ellipsis although the row had free room left of it
// (r8/14_cell_open_z.png). Wanted: an ellipsis only when the text cannot stand between the end of the cell drawn before it + 12 screen px
// (picture px x 0.9657) and the pill's right padding.
const now = Math.round(Date.now() / 1000)
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }

test('#837 b9a A4: «идёт 7 ч 52 мин» is drawn whole in the row, 12 screen px or more right of the act text', async ($, on) => {
  const v = JSON.parse(FAST)
  const live = v.runs.running[0]
  live.issue = 889
  live.progress = { done: 0, total: 1, total_open: false, eta: null, cells: [
    { ref: 'wand', name: 'Wand', seed: 4, state: 'running', started: now - (7 * 3600 + 52 * 60), class: 'Shadow', asc: 'Trickster' },
  ] }
  const OUT: Record<string, string> = { fast: JSON.stringify(v), tickets: TICKETS, slow: SLOW, orch: ORCH }
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = ghostPress(true, await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) }))
  await ui.press({ key: 'tab-pob' }) // #983: the runs card lives on the tab «POB»
  await ui.press({ key: 'cell-' + live.id + '-wand-4' }); await clock.settle()
  const tree: any = await (ui as any).drawn()
  const svg: any[] = []
  walk(tree, n => { if (n.type === 'Svg' && /^Билды/m.test(String(n.props?.alt ?? ''))) svg.push(n) })
  expect(svg.length).toBe(1)
  const rows = dq(String(svg[0].props.source)).split('<g transform="translate(0 ').slice(1)
  const row = rows.find(r => /class="[a-z ]*">[^<]*идёт/.test(r))!
  expect(row, 'the row with the time').toBeTruthy()
  const texts = [...row.matchAll(/<text x="([\d.]+)"[^>]*class="[^"]*"[^>]*>([^<]*)<\/text>/g)].map(m => ({ x: +m[1]!, t: m[2]! }))
  const time = texts.find(t => /идёт/.test(t.t))!
  const act = texts.find(t => t.t === 'считается')!
  console.log('act: ' + JSON.stringify(act) + ' time: ' + JSON.stringify(time))
  expect(time.t, 'the time whole').toBe('идёт 7 ч 52 мин')
  expect(time.x - textWidth(time.t, PX), 'start of the time (end-anchored at x)').toBeGreaterThanOrEqual(act.x + textWidth(act.t, PX) + 12 / 0.9657 - 0.5)
  await ui.unmount()
})
