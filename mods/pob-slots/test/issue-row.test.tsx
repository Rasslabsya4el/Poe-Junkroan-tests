import { test, mock } from 'claude-code/testing'
// #683 r5 / #771: a row of «По тикетам» whose ticket is not in the Tickets payload (a closed ticket under no open goal)
// draws its title and its state icon from the numbers the collector put into the row itself.
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const TITLE = 'Row title that Tickets does not hold'

const drawnWeek = async ($: any, on: any, slow: string) => {
  const OUT: Record<string, string> = { fast: FAST, tickets: TICKETS, slow, orch: ORCH }
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  await ui.press({ key: 'cost-week' }); await clock.settle()
  await ui.press({ key: 'costg-days' }); await clock.settle() // #972: «По тикетам» is in the group «Дни и тикеты»
  const s = JSON.stringify(await ui.drawn())
  await ui.unmount()
  return s
}
const icons = (s: string) => (s.match(/scale\(/g) ?? []).length

const slowWith = (fields: object | null) => {
  const known = new Set(Object.keys(JSON.parse(TICKETS).issues))
  const slow = JSON.parse(SLOW)
  const row = slow.cost_week.cut.by_issue.find((x: any) => !known.has(String(x.number)))
  if (!row) throw new Error('the fixture week has no ticket absent from Tickets')
  if (fields) Object.assign(row, fields)
  return { text: JSON.stringify(slow), n: row.number as number }
}
let baseIcons = -1

test('desktop, Cost: the fixture week as it is (no title on the absent row): the icons drawn', async ($, on) => {
  const a = slowWith(null)
  const s = await drawnWeek($, on, a.text)
  if (s.replace(/\s+/g, '').includes(TITLE.replace(/\s+/g, ''))) throw new Error('the title drawn out of nowhere')
  baseIcons = icons(s)
})

test('desktop, Cost: a «По тикетам» row absent from Tickets draws the title and the state icon of its own row', async ($, on) => {
  const a = slowWith({ title: TITLE, open: false, reason: 'COMPLETED', state: 'closed' })
  const s = await drawnWeek($, on, a.text)
  if (!s.replace(/\s+/g, '').includes(TITLE.replace(/\s+/g, ''))) throw new Error(`#${a.n}: the name cell is empty`)
  if (baseIcons < 0 || icons(s) < baseIcons + 1) throw new Error(`#${a.n}: no state icon (${baseIcons} -> ${icons(s)})`)
})
