import { test } from 'claude-code/testing'
// #863: a queued job whose `--after` predecessor failed reads «держит упавший <job>» in the failure colour, one line,
// no estimate; never «ждёт слот». Fixture: the 2026-10-11 12:26 case (failed j-20261011-1226-6c83, followers -ec7b and -b9ed).
import { FAST } from './fixtures'
import { K } from '../hooks/tokens'
import { dq, mountPane, svgRows } from './kit'

const held = () => {
  const f = JSON.parse(FAST)
  const [a, b] = f.runs.queued
  const mk = (suffix: string, tag: string) => ({ ...a, id: `j-20261011-1226-${suffix}`, tag, issue: 839, after: ['j-20261011-1226-6c83'],
    wait: { kind: 'slots', text: 'слоты: свободно 1 из 5' }, start_s: 600, start_h: '10 min', held_by: { id: 'j-20261011-1226-6c83', tag: 'P1-#839-5' } })
  f.runs.queued = [mk('ec7b', 'P1-#839-6'), mk('b9ed', 'P1-#839-7')]
  void b
  return JSON.stringify(f)
}

test('desktop: a job held by a failed predecessor reads «держит упавший», not «ждёт слот», in one failure-coloured line', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { tab: 'pob', fast: held() }, 160)
  const rows = (await svgRows(ui)).map((r: any) => ({ alt: String(r.props.alt), src: dq(String(r.props.source)) })).filter(r => /queued/.test(r.alt))
  const drawn = rows.map(r => [...r.src.replace(/<style>[\s\S]*?<\/style>/g, '').matchAll(/>([^<>]+)</g)].map(m => m[1]!.trim()).filter(Boolean).join(' | '))
  console.log('drawn: ' + drawn.map(d => `«${d}»`).join(' '))
  const slot = drawn.filter(d => d.includes('ждёт слот')).length
  console.log(`rows reading «ждёт слот»: ${slot} of ${rows.length}`)
  if (rows.length !== 2) throw new Error('queued rows: ' + rows.length)
  if (slot) throw new Error('«ждёт слот» drawn: ' + drawn.join(' || '))
  for (const d of drawn) if (!d.includes('держит упавший #839') || d.includes('~')) throw new Error('reason: ' + d)
  for (const r of rows) {
    const m = /<(?:text|tspan)[^>]*class="er"[^>]*>[^<]*держит/.exec(r.src)?.[0] ?? ''
    if (!m || !r.src.includes(`.er{fill:${K.failed}}`)) throw new Error('not the failure colour ' + K.failed)
    const ys = new Set([...r.src.matchAll(/<(?:text|tspan)\b[^>]*? y="([\d.]+)"/g)].map(x => x[1]))
    const H = Number(/^<svg[^>]* height="([\d.]+)"/.exec(r.src)?.[1])
    console.log(`row height ${H} px, baselines ${ys.size}`)
    if (Math.max(...[...ys].map(Number)) - Math.min(...[...ys].map(Number)) > 1 || H > 30) throw new Error('not one line: ' + H + ' ' + [...ys])
  }
})
