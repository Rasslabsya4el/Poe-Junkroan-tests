import { test, mock } from 'claude-code/testing'
import { PROPS, mountG } from './kit'
import { TICKETS, SLOW, ORCH } from './fixtures'
import { LIVE_FAST } from './fast-live'
import { BUILD_816 } from './buildpanel-answer'
import { FACE_CHARS } from './face-sizes'

// #983 row 6: the size of every tab and every group of «Расходы» on the fixture `live-fast` (the live fast payload of 2026-10-11, the fixtures' tickets and cost), 123 columns,
// every ascendancy face answered at the length of its real file of assets/asc (test/face-sizes.ts). `scripts/pane_dump.py --fixture live-fast|full` draws the same states with
// the files' own bytes; its size a state must be within 2 % of the number printed here (the acceptance row compares the two).
const STATES: [string, string[], boolean][] = [
  ['main', [], false], ['pob', ['tab-pob'], false], ['pob, a build open', ['tab-pob'], true], ['builds', ['tab-builds'], false], ['tickets', ['tab-tickets'], false],
  ['cost, roles', ['tab-cost', 'costg-roles'], false], ['cost, spawn', ['tab-cost', 'costg-spawn'], false], ['cost, days', ['tab-cost', 'costg-days'], false], ['progress', ['tab-progress'], false],
]
for (const [name, keys, open] of STATES) {
  test(`#983 row 6: the size of the state «${name}» on the fixture live-fast`, { timeoutMs: 60_000 }, async ($, on) => {
    const clock = mock.clock(on)
    const all: Record<string, string> = { fast: LIVE_FAST, tickets: TICKETS, slow: SLOW, orch: ORCH }
    on('process.run', async (_$: any, e: any) => ({ value: { exitCode: 0, stdout: e.argv[2] === 'build' ? BUILD_816 : all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } }) as any)
    on('ui.open', async () => ({ value: { isOpen: true } }) as any)
    on('ui.status', async () => ({ value: undefined }) as any)
    on('fs.write', async () => ({ value: undefined }) as any)
    on('fs.read', async (_$: any, e: any) => {
      const m = /[\\/]asc[\\/]([\w-]+_\d+x\d+\.png)$/.exec(String(e.path))
      if (m && e.as === 'bytes' && FACE_CHARS[m[1]!]) return { value: { base64: 'A'.repeat(FACE_CHARS[m[1]!]!) } } as any
      throw new Error('ENOENT ' + e.path)
    })
    void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
    await clock.settle()
    const ui: any = await mountG($, { plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) })
    for (const k of keys) { await ui.press({ key: k }); await clock.settle() }
    if (open) { await ui.press({ key: 'run-pick-j-20261011-0430-e070' }); await clock.settle(); await ui.press({ key: 'cell-j-20261011-0430-e070-stormbrand-1' }); await clock.settle() }
    const json = JSON.stringify(await ui.drawn())
    console.log(`PANESIZE ${name} | ${json.length} | faces ${(json.match(/data:image\/png/g) ?? []).length}`)
    await ui.unmount()
    if (name.startsWith('pob') && !json.includes('data:image/png')) throw new Error('no ascendancy face is drawn')
  })
}
