import { test } from 'claude-code/testing'
import { K, GRID } from '../hooks/tokens'
import { FAST } from './fixtures'
import { marks, mountPane, seen, svgWords, altLines, cutRows, dq, linkLabel, ghostCells, seedLinks, leadOfBox, blankPx, startPx, rowLight, isRowBox } from './kit'
import { CELL_PX, NBSP_PX, PX_PER_COL } from '../hooks/kit'
import { seedW } from '../hooks/addon'
import { textWidth } from '../hooks/draw'
import { legacy } from './layout'

// #683 r5 (B) (owner 10.10: «Квадраты получились уебищными, как это сочетается со стилем?»): the squares of a picked
// run are rows of the pane: a label row («Билды», the run's ticket as a native Link, the counts in words), then ONE
// STRIP PER NAMED BUILD (a reference, each of its variants): the face (or a dot) in the rail, the name in its base
// class's colour, the ascendancy, a state mark + a native press (the seed) per build, what the line came to, its time.
// A picked build = an accent capsule on a selected strip that speaks for that build; the head under it repeats nothing.
const v = JSON.parse(FAST)
const job = v.runs.running[0]
const now = Math.round(Date.now() / 1000)
const METRICS = [['Combined DPS', 737408.4, 561006.9], ['Total Life', 3779, 3727], ['Phys Max Hit', 4848, 4976]]
job.issue = 580
job.progress = {
  done: 3, total: 7, total_open: true, eta: null, cells: [
    { ref: 'smite', name: 'Smite', seed: 4, state: 'done', took: '52 min', class: 'Duelist', asc: 'Slayer', metrics: METRICS },
    { ref: 'spark', name: 'Spark', seed: 4, state: 'running', took: '10:42', started: now - 600, class: 'Witch', asc: 'Elementalist' },
    { ref: 'smite', name: 'Smite', seed: 5, state: 'failed', took: '86 s', class: 'Duelist', asc: 'Slayer' },
    { ref: 'smite', name: 'Smite · no Versatile Combatant', seed: 4, variant: 'no-versatile_combatant', state: 'done', took: '64 min', class: 'Duelist', asc: 'Slayer' },
    { ref: 'spark', name: 'Spark', seed: 5, state: 'waiting', class: 'Witch', asc: 'Elementalist' },
    { ref: 'spark', name: 'Spark', seed: 6, state: 'queued', class: 'Witch', asc: 'Elementalist' },
    { ref: 'nameless', name: 'Nameless', seed: 4, state: 'done', took: '7 min' },
  ],
}
const fast = JSON.stringify(v)
const seedOf = (b: any) => String(b.n.props.key).replace(/^cell-.*-spark-/, '') // the seed is the key's tail (the ghost link has no label)
const key = (c: any) => `cell-${job.id}-${c.ref}-${c.seed}${c.variant ? '-' + c.variant : ''}`
const GH = 'https://github.com/Rasslabsya4el/Poe-Junkroan/issues/'
// a 1x1 PNG
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
// the seeds' press columns at 123 pane columns: round(352 / 7.8) + 2, then 6 columns a one-digit seed
const COLS = [47, 53, 59, 65, 71]
// #837 b2: the same columns as a press stands on the screen: round(x * 930 / 963 / 7.8) of the column's markup x (COLS * 7.8)
// #837 b8: a seed's press is a ghost link over its capsule (drawn from 17 px left of the column), its Box at floor(drawn x * 930 / 963 / 7.8)
// #837 b9 A8: a press's Box stands on the cell edge nearest the capsule's first px (the underline starts GHOST_INSET px left of the edge), was the floor
// #972: no fixed cell any more: a seed's Button starts on its drawn capsule (L * 7.8 + lead * NBSP_PX, within 1.5 px of the capsule's first px) and is as wide as it (within 3 px): `seedCheck`
const FIT = 930 / 963 // the card's screen px a markup px at 123 columns
const DONE = '#ab7df8', FAILED = '#f85149', ACTIVE = '#3fb950', WAIT = '#d29922', ACCENT = '#4493f8'

