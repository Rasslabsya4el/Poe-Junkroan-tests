import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen, bars, svgWords } from './kit'
import { textWidth } from '../hooks/draw'

// #773 (owner 10.10 18:4x): in PoB runs the builds done out of the total are a bar in the run's own line (no track row),
// and priority / machine / slots are three small pictures; the words stay in the row's alt.
const GLYPH = /[▸▾▶◀▴○●◦◆◉⧗⏳✓✔✕✖⊘◷■□•←↑↓]/
const fixture = () => {
  const f = JSON.parse(FAST)
  const base = f.runs.queued[0]
  const cell = f.runs.running[0].progress.cells.find((c: any) => c.state === 'running')
  const bcell = { ...cell, name: 'Bar Build', class: 'Templar', stage: 'improvement loop, pass 2', bar: { w: [0.4706, 0.528, 0.0014], fill: [1, 0.5, 0], at: 1 }, started: Math.round(Date.now() / 1000) - 600 }
  f.runs.running = [{ ...base, id: 'j-r', tag: 'P1-#719-3', issue: 719, host: 'pc', priority: 'P1', state: 'running', locks: 2, workers: 2, left_h: '40 min',
    progress: { done: 1, total: 3, total_open: true, eta: null, dir: 'x', cells: [bcell] } }]
  f.runs.queued = [{ ...base, id: 'j-q', tag: 'P2-#553-9', issue: 553, host: 'laptop', priority: 'P2', workers: 3 }]
  f.runs.history = [{ ...base, id: 'h1', tag: 'P0-#553-8', issue: 553, state: 'done', host: 'pc', priority: 'P0', workers: 1, dur: '55 min', date: '10.10', start: '00:46', rows_done: 6, rows_total: 6 }]
  return JSON.stringify(f)
}
const row = async (ui: any, tag: string, state: string) =>
  (await bars(ui)).filter((p: any) => String(p.alt).startsWith(`${tag} ${state}`))
const dashed = (src: string) => [...src.matchAll(/<path d="M[\d.]+ [\d.]+h([\d.]+)" stroke-width="8" stroke-dasharray="([\d.]+) ([\d.]+)" stroke="([^"]+)"/g)]
  .map(m => ({ len: Number(m[1]), seg: Number(m[2]), gap: Number(m[3]), color: m[4]! }))

// #995 row 3 (the owner, 14.10: «Мне не нужна шкала с квадратиками отображающая колво билдов, х/у достаточно»): the run's builds are the text «done / total» right-aligned
// in the «билды» column (x 552..618), no segments; a build row's old bar (the groups' shares, the loop filled by a time guess) is gone and only a REAL stage stands there:
// «этап N / M» from the collector's `stage_index` / `stage_count` (addon.py build_stage, #985 c)
const countText = (src: string) => [...src.matchAll(/<text x="([\d.]+)" y="[\d.]+" text-anchor="end" class="([^"]*)">([^<]+)<\/text>/g)].map(m => ({ x: Number(m[1]), cls: m[2]!, t: m[3]! }))
test('desktop: a running run with 1 / 3+ builds: no track row, no bar, the text «1 / 3+» right-aligned in the builds column', async ($, on) => {
  const f = JSON.parse(fixture())
  const c0 = f.runs.running[0].progress.cells[0]
  f.runs.running[0].progress.cells.push({ ...c0, name: 'Staged Build', ref: 'ref-staged', stage_index: 22, stage_count: 25 })
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 160)
  const pics = await row(ui, 'P1-#719-3', 'running')
  if (pics.length !== 1) throw new Error('the run has a track row: ' + pics.map((p: any) => p.alt).join(' | '))
  if (dashed(pics[0].src).length) throw new Error('a segment bar is drawn: ' + JSON.stringify(dashed(pics[0].src)))
  const cnt = countText(pics[0].src).filter(t => t.t === '1 / 3+')
  if (cnt.length !== 1 || cnt[0]!.x !== 618) throw new Error('the count: ' + JSON.stringify(countText(pics[0].src)))
  if (!String(pics[0].alt).includes('1 / 3+ билда')) throw new Error('alt: ' + pics[0].alt)
  // a build with no real stage: nothing in its builds column (no zone rects); one with a real stage: «этап 22 / 25» there
  const build = (await bars(ui)).find((p: any) => String(p.alt).startsWith('Bar Build:'))
  if (!build) throw new Error('no build row')
  if (/height="8" rx="1.5"/.test(String(build.src))) throw new Error('a build row still draws the bar of three groups')
  if (countText(String(build.src)).some(t => /этап|\//.test(t.t))) throw new Error('a stage with no real stage: ' + JSON.stringify(countText(String(build.src))))
  const staged = (await bars(ui)).find((p: any) => String(p.alt).startsWith('Staged Build:'))
  const st = countText(String(staged?.src ?? '')).filter(t => t.t === 'этап 22 / 25')
  if (st.length !== 1 || st[0]!.x !== 618) throw new Error('the real stage: ' + JSON.stringify(countText(String(staged?.src ?? ''))))
})

test('desktop: a run of 0 / 1 builds draws the text «0 / 1», no segment', async ($, on) => {
  const f = JSON.parse(fixture())
  f.runs.running[0].progress = { done: 0, total: 1, total_open: false, eta: null, dir: 'x', cells: [] }
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 160)
  const src = (await row(ui, 'P1-#719-3', 'running'))[0].src
  if (dashed(src).length || !countText(src).some(t => t.t === '0 / 1')) throw new Error('0 / 1: ' + JSON.stringify(countText(src)))
})

