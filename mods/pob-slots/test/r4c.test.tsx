import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, svgWords, altLines, cutRows, dq, linkLabel, ghostCells, blankPx, shown } from './kit'
import { pressFaces } from './face'
import { legacy } from './layout'
import { textWidth } from '../hooks/draw'

// #683 r4c: the native presses lie over the row pictures at the column of their fact (a desktop absolute Box is placed
// in cells of 7.8 px: the tick column x 352 = left 45, the name column x 38 = left 5), and a running build is one row:
// its 16-px ascendancy face in the rail, its name in its base class's colour, the group and step its log started (#995: the bar of three groups is gone).
const v = JSON.parse(FAST)
const job = v.runs.running[0]
const started = Math.round(Date.now() / 1000) - 600
job.progress.cells = job.progress.cells.map((c: any) => c.state === 'running'
  ? { ...c, class: 'Templar', asc: 'Hierophant', stage: 'improvement loop, pass 2, gear', group: 'improvement loop', step: 'loop pass 2', move: 'gear',
      bar: { w: [0.4706, 0.528, 0.0014], fill: [1, 0.5, 0], at: 1 }, started } : c)
const fast = JSON.stringify(v)
// a 1x1 PNG
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

// Every element of the drawn tree with the absolute Box it lies in (if any).
const placed = async (ui: any) => {
  const out: { n: any; left: number | null }[] = []
  const walk = (n: any, left: number | null) => {
    if (!n || typeof n !== 'object') return
    const here = n.type === 'Box' && n.props?.position === 'absolute' ? Number(n.props.left) : left
    // #771: a merged picture is read as its rows (cutRows): one pseudo-picture a row, with that row's alt, source and height
    if (n.type === 'Svg' && altLines(n.props?.alt).length > 1) {
      for (const c of cutRows(n.props.alt, dq(String(n.props.source)))) out.push({ n: { ...n, props: { ...n.props, alt: c.alt, source: c.src, height: Number(/height="([\d.]+)"/.exec(c.src)?.[1]) } }, left: here })
      return
    }
    out.push({ n, left: here })
    for (const c of n.children ?? []) walk(c, here)
  }
  walk(legacy(shown(await ui.drawn())), null) // #837 unit 4b: the presses' flow rows read as the absolute Boxes of before
  return out
}