// Every element of the drawn tree with the absolute Box it lies in (if any) and the row Box (the keyed one) around it.
const placed = async (ui: any) => {
  const out: { n: any; top: number | null; left: number | null; row: string | null; offPx?: number; lead: number }[] = []
  type Band = { key: string | null; top: number; alt: string; src: string }
  // #771 A6: the card is ONE picture: its rows are cut (cutRows), the squares' rows named by their place after the label
  // row («Билды …»: sq-label, then sq-0, sq-1 ...); a press lies in the row whose top is nearest to its own (cells * 19 px)
  const bandsOf = (svg: any): Band[] => {
    const alt = svg.props?.alt, src = dq(String(svg.props?.source ?? ''))
    const cut = altLines(alt).length > 1 ? cutRows(alt, src) : [{ alt: String(alt ?? ''), src }]
    let y = 0, k = -2
    return cut.map(c => {
      // #837 b10 S3: the section's head row (the word «сиды») is no strip
      const key = /^Билды/.test(c.alt) ? (k = -1, 'sq-label') : k >= -1 && !c.src.includes('>сиды<') ? `sq-${++k}` : null
      const band = { key, top: y, alt: c.alt, src: c.src }
      y += Number(/height="([\d.]+)"/.exec(c.src)?.[1])
      return band
    })
  }
  const near = (bands: Band[], cells: number) => [...bands].sort((p, q) => Math.abs(cells * CELL_PX - p.top) - Math.abs(cells * CELL_PX - q.top))[0]!
  const walk = (n: any, at: [number, number] | null, row: string | null, bands: Band[] | null, lead0 = 0) => {
    if (!n || typeof n !== 'object') return
    const lead = n.type === 'Box' && n.props?.position === 'absolute' ? leadOfBox(n) : lead0 // #972: the no-break spaces of plain Text before the Button in its absolute Box
    let here: [number, number] | null = n.type === 'Box' && n.props?.position === 'absolute' ? [Number(n.props.top), Number(n.props.left)] : at
    let r = n.type === 'Box' && /^sq-/.test(String(n.props?.key)) ? String(n.props.key) : row
    if (bands && n.type === 'Box' && n.props?.position === 'absolute') {
      const b = near(bands, Number(n.props.top))
      r = b.key ?? r
      here = [Number(n.props.top) - Math.round(b.top / CELL_PX), Number(n.props.left)]
    }
    // #837 b11 D6: the seeds of a row are the links of one Markdown: each link is read as the single ghost link it was, `left` = the Box's left plus the cells its offset reaches, `offPx` = the offset in screen px
    if (n.type === 'Markdown') for (const l of seedLinks(n)) out.push({ n: l.n, top: here ? here[0] : null, left: here ? here[1]! + Math.round(l.off * NBSP_PX / PX_PER_COL) : null, row: r, offPx: l.off * NBSP_PX, lead: 0 })
    else out.push({ n, top: here ? here[0] : null, left: here ? here[1] : null, row: r, lead })
    let sib: Band[] | null = null
    for (const c of (n.children ?? []) as any[]) {
      if (c?.type === 'Svg' && altLines(c.props?.alt).length > 1) {
        sib = bandsOf(c)
        for (const b of sib) out.push({ n: { ...c, props: { ...c.props, alt: b.alt, source: b.src } }, top: null, left: null, row: b.key, lead: 0 })
        continue
      }
      walk(c, here, r, c?.type === 'Box' && c.props?.position === 'absolute' && sib ? sib : bands, lead)
    }
  }
  walk(legacy(await ui.drawn()), null, null, null) // #837 unit 4b: the presses' flow rows read as the absolute Boxes of before
  return out
}
// #771: a merged picture's dither tile is shared (its id carries a number): a row is dithered when its own drawing fills with one
const dithered = (src: string) => /fill="url\(#d\d*\)"/.test(src.replace(/<defs>[\s\S]*?<\/defs>/g, ''))
type Placed = Awaited<ReturnType<typeof placed>>
// the strips of the squares, in drawing order: each row Box sq-<n> with its picture and its presses
const strips = (all: Placed) => {
  const keys = [...new Set(all.filter(x => x.row && /^sq-\d+$/.test(x.row)).map(x => x.row!))]
  return keys.map(k => {
    const own = all.filter(x => x.row === k)
    const pic = own.find(x => x.n.type === 'Svg')!.n.props
    return { key: k, alt: String(pic.alt), src: dq(String(pic.source)), words: svgWords(dq(String(pic.source))), marks: marks(dq(String(pic.source))),
      presses: own.filter(x => x.n.type === 'Button') } // #972: a seed's press is its own blank Button (key cell-…) in an absolute Box at top 0, over its drawn number
  })
}
const pill = (src: string) => new RegExp(`<rect x="${GRID.rail + 4}" width="[\\d.]+" height="20" rx="10" fill="(#\\w+)" fill-opacity="[\\d.]+"\\/>`).exec(src)?.[1]
const isSel = (src: string) => src.includes('height="20" rx="10" fill="#1d3048"/>')
const capsules = (src: string) => [...src.matchAll(/<rect x="([\d.]+)" y="1" width="([\d.]+)" height="18" rx="9" fill="#4493f8" fill-opacity=".22" stroke="#4493f8"\/>/g)].map(m => Number(m[1]))
const textOf = (src: string, word: string) => new RegExp(`<text ([^>]*)>${word}</text>`).exec(src)?.[1] ?? ''
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
/** #972: the seed Buttons of a strip: each is a blank Button (only U+2003 / U+00A0) alone in its absolute Box at top 0; its start (L * 7.8 + lead * NBSP_PX) is within 1.5 px of its capsule's first px
 *  (the drawn number's x - 20, markup, times the card's fit) and its width within 3 px of the capsule's (seedW + 22); the Boxes' lefts strictly increase with the drawn x. Returns the worst [start, width] error. */
