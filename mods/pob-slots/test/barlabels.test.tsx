import { test } from 'claude-code/testing'
import { FAST } from './fixtures'
import { mountPane, bars } from './kit'

// #822 F2: every share of the CPU / RAM stacked bars is labelled under the bar, none inside a segment.
const base = JSON.parse(FAST)
base.machine.cpu = { pob: 60, agents: 5, you: 3 } // one wide share, two under ~8 %
base.machine.ram = { pob: 14, agents: 1.2, you: 0.8 }
const fast = JSON.stringify(base)
const attr = (tag: string, k: string) => Number(new RegExp(`${k}="([-0-9.]+)"`).exec(tag)?.[1])

test('F2: stack labels all under the bar, 0 inside', async ($, on) => {
  const ui = await mountPane($, on, 'desktop', { fast }, 123)
  const pc = String((await ui.findAll({ type: 'Svg' })).find((s: any) => s.props?.alt === 'PC load')?.props?.source ?? '')
  const doc = pc.replace(/<style>[\s\S]*?<\/style>/g, '')
  // segments: height-20 rects inside the clipped bar groups (the 1st of each group is the veil track)
  const segs = [...doc.matchAll(/<rect [^>]*height="20"[^>]*\/>/g)].map(m => m[0])
  const texts = [...doc.matchAll(/<text ([^>]*)>([^<]*)<\/text>/g)].map(m => ({ x: attr(m[1]!, 'x'), y: attr(m[1]!, 'y'), t: m[2]!, a: m[1]! }))
  const bar = segs.map(r => ({ x: attr(r, 'x'), w: attr(r, 'width'), y: attr(r, 'y') }))
  // a label is inside when its anchor lies in any bar rect (the value at the right edge is outside every bar)
  const inside = texts.filter(t => /class="(sg|mu nu)/.test(t.a) && bar.some(b => t.x >= b.x && t.x <= b.x + b.w && t.y >= b.y && t.y <= b.y + 20)).length
  const want = ['PoB 60 %', 'agents 5 %', 'you 3 %', 'PoB 14.0 GB', 'agents 1.2 GB', 'you 0.8 GB']
  const under = want.map(w => texts.filter(t => t.t === w).length)
  console.log(`inside labels ${inside} | under-bar counts ${JSON.stringify(under)}`)
  if (inside !== 0) throw new Error('labels inside a bar: ' + inside)
  if (under.some(n => n !== 1)) throw new Error('under-bar labels not once each: ' + JSON.stringify(under))
  await ui.unmount()
})
