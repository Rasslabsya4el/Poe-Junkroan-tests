import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, dq } from './kit'
import { K, ROLE } from '../hooks/tokens'

// #1018 unit 1: the CPU and RAM bars of the PC card draw the merge (`machine.merge`, bin/collect.py) as a fourth part with its own legend
// entry, so that the parts sum to "now" (cpu_total; ram_total - ram_free). A merge of 0 or absent draws nothing extra.
type Merge = { cpu: number; cpu_raw: number; ram_mb: number }
const reading = (merge?: Merge) => {
  const v = JSON.parse(FAST)
  v.machine = {
    cores: 12, cpu: { pob: 60.0, agents: 15.0, you: 6.0 }, cpu_total: 89.8,
    ram: { pob: 14.0, agents: 3.5, you: 1.5 }, ram_total: 31.9, ram_free: 11.6,
    ...(merge === undefined ? {} : { merge }),
  }
  return JSON.stringify(v)
}
const WITH: Merge = { cpu: 8.7, cpu_raw: 8.7, ram_mb: 1229 }

// one stacked bar of the picture: its track width, its segments (width in px, fill) in drawing order, and its legend words (`name value unit`)
const bar = (src: string, name: string, unit: string) => {
  const g = new RegExp(`<g clip-path="url\\(#cl${name}\\)">([\\s\\S]*?)</g>`).exec(src)?.[1] ?? ''
  const rects = [...g.matchAll(/<rect [^>]*width="([\d.]+)" height="20" fill="([^"]*)" fill-opacity="([^"]*)"\/>/g)]
  const track = Number(rects[0]?.[1])
  const segs = rects.slice(1).map(r => ({ w: Number(r[1]), fill: r[2]! }))
  const legend = [...src.matchAll(/<text [^>]*class="mu nu">([^<]*)<\/text>/g)].map(m => m[1]!)
    .filter(t => new RegExp(`^(PoB|agents|you|мердж) [\\d.]+ ${unit}$`).test(t))
  return { track, segs, legend }
}
const values = (legend: string[]) => legend.map(t => Number(/[\d.]+/.exec(t)![0]))

test('#1018 (a): the parts and the merge sum to "now" (CPU within 1 point, RAM within 0.5 GB); the legend reads «мердж»', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { fast: reading(WITH) }, 123)
  const pc = String((await ui.findAll({ type: 'Svg' })).find((s: any) => s.props?.alt === 'PC load')?.props?.source ?? '')
  const src = dq(pc).replace(/<style>[\s\S]*?<\/style>/g, '')
  const cpu = bar(src, 'CPU', '%'), ram = bar(src, 'RAM', 'GB')
  // CPU: the bar's scale is 100 %, so a segment's share is its width over the track
  const cpuDrawn = cpu.segs.reduce((s, x) => s + (x.w / cpu.track) * 100, 0)
  const cpuLegend = values(cpu.legend).reduce((s, x) => s + x, 0)
  // RAM: the scale is ram_total
  const ramDrawn = ram.segs.reduce((s, x) => s + (x.w / ram.track) * 31.9, 0)
  const ramLegend = values(ram.legend).reduce((s, x) => s + x, 0)
  const mergeSeg = cpu.segs.at(-1)
  console.log(`CPU drawn ${cpuDrawn.toFixed(2)} legend ${cpuLegend} (now 89.8) | RAM drawn ${ramDrawn.toFixed(2)} legend ${ramLegend.toFixed(1)} (now 20.3) | legend ${JSON.stringify(cpu.legend)} ${JSON.stringify(ram.legend)}`)
  if (cpu.segs.length !== 4 || ram.segs.length !== 4) throw new Error(`a bar has ${cpu.segs.length} / ${ram.segs.length} parts, want 4 / 4`)
  if (mergeSeg?.fill !== K.active) throw new Error('the merge part is not drawn in the merge colour ' + mergeSeg?.fill)
  if (Math.abs((mergeSeg.w / cpu.track) * 100 - 8.7) > 0.5) throw new Error('the CPU merge part is not 8.7 points wide')
  if (Math.abs(cpuDrawn - 89.8) > 1 || Math.abs(cpuLegend - 89.8) > 1) throw new Error(`CPU parts do not sum to now: drawn ${cpuDrawn}, legend ${cpuLegend}`)
  if (Math.abs(ramDrawn - 20.3) > 0.5 || Math.abs(ramLegend - 20.3) > 0.5) throw new Error(`RAM parts do not sum to now: drawn ${ramDrawn}, legend ${ramLegend}`)
  if (cpu.legend.length !== 4 || ram.legend.length !== 4) throw new Error('a legend entry is missing: ' + JSON.stringify([cpu.legend, ram.legend]))
  // the legend dot of «мердж» is the colour of its segment (ORCH: the worker's first cut drew it with ROLE[merge] = undefined)
  if (!src.includes(`fill="${K.active}"/><text`)) throw new Error('the legend dot of the merge is not drawn in the merge colour')
  if (src.includes('fill="undefined"')) throw new Error('a legend dot has no colour')
  await ui.unmount()
})

// (b): a merge of 0 or absent: the bar is the three-part bar (the parts at their own shares of 100 % / 31.9 GB, nothing else drawn), no «мердж» entry.
// One mount per test (the mock's hooks are fixed once a test has read the pane), so the two cases are two tests.
const threeParts = async ($: any, on: any, fast: string) => {
  const ui = await mountPane($, on, 'desktop', { fast }, 123)
  const pc = String((await ui.findAll({ type: 'Svg' })).find((s: any) => s.props?.alt === 'PC load')?.props?.source ?? '')
  await ui.unmount()
  const src = dq(pc)
  const cpu = bar(src, 'CPU', '%'), ram = bar(src, 'RAM', 'GB')
  const cpuShares = cpu.segs.map(x => (x.w / cpu.track) * 100), ramShares = ram.segs.map(x => (x.w / ram.track) * 31.9)
  const ok = cpu.segs.length === 3 && ram.segs.length === 3 && cpu.legend.length === 3 && ram.legend.length === 3 && !/мердж/.test(src)
    && cpu.segs.every(s => Object.values(ROLE).includes(s.fill as any))
    && [60, 15, 6].every((v, i) => Math.abs(cpuShares[i]! - v) <= 0.1) && [14, 3.5, 1.5].every((v, i) => Math.abs(ramShares[i]! - v) <= 0.05)
  console.log(`three-part bar: CPU ${cpuShares.map(x => x.toFixed(2)).join(' / ')} | RAM ${ramShares.map(x => x.toFixed(2)).join(' / ')} GB | legend ${cpu.legend.length} + ${ram.legend.length}`)
  if (!ok) throw new Error('the bar is not the three-part bar: ' + JSON.stringify({ cpu: cpu.segs.length, ram: ram.segs.length, legend: [cpu.legend, ram.legend] }))
}
test('#1018 (b1): a merge of 0 draws the three-part bar, no «мердж» entry', async ($, on) => {
  await threeParts($, on, reading({ cpu: 0, cpu_raw: 0, ram_mb: 0 }))
})
test('#1018 (b2): an absent merge (an older payload) draws the three-part bar, no «мердж» entry', async ($, on) => {
  await threeParts($, on, reading())
})