const seedCheck = (s: { alt: string; src: string; presses: Placed }, seeds?: string[], what = s.alt): [number, number] => {
  let worstS = 0, worstW = 0, prevLeft = -1, prevX = -1
  for (const [bi, b] of s.presses.entries()) {
    const seed = seeds?.[bi] ?? seedOf(b)
    const m = new RegExp(`<text x="([0-9.]+)"[^>]*>${seed}</text>`).exec(s.src)
    if (!m) throw new Error(`${what}: no drawn number ${seed}`)
    const capX = (Number(m[1]) - 20) * FIT, capW = (seedW(seed) + 22) * FIT
    const w = blankPx(b.n.props.label)
    if (w == null || b.top !== 0) throw new Error(`${what}, seed ${seed}: not a blank Button at top 0: ${JSON.stringify([b.n.props.label, b.top])}`)
    const start = startPx(b.left!, b.lead)
    worstS = Math.max(worstS, Math.abs(start - capX)); worstW = Math.max(worstW, Math.abs(w - capW))
    if (Math.abs(start - capX) > 1.5 || Math.abs(w - capW) > 3) throw new Error(`${what}, seed ${seed}: start ${start.toFixed(2)} vs capsule ${capX.toFixed(2)}, width ${w.toFixed(2)} vs ${capW.toFixed(2)}`)
    if (b.left! * PX_PER_COL + b.lead * NBSP_PX <= prevLeft || Number(m[1]) <= prevX) throw new Error(`${what}, seed ${seed}: lefts do not increase with the drawn x`)
    prevLeft = startPx(b.left!, b.lead); prevX = Number(m[1])
  }
  return [worstS, worstW]
}

