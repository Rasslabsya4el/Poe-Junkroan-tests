import { test, expect } from 'claude-code/testing'
import { openPane, base, ids, landed, jobHist, waiting } from './budget-kit'

// #995 send-back 1, defect 1 (the brain's pass of 14.10 on the installed 4adfc90f): page 2 of Merge «Готово» held 2 rows, so the card was 2 rows shorter
// and the PC and Laptop cards under it jumped up 26 px. Every page of a paged queue section keeps the height of a full page: a short page is padded with
// blank rows of a strip's height (they draw and light nothing). Merge «Готово» (3 a page), Merge «В очереди», POB «Готово» (6 a page).
const picH = (json: string, altHas: RegExp) => {
  const tree = JSON.parse(json)
  const out: number[] = []
  const walk = (n: any) => {
    if (!n || typeof n !== 'object') return
    if (n.type === 'Svg' && altHas.test(String(n.props?.alt ?? ''))) out.push(Number(n.props?.height))
    for (const c of n.children ?? []) walk(c)
  }
  walk(tree)
  return out
}

test('#995 send-back 1: Merge «Готово» page 2 of 5 landings (3 + 2) keeps page 1 height; the PC card stands where it stood', async ($, on) => {
  const f = base()
  const i = ids()
  f.merge.landed = Array.from({ length: 5 }, () => landed(i))
  const p = await openPane($, on, { fast: f })
  const s1 = await p.see()
  const h1 = picH(s1.json, /landed/)
  const pcAt1 = s1.json.indexOf('"alt":"PC load"')
  expect(h1.length, 'the Merge picture').toBe(1)
  expect(s1.json.includes('"key":"mgd-next"'), 'Merge «Готово» is paged').toBe(true)
  await p.press('mgd-next')
  const s2 = await p.see()
  const h2 = picH(s2.json, /landed/)
  const rows2 = (s2.json.match(/landed rc/g) ?? []).length
  console.log(`MERGE PAGE: page 1 ${h1[0]} px, page 2 ${h2[0]} px (${rows2} landing rows drawn on page 2)`)
  expect(rows2, 'page 2 holds the 2 landings left').toBe(2)
  expect(h2, 'page 2 is as high as page 1').toEqual(h1)
  expect(pcAt1, 'the PC card').toBeGreaterThan(0)
  await p.ui.unmount()
})

test('#995 send-back 1: Merge «В очереди» on its last, shorter page keeps a full page height', async ($, on) => {
  const f = base()
  const i = ids()
  f.merge.waiting = Array.from({ length: 300 }, (_, k) => waiting(i, k + 1))
  const p = await openPane($, on, { fast: f })
  const s1 = await p.see()
  expect(s1.json.includes('"key":"mgw-next"'), 'Merge «В очереди» is paged').toBe(true)
  const h1 = picH(s1.json, /waits/)
  for (let k = 0; k < 300 && (await p.see()).json.includes('"key":"mgw-next"'); k++) await p.press('mgw-next')
  const h2 = picH((await p.see()).json, /waits/)
  console.log(`MERGE WAIT: first page ${h1[0]} px, last page ${h2[0]} px`)
  expect(h2, 'the last page is as high as the first').toEqual(h1)
  await p.ui.unmount()
})

test('#995 send-back 1: POB «Готово» page 2 of 8 runs (6 + 2) keeps page 1 height', async ($, on) => {
  const f = base()
  const i = ids()
  f.runs.history = Array.from({ length: 8 }, () => jobHist(i))
  const p = await openPane($, on, { fast: f })
  await p.press('tab-pob')
  const s1 = await p.see()
  const h1 = picH(s1.json, /задача/)
  expect(s1.json.includes('"key":"hist-next"'), 'POB «Готово» is paged').toBe(true)
  await p.press('hist-next')
  const h2 = picH((await p.see()).json, /задача/)
  console.log(`POB PAGE: page 1 ${h1[0]} px, page 2 ${h2[0]} px`)
  expect(h1.length, 'the runs picture').toBe(1)
  expect(h2, 'page 2 is as high as page 1').toEqual(h1)
  await p.ui.unmount()
})
