"""Dump the drawn tree of the pob-slots pane of one ref as JSON (#843 unit 1).

  python scripts/pane_dump.py --ref <commit|worktree path> [--fixture live-fast|full|fallback]
      [--tab <name>] [--open-square] [--cols N] --out file.json

The mod source of the ref (`git archive` of mods/pob-slots + mods/shared/draw.ts of a commit, a plain copy of a
worktree folder) goes into a folder under `tmp_843/` of the repository root; a rig-only test file mounts the pane
as test/kit.ts does and prints `await ui.drawn()` ({type, props, children}) between two marker lines. The
plugin test runner (`claude plugin test .`, the way tools/agentops/mods.py runs it) is the only process: no
install, no click, no window. The output file is {ref, fixture, tab, open_square, cols, tree}.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN, END = "PANEDUMP_BEGIN", "PANEDUMP_END"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

RIG = r"""import { test, mock } from 'claude-code/testing'
import { FAST, TICKETS, SLOW, ORCH } from './fixtures'
import * as kit from './kit'
import { LIVE_FAST } from './rig-fast-live'
import { BUILD_816 } from './rig-buildpanel-answer'

const CFG = __CFG__
test('rig: dump the drawn tree', { timeoutMs: 120_000 }, async ($, on) => {
  const clock = mock.clock(on)
  // #972: `cache` = the collector's own answers of the installed pane (bin/.cache/shared-<mode>.json): the pane as the owner sees it
  let fastText = CFG.cache ? CFG.cache.fast : CFG.fixture === 'baseline' ? FAST : LIVE_FAST
  if (CFG.slots && CFG.slots.length) { // #837 L7: the workers of the finished runs, one number per run in order
    const d = JSON.parse(fastText)
    const by: Record<string, number> = {}
    d.runs.history.forEach((j: any, i: number) => { if (i < CFG.slots.length) { j.workers = CFG.slots[i]; by[j.id] = CFG.slots[i] } })
    d.runs.recent.forEach((j: any) => { if (by[j.id] != null) j.workers = by[j.id] })
    fastText = JSON.stringify(d)
  }
  if (CFG.fixture === 'held') { // #863: the 2026-10-11 12:26 case: one failed job, two followers queued after it
    const d = JSON.parse(fastText)
    const base = d.runs.running[0]
    const mk = (suffix: string, tag: string) => ({ ...base, id: 'j-20261011-1226-' + suffix, tag, state: 'queued', progress: undefined, locks: undefined,
      after: ['j-20261011-1226-6c83'], wait: { kind: 'slots', text: 'слоты: свободно 1 из 5' }, start_s: 600, start_h: '10 min',
      held_by: { id: 'j-20261011-1226-6c83', tag: 'P1-#839-5' }, dur: '78 min', age: '78 min' })
    d.runs.queued = [mk('ec7b', 'P1-#839-6'), mk('b9ed', 'P1-#839-7')]
    fastText = JSON.stringify(d)
  }
  const all: Record<string, string> = CFG.cache ? { fast: fastText, tickets: CFG.cache.tickets, slow: CFG.cache.slow, orch: CFG.cache.orch } : { fast: fastText, tickets: TICKETS, slow: SLOW, orch: ORCH }
  on('process.run', async (_$: any, e: any) => {
    if (e.argv[2] === 'build') {
      if (CFG.fixture === 'fallback' || CFG.fixture === 'live-fast' || CFG.fixture === 'cache-wait') return new Promise(() => {}) as any
      return { value: { exitCode: 0, stdout: BUILD_816, stderr: '', isStdoutTruncated: false } } as any
    }
    return { value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
  })
  on('ui.open', async () => ({ value: { isOpen: true } }) as any)
  on('ui.status', async () => ({ value: undefined }) as any)
  on('fs.write', async () => ({ value: undefined }) as any)
  // #983: the ascendancy faces the pane reads (assets/asc/<name>_<px>x<px>.png, as bytes) answer with the REAL files' bytes: a dump without them is ~1,100 characters short
  // a 16-px face of a build row and ~6,000 short of an open build's 64-px one
  on('fs.read', async (_$: any, e: any) => {
    const m = /[\\/]asc[\\/]([\w-]+_\d+x\d+\.png)$/.exec(String(e.path))
    if (m && e.as === 'bytes' && CFG.faces[m[1]!]) return { value: { base64: CFG.faces[m[1]!] } } as any
    throw new Error('ENOENT ' + e.path)
  })
  void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
  await clock.settle()
  const props = { title: 'Junkroan', isFocused: false, bodyColumns: CFG.cols, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
  const ui: any = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props })
  // #948: a seed cell is a link of a Markdown since #937 (the press of kit's ghostPress); a Button only where the pane draws one.
  // kit is a namespace import: a ref whose test/kit.ts lacks ghostPress/seedLinks (an older ref) gets the Button press as before.
  const pressCell = async (key: string) => {
    if (typeof kit.ghostPress === 'function' && typeof kit.seedLinks === 'function') {
      const mds: any[] = await ui.findAll({ type: 'Markdown' }).catch(() => [])
      if (mds.some((md: any) => kit.seedLinks(md).some((l: any) => l.key === key))) return kit.ghostPress(true, ui).press({ key })
    }
    return ui.press({ key })
  }
  // #983: the runs card (a run to pick, a build to open) lives on the tab «POB» since #972: a pick or an open square on the default tab goes there
  const hasPob = (await ui.findAll({ type: 'Button' }).catch(() => [])).some((b: any) => String(b.key ?? b.props?.key) === 'tab-pob')
  const tab = CFG.openSquare && hasPob && (!CFG.tab || CFG.tab === 'main') ? 'pob' : CFG.tab
  if (tab && tab !== 'main') { await ui.press({ key: `tab-${tab}` }); await clock.settle() }
  for (const k of (CFG.presses ?? [])) { await ui.press({ key: k }); await clock.settle() } // #972: extra presses after the tab (a period or a group of Расходы, a pager word)
  if (CFG.openSquare) {
    // #972: with the cache fixture the picked run is the first running one (else the first finished), the pressed cell its first done cell (else its first)
    const runs = JSON.parse(fastText).runs
    const fixed = (runs.running ?? []).find((j: any) => j.id === 'j-20261011-0430-e070')
    const job = fixed ?? (runs.running ?? [])[0] ?? (runs.history ?? runs.recent ?? [])[0]
    await ui.press({ key: `run-pick-${job.id}` }); await clock.settle()
    if (CFG.openSquare !== 'pick') {
      let cellKey = `cell-${job.id}-stormbrand-1`
      if (!fixed) {
        const cs = job.progress?.cells ?? []
        const c = cs.find((x: any) => x.state === 'done') ?? cs[0]
        if (c) cellKey = `cell-${job.id}-${c.ref}-${c.seed}${c.variant ? '-' + c.variant : ''}`
      }
      await pressCell(cellKey); await clock.settle()
    }
  }
  console.log('__BEGIN__' + JSON.stringify(await ui.drawn()) + '__END__')
  await ui.unmount()
})
"""


def claude_exe() -> str | None:
    """An absolute claude.exe, found the way the dispatcher finds it (CLAUDE_EXE, the app package, PATH), so the
    merge line's detached runner (no `claude` on PATH, no CLAUDE_CODE_EXECPATH) gets the same one as a session
    (#843 row 8). None when this machine has none."""
    env = os.environ.get("CLAUDE_EXE") or os.environ.get("CLAUDE_CODE_EXECPATH")
    if env and Path(env).is_file():
        return env
    sys.path.insert(0, str(ROOT))
    try:
        from tools.agentops.dispatch import find_claude_exe
        return str(find_claude_exe())
    except (SystemExit, ImportError):
        return None
    finally:
        sys.path.remove(str(ROOT))


def extract(ref: str, dest: Path) -> str:
    """Put mods/pob-slots (+ mods/shared/draw.ts) of ref into dest; returns a label for the ref."""
    p = Path(ref)
    if p.is_dir():
        src = p / "mods"
        shutil.copytree(src / "pob-slots", dest / "mods" / "pob-slots",
                        ignore=shutil.ignore_patterns("node_modules", "__pycache__", ".cache"))
        if (src / "shared").is_dir():
            shutil.copytree(src / "shared", dest / "mods" / "shared")
        return f"worktree {p}"
    tar = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", ref, "mods/pob-slots", "mods/shared"],
                         capture_output=True, creationflags=NO_WINDOW)
    if tar.returncode:  # a ref without mods/shared (the baseline)
        tar = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", ref, "mods/pob-slots"],
                             capture_output=True, creationflags=NO_WINDOW)
        if tar.returncode:
            raise SystemExit(f"git archive {ref}: {tar.stderr.decode(errors='replace')}")
    with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
        t.extractall(dest, filter="data")
    return ref