// #837 b2: a press stands where its text is DRAWN on the screen (x * 930 / 963 / 7.8): the label's ticket Link left 10 -> 9, the seed buttons 47.. -> 45..
test('desktop: the squares = a label row with the ticket Link and the counts, one strip per named build', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast }, 123)
  const all = await placed(ui)
  // the label row: the word, the counts by state in words (non-zero only), the open-total note; the ticket is the
  // native accent Link right after the word (left 10 = x 38 + the word's 35 px + 2), never inside the picture
  const label = all.filter(x => x.row === 'sq-label')
  const lp = label.find(x => x.n.type === 'Svg')?.n.props
  if (lp?.alt !== 'Билды #580' || !same(svgWords(dq(String(lp.source))), ['Билды', '3 готово · 1 считается · 2 ждут · 1 упал · варианты ещё добавляются', '#580'])) throw new Error('label row: ' + JSON.stringify(lp && [lp.alt, svgWords(dq(String(lp.source)))]))
  // #972: the number is drawn in the picture (above: the word '#580') and a blank Button `lk-run<n>-#580` lies over it (its press opens GH + 580)
  const link = label.filter(x => x.n.type === 'Button')
  if (link.length !== 1 || !/^lk-run\d+-#580$/.test(String(link[0]!.n.props.key)) || blankPx(link[0]!.n.props.label) == null || link[0]!.top !== 0)
    throw new Error('ticket Button: ' + JSON.stringify(link.map(x => [x.n.props, x.top, x.left])))
  // its start lies on the drawn number '#580' (within 1.5 px) and it is as wide as the number (within 3 px): L = floor(x * fit / 7.8), the rest in its lead
  const nx = Number(new RegExp('<text x="([0-9.]+)"[^>]*>#580</text>').exec(dq(String(lp.source)))?.[1])
  const lk = link[0]!, lkStart = startPx(lk.left!, lk.lead), lkW = blankPx(lk.n.props.label)!
  if (!(nx > 0) || Math.abs(lkStart - nx * FIT) > 1.5 || Math.abs(lkW - textWidth('#580', 14) * FIT) > 3 || lk.left !== Math.floor(nx * FIT / PX_PER_COL))
    throw new Error(`ticket Button: start ${lkStart.toFixed(2)} vs number ${(nx * FIT).toFixed(2)}, width ${lkW.toFixed(2)} vs ${(textWidth('#580', 14) * FIT).toFixed(2)}, left ${lk.left}`)
  const pics = all.filter(x => x.n.type === 'Svg').map(x => dq(String(x.n.props.source)))
  // (#837: #580 is drawn in the label row's picture, which the `same` check above reads; the Link over it is a ghost)
  // nothing of the old tiles is left
  if (pics.some(src => /<use href="#(done|failed|running|wait|picked)"/.test(src))) throw new Error('a tile of the old squares picture')
  // one strip per named build: references in the order they first appear, a reference's variant right under it
  const ss = strips(all)
  if (!same(ss.map(s => s.alt), [
    'Билд «Smite»: seed 4 готово, seed 5 упал · 1 готово · 1 упал',
    'Билд «Smite · no Versatile Combatant»: seed 4 готово · готово · 64 мин',
    'Билд «Spark»: seed 4 считается, seed 5 ждёт, seed 6 ждёт · 1 считается · 2 ждут',
    'Билд «Nameless»: seed 4 готово · готово · 7 мин',
  ])) throw new Error('strips: ' + ss.map(s => s.alt).join(' | '))
  // the words of a strip: name, ascendancy, the seeds, what it came to, its time (#837 b8: a seed is drawn in the picture, its press is a Markdown ghost link over it)
  if (!same(ss.map(s => s.words), [
    ['Smite', 'Slayer', '4', '5', '1 готово · 1 упал'], ['Smite · no Versatile Combatant', 'Slayer', '4', 'готово', '64 мин'],
    ['Spark', 'Elementalist', '4', '5', '6', '1 считается · 2 ждут'], ['Nameless', '4', 'готово', '7 мин'],
  ])) throw new Error('strip words: ' + JSON.stringify(ss.map(s => s.words)))
  const [smite, variant, spark, nameless] = ss as [typeof ss[0], typeof ss[0], typeof ss[0], typeof ss[0]]
  // the strip is tinted by its base class's colour (no class: the text colour), calm unless a build of it is running
  // (the running line keeps the dither); the name is in the picture in that colour, the rail carries a dot (no face here)
  const BAND = (c: string) => [c] // #837 pass 2 (baseline 50ea5412): the strip is a full pill in its line's colour (class colour, or the text colour) at .09 / .12 / .17
  if (!BAND('#FFD79E').includes(pill(smite.src) ?? '')) throw new Error('Smite pill: ' + pill(smite.src))
  if (!BAND('#9CBBFD').includes(pill(spark.src) ?? '') || dithered(spark.src) /* #994 defect 8: a busy row is one flat fill */ || dithered(smite.src)) throw new Error('Spark pill / dither: ' + pill(spark.src))
  if (!BAND('#f0f6fc').includes(pill(nameless.src) ?? '')) throw new Error('Nameless pill: ' + pill(nameless.src))
  if (!textOf(smite.src, 'Smite').includes('class="nm" style="fill:#FFD79E"') || !textOf(spark.src, 'Spark').includes('style="fill:#9CBBFD"') || !textOf(nameless.src, 'Nameless').includes('style="fill:#f0f6fc"')) throw new Error('name colours')
  if (!textOf(smite.src, 'Slayer').includes('class="mu"')) throw new Error('the ascendancy is not muted: ' + textOf(smite.src, 'Slayer'))
  for (const [s, col] of [[smite, '#FFD79E'], [variant, '#FFD79E'], [spark, '#9CBBFD'], [nameless, '#f0f6fc']] as const)
    if (!s.src.includes(`<circle cx="${GRID.rail / 2}" cy="10" r="3.2" fill="${col}"/>`) || s.src.includes('<image')) throw new Error(`rail of ${s.alt}`)
  // the marks: one per build left of its press's column (the icon's edge = column x 7.8 - 13.5), icon + colour by
  // state, the running one spins; nothing picked: no capsule, no selected strip
  const wantMarks = [
    [['done', DONE], ['failed', FAILED]], [['done', DONE]], [['running', ACTIVE], ['waiting', WAIT], ['waiting', WAIT]], [['done', DONE]],
  ]
  ss.forEach((s, si) => {
    const want = wantMarks[si]!
    if (s.marks.length !== want.length) throw new Error(`${s.alt}: ${s.marks.length} marks`)
    s.marks.forEach((m, n) => {
      if (m.kind !== want[n]![0] || m.color !== want[n]![1] || m.spin !== (m.kind === 'running') || Math.abs(m.x - (COLS[n]! * 7.8 - 13.5)) > 0.06) throw new Error(`${s.alt}, mark ${n}: ${JSON.stringify(m)}`)
    })
    if (capsules(s.src).length || isSel(s.src)) throw new Error(`${s.alt}: picked with nothing picked`)
  })
  if (!spark.src.includes('@keyframes rot')) throw new Error('the running mark does not spin')
  // the tree budget: a still mark is drawn once a strip, its repeats are a <use> of it moved by x (Spark's two waiting builds)
  if (!same(spark.marks.map(m => m.reused), [false, false, true]) || !spark.src.includes('<use href="#mw" x="46.8"/>') || smite.marks.some(m => m.reused)) throw new Error('reused marks: ' + JSON.stringify(spark.marks))
  // what a line came to, in one colour: several builds = the counts and the best ratio (>= 100 %: green), a lone
  // done build with no ratio = the text colour, a line with nothing done but something running = the text colour
  if (!textOf(smite.src, '1 готово · 1 упал').includes('class="ok"') || !textOf(variant.src, 'готово').includes('class="tx"') ||
    !textOf(spark.src, '1 считается · 2 ждут').includes('class="tx"')) throw new Error('act colours')
  // one native plain press per build with its unchanged key, the seed as its label, at its column over its strip
  const cells = job.progress.cells
  const wantPress = [[cells[0], cells[2]], [cells[3]], [cells[1], cells[4], cells[5]], [cells[6]]]
  ss.forEach((s, si) => {
    const want = wantPress[si]!
    if (s.presses.length !== want.length) throw new Error(`${s.alt}: ${s.presses.length} presses`)
    s.presses.forEach((b, n) => {
      const c = want[n]
      // #972: one blank Button per seed (its label is em + no-break blanks only) in its own absolute Box at top 0
      if (b.n.props.key !== key(c) || blankPx(b.n.props.label) == null || b.top !== 0) throw new Error(`${s.alt}, press ${n}: ${JSON.stringify([b.n.props, b.top, b.left])}`)
    })
    seedCheck(s, want.map((c: any) => String(c.seed))) // start / width on the drawn capsule, lefts increasing
  })
  // nothing is picked: no detail
  if (all.some(x => x.n.type === 'Svg' && /^(Smite|Spark|Nameless)( · |$)/.test(String(x.n.props.alt)))) throw new Error('a detail with nothing picked')
  await ui.unmount()
})

