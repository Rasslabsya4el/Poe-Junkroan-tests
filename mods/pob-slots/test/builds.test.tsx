import { test, mock } from 'claude-code/testing'
import { K } from '../hooks/tokens'
import { FAST, TICKETS, SLOW, ORCH, BUILD } from './fixtures'
import { marks, seen, svgWords, dq } from './kit'
import { textWidth } from '../hooks/draw'

// #683 r5 (C). The owner on the live tab (10.10 12:1x): «нахуя подсказка куда смотреть не под спойлером билда?» and
// «опять куча системного стиля написания. Сука это UI/UX… хватит сюда нести тупо вериблы из кода!!». So: a row of the
// Builds tab is a strip of the squares (the ascendancy's face, the build's name in a reader's words, the
// ascendancy, the main number under PoB's own UI label, Life, the build's check as one mark and a plain word); the
// brain's hint and the check's sentences are drawn only in the OPEN build; a build that has an author shows the
// author's PoB button and the versus columns. The rows carry the collector's words (collect.py _reading_facts).
const PROPS: any = { title: 'Junkroan', isFocused: false, bodyColumns: 123, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const DIR = 'C:\\repo\\artifacts\\benchmark\\20261010-0422'
const row = (ref: string, seed: number, extra: any) => ({ run_dir: DIR, run_name: 'P1-#604-3', ref, seed, variant: '', pobbin_id: 'by4kos8YPJCx', author_pobbin_id: null,
  ratio_pct: null, metric: 'CombinedDPS', ours: null, author: null, life: null, stop: null, rank: null, audit: null, floors: null, note: '', added_at: '2026-10-10T08:16:46+00:00',
  name: '', var: '', class: null, asc: null, metric_label: 'Combined DPS', ours_h: '', errors: null, warnings: null, floors_bad: null, said: [], ...extra })
const REQUEST = 'Volcanic Fissure Chieftain, day-1 request 10.10'
const ROWS = [
  row('cold_dot', 1, { author_pobbin_id: 'UNVUy73ibtBL', ratio_pct: 139, ours: 345112, ours_h: '345k', life: 5015, stop: 'converged', name: 'Cold Dot', class: 'Witch', asc: 'Elementalist',
    note: 'Главный билд. Смотри связки Cold Snap и два Cluster Jewel.' }),
  row('01 marauder_chieftain_imperial_staff', 2, { run_name: REQUEST, metric: 'TotalDotDPS', metric_label: 'Total DoT DPS', ours: 216282, ours_h: '216k', life: 4513, rank: 1, audit: '0 errors / 3 warnings', floors: 'ok',
    name: 'Volcanic Fissure', class: 'Marauder', asc: 'Chieftain', errors: 0, warnings: 3, floors_bad: false, said: [[false, 'PoB не считает: Enemies Cannot Leech Life From you (Bloodless)']] }),
  row('absolution_minions', 4, { variant: 'no-eldritch_battery', ratio_pct: 68, ours: 412000, ours_h: '412k', life: 4622, stop: 'time', audit: '2 errors / 5 warnings', floors: 'PhysicalMaximumHitTaken 4,120 < 6,000',
    name: 'Absolution Minions', var: 'без Eldritch Battery', class: 'Templar', asc: 'Guardian', errors: 2, warnings: 5, floors_bad: true,
    said: [[true, 'поиск остановился рано: ещё один проход дал +1.7 %'], [true, 'ниже порога защиты: Phys Max Hit 4,120 при пороге 6,000'], [false, 'PoB не считает: Enemies Cannot Leech Life From you (Bloodless)']],
    note: 'Вариант без Eldritch Battery проиграл автору.' }),
]
const NAMES = ['Cold Dot', 'Volcanic Fissure', 'Absolution Minions · без Eldritch Battery']
const f = JSON.parse(FAST)
f.readings = { updated: '2026-10-10T08:16:47+00:00', rows: ROWS }
const withAuthor = JSON.parse(BUILD) // Smite: author true, author_pobbin_url set
const NO_AUTHOR = { name: 'Volcanic Fissure Chieftain', seed: 2, class: 'Marauder / Chieftain', level: '77', skill: 'Volcanic Fissure',
  author_skill: null, author_class: null, author_level: null, author: false, code: 'eNrtest', pob_file: '', pob_file_exists: false,
  note: 'rank 1 · audit: 0 errors / 0 warnings · floors: ok', pobbin_id: 'vINWTHiqpsye', pobbin_url: 'https://pobb.in/vINWTHiqpsye',
  author_pobbin_url: null, groups: [{ title: 'Main skill', rows: [['Total DoT DPS', '216k', '-', null]] }, { title: 'Character', rows: [['Life', '4,513', '-', null]] }] }

const mount = async ($: any, on: any, build: unknown, opt: { rows?: any[]; cols?: number; faces?: string[] } = {}) => {
  const clock = mock.clock(on)
  const calls: string[][] = []
  const OUT: Record<string, string> = { fast: JSON.stringify(opt.rows ? { ...f, readings: { ...f.readings, rows: opt.rows } } : f), tickets: TICKETS, slow: SLOW, orch: ORCH, build: JSON.stringify(build),
    openpob: JSON.stringify({ ok: true, link: 'pob://pobbin/UNVUy73ibtBL', where: 'pobb.in/UNVUy73ibtBL' }) }
  on('process.run', async (_$: any, e: any) => { calls.push(e.argv.slice(2)); return ({ value: { exitCode: 0, stdout: OUT[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('ui.copy', async () => ({ value: { isCopied: true } }) as any)
  // the mod's assets: only the faces named have a file
  on('fs.read', async (_$: any, e: any) => {
    const m = /[\\/]asc[\\/](\w+)_16x16\.png$/.exec(e.path)
    if (m && (opt.faces ?? []).includes(m[1]!)) return { value: { base64: `FACE_${m[1]}` } } as any
    throw new Error('ENOENT ' + e.path)
  })
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: { ...PROPS, bodyColumns: opt.cols ?? 123 } })
  await ui.press({ key: 'tab-builds' }); await clock.settle()
  const picks = async (): Promise<any[]> => (await ui.findAll({ type: 'Button' })).filter((b: any) => String(b.key ?? '').startsWith('rd-pick-'))
  const svgs = async (): Promise<any[]> => (await ui.findAll({ type: 'Svg' })).map((x: any) => x.props ?? x)
  // a reading's strip: the only pictures whose alt says a Life
  const strips = async (): Promise<any[]> => (await svgs()).filter(p => / · Life [\d,]+/.test(String(p.alt)))
  // #972: a reading's name is drawn in the row's own picture (its first word); the blank Button `rd-pick-…` over it holds only the press
  const names = async (): Promise<string[]> => (await strips()).map(p => svgWords(dq(String(p.source)))[0] ?? '')
  return { ui, clock, calls, picks, svgs, strips, names }
}
/** the words of a reading's strip after its name (the name is the picture's first word, #972) */
const afterName = (p: any): string[] => svgWords(dq(String(p.source))).slice(1)
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const DONE = '#ab7df8', FAILED = '#f85149', BAD = '#ff6961', TEXT = '#ffffff', MUTED = '#98989f'
// the code's vocabulary: none of it may stand on the tab
const CODE = /…|\bseed\b|\brank\b|audit|floors|errors|warnings|stopped|converged|TotalDotDPS|CombinedDPS|MaximumHitTaken|_|\bs\d/
// every callout drawn, with the Boxes above it
const callouts = async (ui: any) => {
  const found: { n: any; up: any[] }[] = []
  const walk = (n: any, up: any[]) => {
    if (!n || typeof n !== 'object') return
    if (n.type === 'Box' && n.props?.backgroundColor === `${K.accent}1f`) found.push({ n, up })
    for (const c of n.children ?? []) walk(c, [n, ...up])
  }
  walk(await ui.drawn(), [])
  return found
}
const textOf = (n: any): string => typeof n === 'string' ? n : (n.children ?? []).map(textOf).join('')

test('desktop: a reading\'s row says the build in a reader\'s words: name | ascendancy | main number | Life | one check mark', async ($, on) => {
  const { ui, picks, strips, names: namesOf } = await mount($, on, withAuthor)
  // the names (drawn in the row's picture since #972; the press over each is a blank Button): the collector's words; what a variant lacks stands in the name
  const names = await namesOf()
  if (!same(names, NAMES)) throw new Error('names: ' + names.join(' | '))
  if ((await picks()).length !== NAMES.length) throw new Error('presses: ' + (await picks()).length)
  const rows = await strips()
  if (!same(rows.map(p => p.alt), [
    'Cold Dot · Elementalist · 139 % автора · Life 5,015',
    'Volcanic Fissure · Chieftain · Total DoT DPS 216k · Life 4,513 · рейлы 0',
    'Absolution Minions · без Eldritch Battery · Guardian · 68 % автора · Life 4,622 · рейлы 2',
  ])) throw new Error('alts: ' + rows.map(p => p.alt).join(' | '))
  const words = rows.map(afterName)
  if (!same(words, [
    ['Elementalist', '139 % автора', '5,015'],
    ['Chieftain', 'Total DoT DPS 216k', '4,513', '0'],
    ['Guardian', '68 % автора', '4,622', '2'],
  ])) throw new Error('row words: ' + JSON.stringify(words))
  // nothing of the code's vocabulary: on the pictures, in the alts, on the presses, in any native text
  const all = [...words.flat(), ...rows.map(p => String(p.alt)), ...names, ...(await seen(ui))]
  if (all.some(w => CODE.test(w))) throw new Error('a code word on the tab: ' + all.filter(w => CODE.test(w)).join(' | '))
  // the marks: a check not known = none; passed = the done icon with a muted word; failed = the failed icon, red words
  const mk = rows.map(p => marks(dq(String(p.source))).map(m => [m.kind, m.color]))
  if (!same(mk, [[], [['done', DONE]], [['failed', FAILED]]])) throw new Error('marks: ' + JSON.stringify(mk))
  const cls = (src: string, w: string) => new RegExp(`class="(\\w+)(?: nu)?">${w}</text>`).exec(src)?.[1]
  if (cls(dq(String(rows[1].source)), '0') !== 'mu' || cls(dq(String(rows[2].source)), '2') !== 'er') throw new Error('mark word colours')
  // #962 row 3: floors_bad says nothing in the list: the words «ниже порога» stand 0 times on the list's pictures and alts
  if (words.flat().concat(rows.map(p => String(p.alt))).some(w => /ниже порога|проверен/.test(w))) throw new Error('an old check word in the list')
  // the numbers are read first: the main number and Life in the text colour, the ascendancy muted
  if (cls(dq(String(rows[1].source)), 'Total DoT DPS 216k') !== 'tx' || cls(dq(String(rows[1].source)), '4,513') !== 'tx' || cls(dq(String(rows[1].source)), 'Chieftain') !== 'mu') throw new Error('number colours')
  await ui.unmount()
})

test('desktop: a row is a strip of the squares: its ascendancy\'s face in the rail, a dot where there is no asset', async ($, on) => {
  const { ui, strips } = await mount($, on, withAuthor, { faces: ['chieftain'] })
  const rows = await strips()
  const face = rows.map(p => /<image [^>]*href="([^"]*)"/.exec(dq(String(p.source)))?.[1] ?? '')
  if (!same(face, ['', 'data:image/png;base64,FACE_chieftain', ''])) throw new Error('faces: ' + JSON.stringify(face))
  // no number in the rail any more: the rows stand in the request's order, the open build says its place
  if (rows.some(p => dq(String(p.source)).includes('class="rn"'))) throw new Error('a rank number in the rail')
  await ui.unmount()
})

test('desktop: two rows that are one build but for the seed say the seed; no other row does', async ($, on) => {
  const twin = { ...ROWS[1]!, seed: 3, ours: 189896, ours_h: '190k' }
  const { ui, names: namesOf } = await mount($, on, withAuthor, { rows: [...ROWS, twin] })
  const names = await namesOf()
  if (!same(names, ['Cold Dot', 'Volcanic Fissure · seed 2', NAMES[2], 'Volcanic Fissure · seed 3'])) throw new Error('names: ' + names.join(' | '))
  await ui.unmount()
})

test('desktop: the hint («Куда смотреть») and the check sentences are drawn only in the OPEN build, as the rows of one table (#793 F03, F06)', async ($, on) => {
  const m = await mount($, on, withAuthor)
  // closed: no table of facts, no note, no sentence of a check anywhere
  let texts = await seen(m.ui)
  if (texts.some(t => /Куда смотреть|Главный билд|проиграл автору|Проверка билда|PoB не считает|место в запросе/.test(t))) throw new Error('an open build line on a closed tab: ' + texts.join(' | ').slice(0, 600))
  // the worst reading open: NO callout (the tinted bordered box), NO text node that starts with a `·` bullet, NO note line
  // (a Text) in the build's panel; its facts are the rows of ONE table under the head, head «рейлы | результат»
  await m.ui.press({ key: (await m.picks())[2].key }); await m.clock.settle()
  if ((await callouts(m.ui)).length) throw new Error('a callout in the open build')
  texts = await seen(m.ui)
  const bullets = texts.filter(t => /^\s*·/.test(t))
  if (bullets.length) throw new Error('a `·` bullet text: ' + bullets.join(' | '))
  const facts = (await m.svgs()).find(p => /Куда смотреть/.test(String(p.alt)) && /рейлы/.test(svgWords(dq(String(p.source))).join(' ')))
  if (!facts) throw new Error('no table of the open build facts: ' + texts.join(' | ').slice(0, 800))
  const w = svgWords(dq(String(facts.source)))
  if (!same(w.slice(0, 2), ['рейлы', 'результат'])) throw new Error('facts head: ' + w.slice(0, 4).join(' | '))
  for (const x of ['Куда смотреть', ROWS[2]!.note, 'Проверка билда', '2 ошибки, 5 замечаний', 'Замечание', 'поиск остановился рано: ещё один проход дал +1.7 %',
    'ниже порога защиты: Phys Max Hit 4,120 при пороге 6,000', 'PoB не считает: Enemies Cannot Leech Life From you (Bloodless)', 'Поиск', 'остановлен по времени: билд не досчитан'])
    if (!w.some(t => t.includes(x))) throw new Error(`the facts table lacks ${x}: ${w.join(' | ')}`)
  // the failed sentences are red, the muted one is not
  const red = (t: string) => new RegExp(`class="er"[^>]*>(?:<tspan[^>]*>)*[^<]*${t.slice(0, 12)}`).test(dq(String(facts.source)))
  if (!/class="er/.test(dq(String(facts.source)))) throw new Error('no red row in the facts table')
  void red
  // a request's build: its place in the request and a passed check, muted; no hint where the brain wrote none
  await m.ui.press({ key: (await m.picks())[1].key }); await m.clock.settle()
  const req = svgWords(String(((await m.svgs()).find(p => /Место/.test(String(p.alt))) ?? { source: '' }).source))
  for (const x of [`1-е в запросе «${REQUEST}»`, 'ошибок нет, 3 замечания', 'PoB не считает: Enemies Cannot Leech Life From you (Bloodless)'])
    if (!req.some(t => t.includes(x)) && !(await seen(m.ui)).some(t => t.includes(x))) throw new Error(`the open request build lacks ${x}`)
  if (req.includes('Куда смотреть')) throw new Error('a hint row where the brain wrote none')
  // a converged search says nothing about its stop
  await m.ui.press({ key: (await m.picks())[0].key }); await m.clock.settle()
  texts = await seen(m.ui)
  if (texts.some(t => /converged|Поиск/.test(t) && !/^Куда смотреть/.test(t)) || !texts.some(t => t.includes(ROWS[0]!.note))) throw new Error('the converged build lines: ' + texts.join(' | ').slice(0, 600))
  await m.ui.unmount()
})

// #793 F04: the Builds list has its column heads, muted, like every table of the pane
test('desktop: the Builds list has column heads (#793 F04)', async ($, on) => {
  const { ui, svgs } = await mount($, on, withAuthor)
  const head = (await svgs()).find(p => svgWords(dq(String(p.source))).join('|') === 'билд|ascendancy|результат|Life|рейлы')
  if (!head) throw new Error('no head row: ' + (await seen(ui)).slice(0, 12).join(' | '))
  if (!/class="mu"/.test(dq(String(head.source)))) throw new Error('heads are not muted: ' + head.source)
  await ui.unmount()
})

// a name far past its column: a long skill and two things the variant lacks
const LONG = row('06 marauder_chieftain_volcanic_fissure_of_snaking', 12, { run_name: REQUEST, metric: 'TotalDotDPS', metric_label: 'Total DoT DPS', ours: 1216282, ours_h: '1.22M', life: 14513, rank: 12, stop: 'time',
  name: 'Volcanic Fissure of Snaking', var: 'без Versatile Combatant, Resolute Technique', class: 'Marauder', asc: 'Chieftain', errors: 12, warnings: 15, floors_bad: true,
  said: [[true, 'ниже порога защиты: Phys Max Hit 4,120 при пороге 6,000']], note: 'Почему проиграл.' })
const LONG_NAME = 'Volcanic Fissure of Snaking · без Versatile Combatant, Resolute Technique'
const cut = async (m: any) => {
  const inPics = (await m.svgs()).flatMap((p: any) => svgWords(dq(String(p.source))))
  const labels = (await m.ui.findAll({ type: 'Button' })).map((b: any) => String((b.props ?? b).label ?? ''))
  return [...inPics, ...labels].filter(w => w.endsWith('…'))
}
for (const cols of [123, 100, 80]) {
  test(`desktop, ${cols} columns: no word of the Builds tab is cut with «…», closed or open`, async ($, on) => {
    const m = await mount($, on, withAuthor, { rows: ROWS, cols })
    if ((await cut(m)).length) throw new Error('cut closed: ' + (await cut(m)).join(' | '))
    const rows = (await m.strips()).map(afterName)
    // 123 columns (the owner's pane): every column of the worst reading stands
    if (cols === 123 && !same(rows[2], ['Guardian', '68 % автора', '4,622', '2'])) throw new Error('worst row: ' + JSON.stringify(rows[2]))
    // every name whole at every width
    const names = await m.names()
    if (!same(names, NAMES)) throw new Error('names: ' + names.join(' | '))
    await m.ui.press({ key: (await m.picks())[2].key }); await m.clock.settle()
    if ((await cut(m)).length) throw new Error('cut open: ' + (await cut(m)).join(' | '))
    await m.ui.unmount()
  })
}
test('desktop, 123 columns: a name far past its column pushes the later columns right; with the check column now a bare number every column stands whole (#962)', async ($, on) => {
  const m = await mount($, on, withAuthor, { rows: [...ROWS, LONG], cols: 123 })
  if ((await cut(m)).length) throw new Error('cut: ' + (await cut(m)).join(' | '))
  const names = await m.names()
  if (!same(names, [...NAMES, LONG_NAME])) throw new Error('names: ' + names.join(' | '))
  const rows = await m.strips()
  const words = rows.map(afterName)
  if (!same(words, [['Elementalist', '139 % автора', '5,015'], ['Chieftain', 'Total DoT DPS 216k', '4,513', '0'], ['Guardian', '68 % автора', '4,622', '2'], ['Chieftain', 'Total DoT DPS 1.22M', '14,513', '12']])) throw new Error('row words: ' + JSON.stringify(words))
  // one grid for the tab: the main number of every row starts right of the longest name, not at the design's x
  const numX = rows.slice(1, 2).concat(rows.slice(3)).map((p: any) => Number(/<text x="([\d.]+)"[^>]*text-anchor="end"[^>]*>(?:Total DoT DPS )?[\d.]+[kM]</.exec(dq(String(p.source)))?.[1]))
  if (new Set(numX).size !== 1 || !(numX[0]! > 500)) throw new Error('number column: ' + numX.join(' '))
  // the alt still says the ascendancy
  if (!String(rows[3].alt).startsWith(`${LONG_NAME} · Chieftain · Total DoT DPS 1.22M · Life 14,513 · рейлы 12`)) throw new Error('alt: ' + rows[3].alt)
  await m.ui.unmount()
})

test('desktop, 105 columns: with no room left for the long name the ascendancy leaves every row, the number of errors (a bare number) stays, nothing is cut', async ($, on) => {
  const m = await mount($, on, withAuthor, { rows: [...ROWS, LONG], cols: 105 })
  if ((await cut(m)).length) throw new Error('cut: ' + (await cut(m)).join(' | '))
  const names = await m.names()
  if (names[3] !== LONG_NAME) throw new Error('the long name: ' + names[3])
  const rows = await m.strips()
  const words = rows.map(afterName)
  // the grid is one for the tab: the ascendancy left every row, the number of errors fits, nothing is cut (#962)
  if (!same(words, [['139 % автора', '5,015'], ['Total DoT DPS 216k', '4,513', '0'], ['68 % автора', '4,622', '2'], ['Total DoT DPS 1.22M', '14,513', '12']])) throw new Error('row words: ' + JSON.stringify(words))
  if (!String(rows[3].alt).endsWith('рейлы 12')) throw new Error('alt: ' + rows[3].alt)
  await m.ui.press({ key: (await m.picks())[3].key }); await m.clock.settle()
  const texts = await seen(m.ui)
  const fw = (await m.svgs()).flatMap(p => svgWords(dq(String(p.source))))
  for (const w of ['12 ошибок, 15 замечаний', 'ниже порога защиты: Phys Max Hit 4,120 при пороге 6,000', 'остановлен по времени: билд не досчитан'])
    if (!fw.includes(w) && !texts.includes(w)) throw new Error(`the open build lacks «${w}»`)
  await m.ui.unmount()
})

test('desktop: a build with an author: «Открыть PoB автора» and the «наш / автор» + «автор» columns; the head does not repeat the row', async ($, on) => {
  const { ui, clock, calls, picks, svgs } = await mount($, on, withAuthor)
  await ui.press({ key: (await picks())[0].key }); await clock.settle()
  if (!calls.some(c => c[0] === 'build' && c[1] === DIR && c[2] === 'cold_dot' && c[3] === '1')) throw new Error('build not asked: ' + JSON.stringify(calls))
  const btns: any[] = (await ui.findAll({ type: 'Button' })).map((b: any) => b.props ? { key: b.key ?? b.props.key, ...b.props } : b)
  const ours = btns.find(b => String(b.key).startsWith('open-pob-')), author = btns.find(b => String(b.key).startsWith('open-author-'))
  if (ours?.label !== 'Открыть наш PoB' || ours.variant != null || !ours.plain || author?.label !== 'Открыть PoB автора' || author.variant != null) throw new Error('buttons: ' + JSON.stringify([ours, author]))
  const all = await svgs()
  const table = all.find(p => String(p.alt) === 'Smite stats')
  const tw = table ? svgWords(dq(String(table.source))) : []
  if (!same(tw.slice(0, 4), ['показатель', 'наш', 'наш / автор', 'автор (адапт.)'])) throw new Error('versus columns: ' + tw.slice(0, 6).join(' | '))
  // #1018 B: the author's head fits clear of «наш / автор»: its words start after the ratio head's end (12 px apart at least), and end at TW - 12
  const heads = [...dq(String(table!.source)).matchAll(/<text x="([\d.]+)" y="13" class="mu"( text-anchor="end")?>([^<]*)<\/text>/g)].map(m => ({ x: +m[1]!, end: !!m[2], t: m[3]! }))
  const ratioH = heads.find(h => h.t === 'наш / автор'), authorH = heads.find(h => h.t === 'автор (адапт.)')
  if (!ratioH || !authorH || !authorH.end || authorH.x !== table!.width - 12) throw new Error('versus heads: ' + JSON.stringify(heads))
  const authorStart = authorH.x - textWidth(authorH.t, 12), ratioEnd = ratioH.x + textWidth(ratioH.t, 12)
  if (authorStart - ratioEnd < 12) throw new Error(`author head cut or overlapping «наш / автор»: ${ratioEnd.toFixed(1)} → ${authorStart.toFixed(1)}`)
  // a versus row: ours, the ratio, the author's
  for (const w of ['Combined DPS', '737k', '561k', '131 %']) if (!tw.includes(w)) throw new Error(`table lacks «${w}»: ${tw.slice(0, 30).join(' | ')}`)
  // the head: the skill, class and level; no seed (the row says it), nothing else
  const head = all.find(p => String(p.alt).startsWith('Smite · '))
  if (!head || !same(svgWords(dq(String(head.source))), ['Smite', 'Duelist / Slayer · Level 78'])) throw new Error('head: ' + (head && svgWords(dq(String(head.source))).join(' | ')))
  // the author's button opens the author's PoB
  await ui.press({ key: author.key }); await clock.settle()
  if (!calls.some(c => c[0] === 'openpob' && c[2] === 'cold_dot' && c[4] === 'author')) throw new Error('openpob author not asked: ' + JSON.stringify(calls))
  if (!(await seen(ui)).includes('PoB автора запущен: pobb.in/UNVUy73ibtBL')) throw new Error('no opened note')
  await ui.unmount()
})

test('desktop: a build with no author: no author button, no versus columns; a replay note stays in the head', async ($, on) => {
  // the collector's own «rank … · audit: … · floors: …» note is the row's facts: not drawn again
  let m = await mount($, on, NO_AUTHOR)
  await m.ui.press({ key: (await m.picks())[1].key }); await m.clock.settle()
  let texts = await seen(m.ui)
  if (texts.includes('Открыть PoB автора') || !texts.includes('Открыть наш PoB')) throw new Error('buttons of a build with no author')
  let all = await m.svgs()
  const tw = svgWords(String(all.find(p => String(p.alt) === 'Volcanic Fissure stats')?.source ?? ''))
  // #1018 B: the no-author table is unchanged: what | наш, no author head of any words (`автор`, `автор (адапт.)`)
  if (!same(tw.slice(0, 2), ['показатель', 'наш']) || tw.includes('автор') || tw.some(w => w.startsWith('автор')) || tw.includes('наш / автор')) throw new Error('columns of a build with no author: ' + tw.slice(0, 6).join(' | '))
  let head = all.find(p => String(p.alt).startsWith('Volcanic Fissure · Marauder / '))
  if (!head || !same(svgWords(dq(String(head.source))), ['Volcanic Fissure', 'Marauder / Chieftain · Level 77'])) throw new Error('head: ' + (head && svgWords(dq(String(head.source))).join(' | ')))
  await m.ui.unmount()
})

test('desktop: a replay build\'s before -> after note is not a repeat: it stays in the open reading\'s head', async ($, on) => {
  const note = 'replay loop: Combined DPS 646k -> 438k (-32.21 %) · 11 min'
  const m = await mount($, on, { ...NO_AUTHOR, note })
  await m.ui.press({ key: (await m.picks())[1].key }); await m.clock.settle()
  const head = (await m.svgs()).find(p => String(p.alt).startsWith('Volcanic Fissure · Marauder / '))
  if (!head || !same(svgWords(dq(String(head.source))), ['Volcanic Fissure', 'Marauder / Chieftain · Level 77', note])) throw new Error('head: ' + (head && svgWords(dq(String(head.source))).join(' | ')))
  await m.ui.unmount()
})

// #793 F15: the main number and Life are two right-aligned numeric columns with a head, not inline text
test('desktop: the main number and Life are right-aligned columns with a head (#793 F15)', async ($, on) => {
  const { svgs, strips } = await mount($, on, withAuthor)
  const head = (await svgs()).find(p => svgWords(dq(String(p.source))).join('|') === 'билд|ascendancy|результат|Life|рейлы')
  if (!head || (dq(String(head.source)).match(/text-anchor="end"/g) ?? []).length !== 2) throw new Error('no head with two right-aligned labels')
  const rows = await strips()
  for (const p of rows) {
    const src = dq(String(p.source))
    if (svgWords(src).some(w => /^Life /.test(w))) throw new Error('Life is still inline text: ' + svgWords(src).join(' | '))
    if ((src.match(/text-anchor="end"[^>]*class="[^"]*nu"|class="[^"]*nu"[^>]*text-anchor="end"/g) ?? []).length < 2) throw new Error('two numeric right-aligned cells expected')
  }
})

// #962: the Builds list column is «рейлы» and its cell is the number of errors, nothing else
test('desktop: the Builds list head reads «рейлы» and each cell is the bare number of errors (#962 rows 1-5)', async ($, on) => {
  const m = await mount($, on, withAuthor, { rows: [...ROWS, LONG] })
  // row 1: the head string
  const head = (await m.svgs()).find(p => svgWords(dq(String(p.source))).join('|') === 'билд|ascendancy|результат|Life|рейлы')
  if (!head) throw new Error('no head: ' + (await seen(m.ui)).slice(0, 12).join(' | '))
  const rows = await m.strips()
  const src = rows.map((p: any) => dq(String(p.source)))
  const w = src.map((x: string) => svgWords(x).slice(1)) // after the name (#972)
  const cls = (s: string, t: string) => new RegExp(`class="(\\w+)(?: nu)?">${t}</text>`).exec(s)?.[1]
  // row 2: errors 0, floors_bad false -> '0', class mu
  if (w[1]!.at(-1) !== '0' || cls(src[1]!, '0') !== 'mu') throw new Error('errors 0: ' + JSON.stringify(w[1]))
  // row 3: errors 2, floors_bad true -> '2', class er, «ниже порога» 0 times in the list
  if (w[2]!.at(-1) !== '2' || cls(src[2]!, '2') !== 'er') throw new Error('errors 2: ' + JSON.stringify(w[2]))
  const old = [...w.flat(), ...rows.map((p: any) => String(p.alt))].filter(t => /ниже порога/.test(t))
  if (old.length !== 0) throw new Error('«ниже порога» in the list: ' + old.length)
  // row 4: errors 12 -> '12', class er
  if (w[3]!.at(-1) !== '12' || cls(src[3]!, '12') !== 'er') throw new Error('errors 12: ' + JSON.stringify(w[3]))
  // row 5: errors null -> an empty cell, an alt with no «рейлы» tail
  if (w[0]!.length !== 3 || /рейлы/.test(String(rows[0].alt))) throw new Error('errors null: ' + JSON.stringify(w[0]) + ' ' + rows[0].alt)
  await m.ui.unmount()
})