def faces(mod: Path) -> dict[str, str]:
    """The ascendancy faces of the dumped ref (assets/asc/*.png) as base64, by file name: the rig answers the pane's reads with them (#983)."""
    import base64
    d = mod / "assets" / "asc"
    return {f.name: base64.b64encode(f.read_bytes()).decode("ascii") for f in sorted(d.glob("*.png"))} if d.is_dir() else {}


def dump(ref: str, fixture: str = "live-fast", tab: str = "main", open_square: bool = False, cols: int = 123, presses=None,
         work: Path | None = None, slots: list[int] | None = None) -> dict:
    work = work or ROOT / "tmp_843" / f"dump-{os.getpid()}-{int(time.time() * 1000)}"
    work.mkdir(parents=True)
    try:
        label = extract(ref, work)
        mod = work / "mods" / "pob-slots"
        shared = work / "mods" / "shared"
        if shared.is_dir():  # the generated hooks/draw.ts (mods.sync_shared); gitignored, so not in an archive
            for f in shared.glob("*.ts"):
                shutil.copyfile(f, mod / "hooks" / f.name)
        test = mod / "test"
        for f in list(test.rglob("*")):  # only the rig runs
            if f.is_file() and ".test." in f.name:
                f.unlink()
        here = ROOT / "mods" / "pob-slots" / "test"
        shutil.copyfile(here / "fast-live.ts", test / "rig-fast-live.ts")
        shutil.copyfile(here / "buildpanel-answer.ts", test / "rig-buildpanel-answer.ts")
        names = {"live-fast", "full", "fallback", "held", "cache", "cache-wait"}
        if fixture not in names:
            raise SystemExit(f"--fixture {fixture} not in {sorted(names)}")
        if open_square is False and fixture in ("full", "fallback"):
            open_square = True  # the two build panel states are the open square
        cfg = dict(fixture=fixture, tab=tab, openSquare=open_square, cols=cols, slots=slots or [], presses=presses or [], faces=faces(mod))
        if fixture.startswith("cache"):  # #972: the installed pane's own collector answers (what the owner's pane draws now)
            cache_dir = Path.home() / ".claude" / "mods" / "pob-slots" / "bin" / ".cache"
            cfg["cache"] = {m: (cache_dir / f"shared-{m}.json").read_text(encoding="utf-8") for m in ("fast", "tickets", "slow", "orch")}
        rig = RIG.replace("__CFG__", json.dumps(cfg)).replace("__BEGIN__", BEGIN).replace("__END__", END)
        (test / "rig-dump.test.tsx").write_text(rig, encoding="utf-8")
        exe = claude_exe()
        if exe is None:
            raise SystemExit("no claude.exe found (CLAUDE_EXE, the app package, PATH): the plugin test cannot run here")
        r = subprocess.run([exe, "plugin", "test", "."], cwd=mod, capture_output=True, text=True,
                           timeout=900, creationflags=NO_WINDOW)
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(BEGIN + r"(.*?)" + END, out, re.S)
        if not m:
            raise SystemExit(f"no tree in the plugin test output (exit {r.returncode}):\n{out[-3000:]}")
        return dict(ref=label, fixture=fixture, tab=tab, presses=presses or [], open_square=open_square, cols=cols, tree=json.loads(m.group(1)))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", required=True, help="a commit or a worktree path")
    ap.add_argument("--fixture", default="live-fast", choices=["live-fast", "full", "fallback", "held", "cache", "cache-wait"],
                    help="cache / cache-wait (#972): the installed pane's own collector answers; -wait = the build is read and never answers")
    ap.add_argument("--open-square", action="store_true")
    ap.add_argument("--pick", action="store_true", help="#972: pick a run only (no cell pressed)")
    ap.add_argument("--tab", default="main")
    ap.add_argument("--cols", type=int, default=123)
    ap.add_argument("--slots", help="comma list: the workers of the first finished runs (#837 L7), e.g. 1,3,7,10")
    ap.add_argument("--press", action="append", default=[], help="#972: a Button key pressed after the tab press (repeatable), e.g. cost-month, costg-spawn")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t0 = time.time()
    res = dump(a.ref, a.fixture, a.tab, "pick" if a.pick else a.open_square, a.cols,
               presses=a.press, slots=[int(x) for x in a.slots.split(",")] if a.slots else None)
    Path(a.out).write_text(json.dumps(res), encoding="utf-8")
    from junkroan.report_format import human_duration
    print(f"installs 0 clicks 0; wrote {a.out} in {human_duration(time.time() - t0)}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    raise SystemExit(main())
