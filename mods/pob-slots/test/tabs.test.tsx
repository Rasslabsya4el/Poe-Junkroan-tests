import { test } from 'claude-code/testing'
import { mountPane, dq } from './kit'
import { GRID } from '../hooks/tokens'

// #683 r5 pt 8: the tab bar is one picture (a rule + the selected tab's accent underline) with the five labels as native plain presses over it,
// left to right at whole pane columns; no hotkey digits, no count badge ("цифры и хотки цифр вообще не надо").
test('desktop: tab bar = one picture + six plain presses (POB second, #972), no hotkeys, no counts', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', {}, 123)
  const tree = await ui.drawn()
  const tabs: { label: string; left: number; plain: boolean; hotkey: unknown }[] = []
  const walk = (n: any, left: number | null) => {
    if (!n || typeof n !== 'object') return
    const here = n.type === 'Box' && n.props?.position === 'absolute' ? Number(n.props.left) : left
    if (n.type === 'Button' && String(n.props?.key).startsWith('tab-'))
      tabs.push({ label: String(n.props.label), left: here ?? -1, plain: !!n.props.plain, hotkey: n.props.hotkey })
    for (const c of n.children ?? []) walk(c, here)
  }
  walk(tree, null)
  console.log(JSON.stringify(tabs))
  if (tabs.map(x => x.label).join('|') !== 'Главная|POB|Билды|Тикеты|Расходы|Прогресс') throw new Error('labels: ' + tabs.map(x => x.label))
  if (tabs.some(x => !x.plain || x.hotkey != null)) throw new Error('a tab press is not plain or keeps a hotkey')
  if (tabs.some((x, i) => x.left < 1 || (i && x.left <= tabs[i - 1]!.left + tabs[i - 1]!.label.length))) throw new Error('tab columns overlap')
  const pic = (await ui.findAll({ type: 'Svg' })).find((s: any) => String(s.props?.alt).startsWith('Главная'))
  if (!pic || pic.props.height !== GRID.tab) throw new Error('no tab bar picture of height 28')
  // variant B (the owner's pick 10.10): one accent underline under the selected label, one rule across, no tile
  const src = dq(String(pic.props.source))
  if ((src.match(/fill="#4493f8"/g) ?? []).length !== 1 || !src.includes('height="3"')) throw new Error('no single accent underline')
  if (src.includes('#262628') || src.includes('#1d3048')) throw new Error('the bar still draws a tile or a selected segment')
})

test('terminal: tab bar = native buttons without hotkeys', async ($, on) => {
  const ui = await mountPane($, on, 'terminal', {}, 100)
  const btns = (await ui.findAll({ type: 'Button' })).filter((b: any) => String(b.props?.key).startsWith('tab-'))
  if (btns.length !== 6 || btns.some((b: any) => b.props.hotkey != null)) throw new Error('terminal tabs: ' + btns.length)
})
