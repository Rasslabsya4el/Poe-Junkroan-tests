import { test, mock } from 'claude-code/testing'
import { makeRegistry } from '../hooks/register'
import { COMMAND } from '../hooks/project'
import { ADDON } from '../hooks/addon'
import * as KIT from '../hooks/kit'
import * as ADD from '../hooks/addon'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'

// #1094 unit 6: this repo's own test, not in the core manifest (the shipped pane-generic.test.tsx stays main's): the pane with the add-on absent.

// #1094 unit 3b: the seed and face pieces are the add-on's (a generic pane with no add-on draws none of them): kit exports neither, addon exports seedW
test('kit holds no seed or face piece; the add-on exports seedW', () => {
  for (const name of ['SEED_MARK', 'seedW', 'shareFaces', 'FACE_TAG']) if (name in KIT) throw new Error(`kit still exports ${name}`)
  if (typeof (ADD as any).seedW !== 'function') throw new Error('addon does not export seedW')
})

// #1094 unit 3b (ORCH): the add-on ABSENT, as the target's stub leaves it (`ADDON = { cards: [], tabs: [] }`): no card, tab, make, prepare or
// signature of the add-on, and no shared face pass (PICTURE_PASSES empty). Everything is put back in `finally`.
const withoutAddon = async (fn: () => Promise<void>): Promise<void> => {
  const saved = { cards: ADDON.cards.splice(0), tabs: ADDON.tabs.splice(0), make: ADDON.make, prepare: ADDON.prepare, signature: ADDON.signature }
  const passes = KIT.PICTURE_PASSES.splice(0)
  Object.assign(ADDON, { make: undefined, prepare: undefined, signature: undefined })
  try { await fn() } finally {
    ADDON.cards.push(...saved.cards)
    ADDON.tabs.push(...saved.tabs)
    Object.assign(ADDON, { make: saved.make, prepare: saved.prepare, signature: saved.signature })
    KIT.PICTURE_PASSES.push(...passes)
  }
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`add-on absent (${surface}): every generic card draws its title, every tab draws, the redraw log holds no error line`, async ($, on) => {
    await withoutAddon(async () => {
      const clock = mock.clock(on)
      const files: Record<string, string> = {}
      const key = (p: string) => (p.endsWith('redraws.log') ? 'redraws.log' : p.endsWith('pane.silenced') ? 'pane.silenced' : p)
      // The collector's real answers (test/fixtures.ts): the agents card draws only when the fast pull holds its key.
      on('process.run', async (_$, e) => ({ value: { exitCode: 0, stdout: ({ fast: FAST, tickets: TICKETS, slow: SLOW, orch: ORCH } as any)[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
      on('ui.open', async () => ({ value: { isOpen: true } }) as any)
      on('ui.status', async () => ({ value: undefined }) as any)
      on('fs.exists', async (_$, e) => ({ value: key(e.path) in files }) as any)
      on('fs.read', async (_$, e) => { if (key(e.path) in files) return { value: files[key(e.path)] } as any; throw new Error('ENOENT') })
      on('fs.write', async (_$, e) => { files[key(e.path)] = e.text; return { value: undefined } as any })
      void ($ as any).command.run({ command: COMMAND, args: '', origin: 'user', presentation: 'text' }).catch(() => {})
      await clock.settle()
      const ui = await $.ui.mount({ plugin: 'pob-slots', surface, component: 'Pane', requestId: COMMAND, props: PROPS })
      await clock.settle()
      const first = await stats(ui)
      if (!(first.cards > 0)) throw new Error(`${surface}: main tab draws no card`)
      const json = JSON.stringify(await ui.drawn())
      for (const c of makeRegistry({ cards: [], tabs: [] }).cards) if (c.name && !json.includes(c.name)) throw new Error(`${surface}: card ${c.id} does not draw its title «${c.name}»`)
      for (const id of ['tickets', 'cost', 'progress']) {
        await ui.press({ key: `tab-${id}` })
        await clock.settle()
        if (!((await stats(ui)).nodes > 0)) throw new Error(`${surface}: tab ${id} drew no nodes`)
      }
      await ui.unmount()
      const log = (files['redraws.log'] ?? '').split('\n').filter(Boolean)
      if (log.length === 0) throw new Error(`${surface}: the redraw log holds no line, the error check would prove nothing`)
      const errs = log.filter(l => /\berror (pull|render) /.test(l))
      if (errs.length) throw new Error(`${surface}: ${errs.length} error line(s) in the redraw log: ${errs[0]}`)
    })
  })
}

// #1094 unit 3b (ORCH): a column and a cell with no `kind` (the add-on's ratio column is not there) draw as plain text, no throw.
test('a column and a cell with kind unset draw as plain text', () => {
  const cols: KIT.TCol[] = [{ label: 'Name', x: 0 }, { label: 'Count', x: 200, end: true }]
  const out = KIT.tableSvg(cols, [{ rows: [['alpha', '12'], [{ t: 'beta' }, { t: '7' }]] }], 320)
  for (const s of ['alpha', '12', 'beta', '7']) if (!out.svg.includes(s)) throw new Error(`plain text «${s}» is not drawn`)
})

// The pane's props and the tree helpers, as pane-generic.test.tsx holds them (a copy: that shipped file stays main's).
const PROPS: any = { title: 'Monitor', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }

const walk = (x: any, f: (n: any) => void) => {
  if (!x || typeof x !== 'object') return
  f(x)
  for (const c of (x.children ?? x.props?.children ?? [])) walk(c, f)
}
const stats = async (ui: any) => {
  const tree = await ui.drawn()
  let nodes = 0, cards = 0
  walk(tree, n => { nodes++; if (String(n.props?.key ?? n.key ?? '').startsWith('card-')) cards++ })
  return { nodes, cards }
}
