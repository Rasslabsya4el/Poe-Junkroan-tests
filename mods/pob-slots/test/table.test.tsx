import { test, mock } from 'claude-code/testing'
import { K, GRID } from '../hooks/tokens'
import { CELL_PX } from '../hooks/kit'
import { FAST, TICKETS, SLOW, ORCH, CELLS, BUILD } from './fixtures'
import { seen, svgWords, altLines, cutRows, dq, mountG } from './kit'

// #683 r5 (0): a build's stats = THE table of the pane: one plain picture on the native 20-px line grid, drawn 1:1,
// Main skill first, and a keyed hover Box over every data row (an interactive Svg is a frame that blinks on a redraw).
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const W = Math.round(123 * 7.8) + 4
const b = JSON.parse(BUILD)
b.groups = [...b.groups.filter((g: any) => g.title === 'Main skill'), ...b.groups.filter((g: any) => g.title !== 'Main skill')]
const OUT: Record<string, string> = { fast: FAST, tickets: TICKETS, slow: SLOW, orch: ORCH, cells: CELLS, build: JSON.stringify(b) }

// Every Box of the drawn tree with its parent's first child (`prev`: the picture an absolute Box is laid over).
const boxes = async (ui: any) => {
  const out: { n: any; prev: any }[] = []
  const walk = (n: any) => {
    if (!n || typeof n !== 'object') return
    const kids = n.children ?? []
    for (const c of kids) { if (c?.type === 'Box') out.push({ n: c, prev: kids[0] }); walk(c) }
  }
  walk(await ui.drawn())
  return out
}

