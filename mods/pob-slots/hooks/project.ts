// This project's own constants: the one place the generic pane code reads its identity from.
// The plugin id of every atom stays spelled 'pob-slots' in register.tsx: the state library's scan reads it as a string literal there.
export const MOD_DIR = 'C:/Users/user/.claude/mods/pob-slots'
export const SCRIPT = `${MOD_DIR}/bin/collect.py`
// #142 u2: the fast payload an always-running collector writes ({ at_ms, refresh_s, data }); the pane's fast pull reads it first
export const COLLECTOR_FAST = `${MOD_DIR}/bin/.cache/collector-fast.json`
export const WORD_CACHE = `${MOD_DIR}/bin/.cache/activity.json`
export const WORD_USAGE = `${MOD_DIR}/activity-usage.jsonl`
export const REDRAW_LOG = `${MOD_DIR}/bin/.cache/redraws.log`
export const SILENCE_FLAG = `${MOD_DIR}/bin/.cache/pane.silenced`
export const REPO = 'C:/Coding/poe-junkroan-v2'
export const REPO_NAME = 'Rasslabsya4el/Poe-Junkroan'
export const GH = `https://github.com/${REPO_NAME}/issues/`
// Base-class colours read off the class tool's own site; an ascendancy takes its base class's colour. The add-on's rows read them (addon.tsx).
export const CLASS: Record<string, string> = { Witch: '#9CBBFD', Marauder: '#FFB1AA', Ranger: '#9BD19F', Duelist: '#FFD79E', Templar: '#DEB4E1', Shadow: '#73BDB4', Scion: '#d8d8de' }
export const PANE = 'pob'
export const TITLE = 'Junkroan'
export const COMMAND = 'pob'
// The generic CPU / RAM split's first share (the work the machine does for the project): the key the collector
// writes into the payload (`m.cpu[WORK_KEY]`, `m.ram[WORK_KEY]`), and the name its legend shows.
export const WORK_KEY = 'pob' as const
export const WORK_NAME = 'PoB'

// The icons this project's rows add to the pane's table (kit.tsx merges them into ICONS), and the host each machine row is drawn with.
export const PROJECT_ICONS: Record<string, ['o' | 'l', string]> = {
  "laptop": ["l", "<path d=\"M18 5a2 2 0 0 1 2 2v8.526a2 2 0 0 0 .212.897l1.068 2.127a1 1 0 0 1-.9 1.45H3.62a1 1 0 0 1-.9-1.45l1.068-2.127A2 2 0 0 0 4 15.526V7a2 2 0 0 1 2-2z\" />\n  <path d=\"M20.054 15.987H3.946\" />"],
}
export const HOST_ICON: Record<string, string> = { laptop: 'laptop' }
// The label over the slot squares of the machine card, and the icon of the agent words only this project has.
export const SLOTS_LABEL = 'PoB slots'
export const PROJECT_ACT_ICON: [RegExp, string][] = [[/PoB|ран/, 'cpu.octicons'], [/poedb/, 'globe.octicons']]
// The words the Haiku agent-status prompt may answer with beyond the generic vocabulary (it goes before 'думает').
export const PROJECT_WORDS = ['запускает PoB']
// The machines whose CPU history the pane keeps (host key, where the payload holds its machine), the job queues a parked ticket may wait on, and its words.
export const MACHINES: [string, (v: any) => any][] = [['pc', v => v.machine], ['laptop', v => v.laptop?.machine]]
export const JOB_QUEUES = (f: any): any[] => [f?.runs, f?.laptop?.runs]
export const JOB_WAIT = 'ждёт PoB ран'
// What the command that opens the pane answers.
export const OPENED_TEXT = `${TITLE} monitor pane opened.`
