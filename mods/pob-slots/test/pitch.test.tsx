import { test } from 'claude-code/testing'
import { mountPane, dq, altLines, cutRows } from './kit'
import { LIVE_FAST } from './fast-live'
import { GRID, PITCH, CARD_PITCH, LABEL_PITCH, SP } from '../hooks/tokens'

// #822 unit 2 (F11), moved to the pass-2 rule of #837 (baseline 50ea5412): the Главная tab has THREE pitches, each one per kind:
// a card strip row = a 20-px pill + 6 px air (CARD_PITCH 26), a table row (GRID.row 19, one engine cell), a machine card's
// bar row 26 and slot row 30 (the baseline 50ea5412's, restored), the legend row under a bar 24 (PITCH, kept from #822 F11).
test('F11 (#837 pass 2): the Главная tab rows are on three pitches: strips 26, table rows 19; a machine card: bar 26, slot row 30, legend 24', async ($, on) => {
  on('fs.write', async () => ({ value: undefined }) as any)
  const ui = await mountPane($, on, 'desktop', { fast: LIVE_FAST }, 123)
  const svgs = (await ui.findAll({ type: 'Svg' })) as any[]
  const pitches: Record<number, string[]> = {}
  const note = (p: number, what: string) => (pitches[p] ??= []).push(what)
  for (const s of svgs) {
    const src = dq(String(s.props?.source ?? ''))
    const alt = String(s.props?.alt ?? '')
    const h = Number(s.props?.height)
    if (/ load$/.test(alt)) {
      // a machine card is ONE picture: a bar's clip rect (kind bar), a legend dot (kind legend), the slot squares' label (kind slots)
      const tops: [number, string][] = []
      for (const m of src.matchAll(/<clipPath id="cl[^"]*"><rect [^>]*y="([\d.]+)"/g)) tops.push([+m[1]!, 'bar'])
      for (const m of src.matchAll(/<circle [^>]*cy="([\d.]+)"/g)) tops.push([+m[1]! - PITCH / 2, 'legend'])
      const lab = (t: string) => +(new RegExp(`<text x="\\d+" y="([\\d.]+)" class="lb">${t}</text>`).exec(src)?.[1] ?? NaN) - 14.4
      const slots = lab('PoB slots'), next = lab('CPU, 10 мин')
      if (!Number.isNaN(slots)) tops.push([slots, 'slots'])
      tops.sort((a, b) => a[0] - b[0])
      for (let i = tops.length - 1; i > 0; i--) if (Math.abs(tops[i]![0] - tops[i - 1]![0]) < 0.5) tops.splice(i, 1) // the dots of one legend row stand on one top
      tops.slice(1).forEach(([y], i) => { const d = Math.round((y - tops[i]![0]) * 10) / 10; note(d, `${alt} ${tops[i]![1]} row ${i + 1}`) })
      if (!Number.isNaN(slots) && !Number.isNaN(next)) note(next - slots, `${alt} slots row`)
      continue
    }
    // a merged picture (the strip rows of a card): each cut row is a strip of the card pitch (pill rows only)
    if (altLines(s.props?.alt).length >= 2) {
      const cut = cutRows(s.props.alt, src), pill = cut.map(c => /rx="10"/.test(c.src))
      cut.forEach((c, i) => { if (pill[i] && pill[i + 1]) { const h = Number(/height="([\d.]+)"/.exec(c.src)?.[1]); note(h > CARD_PITCH && h <= CARD_PITCH + 4 ? CARD_PITCH : h, `strip ${c.alt} h=${h}`) /* a 4-px gap row after a strip is part of its cut height */ } })
      continue
    }
    // a card's title (28 / 30) and a gap (no words, <= 8) are no row; a row that wraps is whole lines of the pitch
    if (h >= 28 || !alt && h <= 8) continue
    note(h / Math.max(1, Math.round(h / PITCH)), `${alt || 'row'} h=${h}`)
  }
  const set = Object.keys(pitches).map(Number).sort((a, b) => a - b)
  console.log(`distinct pitches ${JSON.stringify(set)}; ` + set.map(p => `${p}: ${pitches[p]!.length} rows e.g. ${pitches[p]![0]}`).join(' | '))
  if (!set.includes(CARD_PITCH)) throw new Error(`no strip row at the card pitch ${CARD_PITCH}: ${JSON.stringify(set)}`)
  const alien = set.filter(p => ![CARD_PITCH, PITCH, GRID.row, GRID.tab, 30, LABEL_PITCH].includes(p))
  if (alien.length) throw new Error(`rows at pitches ${JSON.stringify(alien)}, want only ${CARD_PITCH} / ${PITCH} / ${GRID.row} / ${LABEL_PITCH} (a label or head row, the baseline's 22)`)
  const want: Record<string, number> = { bar: 26, legend: PITCH, slots: 30 }
  const rows = Object.entries(pitches).flatMap(([p, ws]) => ws!.filter(w => / load /.test(w)).map(w => [w, Number(p)] as const))
  console.log(`machine rows ${JSON.stringify(rows)}`)
  const bad = rows.filter(([w, p]) => p !== want[/ load (bar|legend|slots) row/.exec(w)![1]!])
  if (bad.length || !rows.some(([w]) => /bar row/.test(w)) || !rows.some(([w]) => /slots row/.test(w))) throw new Error(`a machine card row is off its pitch (bar 26, legend ${PITCH}, slots 30): ${JSON.stringify(bad)} of ${rows.length}`)
  if (GRID.row !== 19 || CARD_PITCH !== 26 || PITCH % 4) throw new Error(`GRID.row ${GRID.row}, CARD_PITCH ${CARD_PITCH}, PITCH ${PITCH}`)
})