test('desktop: ticket Links at the tick column, titles at the name column, the pager on the History label', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast }, 123)
  const all = await placed(ui)
  // #972: a ticket number is drawn in the picture; the press over it is a blank Button `lk-<card><row>-#N` (its number is the key's tail)
  const tickOf = (n: any): string => /^lk-.*-(#\d+)$/.exec(String(n.props?.key))?.[1] ?? ''
  const links = all.filter(x => x.n.type === 'Button' && tickOf(x.n) && blankPx(x.n.props.label) != null)
  // (#683 r5 (B): the picked run's ticket stands once more right after «Билды» on its squares' label row, left 10)
  // (#793 F26: the PoB runs queue has its own grid, its tick column is back at x 352 = left 45, the baseline grid (#837 unit 10, 6115205025); was x 166 = left 21 in unit 4); all cards one x)
  // #837 b2: a card press stands where its text is DRAWN on the screen: the picture's markup x (352) fitted into the 930-px slot (x * 930 / 963 / 7.8 = 43.6 -> 44; the squares' label link 10 -> 9)
  // #837 b5: the ghost Link is centred on the drawn number: the number is drawn at x 359.8 (one cell right of its press), 4 chars wide at 14 px: left 44 -> 45
  // #972: no fixed cell any more. A ticket Button's Box is at L = floor(drawn x * fit / 7.8) cells and the rest of the drawn x is its lead of no-break spaces: its screen start
  // L * 7.8 + lead * NBSP_PX lies within 1.5 px of the drawn number's x (the `lk` text of its row times the card's fit), its width (blank label) within 3 px of the number's
  const reads = pressFaces(await ui.drawn(), 123).filter(f => f.kind === 'ticket')
  const wrong = reads.filter(f => !f.face || Math.abs(f.dStart!) > 1.5 || Math.abs(f.dWidth!) > 3)
  const worstS = Math.max(0, ...reads.filter(f => f.face).map(f => Math.abs(f.dStart!))), worstW = Math.max(0, ...reads.filter(f => f.face).map(f => Math.abs(f.dWidth!)))
  console.log(`links ${links.length}, read against their number ${reads.length}, off the number ${wrong.length} (worst start ${worstS.toFixed(2)} px, worst width ${worstW.toFixed(2)} px)`)
  if (!links.length || reads.length !== links.length || wrong.length) throw new Error('a ticket link off its drawn number: ' + JSON.stringify(wrong.map(f => [f.key, f.dStart, f.dWidth])))
  // #837 b8: a run title, a history title and the pager word are no Buttons but a Markdown ghost link of no-break spaces (rowsOne.pressAt); the Box's left is floor(drawn x * 930 / 963 / 7.8)
  const md = (key: string) => all.find(x => x.n.type === 'Markdown' && x.n.props?.key === key)
  // history titles and a run title are drawn at x 38 (#837 b9b B3a: the run title's 6 px offset is gone, so both stand on the column x); the ghost's left is the nearest cell edge (#837 b9a A8): round((38 * 930 / 963 + 1.4) / 7.8) = 5 for both (b9b alone, with floor, pinned 4; b9a alone pinned 6 for the run title at x 44)
  // #837 b18: a run title is a host Button with its own visible label (the picture draws no title text): the press is found as a Button, its label is the title (>= 4 chars, as the 4 cells of the old ghost)
  const title = all.find(x => x.n.type === 'Button' && x.n.props?.key === `run-pick-${job.id}`)
  // #972: a title's Button is blank (em + no-break spaces) and starts on its drawn word (within 1.5 px), not on a fixed cell
  const tFaces = pressFaces(await ui.drawn(), 123).filter(f => f.kind === 'title')
  const tBad = tFaces.filter(f => !f.face || Math.abs(f.dStart!) > 1.5 || Math.abs(f.dWidth!) > 3)
  console.log(`titles read ${tFaces.length}, off their word ${tBad.length}`)
  if (!tFaces.length || tBad.length) throw new Error('title press off its drawn word: ' + JSON.stringify(tBad.map(f => [f.key, f.dStart, f.dWidth])))
  if (!title || blankPx(title.n.props.label) == null) throw new Error('run title press: ' + JSON.stringify(title && [title.left, title.n.props]))
  if (all.some(x => x.n.type === 'Markdown' && /^run-(pick|hist)-/.test(String(x.n.props?.key)))) throw new Error('a ghost link is left over a title')
  const hist = all.filter(x => x.n.type === 'Button' && String(x.n.props?.key).startsWith('run-hist-'))
  if (hist.length !== 6 || hist.some(x => blankPx(x.n.props.label) == null)) throw new Error('history titles: ' + hist.length + ' ' + JSON.stringify(hist.map(x => x.left)))
  // #837 b17: the pager words are host Buttons with their label (pager-button-837-b17.test.tsx), no ghost link; the first page's «новее» is a dim Button, «старее» is not
  const pb = (key: string) => all.find(x => x.n.type === 'Button' && x.n.props?.key === key)
  // #994: the pager is two icon buttons: the first page's «previous» is drawn dim and is no Button, «next» is a blank Button over its chevron
  if (md('hist-prev') || md('hist-next') || pb('hist-prev') || blankPx(pb('hist-next')?.n.props?.label ?? 'x') == null) throw new Error('pager')
  // #837 u4: the run's title is DRAWN in its picture (on the row's centre, runs-title-837.test.tsx) and its Button is a ghost: once in the picture, the Button's text transparent.
  const strip = all.find(x => x.n.type === 'Svg' && String(x.n.props?.alt).startsWith(`${job.tag} running`))
  if (!strip) throw new Error('the title is drawn once in its picture')
})