test('desktop: a picked build = an accent capsule on a selected strip that speaks for it; the head repeats nothing', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast }, 123)
  const cells = job.progress.cells
  const state = async () => { const all = await placed(ui); return { all, ss: strips(all) } }
  const headOf = (all: Placed, name: string) => all.find(x => x.n.type === 'Svg' && (String(x.n.props?.alt) === name || String(x.n.props?.alt).startsWith(`${name} · `)))?.n.props
  const headWords = (all: Placed, name: string) => { const h = headOf(all, name); return h ? svgWords(dq(String(h.source))) : [] }
  // the capsule of a one-digit seed at press column `col`: from 17 px left of the column
  const capAt = (src: string, col: number) => { const c = capsules(src); return c.length === 1 && Math.abs(c[0]! - (col * 7.8 - 17)) < 0.06 }
  // a running build: its strip is the selected one, the capsule around its mark and seed, the act and the time are
  // that build's; every other press dims; no build to load yet, so the head alone, and it does not say seed / state / time
  await ui.press({ key: key(cells[1]) })
  let { all, ss } = await state()
  let spark = ss[2]!
  if (!isSel(spark.src) || !capAt(spark.src, 47) || ss.some((s, i) => i !== 2 && (isSel(s.src) || capsules(s.src).length))) throw new Error('picked strip: ' + JSON.stringify(ss.map(s => [isSel(s.src), capsules(s.src)])))
  if (!same(spark.words, ['Spark', 'Elementalist', '4', '5', '6', 'считается', 'идёт 10 мин']) || !textOf(spark.src, 'считается').includes('class="tx"')) throw new Error('running strip: ' + spark.words.join(' | '))
  if (spark.alt !== 'Билд «Spark»: seed 4 считается, seed 5 ждёт, seed 6 ждёт · считается · идёт 10 мин') throw new Error('alt: ' + spark.alt)
  // #972: the presses are blank Buttons (one per seed, key cell-…); the picture draws each seed, every one but the picked in the muted colour
  const btns = all.filter(x => x.n.type === 'Button' && String(x.n.props?.key).startsWith('cell-'))
  const seedTx = ss.flatMap(st => [...dq(st.src).matchAll(/<text [^>]*class="tx"( style="fill:([^"]*)")?[^>]*>(\d+)<\/text>/g)].map(m => ({ key: st.alt, seed: m[3]!, muted: m[2] === K.muted })))
  if (btns.length !== cells.length || seedTx.length !== cells.length || seedTx.filter(t => !t.muted).length !== 1 || seedTx.find(t => !t.muted)!.key !== spark.alt) throw new Error('dimmed presses: ' + JSON.stringify([btns.map(b => b.n.props.key), seedTx]))
  if (!same(headWords(all, 'Spark'), ['Spark', 'Witch / Elementalist'])) throw new Error('running head: ' + headWords(all, 'Spark').join(' | '))
  const noRepeat = async () => {
    const texts = (await seen(ui)).map(t => t.trim())
    const bad = texts.filter(t => t === 'состояние' || t === 'время' || t === 'main stat' || /^started /.test(t) || /^seed \d+ · /.test(t))
    if (bad.length) throw new Error('the strip\'s facts are repeated under it: ' + bad.join(' | '))
  }
  await noRepeat()
  // a waiting build of the same line: the capsule moves to its column; «ждёт», muted, no time
  await ui.press({ key: key(cells[4]) })
  ;({ all, ss } = await state())
  spark = ss[2]!
  if (!isSel(spark.src) || !capAt(spark.src, 53) || !same(spark.words, ['Spark', 'Elementalist', '4', '5', '6', 'ждёт']) || !textOf(spark.src, 'ждёт').includes('class="mu"')) throw new Error('waiting strip: ' + spark.words.join(' | '))
  if (!same(headWords(all, 'Spark'), ['Spark', 'Witch / Elementalist'])) throw new Error('waiting head: ' + headWords(all, 'Spark').join(' | '))
  // a failed build of a run with no folder: «упал» in the failed colour, its time (86 s stays seconds)
  await ui.press({ key: key(cells[2]) })
  ;({ all, ss } = await state())
  if (!isSel(ss[0]!.src) || !capAt(ss[0]!.src, 53) || !same(ss[0]!.words, ['Smite', 'Slayer', '4', '5', 'упал', '86 с']) || !textOf(ss[0]!.src, 'упал').includes('class="er"')) throw new Error('failed strip: ' + ss[0]!.words.join(' | '))
  if (!same(headWords(all, 'Smite'), ['Smite', 'Duelist / Slayer'])) throw new Error('failed head: ' + headWords(all, 'Smite').join(' | '))
  // a variant's build: its own strip is the selected one; the head is titled by the build's own name; a done build
  // of a running run that has no folder yet says when its full stats come
  await ui.press({ key: key(cells[3]) })
  ;({ all, ss } = await state())
  if (!isSel(ss[1]!.src) || isSel(ss[0]!.src) || !capAt(ss[1]!.src, 47) || !same(ss[1]!.words, ['Smite · no Versatile Combatant', 'Slayer', '4', 'готово', '64 мин'])) throw new Error('variant strip: ' + ss[1]!.words.join(' | '))
  if (!same(headWords(all, 'Smite · no Versatile Combatant'), ['Smite · no Versatile Combatant', 'Duelist / Slayer',
    'полные статы и PoB — когда ран закончится: replay пишет их только в конце'])) throw new Error('variant head: ' + headWords(all, 'Smite · no Versatile Combatant').join(' | '))
  // a done build with metrics: the strip says its state and its ratio to the author (131 %: green) and its time;
  // with no loaded build the same versus table as the stats (metric | наш | bar + % | автор)
  await ui.press({ key: key(cells[0]) })
  ;({ all, ss } = await state())
  if (!isSel(ss[0]!.src) || !capAt(ss[0]!.src, 47) || !same(ss[0]!.words, ['Smite', 'Slayer', '4', '5', 'готово', '52 мин']) || !textOf(ss[0]!.src, 'готово').includes('class="ok"')) throw new Error('done strip: ' + ss[0]!.words.join(' | '))
  const head = headOf(all, 'Smite')
  if (head.width !== 959 || Number(head.height) !== Number(/height="([\d.]+)"/.exec(dq(String(head.source)))?.[1])) throw new Error('head size')
  const mt = all.find(x => x.n.type === 'Svg' && x.n.props?.alt === 'Smite metrics')?.n.props
  const mw = mt ? svgWords(dq(String(mt.source))) : []
  for (const w of ['показатель', 'наш', 'наш / автор', 'автор (адапт.)', 'Combined DPS', '737,408', '561,007', '131 %', 'Phys Max Hit', '97 %'])
    if (!mw.includes(w)) throw new Error(`metrics table lacks «${w}»: ${mw.join(' | ')}`)
  if (mt.width !== 959 || mt.height !== 4 * CELL_PX || mt.isInteractive) throw new Error(`metrics table ${mt.width} x ${mt.height}`)
  const hov = all.filter(x => x.n.type === 'Box' && /^mt-h\d+$/.test(String(x.n.props?.key)))
  // #613: #837 pass 2: each row's hover Box is its own absolute Box at its `top`; rows 1, 2, 3
  // #995 send-back 2 row 3: a table row draws no light of its own (one light rule): its keyed Box keeps its place, with no light
  const tops = hov.map(x => [x.n.props.position === 'absolute' ? Number(x.n.props.top) : NaN, x.n.props.height, rowLight(x.n)])
  if (!same(tops, [1, 2, 3].map(t => [t, 1, false]))) throw new Error('metrics hover Boxes: ' + JSON.stringify(hov.map(x => x.n)))
  await noRepeat()
  // pressed again: the build closes, the strip speaks for its line again
  await ui.press({ key: key(cells[0]) })
  ;({ all, ss } = await state())
  if (ss.some(s => isSel(s.src) || capsules(s.src).length) || headOf(all, 'Smite') || !ss[0]!.words.includes('1 готово · 1 упал')) throw new Error('the build did not close')
  await ui.unmount()
})

