import { test, mock } from 'claude-code/testing'
import { K, GRID } from '../hooks/tokens'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import { seen, svgWords, rowLight, isRowBox } from './kit'
import { CELL_PX } from '../hooks/kit'

// #730: a build made from a `junkroan build` request sits in the Builds tab with no author: the row names its rank,
// its own metric and audit instead of a ratio; a press opens the panel with the Open PoB button and no author button.
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const REF = '01 marauder_chieftain_imperial_staff'
const DIR = 'C:\\repo\\artifacts\\search-volcanic_fissure\\20261010-0221'
const f = JSON.parse(FAST)
f.readings = { updated: '2026-10-10T08:16:47+00:00', rows: [{
  run_dir: DIR, run_name: 'Volcanic Fissure Chieftain, day-1 request 10.10', ref: REF, seed: 2, variant: '', pobbin_id: 'vINWTHiqpsye',
  author_pobbin_id: null, ratio_pct: null, metric: 'TotalDotDPS', ours: 216282, author: null, life: 4513, stop: null, rank: 1,
  audit: '0 errors / 3 warnings', floors: 'ok', note: 'Main build.', added_at: '2026-10-10T08:16:46+00:00',
  // the collector's words (collect.py _reading_facts)
  name: 'Volcanic Fissure', var: '', class: 'Marauder', asc: 'Chieftain', metric_label: 'Total DoT DPS', ours_h: '216k', errors: 0, warnings: 3, floors_bad: false,
  said: [[false, 'PoB не считает: Enemies Cannot Leech Life From you (Bloodless)']] }] }
const BUILD = JSON.stringify({ name: 'Volcanic Fissure Chieftain', seed: 2, class: 'Marauder / Chieftain', level: '77', skill: 'Volcanic Fissure',
  author_skill: null, author_class: null, author_level: null, author: false, code: 'eNrtest', pob_file: '', pob_file_exists: false,
  note: 'rank 1 · audit: 0 errors / 3 warnings · floors: ok', pobbin_id: 'vINWTHiqpsye', pobbin_url: 'https://pobb.in/vINWTHiqpsye',
  author_pobbin_url: null, groups: [{ title: 'Main skill', rows: [['Total DoT DPS', '216k', '-', null]] }, { title: 'Character', rows: [['Life', '4,513', '-', null]] }] })

