import { test, mock, expect } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { PROPS, dq } from './kit'

// #837 unit 2: the Progress tab's prog-labels card head is the baseline's (50ea5412): `<Card k name state={{t: total, cls: 'nm'}}>`, no
// iconName (no icon in the title picture) and no sub (the total is the state chip, class "nm", not the muted "su" word).
test('#837 u2: the prog-labels card head carries no icon and no sub, the total is the baseline state chip', async ($, on) => {
  const clock = mock.clock(on)
  const all: Record<string, string> = { fast: FAST, tickets: TICKETS, slow: SLOW, orch: ORCH }
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui: any = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) })
  await ui.press({ key: 'tab-progress' }); await clock.settle()
  const svgs: string[] = []
  const walk = (n: any) => { if (n && typeof n === 'object') { if (n.type === 'Svg') svgs.push(dq(String(n.props?.source ?? ''))); for (const c of n.children ?? []) walk(c) } }
  walk(await ui.drawn())
  await ui.unmount()
  // #995 row 5: the tab's two cards «По тикетам» and «Остальное» keep that head
  for (const name of ['По тикетам', 'Остальное']) {
    const head = svgs.find(s => s.includes(`class="ti">${name}<`))!
    const icon = /<g[^>]*transform="translate\([\d. ]+\) scale/.test(head)
    const su = /class="su"/.test(head), nm = /class="nm"/.test(head)
    console.log(`${name} head: icon ${icon}, class su ${su}, class nm ${nm}`)
    expect({ icon, su, nm }).toEqual({ icon: false, su: false, nm: true })
  }
})
