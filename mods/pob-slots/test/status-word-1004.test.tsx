import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, bars, svgWords } from './kit'

// #1004 unit 1 (the owner, 14.10: the monitor's build rows say the raw stage, «loop pass 4 …», in English): a running build's act text is its status
// word (addon.py `status`, the data's own Russian words, «строит Tree», «подбирает Items»); the raw `stage` stays in the row's alt only; a cell with no
// status keeps today's fallback (its stage), never an invented word. A started build row is never drawn with an empty act.
test('#1004 u1: a running run draws each started build row with its status word; the raw stage of a cell with a status is not drawn; no status keeps the stage', async ($, on) => {
  const f = JSON.parse(FAST)
  const job = f.runs.running[0]
  const now = Math.round(Date.now() / 1000)
  const cell = job.progress.cells.find((c: any) => c.state === 'running') ?? job.progress.cells[0]
  const kid = (name: string, extra: Record<string, unknown>) => ({ ...cell, status: undefined, name, ref: `ref-${name}`, seed: 1, state: 'running', class: 'Templar', asc: 'Hierophant', started: now - 600, ...extra })
  job.progress.cells = [
    kid('Status Tree', { status: 'строит Tree', stage: 'tree greedy' }),
    kid('Status Items', { status: 'подбирает Items', stage: 'gear pass 2 (with tree)' }),
    kid('No Status', { stage: 'loop pass 4, gear' }),
  ]
  f.runs.running = [job]
  f.runs.queued = []
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: JSON.stringify(f) }, 160)
  const rows = await bars(ui)
  const want: [string, string, string | null][] = [['Status Tree', 'строит Tree', 'tree greedy'], ['Status Items', 'подбирает Items', 'gear pass 2 (with tree)'], ['No Status', 'loop pass 4, gear', null]]
  let started = 0
  for (const [name, act, raw] of want) {
    const p = rows.find((r: any) => String(r.alt).startsWith(`${name}:`))
    if (!p) throw new Error(`no row of ${name}: ${rows.map((r: any) => r.alt).join(' | ')}`)
    const words = svgWords(String(p.src))
    console.log(`#1004 u1 ${name}: drawn ${JSON.stringify(words)} alt «${p.alt}»`)
    if (!words.includes(act)) throw new Error(`${name}: no act «${act}» drawn: ${JSON.stringify(words)}`)
    if (raw && words.some((w: string) => w.includes(raw))) throw new Error(`${name}: the raw stage «${raw}» is drawn: ${JSON.stringify(words)}`)
    if (!raw && !words.some((w: string) => w.includes('loop pass 4'))) throw new Error(`${name}: the fallback stage is not drawn: ${JSON.stringify(words)}`)
    started++
  }
  // the status words of the cells that have one are the only act words of their rows; a started build row never draws an empty act
  if (started !== 3) throw new Error(`started build rows drawn: ${started} of 3`)
  await ui.unmount()
})
