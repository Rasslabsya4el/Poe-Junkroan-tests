import { test, expect } from 'claude-code/testing'
import { createRecorder, stateSignature, STATE_CAP, TREE_RING } from '../hooks/staterec'
import type { StateInput } from '../hooks/staterec'

// #944 unit 1: the pure state recorder, tested with a fake fs (no mount, no PoB).
const DIR = 'C:/Users/user/.claude/mods/pob-slots/bin/.cache'
const STATE = `${DIR}/state.jsonl`
const TREE_DIR = `${DIR}/state/`
const LINE_KEYS = ['cards', 'entry', 'guard', 'open', 'picked', 'session', 't', 'tab', 'tree']
const GUARD_KEYS = ['first_measure', 'forced', 'limit', 'measure']

function fakeFs() {
  const files = new Map<string, string>()
  const fs = {
    files,
    failWrite: false,
    failRead: false,
    write: async (p: string, t: string) => {
      if (fs.failWrite) throw new Error('write refused')
      files.set(p, t)
    },
    read: async (p: string) => {
      if (fs.failRead) throw new Error('read refused')
      return files.get(p) ?? ''
    },
    exists: async (p: string) => {
      if (fs.failRead) throw new Error('exists refused')
      return files.has(p)
    },
  }
  return fs
}

function input(over: Partial<StateInput> = {}): StateInput {
  return {
    session: 'abcdef12-3456-7890-aaaa-bbbbccccdddd',
    tab: 'main',
    rowForm: 'mask',
    lightCards: [],
    picked: null,
    open: null,
    cards: { grid: 'mask', ag: 'mask', mg: 'mask', run: 'mask' },
    measure: 80000,
    firstMeasure: 85000,
    limit: 90000,
    forced: null,
    entry: { register: 1, kit: 2, version: '0.9.0' },
    ...over,
  }
}

const lines = (fs: ReturnType<typeof fakeFs>): any[] =>
  (fs.files.get(STATE) ?? '').split('\n').filter(Boolean).map(l => JSON.parse(l))
const trees = (fs: ReturnType<typeof fakeFs>): string[] => [...fs.files.keys()].filter(k => k.startsWith(TREE_DIR))

test('a change writes one line and one tree file each; the line carries the 9 keys and the tree content', async () => {
  const fs = fakeFs()
  const rec = createRecorder(fs, DIR, () => new Date(2026, 9, 13, 14, 5, 9))
  expect(await rec.record(input(), '{"a":1}')).toBe(true)
  expect(await rec.record(input({ tab: 'builds' }), '{"b":2}')).toBe(true)
  const ls = lines(fs)
  expect(ls.length).toBe(2)
  for (const l of ls) {
    expect(Object.keys(l).sort()).toEqual(LINE_KEYS)
    expect(Object.keys(l.guard).sort()).toEqual(GUARD_KEYS)
  }
  expect(ls[0].t).toBe('2026-10-13T14:05:09')
  expect(ls[0].tree).toBe('tree-00.json')
  expect(ls[1].tree).toBe('tree-01.json')
  expect(fs.files.get(`${TREE_DIR}${ls[0].tree}`)).toBe('{"a":1}')
  expect(fs.files.get(`${TREE_DIR}${ls[1].tree}`)).toBe('{"b":2}')
  expect(ls[1].tab).toBe('builds')
})

test('the same signature after the first call writes nothing, even with a different measure', async () => {
  const fs = fakeFs()
  const rec = createRecorder(fs, DIR)
  expect(await rec.record(input(), '{"a":1}')).toBe(true)
  for (let k = 1; k <= 10; k++) {
    expect(await rec.record(input({ measure: 80000 + k * 100 }), `{"a":${k + 1}}`)).toBe(false)
  }
  expect(lines(fs).length).toBe(1)
  expect(trees(fs).length).toBe(1)
})

test('25 signatures keep at most 20 tree files; a state.jsonl at 1.1 MB is cut and the new line follows', async () => {
  const fs = fakeFs()
  const rec = createRecorder(fs, DIR)
  for (let k = 0; k < 25; k++) expect(await rec.record(input({ tab: `t${k}` }), `{"k":${k}}`)).toBe(true)
  expect(trees(fs).length).toBe(TREE_RING)
  expect(TREE_RING).toBe(20)

  const fs2 = fakeFs()
  const pad = JSON.stringify({ pad: 'a'.repeat(99) }) + '\n'
  const big = pad.repeat(10000)
  expect(big.length > STATE_CAP).toBe(true)
  fs2.files.set(STATE, big)
  expect(await createRecorder(fs2, DIR).record(input({ tab: 'x' }), '{}')).toBe(true)
  const content = fs2.files.get(STATE) ?? ''
  expect(content.length < STATE_CAP + 1000).toBe(true)
  const all = content.split('\n').filter(Boolean)
  expect(JSON.parse(all[0]).pad).toBe('a'.repeat(99))
  expect(JSON.parse(all[all.length - 1]).tab).toBe('x')
})

test('a throwing write or read resolves false, never throws; the same input writes once the fs works again', async () => {
  const fs = fakeFs()
  const rec = createRecorder(fs, DIR)
  fs.failWrite = true
  expect(await rec.record(input(), '{}')).toBe(false)
  expect(fs.files.size).toBe(0)
  fs.failWrite = false
  expect(await rec.record(input(), '{}')).toBe(true)
  expect(lines(fs).length).toBe(1)

  fs.failRead = true
  expect(await rec.record(input({ tab: 'builds' }), '{}')).toBe(false)
  fs.failRead = false
  expect(await rec.record(input({ tab: 'builds' }), '{}')).toBe(true)
  expect(lines(fs).length).toBe(2)
})

test('the order of lightCards does not change the signature', async () => {
  expect(stateSignature(input({ lightCards: ['ag', 'mg'] }))).toBe(stateSignature(input({ lightCards: ['mg', 'ag'] })))
  expect(stateSignature(input({ lightCards: ['ag'] }))).not.toBe(stateSignature(input()))
  const fs = fakeFs()
  const rec = createRecorder(fs, DIR)
  expect(await rec.record(input({ lightCards: ['ag', 'mg'] }), '{}')).toBe(true)
  expect(await rec.record(input({ lightCards: ['mg', 'ag'] }), '{}')).toBe(false)
  expect(lines(fs).length).toBe(1)
})
