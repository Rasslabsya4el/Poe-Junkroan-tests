import { test } from 'claude-code/testing'
// #1106: a queued job whose `--after` predecessor still runs or waits reads «ждёт <that tag>», the tag verbatim
// (no `P\d-#N` -> `#N` rewrite, no job id); a job with no predecessor keeps «ждёт слот». Text only: the colour is `wt`.
import { FAST } from './fixtures'
import { dq, mountPane, svgRows } from './kit'

const waitsFor = () => {
  const f = JSON.parse(FAST)
  const [a] = f.runs.queued
  const mk = (suffix: string, tag: string, extra: Record<string, unknown>) => ({ ...a, id: `j-20261015-2010-${suffix}`, tag,
    issue: 406, host: 'laptop', workers: 1, start_s: 600, start_h: '10 min', ...extra })
  f.runs.queued = [
    mk('b1b1', 'P1-#406', { after: ['j-20261013-2220-1c28'], waits_for: { tag: 'P2-core' }, wait: { kind: 'slots', text: 'слоты: свободно 0 из 5' } }),
    mk('c2c2', 'P1-#406-2', { after: ['j-20261013-2220-1c28', 'j-20261015-2010-b1b1'], waits_for: { tag: 'P1-#406' } }),
    mk('d3d3', 'P2-free', { after: [], wait: { kind: 'slots', text: 'слоты: свободно 0 из 5' } }),
  ]
  return JSON.stringify(f)
}

test('desktop: a queued job behind a predecessor reads «ждёт <its tag>», a slot-only job reads «ждёт слот», no job id is drawn', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: waitsFor() }, 160)
  const rows = (await svgRows(ui)).map((r: any) => ({ alt: String(r.props.alt), src: dq(String(r.props.source)) })).filter(r => /queued/.test(r.alt))
  const drawn = rows.map(r => [...r.src.replace(/<style>[\s\S]*?<\/style>/g, '').matchAll(/>([^<>]+)</g)].map(m => m[1]!.trim()).filter(Boolean).join(' | '))
  console.log('drawn: ' + drawn.map(d => `«${d}»`).join(' '))
  if (rows.length !== 3) throw new Error('queued rows: ' + rows.length)
  if (!drawn[0]!.includes('ждёт P2-core') || drawn[0]!.includes('ждёт слот')) throw new Error('row 1: ' + drawn[0])
  if (!drawn[1]!.includes('ждёт P1-#406') || drawn[1]!.includes('ждёт слот')) throw new Error('row 2: ' + drawn[1])
  if (!drawn[2]!.includes('ждёт слот') || drawn[2]!.includes('ждёт P')) throw new Error('row 3: ' + drawn[2])
  for (const d of drawn) if (/j-\d{8}-\d{4}-[0-9a-f]{4}/.test(d)) throw new Error('a job id drawn: ' + d)
})
