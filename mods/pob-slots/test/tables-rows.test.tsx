import { test, mock, expect } from 'claude-code/testing'
// #671 u4 / #837: a native Box laid over a table row stands where the row's picture is. The table's row is LROW = CELL_PX = 19 px,
// one engine cell (`top` / `height` are in cells). #837 pass 2 (rule 2): each row has its OWN absolute Box (`top` = its grid line,
// `height` = its span, as at 50ea5412), so the row's place never depends on the Boxes before it. These tests read each Box's own `top`
// and `height` (red on a column of marginTop gaps: no `top`), the position of the ticket-number Link (the line its text lands on)
// against the title's line, and the band (top, bottom) against the row's (top, bottom).
import { FAST, SLOW, ORCH } from './fixtures'
import { LIVE as TODAY } from './tickets-live-20261011'
import { COST_SLOW_20261011, COST_TICKETS_20261011 } from './cost-live-20261011'
import { CELL_PX } from '../hooks/kit'
import { dq } from './kit'

const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const TK = JSON.parse(TODAY)
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
const unesc = (s: string) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&')
const tspans = (src: string) => [...src.matchAll(/<tspan x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]*)<\/tspan>/g)].map(m => ({ x: +m[1]!, y: +m[2]!, t: unesc(m[3]!) }))
const mount = async ($: any, on: any, out: Record<string, string>) => {
  const clock = mock.clock(on)
  on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: out[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  return { ui, clock }
}
const report = (label: string, errs: number[]) => {
  const max = Math.max(...errs.map(Math.abs))
  console.log(`${label}: rows ${errs.length}, max |error| ${max} px, last row error ${errs[errs.length - 1]} px`)
  return max
}

/** the own hover Boxes laid over a table's picture: siblings of the Svg, absolute, keyed by `re` */
const tableBoxes = (node: any, re: RegExp) => {
  const kids: any[] = node.children ?? []
  const svg = kids.find(c => c?.type === 'Svg' && dq(String(c.props?.source ?? '')).includes('<tspan'))
  const boxes = kids.filter(c => c?.type === 'Box' && re.test(String(c.props?.key)))
  return svg && boxes.length ? { svg, boxes } : null
}
const ownTop = (b: any) => (b.props.position === 'absolute' && b.props.top != null ? Number(b.props.top) : NaN) // NaN = the Box has no place of its own
const rowYsOf = (src: string) => {
  const ts = tspans(src)
  const x0 = Math.min(...ts.map(t => t.x))
  return [...new Set(ts.filter(t => t.x === x0).map(t => t.y - 14))].sort((a, b) => a - b)
}

test('#837 pass 2: every ticket row of the opened #670 has its OWN Box; its ticket press (a blank Button tl-tk…, #972) lies on the title\'s line, its band on the row (top and bottom)', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui, clock } = await mount($, on, { fast: FAST, tickets: TODAY, slow: SLOW, orch: ORCH })
  await ui.press({ key: 'tab-tickets' }); await clock.settle()
  await ui.press({ key: 'tg-670' }); await clock.settle()
  const errs: number[] = [], linkErrs: number[] = [], bandErrs: number[] = []
  walk(await ui.drawn(), (node) => {
    const t = tableBoxes(node, /^hv-tk-\d+$/)
    if (!t) return
    const ts = tspans(dq(String(t.svg.props.source)))
    let at = 0
    for (const b of t.boxes) {
      expect(b.props.position, 'own Box is absolute').toBe('absolute')
      expect(b.props.marginTop, 'no marginTop gap: the place is its own').toBeUndefined()
      const n = Number(/(\d+)$/.exec(String(b.props.key))![1])
      const title = unesc(String(TK.issues[String(n)].title)).slice(0, 14)
      let j = at
      while (j < ts.length && !ts[j]!.t.startsWith(title)) j++
      if (j >= ts.length) throw new Error(`no title tspan for #${n} (${title}) after tspan ${at}`)
      at = j + 1
      const rowTop = ts[j]!.y - 14, rowBot = rowTop + CELL_PX * Number(b.props.height)
      let link: any = null, linkTop = 0
      const find = (x: any, top: number) => { const tp = top + (x.props?.position === 'absolute' ? Number(x.props?.top ?? 0) : 0); if (x.type === 'Button' && new RegExp(`^tl-tk[\\w-]*-#?${n}$`).test(String(x.props?.key))) { link = x; linkTop = tp } for (const c of x.children ?? []) find(c, tp) }
      find(b, 0)
      if (!link) console.log('PROBE', JSON.stringify(b))
      expect(link, `#${n} has its ticket Button tl-tk…-${n}`).not.toBeNull()
      // #972: the number itself is a word of the table's picture (class ac) and the Button over it is blank
      expect(new RegExp(`class="ac"[^>]*>(?:<tspan[^>]*>[^<]*</tspan>)*<tspan[^>]*>#${n}<`).test(dq(String(t.svg.props.source))), `#${n} is drawn in the picture, class ac`).toBe(true)
      expect(String(link.props.label).replace(/\s/g, ''), `#${n} Button is blank`).toBe('')
      errs.push(ownTop(b) * CELL_PX - rowTop)
      linkErrs.push(linkTop * CELL_PX - rowTop) // the Link's line = the title's line
      bandErrs.push(ownTop(b) * CELL_PX - rowTop, ownTop(b) * CELL_PX + Number(b.props.height) * CELL_PX - rowBot)
    }
  })
  report('tickets #670 link', linkErrs); report('tickets #670 band top/bottom', bandErrs)
  const max = report('tickets #670 open', errs)
  expect(errs.length, 'ticket rows checked').toBeGreaterThanOrEqual(60) // #983: the rows of the page the budget gives, no longer the 97 of the old 60,000-character literal
  for (const e of [...errs, ...linkErrs, ...bandErrs]) expect(e).toBe(0)
  expect(max).toBe(0)
  await ui.unmount()
})

