import { test, expect } from 'claude-code/testing'
import { dq } from './kit'
import { allPics, readPic, mountTab } from './pics-837-b9b'
import { TICKETS } from './fixtures'
import { icon, TICON, LABEL_WORD, STATE_ICON } from '../hooks/kit'
import { K } from '../hooks/tokens'

// #837 round 9b (B10): on the Прогресс tab 4 of 9 label rows carried an icon («не разобран», «готов агенту», «ждёт тебя», «заблокирован»), 5 did not. Wanted: every row carries an icon of the kit's set, each row its own,
// the four old ones unchanged. The tickets are made here so that every line of the card has a count (the card hides an empty line, except «не разобран» and «без метки»).
const mk = (n: number, labels: string[], more: object = {}) => ({ n, title: `ticket ${n}`, open: true, reason: null, labels, parent: null, blockers: [], created: '2026-10-01T10:00:00Z', author: 'x', kids: [], state: 'open', ...more })
const tickets = (withWontfix: boolean) => JSON.stringify({
  ...JSON.parse(TICKETS), goals: [], loose: [],
  issues: Object.fromEntries([mk(1, ['needs-triage']), mk(2, ['needs-info']), mk(3, ['ready-for-agent']), mk(4, ['ready-for-human']), mk(5, ['autopilot']), mk(6, ['wayfinder:map']), mk(7, [], { blockers: [6] }),
    mk(8, [], { parked_on_run: true }), mk(9, []), ...(withWontfix ? [mk(10, ['wontfix'])] : [])].map(i => [String(i.n), i])),
})
const LINES: [string, string][] = [['needs-triage', 'draft'], ['needs-info', ''], ['ready-for-agent', 'bot.hubot.octicons'], ['ready-for-human', 'person'], ['autopilot', ''], ['folder', ''], ['blocked', 'hourglass.octicons'], ['parked-on-run', ''], ['no label', '']]
const norm = (s: string) => dq(s).replace(/translate\([^)]*\)/, 'T')
const iconsOf = (src: string) => [...dq(src).matchAll(/<g transform="translate\([\d.]+ ([\d.]+)\) scale\([\d.]+\)"[^>]*>(?:<g[^>]*>.*?<\/g>)<\/g>/g)].map(m => ({ y: +m[1]!, key: norm(m[0]) }))

for (const wontfix of [false, true]) {
  test(`#837 b9b B10: Прогресс${wontfix ? ' with a «не делаем» line' : ''}: every label row has an icon, all different, the four old ones unchanged`, { timeoutMs: 60_000 }, async ($, on) => {
    const { ui } = await mountTab($, on, { tickets: tickets(wontfix) }, 'progress', 123)
    const tree: any = await (ui as any).drawn()
    // #995 row 5: the lines stand in two tables, «По тикетам» then «Остальное» (the folder); read both, each row with its own icon
    const pics = allPics(tree).filter(n => n.props.width && /^(По тикетам|Остальное)/.test(String(n.props.alt)))
    expect(pics.map(n => String(n.props.alt).split('\n')[0]), 'the two label tables, in order').toEqual(['По тикетам', 'Остальное'])
    const rows: { t: string; y: number; pic: number }[] = [], ics: { y: number; key: string; pic: number }[] = []
    pics.forEach((pic, k) => {
      for (const i of readPic(pic, 123).items.filter(i => i.kind === 'text' && !i.head && i.x0 >= 40 && i.x0 <= 50)) rows.push({ t: i.t, y: i.y, pic: k })
      for (const i of iconsOf(String(pic.props.source))) ics.push({ ...i, pic: k })
    })
    console.log(`B10 ${wontfix ? 'with' : 'without'} wontfix: ${rows.length} label rows [${rows.map(r => r.t).join(' | ')}], ${ics.length} icons, ${new Set(ics.map(i => i.key)).size} different`)
    const want = LINES.map(([l]) => LABEL_WORD[l]!).concat(wontfix ? [LABEL_WORD.wontfix!] : [])
    expect(rows.map(r => r.t).sort()).toEqual([...want].sort())
    expect(rows.filter(r => r.pic === 1).map(r => r.t), '«Остальное» holds the folder line').toEqual([LABEL_WORD.folder!])
    expect(rows.length).toBe(wontfix ? 10 : 9)
    expect(ics.length, 'one icon a row').toBe(rows.length)
    expect(new Set(ics.map(i => i.key)).size, 'all different').toBe(rows.length)
    // an icon stands on its own row's line
    const iconOf = (r: { y: number; pic: number }) => ics.filter(i => i.pic === r.pic && Math.abs(i.y + 6 - (r.y - 4.5)) <= 3)
    for (const r of rows) expect(iconOf(r).length, `the row «${r.t}» has its icon`).toBe(1)
    // the four old ones: the Tickets legend's icon of the state (the shape of the name, the colour of the state)
    const colOf: Record<string, string> = { draft: K.muted, 'bot.hubot.octicons': K.accent, person: K.owner, 'hourglass.octicons': K.hold }
    for (const [label, name] of LINES.filter(l => l[1])) {
      const row = rows.find(r => r.t === LABEL_WORD[label])!
      const got = iconOf(row)[0]!
      expect(got.key, `«${LABEL_WORD[label]}» keeps ${name}`).toBe(norm(icon(name, 7, 0, TICON, colOf[name]!)).replace(/translate\([^)]*\)/, 'T'))
    }
    expect([STATE_ICON.triage[0], STATE_ICON.ready[0], STATE_ICON.owner[0], STATE_ICON.blocked[0]]).toEqual(['draft', 'bot.hubot.octicons', 'person', 'hourglass.octicons'])
    await ui.unmount()
  })
}