test('desktop: the face of a line\'s ascendancy stands in its rail; a single build under the author reads by its ratio', async ($, on) => {
  on('fs.read', async (_$: any, e: any) => {
    if (/[\\/]assets[\\/]asc[\\/]\w+_16x16\.png$/.test(e.path) && e.as === 'bytes' && !/slayer/.test(e.path)) return { value: { base64: PNG } } as any
    throw new Error('ENOENT ' + e.path)
  })
  const v2 = JSON.parse(fast)
  const pct = (p: number) => [['Combined DPS', 1000 * p, 100_000]]
  v2.runs.running[0].progress.cells = [
    { ref: 'spark', name: 'Spark', seed: 4, state: 'done', took: '61 min', class: 'Witch', asc: 'Elementalist', metrics: pct(72) },
    { ref: 'smite', name: 'Smite', seed: 4, state: 'done', took: '52 min', class: 'Duelist', asc: 'Slayer', metrics: pct(86) },
    { ref: 'rf', name: 'Righteous Fire', seed: 4, state: 'done', took: '40 min', class: 'Marauder', metrics: [['Total DoT DPS', 216282.4, null]] },
    { ref: 'la', name: 'Lightning Arrow', seed: 4, state: 'waiting', class: 'Ranger', asc: 'Deadeye' },
  ]
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(v2) }, 123)
  const ss = strips(await placed(ui))
  // a face: the 16-px picture at the rail's centre, pixel art; an ascendancy with no asset draws the class dot;
  // a build with no ascendancy asks for its class's face and names its class
  if (!ss[0]!.src.includes(`<image href="data:image/png;base64,${PNG}" x="${GRID.rail / 2 - 8}" y="2" width="16" height="16" style="image-rendering:pixelated"/>`) || ss[0]!.src.includes('<circle')) throw new Error('no face on Spark')
  if (ss[1]!.src.includes('<image') || !ss[1]!.src.includes(`<circle cx="${GRID.rail / 2}" cy="10" r="3.2" fill="#FFD79E"/>`)) throw new Error('Smite: a face with no asset')
  if (!ss[2]!.src.includes('<image') || !ss[2]!.words.includes('Marauder')) throw new Error('Righteous Fire: ' + ss[2]!.words.join(' | '))
  // one build a line: its state and its main number: under 80 % of the author red, 80..99 % the text colour, no
  // author = the metric by its name; a waiting build is muted
  const want: [string, string][] = [['готово', 'er'], ['готово', 'tx'], ['готово', 'tx'], ['ждёт', 'mu']]
  want.forEach(([t, cls], i) => { if (!textOf(ss[i]!.src, t).includes(`class="${cls}"`)) throw new Error(`strip ${i}: ${ss[i]!.words.join(' | ')}`) })
  await ui.unmount()
})