test('desktop: a running build = face, class colour, no bar of three groups (#995), group + pass + move, minutes', async ($, on) => {
  // The faces come from the mod's assets/asc as bytes (base64); the engine stands for the disk here.
  const asked: string[] = []
  on('fs.read', async (_$: any, e: any) => {
    asked.push(`${e.path} ${e.as}`)
    if (/_16x16\.png$/.test(e.path) && e.as === 'bytes') return { value: { base64: PNG } } as any
    throw new Error('ENOENT ' + e.path)
  })
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast }, 123)
  if (!asked.some(x => /[\\/]assets[\\/]asc[\\/]hierophant_16x16\.png bytes$/.test(x))) throw new Error('face path: ' + JSON.stringify(asked))
  const all = await placed(ui)
  const run = job.progress.cells.find((c: any) => c.state === 'running')
  const row = all.find(x => x.n.type === 'Svg' && String(x.n.props?.alt).startsWith(`${run.name}:`))
  const src = dq(String(row?.n.props.source ?? ''))
  const words = svgWords(src)
  // #995 row 3: the old bar of three groups (the loop filled by a time guess) marked no real stage: gone. The «билды» column holds the build's REAL stage, «этап N / M»
  // (the collector's stage_index / stage_count, #985 c); this cell has none, so the column is empty
  const zones = [...src.matchAll(/height="8" rx="1.5"/g)].length
  console.log(`build row ${src.length} chars, face ${src.includes('<image href="data:image/png;base64,')}, zone rects ${zones}, words ${words.join(' | ')}`)
  if (!src.includes('<image href="data:image/png;base64,') || !src.includes('image-rendering:pixelated')) throw new Error('no face')
  if (zones !== 0) throw new Error('zones ' + zones)
  if (words.some(w => /^этап /.test(w))) throw new Error('a stage drawn with no stage_index')
  // #837 unit 10 (6115205025): the status is cut with an ellipsis in the room left on the baseline grid (name x 38 w 300, tick x 352, билды x 552..618 since #837 unit 11, autopilot comparison 00:08Z)
  for (const w of [run.name, 'Hierophant', 'improvement loop', '10 мин']) if (!words.some((x: string) => x === w || (w === 'improvement loop' && x.startsWith(w)))) throw new Error('missing ' + w)
  if (words.some(w => /^\d+\/12$/.test(w))) throw new Error('the i/12 count is back')
  // #683 r5 (B): the squares = a strip per named build: the same face in its rail, a state mark (the running one
  // spins) and a native press, the seed, per build
  // #972: the seed is drawn in the strip's picture; its press is a blank Button (key cell-<job>-<name>-<seed>) of whitespace
  const sq = all.filter(x => x.n.type === 'Button' && String(x.n.props?.key).startsWith(`cell-${job.id}-`))
  if (!sq.length || sq.some(x => !/^\s{2,}$/.test(String(x.n.props.label)) || x.left == null || !String(x.n.props.key).endsWith('-' + run.seed))) throw new Error('squares: ' + sq.map(x => x.n.props.key).join(' '))
  const line = all.find(x => x.n.type === 'Svg' && String(x.n.props?.alt).startsWith(`Билд «${run.name}»: `))
  const ls = dq(String(line?.n.props.source ?? ''))
  if (!ls.includes('<image href="data:image/png;base64,') || !/stroke="#3fb950"[^>]*><g class="sp">/.test(ls)) throw new Error('the running build\'s strip: no face or no spinning mark')
})

// #683 r5 pt 6: a picture without its height is 0 tall until it decodes, so each redraw shrank the body and threw
// the scrolled pane to the top (measured live 10.10 00:36). Every Svg carries its markup's own height.
test('desktop: every Svg of the main tab carries its markup height', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast }, 123)
  const svgs = (await placed(ui)).filter(x => x.n.type === 'Svg')
  const bad = svgs.filter(x => Number(x.n.props.height) !== Number(/height="([\d.]+)"/.exec(dq(x.n.props.source))?.[1]))
  console.log(`svgs ${svgs.length}, without their height ${bad.length}`)
  if (!svgs.length || bad.length) throw new Error('Svg without height: ' + bad.map(x => x.n.props.alt).join(', '))
})

// #711: a build whose log has no `step start:` line yet names no step
test('desktop: a build with no started step reads «запускается», with no bar', async ($, on) => {
  const v2 = JSON.parse(fast)
  v2.runs.running[0].progress.cells = v2.runs.running[0].progress.cells.map((c: any) => {
    if (c.state !== 'running') return c
    const { stage, group, step, move, bar, ...rest } = c
    return rest
  })
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(v2) }, 123)
  const all = await placed(ui)
  const run = job.progress.cells.find((c: any) => c.state === 'running')
  const row = all.find(x => x.n.type === 'Svg' && String(x.n.props?.alt).startsWith(`${run.name}:`))
  const src = dq(String(row?.n.props.source ?? ''))
  const words = svgWords(src)
  console.log(`no start line: words ${words.join(' | ')}`)
  if (!words.includes('запускается')) throw new Error('no «запускается»: ' + words.join(' | '))
  if (/height="8" rx="1.5"/.test(src)) throw new Error('a bar is drawn for a build that started no step')
})
