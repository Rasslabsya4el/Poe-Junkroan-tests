import { test, expect } from 'claude-code/testing'
import { mountPane, dq } from './kit'
import { LIVE_FAST } from './fast-live'

// #837 round 8 (D): the Agents card's sub line agrees the verb with the number: «1 работает, 1 без дела», «2 работают» ... «5 работают» (the mod's `plural`: 1 / 2-4 / 5+ and 11-14).
const walk = (n: any, f: (n: any) => void) => { if (n == null || typeof n !== 'object') return; f(n); for (const c of n.children ?? []) walk(c, f) }
const WANT: [number, string][] = [[0, '0 работают, 12 без дела'], [1, '1 работает, 11 без дела'], [2, '2 работают, 10 без дела'], [3, '3 работают, 9 без дела'], [4, '4 работают, 8 без дела'], [5, '5 работают, 7 без дела'], [11, '11 работают, 1 без дела'], [12, '12 работают, 0 без дела']]
for (const [busy, want] of WANT) {
  test(`#837 b8: the Agents card's sub line, ${busy} working: «${want}»`, { timeoutMs: 60_000 }, async ($, on) => {
    on('fs.write', async () => ({ value: undefined }) as any)
    const f = JSON.parse(LIVE_FAST)
    const base = f.agents[0]
    const f2 = { ...f, agents: Array.from({ length: 12 }, (_, i) => ({ ...base, name: `a${i}`, busy: i < busy })) }
    const ui = await mountPane($, on, 'desktop', { fast: JSON.stringify(f2) }, 123)
    const words: string[] = []
    walk(await (ui as any).drawn(), n => { if (n.type === 'Svg') words.push(...[...dq(String(n.props?.source ?? '')).matchAll(/>(\d+ работа[^<]*)</g)].map(m => m[1]!)) })
    console.log(`agents verb ${busy}: ${words.join(' | ')}`)
    expect(words, `${busy} working`).toEqual([want])
    await ui.unmount()
  })
}