// #837 b11 D6: the seeds of a row are the links of ONE Markdown (key = the first seed's key, the href's last segment names the seed): each press reaches its own seed
test('desktop: the three seeds of one row are three blank Buttons (one each, in absolute Boxes at top 0), and each press reaches its own seed (#972)', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast }, 123)
  const btns = (await placed(ui)).filter(x => x.n.type === 'Button' && x.n.props.key.startsWith(`cell-${job.id}-spark-`))
  const sparkKeys = [4, 5, 6].map(s => key({ ref: 'spark', seed: s }))
  const row = (await ui.findAll({ type: 'Button' })).filter((m: any) => String(m.key ?? m.props?.key).startsWith(`cell-${job.id}-spark-`))
  if (row.length !== 3 || !same(row.map((m: any) => m.key ?? m.props?.key), sparkKeys)) throw new Error('three Buttons for the spark row: ' + JSON.stringify(row.map((m: any) => m.key)))
  if (!same(btns.map(x => [x.n.props.key, x.top]), sparkKeys.map(k => [k, 0])) || btns.some(x => blankPx(x.n.props.label) == null)) throw new Error('placed Buttons: ' + JSON.stringify(btns.map(x => [x.n.props.key, x.top, x.left])))
  const sp = strips(await placed(ui))[2]!
  const [ws, ww] = seedCheck(sp) // starts within 1.5 px of the drawn capsules, widths within 3 px, lefts strictly increasing
  console.log(`#972 seeds of the Spark row: lefts ${btns.map(x => x.left).join('/')}, leads ${btns.map(x => x.lead).join('/')}, worst start ${ws.toFixed(2)} px, worst width ${ww.toFixed(2)} px`)
  for (const [n, k] of sparkKeys.entries()) {
    await ui.press({ key: k })
    const spark = strips(await placed(ui))[2]!
    const cap = capsules(spark.src)
    if (!isSel(spark.src) || cap.length !== 1 || Math.abs(cap[0]! - (COLS[n]! * 7.8 - 17)) > 0.06) throw new Error(`seed ${n} (${k}): capsule ${JSON.stringify(cap)}`)
  }
  await ui.unmount()
})

test('desktop: seeds past the act column wrap to a strip of their own; a run with no ticket is named by its tag', async ($, on) => {
  const v2 = JSON.parse(fast)
  const j2 = v2.runs.running[0]
  j2.issue = null
  j2.progress.cells = [4, 5, 6, 7, 8, 9, 10].map(seed => ({ ref: 'spark', name: 'Spark', seed, state: seed === 4 ? 'running' : 'done', took: '9 min', started: now - 60, class: 'Witch', asc: 'Elementalist' }))
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(v2) }, 123)
  const all = await placed(ui)
  // a label row with no press is a bare picture (#771: no Box around it), found by its alt; no Link carries the tag
  const lp = all.find(x => x.n.type === 'Svg' && String(x.n.props?.alt) === `Билды ${j2.tag}`)?.n.props
  if (lp?.alt !== `Билды ${j2.tag}` || svgWords(dq(String(lp.source)))[0] !== `Билды ${j2.tag}` || all.some(x => x.n.type === 'Link' && x.n.props?.label === j2.tag)) throw new Error('label of a run with no ticket: ' + JSON.stringify(lp && svgWords(dq(String(lp.source)))))
  const ss = strips(all)
  if (ss.length !== 2) throw new Error(`${ss.length} strips`)
  // five one-digit seeds end left of the act column (x 576); the sixth starts the continuation strip at the first column
  // #972: one blank Button a seed (starts on its drawn capsule, lefts strictly increasing, not a fixed cell any more)
  if (!same(ss[0]!.presses.map(b => seedOf(b)), ['4', '5', '6', '7', '8'])) throw new Error('first strip: ' + JSON.stringify(ss[0]!.presses.map(b => [seedOf(b), b.left, b.lead])))
  if (!same(ss[1]!.presses.map(b => seedOf(b)), ['9', '10'])) throw new Error('continuation: ' + JSON.stringify(ss[1]!.presses.map(b => [seedOf(b), b.left, b.lead])))
  seedCheck(ss[0]!); seedCheck(ss[1]!)
  // the continuation starts again at the first column: its first Button is where the first strip's first one is
  if (Math.abs(startPx(ss[1]!.presses[0]!.left!, ss[1]!.presses[0]!.lead) - startPx(ss[0]!.presses[0]!.left!, ss[0]!.presses[0]!.lead)) > 1.5) throw new Error('the continuation does not start at the first column')
  // the continuation: no name, no rail mark, no words; the line's tint and dither; its marks at its presses
  if (!same(ss[1]!.words, ['9', '10']) /* #837 b8: the seeds are its only words */ || ss[1]!.src.includes('<circle') || ss[1]!.src.includes('<image') || pill(ss[1]!.src) !== '#9CBBFD' || dithered(ss[1]!.src) /* #994 defect 8: one flat fill */) throw new Error('continuation strip: ' + ss[1]!.words.join(' | '))
  if (ss[1]!.alt !== 'Билд «Spark», ещё: seed 9 готово, seed 10 готово' || ss[1]!.marks.length !== 2) throw new Error('continuation alt / marks: ' + ss[1]!.alt)
  if (!ss[0]!.words.includes('6 готово · 1 считается')) throw new Error('the line\'s counts: ' + ss[0]!.words.join(' | '))
  // a picked build on the continuation: both strips of the line are selected, the capsule is on the continuation,
  // the first strip speaks for the picked build
  await ui.press({ key: `cell-${j2.id}-spark-10` })
  const s2 = strips(await placed(ui))
  if (!isSel(s2[0]!.src) || !isSel(s2[1]!.src) || capsules(s2[0]!.src).length || capsules(s2[1]!.src).length !== 1 || !same(s2[0]!.words, ['Spark', 'Elementalist', '4', '5', '6', '7', '8', 'готово', '9 мин'])) throw new Error('picked on the continuation: ' + s2[0]!.words.join(' | '))
  await ui.unmount()
})

