import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, bars, seen, svgWords } from './kit'

// #837 pass 2 (owner 11.10), unit 3 of 3: the texts of the PoB runs card.
//  rule 4 «В очереди»: the reason = what the job waits for and how long; rule 5 «Билды»: a build row's status is one word
//  of the legend; rule 6 «Идёт»: a build's real stage («этап N / M», #995) sits in the «билды» column, directly left of its status.
const BAD = ['привязан', 'свободно', 'оценки нет', 'займёт', '->']

test('rule 4: queued rows read «ждёт #N · ~time», «ждёт слот», «ждёт RAM»; none of the withdrawn words in a row', async ($, on) => {
  const f = JSON.parse(FAST)
  const [a, b] = f.runs.queued
  a.wait = { kind: 'after', text: 'ждёт P1-#814-2' }; a.host_fixed = true; a.start_s = 6960; a.start_h = '1 h 56 min'; a.takes_h = '36 min'
  b.wait = { kind: 'slots', text: 'слоты: свободно 1 из 5' }; b.takes_h = ''; delete b.start_h
  f.runs.queued.push({ ...b, id: 'j-ram', tag: 'P2-#2-1', issue: 2, wait: { kind: 'ram', text: 'RAM: свободно 4.4 из 8 GB' } })
  f.runs.queued.push({ ...b, id: 'j-plain', tag: 'P2-#1-1', issue: 1, wait: undefined })
  f.laptop = { runs: { ...f.runs, running: [], queued: [], daemon: { host: 'laptop', age_s: 3, slots_total: 6, slots_in_use: 0, reserved: 0, reserved_until: null } } }
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 123)
  const rows = (await bars(ui)).filter((p: any) => / queued,/.test(p.alt))
  const said = Object.fromEntries(rows.map((p: any) => [p.alt.split(' ')[0], svgWords(p.src).find((w: string) => /^ждёт (#|слот|RAM)/.test(w))]))
  console.log('drawn reasons by run: ' + JSON.stringify(said))
  const mine = [a.tag, 'P2-#2-1', 'P2-#1-1'].map(g => said[g])
  if (mine[0] !== 'ждёт #814 · ~1 ч 56 мин' || mine[1] !== 'ждёт RAM' || mine[2] !== 'ждёт слот' || said[b.tag] !== 'ждёт слот') throw new Error('reasons: ' + JSON.stringify(said))
  const all = rows.map((p: any) => svgWords(p.src).join(' | ') + ' ' + p.alt).join(' || ')
  const hits = BAD.filter(w => all.includes(w))
  console.log(`occurrences in the queued rows: ${BAD.map(w => `«${w}» ${all.split(w).length - 1}`).join(', ')}`)
  if (hits.length) throw new Error('withdrawn words drawn: ' + hits.join(', '))
})

test('rule 5: a build row of «Идёт» says one word of the legend; the numbers are in its picked build\'s head', async ($, on) => {
  const f = JSON.parse(FAST)
  const job = f.runs.running[0]
  job.progress = { done: 1, total: 2, total_open: false, eta: null, kind: 'replay', cells: [
    { ref: 'smite', name: 'Smite', seed: 4, state: 'done', took: '5.3 min', class: 'Duelist', asc: 'Slayer', delta: '1,288,274 -> 1,381,385 (+7.23 %)' },
    { ref: 'spark', name: 'Spark', seed: 4, state: 'failed', took: '1 min', class: 'Witch', asc: 'Elementalist', delta: '10 -> 5 (-50 %)' },
  ] }
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 123)
  const rows = (await bars(ui)).filter((p: any) => String(p.alt).startsWith('Билд «'))
  const words = rows.map((p: any) => svgWords(p.src))
  console.log('build rows drawn: ' + JSON.stringify(words))
  if (!words.some(w => w.includes('готово')) || !words.some(w => w.includes('упал'))) throw new Error('no one-word status: ' + JSON.stringify(words))
  if (rows.some((p: any) => BAD.some(w => p.src.includes(w) || p.alt.includes(w)) || /%/.test(p.src))) throw new Error('numbers in a build row: ' + JSON.stringify(words))
  await ui.press({ key: `cell-${job.id}-smite-4` })
  const after = (await seen(ui)).join(' | ')
  if (!after.includes('1,288,274 -> 1,381,385 (+7.23 %)')) throw new Error('the numbers left the panel too: ' + after.slice(-300))
})

// #995 row 3: rule 6 now holds the build's REAL stage: «этап N / M» (stage_index / stage_count, #985 c) right-aligned in the «билды» column, left of its status;
// a build with no real stage (the replay's time bar, the old bar of three groups) draws nothing there
test("rule 6: a running build's real stage «этап N / M» stands in the «билды» column (x ..618), left of its status; no time bar, no bar of groups", async ($, on) => {
  const f = JSON.parse(FAST)
  const job = f.runs.running[0]
  const now = Math.round(Date.now() / 1000)
  job.progress.cells = job.progress.cells.map((c: any) => c.state === 'running'
    ? { ...c, class: 'Templar', asc: 'Hierophant', stage: 'improvement loop, pass 2, gear', started: now - 600, bar: { w: [0.4706, 0.528, 0.0014], fill: [1, 0.5, 0], at: 1 }, stage_index: 22, stage_count: 25 } : c)
  // and a replay build: no stage (its old time bar was no stage)
  job.progress.cells.push({ ref: 'rep', name: 'Replayed', seed: 1, state: 'running', class: 'Witch', asc: 'Elementalist', started_est: now - 120, expect_s: 300 })
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 123)
  const all = await bars(ui)
  for (const [name, status, stage] of [['Hierophant', 'improvement loop', 'этап 22 / 25'], ['Elementalist', 'считается, обычно', '']] as const) {
    const row = all.find((p: any) => svgWords(p.src).includes(name) && svgWords(p.src).some((w: string) => w.startsWith(status)))
    if (!row) throw new Error('no row of ' + name)
    const segs = [...row.src.matchAll(/height="8"/g)].length + [...row.src.matchAll(/<use href="#s/g)].length
    if (segs) throw new Error(`${name}: ${segs} segments drawn`)
    const sx = Number(new RegExp(`<text x="([\\d.]+)"[^>]*>${status}`).exec(row.src)?.[1])
    const st = /<text x="([\d.]+)" y="[\d.]+" text-anchor="end" class="[^"]*">(этап [^<]*)</.exec(row.src)
    console.log(`${name}: stage ${st ? `«${st[2]}» ending at x ${st[1]}` : 'none'}, status text x ${sx}`)
    if (!stage) { if (st) throw new Error(`${name}: a stage with no stage_index: ${st[2]}`); continue }
    if (!st || st[2] !== stage || Number(st[1]) !== 618 || !(618 < sx)) throw new Error(`${name}: stage ${st?.[2]} at ${st?.[1]}, status at ${sx}`)
  }
})