test('desktop: meta of running, queued and finished rows = three pictures, the words only in alt', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: fixture() }, 160)
  const want: [string, string, number, number, string[]][] = [ // tag, state, lit bars, squares, words in alt
    ['P1-#719-3', 'running', 2, 2, ['P1', 'pc', '2 слота']], ['P2-#553-9', 'queued', 1, 3, ['P2', 'laptop', '3 слота']], ['P0-#553-8', 'done', 3, 1, ['P0', 'pc', '6 / 6 билдов']]]
  for (const [tag, state, lit, sq, words] of want) {
    const p = (await row(ui, tag, state))[0]
    if (!p) throw new Error('no row ' + tag)
    const src = String(p.src), said = svgWords(src).filter(w => w !== tag).join(' | ') // #837 u4: the title (here the run's tag) is drawn in the picture
    if (/P[0-2]\b|\bpc\b|laptop|(^|, )\d+ слот/.test(said)) throw new Error(`${tag}: words in the drawn row: ${said}`)
    for (const w of words) if (!String(p.alt).includes(w)) throw new Error(`${tag}: alt misses «${w}»: ${p.alt}`)
    const litD = /<path d="([^"]*)" fill="#f0f6fc"\/>/.exec(src)?.[1] ?? ''
    if ((litD.match(/M/g) ?? []).length !== lit) throw new Error(`${tag}: lit bars ${(litD.match(/M/g) ?? []).length}, want ${lit}`)
    const host = tag.startsWith('P2') ? 'M18 5a2 2 0 0 1 2 2v8.526' : 'M14.25 1c.966'
    if (!src.includes(host)) throw new Error(`${tag}: no machine icon`)
    if ((src.match(/h3v5h-3z/g) ?? []).length !== sq) throw new Error(`${tag}: squares ${(src.match(/h3v5h-3z/g) ?? []).length}, want ${sq}`)
    if (!/stroke-width="3" stroke-linejoin="round"/.test(src)) throw new Error(`${tag}: a square is not 6 x 8 px with a 1.5 corner`)
  }
  const fin = (await row(ui, 'P0-#553-8', 'done'))[0]
  if (!svgWords(fin.src).includes('10.10 00:46')) throw new Error('a finished row keeps its date and start: ' + svgWords(fin.src).join('|'))
  // #995 row 3: a finished run's builds are the text «6 / 6», no bar
  if (dashed(fin.src).length || !countText(fin.src).some(t => t.t === '6 / 6')) throw new Error('finished count: ' + JSON.stringify(countText(fin.src)))
})

test('desktop: the main tab draws no text mark in place of a picture', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: fixture() }, 160)
  const bad = (await seen(ui)).filter(w => GLYPH.test(w))
  if (bad.length) throw new Error('a text character stands for an icon: ' + JSON.stringify(bad.slice(0, 8)))
})

// #773 row 1, moved by #837 unit 11 (autopilot comparison 00:08Z: the baseline 50ea5412 grid, meta 428/120): a finished run's squares (3 and 8) stay,
// its "date start" is cut to the room left of them, as the baseline cut it: no text past x 548, a cut one is a prefix of the date ending in `…`
test('123 columns: a finished row with 3 and 8 slots keeps its squares, its date and start are cut inside the 120 px meta column', async ($, on) => {
  const f = JSON.parse(fixture())
  const h = f.runs.history[0]
  f.runs.history = [
    { ...h, id: 'h3', tag: 'P0-#553-3', workers: 3, date: '10.10', start: '17:15' },
    { ...h, id: 'h8', tag: 'P1-#553-8', workers: 8, date: '09.10', start: '23:05' }]
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 123)
  for (const [tag, want] of [['P0-#553-3', '10.10 17:15'], ['P1-#553-8', '09.10 23:05']]) {
    const p = (await row(ui, tag!, 'done'))[0]
    if (!p) throw new Error('no row ' + tag)
    const w = svgWords(p.src)
    const squares = (p.src.match(/h3v5h-3z/g) ?? []).length
    if (squares !== (tag === 'P0-#553-3' ? 3 : 8)) throw new Error(`${tag}: ${squares} squares`)
    const d = w.filter(x => /^\d\d\.\d\d/.test(x))
    console.log(`DATE ${tag}: ${JSON.stringify(d)}`)
    if (d.some(x => !want!.startsWith(x.replace(/…$/, '')))) throw new Error(`${tag}: want a prefix of «${want}», drawn: ${JSON.stringify(w)}`)
    for (const x of d) { const at = Number(new RegExp(`<text x="([\d.]+)"[^>]*>${x.slice(0, 5)}`).exec(p.src)?.[1]); if (at + textWidth(x) > 549) throw new Error(`${tag}: the date ends at ${at + textWidth(x)}, past the meta column`) }
  }
  await ui.unmount()
})