for (const surface of ['desktop', 'terminal'] as const) {
  test(`${surface}: a request build's row opens its panel with Open PoB`, async ($, on) => {
    const clock = mock.clock(on)
    const calls: string[][] = []
    const OUT: Record<string, string> = { fast: JSON.stringify(f), tickets: TICKETS, slow: SLOW, orch: ORCH, build: BUILD,
      openpob: JSON.stringify({ ok: true, link: 'pob://pobbin/vINWTHiqpsye', where: 'pobb.in/vINWTHiqpsye' }) }
    on('process.run', async (_$, e) => { calls.push(e.argv.slice(2)); return ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any })
    on('ui.open', async () => ({ value: { isOpen: true } }) as any)
    on('ui.status', async () => ({ value: undefined }) as any)
    on('ui.copy', async () => ({ value: { isCopied: true } }) as any)
    void ($ as any).command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
    await clock.settle()
    const ui = await $.ui.mount({ plugin: 'pob-slots', surface, component: 'Pane', requestId: 'pob', props: PROPS })
    await ui.press({ key: 'tab-builds' }); await clock.settle()
    let all = (await seen(ui)).join(' | ')
    // #683 r5 (0): the desktop row is a strip of the pane's grid (no «▸» glyph: the open row is the selected strip)
    // (the owner 10.10 12:1x: no word of the code on the tab: the name is the build's skill, the number stands
    // under PoB's UI label, the check is one plain word; its sentences are the open build's)
    const name = 'Volcanic Fissure'
    for (const w of [surface === 'desktop' ? name : `▸ ${name}`, 'Total DoT DPS 216k', 'Life 4,513'])
      if (!all.includes(w)) throw new Error(`row lacks «${w}»: ${all.slice(0, 900)}`)
    const pick: any = (await ui.findAll({ type: 'Button' })).find((b: any) => String(b.key ?? '').startsWith('rd-pick-'))
    if (surface === 'desktop') {
      if (all.includes('▸') || all.includes('▾')) throw new Error('a glyph on a desktop row')
      // a card with its count and the run's name, the row = one strip picture: the name is drawn in it (#972; the blank Button over it holds the press), the ascendancy, the main number, Life and the check's mark sit in the picture's
      // columns; the alt says them whole
      for (const w of ['Билды', '1 билд · Volcanic Fissure Chieftain, day-1 request 10.10', 'обновлено '])
        if (!all.includes(w)) throw new Error(`tab lacks «${w}»: ${all.slice(0, 900)}`)
      const strip: any = (await ui.findAll({ type: 'Svg' })).find((x: any) =>
        String(x.props?.alt ?? x.alt) === `${name} · Chieftain · Total DoT DPS 216k · Life 4,513 · рейлы 0`)
      const words = strip ? svgWords(String((strip.props ?? strip).source)) : []
      if (JSON.stringify(words) !== JSON.stringify([name, 'Chieftain', '216k', '4,513', '0'])) throw new Error('row picture: ' + words.join(' | '))
      if (/rank|seed|audit|floors|TotalDotDPS|marauder_|Main build/.test(all)) throw new Error('a code word or the hint on the closed tab: ' + all.slice(0, 900))
      if (!/^\s+$/.test(String((pick.props ?? pick).label)) || !(pick.props ?? pick).plain) throw new Error('the name press (a blank plain Button over the drawn name): ' + JSON.stringify(pick))
    }
    await ui.press({ key: pick.key }); await clock.settle()
    if (!calls.some(c => c[0] === 'build' && c[1] === DIR && c[2] === REF && c[3] === '2')) throw new Error('build not asked: ' + JSON.stringify(calls))
    all = (await seen(ui)).join(' | ')
    // (the collector's note «rank … · audit: … · floors: …» is the row's own facts: the desktop head does not repeat it)
    for (const w of ['Volcanic Fissure', 'Marauder / Chieftain · Level 77', ...(surface === 'terminal' ? ['rank 1 · audit: 0 errors / 3 warnings · floors: ok'] : ['Main build.', '1-е в запросе «Volcanic Fissure Chieftain, day-1 request 10.10»', 'ошибок нет, 3 замечания']), 'Открыть наш PoB', 'Total DoT DPS', '216k'])
      if (!all.includes(w)) throw new Error(`panel lacks «${w}»: ${all.slice(0, 1200)}`)
    if (all.includes('Открыть PoB автора')) throw new Error('an author button on a build with no author')
    if (surface === 'desktop') {
      // the same detail panel as a square of PoB runs: ONE head picture (title, class and level: the seed, the rank,
      // audit and floors are said by the row above it, once) with the Open PoB press laid over it, then the one
      // table (#613: one hover Box per data row, one absolute column)
      const svgs: any[] = (await ui.findAll({ type: 'Svg' })).map((x: any) => x.props ?? x)
      const head = svgs.find(p => String(p.alt).startsWith('Volcanic Fissure · Marauder / '))
      const hw = head ? svgWords(String(head.source)) : []
      if (JSON.stringify(hw) !== JSON.stringify(['Volcanic Fissure', 'Marauder / Chieftain · Level 77'])) throw new Error('head: ' + hw.join(' | '))
      const table = svgs.find(p => String(p.alt) === 'Volcanic Fissure stats')
      // header + «Main skill» + 1 row + a blank line + «Character» + 1 row = 6 lines of 20 px
      if (!table || table.height !== 6 * CELL_PX || table.width !== 959 || table.isInteractive) throw new Error('table: ' + JSON.stringify(table && [table.width, table.height]))
      const tops: number[] = []
      const walk = (n: any) => {
        if (!n || typeof n !== 'object') return
        if (n.type === 'Box' && /^st-h\d+$/.test(String(n.props?.key)) && (rowLight(n) || isRowBox(n))) { /* #972: a table row's highlight is its light (kit `rowLight`) */ tops.push(n.props.position === 'absolute' ? Number(n.props.top) : NaN) }
        for (const c of n.children ?? []) walk(c)
      }
      walk(await ui.drawn())
      // one hover Box per data row, each on its picture line: header line 0, «Main skill» 1, its row 2, blank 3, «Character» 4, its row 5
      if (JSON.stringify(tops) !== JSON.stringify([2, 5])) throw new Error('hover Boxes over the stat rows (tops in cells): ' + JSON.stringify(tops))
    }
    const open: any = (await ui.findAll({ type: 'Button' })).find((b: any) => String(b.key ?? '').startsWith('open-pob-'))
    await ui.press({ key: open.key }); await clock.settle()
    if (!calls.some(c => c[0] === 'openpob' && c[1] === DIR && c[2] === REF && c[4] === 'ours')) throw new Error('openpob not asked: ' + JSON.stringify(calls))
    all = (await seen(ui)).join(' | ')
    if (!all.includes('наш PoB запущен: pobb.in/vINWTHiqpsye')) throw new Error('no opened note: ' + all.slice(0, 1200))
  })
}