test('desktop: an open square draws its stats as one plain table picture with a hover Box per row', async ($, on) => {
  const clock = mock.clock(on)
  on('process.run', async (_$, e) => ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await mountG($, { plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-pob' }) // #983: the runs card lives on the tab «POB»
  const RUN = 'run-hist-j-20261006-1042-6ea8'
  const drawn = async () => [...(await ui.findAll({ type: 'Markdown' })), ...(await ui.findAll({ type: 'Button' }))].some((x: any) => x.key === RUN)
  for (let i = 0; i < 40 && !(await drawn()); i++) { await ui.press({ key: 'hist-next' }); await clock.settle() }
  await ui.press({ key: RUN }); await clock.settle()
  await ui.press({ key: 'cell-j-20261006-1042-6ea8-smite-4' }); await clock.settle()
  const svgs = await ui.findAll({ type: 'Svg' })
  const tables = svgs.filter((x: any) => String(x.props?.alt ?? x.alt).endsWith(' stats'))
  if (tables.length !== 1) throw new Error(`${tables.length} stats pictures`)
  const p = (tables[0] as any).props ?? tables[0]
  const words = svgWords(p.source)
  const rows = b.groups.reduce((s: number, g: any) => s + g.rows.length, 0)
  console.log(`table ${p.source.length} chars, ${p.width} x ${p.height}, ${rows} data rows, interactive ${p.isInteractive}`)
  // Not interactive: the frame reloads on every redraw and blinked (owner 10.10 00:5x).
  if (p.isInteractive) throw new Error('interactive frame blinks')
  // Drawn 1:1 (the markup's width = the Svg's = W - 4) on the native line grid: the header line, a label line per
  // group and a blank line before every group but the first, then a line per row; no trailing gap.
  const own = (k: string) => Number(new RegExp(`^<svg[^>]* ${k}="([0-9.]+)"`).exec(dq(p.source))?.[1])
  if (p.width !== W - 4 || own('width') !== W - 4) throw new Error(`width ${p.width} / ${own('width')}, want ${W - 4}`)
  if (p.height % CELL_PX !== 0 || own('height') !== p.height) throw new Error(`height ${p.height} / ${own('height')}`)
  if (p.height !== CELL_PX * (1 + rows + 2 * b.groups.length - 1)) throw new Error(`height ${p.height} for ${rows} rows in ${b.groups.length} groups`)
  if (!(words.indexOf('Main skill') >= 0 && words.indexOf('Main skill') < words.indexOf('Character'))) throw new Error('Main skill not first')
  if (!words.includes('Fire Max Hit') || p.source.length > 10000) throw new Error('stats / size ' + p.source.length)
  if (/:hover/.test(p.source)) throw new Error('dead :hover css in a plain picture')
  // #613: the stat table's hover Boxes are each their OWN absolute Box (position, top, height) laid over the picture (#837 pass 2):
  // one Box per data row (hov.length === rows), each at its picture row to the pixel (drift 0).
  const hov = (await boxes(ui)).filter(x => /^st-h\d+$/.test(String(x.n.props?.key)))
  if (hov.length !== rows) throw new Error(`${hov.length} hover Boxes over the stat rows, ${rows} data rows`)
  // the picture's lines: the header, then per group (a blank line before every group but the first) its label and a line per row
  const dataYs: number[] = []
  let line = 1
  b.groups.forEach((g: any, gi: number) => { line += (gi ? 1 : 0) + 1; for (let r = 0; r < g.rows.length; r++) dataYs.push((line++) * CELL_PX) })
  const groupLabels = b.groups.length
  const rowYs = dataYs
  const drift = hov.map((h, i) => (h.n.props.position === 'absolute' ? Number(h.n.props.top) : NaN) * CELL_PX - dataYs[i]!)
  console.log(`stat hover Boxes ${hov.length} of ${rows} rows (${groupLabels} groups, ${rowYs.length} lines at the first column), max |drift| ${Math.max(...drift.map(Math.abs))} px`)
  if (drift.some(e => e !== 0)) throw new Error('hover Box drift: ' + drift.join(','))
  const bands = [...dq(String(p.source)).matchAll(/<use href="#z" y="(\d+)"\/>/g)].map(m => Number(m[1]))
  if (!bands.length || bands.some(y => y % CELL_PX !== 0)) throw new Error('zebra off the grid: ' + bands.join(','))
  // #683 r5 (B): the square's own facts (seed, state, ratio, time) are said by its strip, once; the head picture
  // (title = the square's name) carries the build's class and level only.
  const all: any[] = svgs.flatMap((x: any) => (altLines(x.props?.alt).length > 1 ? cutRows(x.props.alt, String(x.props.source)).map(c => ({ ...x.props, alt: c.alt, source: c.src })) : [x.props ?? x])) // #771: a merged picture row by row
  const head = all.find((x: any) => String(x.alt).startsWith('Smite · '))
  if (!head || head.width !== W - 4 || head.alt !== 'Smite · Duelist / Slayer · Level 78') throw new Error('head: ' + (head && head.alt))
  const strip = all.find((x: any) => String(x.alt).startsWith('Билд «Smite»: '))
  if (strip?.alt !== 'Билд «Smite»: seed 4 готово · готово · 52 мин') throw new Error('strip: ' + (strip && strip.alt))
  console.log('TABLESVG ' + p.source)
  await ui.unmount()
})

// #683 r5: a replay run's square: the panel says the replay's own before -> after under the class line.
test('desktop: the panel of a replay square carries its before -> after', async ($, on) => {
  const clock = mock.clock(on)
  const note = 'replay loop: Combined DPS 646k -> 438k (-32.21 %) · 11 min'
  const out = { ...OUT, build: JSON.stringify({ ...b, note }) }
  on('process.run', async (_$, e) => ({ value: { exitCode: 0, stdout: out[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await mountG($, { plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS })
  await ui.press({ key: 'tab-pob' }) // #983: the runs card lives on the tab «POB»
  const RUN = 'run-hist-j-20261006-1042-6ea8'
  const drawn = async () => [...(await ui.findAll({ type: 'Markdown' })), ...(await ui.findAll({ type: 'Button' }))].some((x: any) => x.key === RUN)
  for (let i = 0; i < 40 && !(await drawn()); i++) { await ui.press({ key: 'hist-next' }); await clock.settle() }
  await ui.press({ key: RUN }); await clock.settle()
  await ui.press({ key: 'cell-j-20261006-1042-6ea8-smite-4' }); await clock.settle()
  const texts = await seen(ui)
  if (!texts.some(t => t.includes(note))) throw new Error('no before -> after line: ' + texts.slice(0, 40).join(' | '))
  // the note is the head picture's own third line, drawn whole
  const head: any = (await ui.findAll({ type: 'Svg' })).map((x: any) => x.props ?? x).find((x: any) => String(x.alt).startsWith('Smite · '))
  if (!head || !svgWords(String(head.source)).includes(note)) throw new Error('the note is not a line of the head: ' + (head && svgWords(String(head.source)).join(' | ')))
  await ui.unmount()
})
