import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, seen, svgRows, svgWords, dq } from './kit'

// #1004 unit 2 (the owner, 14.10: «если ран идет на ноуте то я не вижу в режиме лайв как делаются билды также как с ранами на ПК»): a run that
// executes on the LAPTOP shows its builds live exactly like a PC run. The pane draws every running job alike (hooks/addon.tsx runAll): one run strip
// with the `done / total` count, then one row per cell in state `running`. merge_laptop (addon.py) only appends the laptop's rows to the PC's list.
// Fixture: the same running job twice, host 'laptop' and host 'pc', the same three cells (two running, one done).

const NOW = Math.floor(Date.now() / 1000)
const CELLS = [
  { ref: 'alpha_build', name: 'Alpha Build', seed: 4, state: 'running', started: NOW - 300, status: 'строит Tree', stage: 'improvement loop, pass 2' },
  { ref: 'beta_build', name: 'Beta Build', seed: 5, state: 'running', started: NOW - 90, status: 'подбирает Items', stage: 'improvement loop, pass 1' },
  { ref: 'gamma_build', name: 'Gamma Build', seed: 6, state: 'done', took: '12:40', status: 'готово' },
]
const NAMES = ['Alpha Build', 'Beta Build', 'Gamma Build']

const job = (host: 'laptop' | 'pc', tag: string, extra: Record<string, unknown> = {}) => {
  const base = JSON.parse(FAST).runs.running[0]
  return {
    ...base, id: `j-1004-${host}-${tag.slice(-1)}`, tag, issue: null, priority: 'P1', host, state: 'running', workers: 1,
    age: '40 min', date: '14.10', start: '00:20', dur: '40 min', ...extra,
    progress: { done: 3, total: 9, total_open: false, eta: null, dir: 'x', cells: CELLS },
  }
}

const rowsOf = async (ui: any): Promise<{ alt: string; src: string }[]> =>
  (await svgRows(ui)).map((s: any) => ({ alt: String(s.props?.alt ?? ''), src: dq(String(s.props?.source ?? '')) }))

/** one run's card: its strip (the picture whose alt opens with its tag and state) and the build rows drawn after it, up to the next run strip */
const runCard = (rows: { alt: string; src: string }[], tag: string) => {
  const at = rows.findIndex(r => r.alt.startsWith(tag + ' '))
  if (at < 0) throw new Error(`no run strip for ${tag}: ` + rows.map(r => r.alt).join(' | '))
  let end = at + 1
  while (end < rows.length && !/^P\d-/.test(rows[end]!.alt)) end++
  const builds = rows.slice(at + 1, end).filter(r => NAMES.some(n => r.alt.startsWith(n + ': ')))
  return { strip: rows[at]!, builds }
}

test('desktop: a laptop run draws its live build rows exactly like a PC run of the same builds: 3 / 9, 2 running rows, the done cell not drawn', async ($, on) => {
  const f = JSON.parse(FAST)
  f.runs.running = [job('laptop', 'P1-#1004-L'), job('pc', 'P1-#1004-P')]
  f.runs.queued = []
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 160)
  const rows = await rowsOf(ui)
  const lap = runCard(rows, 'P1-#1004-L'), pc = runCard(rows, 'P1-#1004-P')
  const cnt = (c: { strip: { src: string } }) => svgWords(c.strip.src).filter(w => /^\d+ \/ \d+$/.test(w))
  console.log(`#1004 build rows per run: laptop ${lap.builds.length}, pc ${pc.builds.length}; drawn done / total: laptop ${cnt(lap).join(' ') || 'none'}, pc ${cnt(pc).join(' ') || 'none'}`)
  for (const [host, card] of [['laptop', lap], ['pc', pc]] as const) {
    if (!cnt(card).includes('3 / 9')) throw new Error(`${host}: the run's strip lacks «3 / 9»: ${svgWords(card.strip.src).join(' | ')}`)
    if (!card.strip.alt.includes('3 / 9 билд')) throw new Error(`${host}: the strip alt lacks «3 / 9 билд»: ${card.strip.alt}`)
    if (card.builds.length !== 2) throw new Error(`${host}: ${card.builds.length} build rows, not 2: ${card.builds.map(b => b.alt).join(' | ')}`)
    const names = card.builds.map(b => b.alt.split(':')[0])
    if (JSON.stringify(names) !== JSON.stringify(['Alpha Build', 'Beta Build'])) throw new Error(`${host}: the build rows are ${names.join(', ')}`)
  }
  // the same cell, the same words, on either host: the row's alt and its drawn words
  const altOf = (c: typeof lap) => c.builds.map(b => b.alt)
  const wordsOf = (c: typeof lap) => c.builds.map(b => svgWords(b.src))
  if (JSON.stringify(altOf(lap)) !== JSON.stringify(altOf(pc))) throw new Error(`alt differs: ${altOf(lap).join(' | ')} vs ${altOf(pc).join(' | ')}`)
  if (JSON.stringify(wordsOf(lap)) !== JSON.stringify(wordsOf(pc))) throw new Error(`drawn words differ: ${JSON.stringify(wordsOf(lap))} vs ${JSON.stringify(wordsOf(pc))}`)
  // the names and the stage word are drawn on the pane itself (not only in an alt)
  const seenWords = await seen(ui)
  const words = seenWords.join(' | ')
  for (const w of ['Alpha Build', 'Beta Build', 'improvement loop, pass 2']) if (!words.includes(w)) throw new Error(`«${w}» is not drawn: ${words}`)
  // the done cell may stand in the POB tab's builds list of the picked run (not a live row): where it is drawn is printed, not judged here
  console.log('#1004 done cell «Gamma Build» drawn as: ' + (seenWords.filter(w => w.includes('Gamma Build')).map(w => `«${w.slice(0, 60)}»`).join(' ') || 'nowhere'))
  await ui.unmount()
})

test('desktop: a stale laptop run keeps its live build rows drawn, faded, with the time of its last reading', async ($, on) => {
  const f = JSON.parse(FAST)
  f.runs.running = [job('laptop', 'P1-#1004-L', { stale: true, stale_since: '10:30' })]
  f.runs.queued = []
  f.laptop = { error: 'ssh timeout', offline: { seen: '10:30' } }
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 160)
  const rows = await rowsOf(ui)
  const card = runCard(rows, 'P1-#1004-L')
  const words = (await seen(ui)).join(' | ')
  console.log(`#1004 stale laptop run: build rows ${card.builds.length}; faded ${card.strip.src.includes('<g opacity=".45">') ? 'yes' : 'no'}`)
  if (!words.includes('нет связи с ноутом, данные от 10:30')) throw new Error('no stale words: ' + words)
  if (!card.strip.alt.startsWith('P1-#1004-L stale')) throw new Error('the strip is not the stale one: ' + card.strip.alt)
  if (!card.strip.src.includes('<g opacity=".45">')) throw new Error('the stale run is not faded')
  if (card.builds.length !== 2) throw new Error(`stale run: ${card.builds.length} build rows, not 2: ${card.builds.map(b => b.alt).join(' | ')}`)
  await ui.unmount()
})