// The owner's rule (10.10, on the mock of the Builds tab): «Если что то не умещается и многоточит, значит оно там
// быть не должно»: the same rule on the strips: a long name pushes the later columns right, the ascendancy leaves
// when they no longer fit, what the line came to keeps only the parts that fit whole.
const LONG = 'Volcanic Fissure of Snaking · no Versatile Combatant'
for (const cols of [123, 105]) {
  test(`desktop, ${cols} columns: no strip of the squares cuts a word with «…»; the names stand whole`, async ($, on) => {
    const v3 = JSON.parse(fast)
    const j3 = v3.runs.running[0]
    const R = [['Combined DPS', 1204000, 1158000]]
    const vf = { ref: 'vfos', name: LONG, variant: 'no-versatile_combatant', class: 'Marauder', asc: 'Chieftain' }
    j3.progress.cells = [
      { ...vf, seed: 4, state: 'done', took: '2 h 04 min', metrics: R },
      { ...vf, seed: 5, state: 'running', took: '10:42', started: now - 600 },
      { ...vf, seed: 6, state: 'waiting' },
      { ref: 'absolution_minions', name: 'Absolution Minions · no Eldritch Battery', seed: 4, variant: 'no-eldritch_battery', state: 'done', took: '2 h 04 min', class: 'Templar', asc: 'Guardian', metrics: R },
      { ref: 'smite', name: 'Smite', seed: 4, state: 'done', took: '52 min', class: 'Duelist', asc: 'Slayer', metrics: R },
    ]
    const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(v3) }, cols)
    let ss = strips(await placed(ui))
    const bad = () => ss.flatMap(x => x.words).filter(w => w.endsWith('…'))
    if (bad().length) throw new Error('cut: ' + bad().join(' | '))
    if (!same(ss.map(x => x.words[0]), [LONG, 'Absolution Minions · no Eldritch Battery', 'Smite'])) throw new Error('names: ' + ss.map(x => x.words[0]).join(' | '))
    // 123 columns (the owner's pane): the worst line keeps every column whole
    if (cols === 123 && !same(ss.map(x => x.words), [
      [LONG, 'Chieftain', '4', '5', '6', '1 готово · 1 считается · 1 ждёт'], // #837 b8: the seeds are drawn in the picture
      ['Absolution Minions · no Eldritch Battery', 'Guardian', '4', 'готово', '2 ч 4 мин'],
      ['Smite', 'Slayer', '4', 'готово', '52 мин'],
    ])) throw new Error('strips: ' + JSON.stringify(ss.map(x => x.words)))
    // the columns are one grid for the block: a short name's ascendancy stands where the long one's does
    const metaX = ss.map(x => Number(/<text x="([\d.]+)" [^>]*class="mu">(?:Chieftain|Guardian|Slayer)</.exec(x.src)?.[1]))
    if (cols === 123 && (new Set(metaX).size !== 1 || !(metaX[0]! > 244))) throw new Error('meta column: ' + metaX.join(' '))
    // picked: the strip speaks for that build, still whole
    await ui.press({ key: `cell-${j3.id}-vfos-4-no-versatile_combatant` })
    ss = strips(await placed(ui))
    if (bad().length) throw new Error('cut, picked: ' + bad().join(' | '))
    if (cols === 123 && !same(ss[0]!.words, [LONG, 'Chieftain', '4', '5', '6', 'готово', '2 ч 4 мин'])) throw new Error('picked strip: ' + ss[0]!.words.join(' | '))
    await ui.unmount()
  })
}

test('terminal: the squares stay glyph presses with the facts as text', async ($, on) => {
  const ui = await mountPane($, on, 'terminal', { tab: 'pob', fast }, 123)
  const btns = (await ui.findAll({ type: 'Button' })).filter((b: any) => String(b.key).startsWith('cell-'))
  if (btns.length !== job.progress.cells.length) throw new Error(`${btns.length} presses`)
  await ui.press({ key: key(job.progress.cells[0]) })
  const texts = (await seen(ui)).map(t => t.trim())
  for (const w of ['состояние', 'done', 'время', '52 min', 'Combined DPS']) if (!texts.includes(w)) throw new Error(`terminal lacks «${w}»: ${texts.slice(-40).join(' | ')}`)
  await ui.unmount()
})
