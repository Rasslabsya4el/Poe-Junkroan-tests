import { test, expect } from 'claude-code/testing'
import { svgDoc } from '../hooks/kit'
import '../hooks/addon'
import { flat, faceBase64 } from './kit'

// #837 b17f: an ascendancy face a picture draws twice or more is embedded ONCE in the picture (`<image id='fN' ..>` in its defs, `<use href='#fN' x y/>` where it stood). The runs card of the real payload drew
// 18 faces of 9 ascendancies = 18 copies of ~1,070 characters; the main tab was 98k in the real pane, over the 90,000 guard, and lost all row hover. `flat` writes the uses out again for the readers of the old markup.
const ASC = ['Chieftain', 'Necromancer', 'Slayer', 'Guardian', 'Occultist', 'Pathfinder', 'Ascendant', 'Gladiator', 'Elementalist']
const uri = (n: string) => `data:image/png;base64,${faceBase64(n)}`
const img = (n: string, x: number, y: number) => `<image href="${uri(n)}" x="${x}" y="${y}" width="16" height="16" style="image-rendering:pixelated"/>`
const rows = (names: string[]) => names.map((n, i) => `<g transform="translate(0 ${i * 26})">${img(n, i % 2 ? 27 : 45, 2)}<rect width="9" height="9" fill="#fff"/></g>`).join('')
const count = (s: string, re: RegExp) => (s.match(re) ?? []).length

test('#837 b17f: 18 face images of 9 ascendancies are 9 embedded copies and 18 uses; flat gives the 18 images back as drawn', () => {
  const names = [...ASC, ...ASC]
  const body = rows(names)
  const doc = svgDoc(400, 600, body)
  expect(count(doc, /data:image\/png;base64,/g), 'copies embedded').toBe(9)
  expect(count(doc, /<use href='#f\d+' x='\d+' y='2'\/>/g), 'uses').toBe(18)
  expect(count(doc, /<image /g), 'image elements').toBe(9)
  expect(doc.indexOf("<image id='f0'"), 'in the defs, before the body').toBeLessThan(doc.indexOf('</defs>'))
  const back = flat(doc)
  expect(count(back, /<image href='data:/g), 'flat: the images as drawn').toBe(18)
  expect(count(back, /<use /g), 'flat: no use left').toBe(0)
  expect(count(back, /<image id=/g), 'flat: no def left').toBe(0)
})

test('#837 b17f: a face drawn once stays where it was (no def); a picture with 2 copies of one face and 1 of another shares only the repeated one', () => {
  const once = svgDoc(400, 100, rows(['Slayer']))
  expect(count(once, /<use href='#f/g)).toBe(0)
  expect(count(once, /<image id=/g)).toBe(0)
  expect(count(once, /<image href='data:/g)).toBe(1)
  const mixed = svgDoc(400, 100, rows(['Slayer', 'Witch', 'Slayer']))
  expect(count(mixed, /data:image\/png;base64,/g), 'Slayer once, Witch once').toBe(2)
  expect(count(mixed, /<use href='#f0' /g), 'two uses of the repeated one').toBe(2)
  expect(count(mixed, /<image id='f0'/g)).toBe(1)
  expect(count(flat(mixed), /<image href='data:/g)).toBe(3)
})
