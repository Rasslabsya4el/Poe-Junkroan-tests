import { test } from 'claude-code/testing'
import { makeRegistry } from '../hooks/register'
import { ADDON } from '../hooks/addon'

// #796 u4b: the main-tab cards and the tabs come from one registry built from an add-on object.
test('an empty add-on gives the 3 generic cards and the 3 generic tabs', async () => {
  const r = makeRegistry({ cards: [], tabs: [] })
  const cards = r.cards.map(c => c.name)
  const tabs = r.tabs.map(t => t.label)
  if (cards.join() !== 'Agents,Merge,PC') throw new Error(`cards: ${cards}`)
  if (tabs.join() !== 'Тикеты,Расходы,Прогресс') throw new Error(`tabs: ${tabs}`)
  if (r.tabs.some(t => t.id === 'builds')) throw new Error('the empty add-on has a Builds tab (#796 u4d)')
})

test('this repo add-on gives the 4 cards of «Главная» in order 10..50, the tab POB first and the Builds tab second (#972: the runs card is the tab POB)', async () => {
  const r = makeRegistry(ADDON)
  const cards = r.cards.map(c => `${c.order}:${c.name}`)
  if (cards.join() !== '10:Agents,20:Merge,40:PC,50:Laptop') throw new Error(`cards: ${cards}`)
  const tabs = r.tabs.map(t => t.id)
  if (tabs.join() !== 'pob,builds,tickets,cost,progress') throw new Error(`tabs: ${tabs}`)
  const pob = r.tabs.find(t => t.id === 'pob')
  if (!pob || pob.order !== 10 || pob.label !== 'POB') throw new Error(`POB tab: ${JSON.stringify(pob)}`)
  const b = r.tabs.find(t => t.id === 'builds')
  if (!b || b.order !== 20 || b.label !== 'Билды') throw new Error(`Builds tab: ${JSON.stringify(b)}`)
  if (!ADDON.prepare) throw new Error('the add-on loads its own faces (prepare)')
})