test('#837 pass 2: the Cost cards (tableOf): each row has its OWN Box on its picture row, the "По ролям" first row too', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui, clock } = await mount($, on, { fast: '{}', tickets: COST_TICKETS_20261011, slow: COST_SLOW_20261011, orch: '{}' })
  await ui.press({ key: 'tab-cost' }); await clock.settle()
  await ui.press({ key: 'cost-week' }); await clock.settle()
  const errs: number[] = []
  let tables = 0
  // #972: the cards stand in three groups behind a second switch: each is drawn and read
  for (const group of ['roles', 'spawn', 'days']) {
  await ui.press({ key: `costg-${group}` }); await clock.settle()
  walk(await ui.drawn(), (node) => {
    const t = tableBoxes(node, /^hv-/)
    if (!t) return
    const rowYs = rowYsOf(dq(String(t.svg.props.source)))
    if (rowYs.length !== t.boxes.length) { console.log(`cost table skipped: ${rowYs.length} picture rows vs ${t.boxes.length} boxes`); return }
    tables++
    t.boxes.forEach((b, i) => {
      expect(b.props.marginTop, 'no marginTop gap').toBeUndefined()
      errs.push(ownTop(b) * CELL_PX - rowYs[i]!)
      errs.push((ownTop(b) + Number(b.props.height)) * CELL_PX - (rowYs[i]! + CELL_PX * Number(b.props.height))) // band bottom
    })
  })
  }
  const max = report('cost week tables', errs)
  expect(tables, 'cost tables checked').toBeGreaterThan(2)
  expect(errs.length, 'cost rows checked').toBeGreaterThan(5)
  expect(max).toBe(0)
  await ui.unmount()
})

// #995 send-back 1 (defect 4): a Progress count row opens nothing, so its table carries no row Box at all (the picture's rows stand alone)
test('#995 send-back 1: the Progress cards (tableOf): their pictures have rows and no row Box over them', { timeoutMs: 60_000 }, async ($, on) => {
  const { ui, clock } = await mount($, on, { fast: FAST, tickets: TODAY, slow: SLOW, orch: ORCH })
  await ui.press({ key: 'tab-progress' }); await clock.settle()
  let rows = 0, boxes = 0
  walk(await ui.drawn(), (node) => {
    if (node?.type !== 'Svg' || !/^(По тикетам|Остальное)$/.test(String(node.props?.alt))) return
    rows += rowYsOf(dq(String(node.props.source))).length
  })
  walk(await ui.drawn(), (node) => { if (/^(hv-prog-|p[lo]-h\d)/.test(String(node?.key ?? node?.props?.key ?? ''))) boxes++ })
  report('progress labels', [])
  expect(rows, 'progress picture rows').toBeGreaterThan(3)
  expect(boxes, 'row Boxes over the Progress tables').toBe(0)
  await ui.unmount()
})
