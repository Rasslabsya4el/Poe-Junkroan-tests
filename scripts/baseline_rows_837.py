"""The row heights the monitor's baseline `50ea5412` renders (#837), the numbers `mods/pob-slots/test/baseline-rows-837.ts` holds.

    python scripts/baseline_rows_837.py            # print the table the baseline renders (runs the baseline mod's own hooks in `claude plugin test`)
    python scripts/baseline_rows_837.py --check    # same, and exit 1 when it differs from the checked-in table
    python scripts/baseline_rows_837.py --write    # same, and rewrite the checked-in table

How: `git archive` of the baseline's mod folder (its hooks, assets and plugin files) goes into `artifacts/baseline_rows_837/mods/pob-slots`,
the repo's fixtures (`test/fixtures.ts`, `kit.ts`, `fast-live.ts`, `buildpanel-answer.ts`) and the in-flow measure `test/rowheights.ts` go next
to a probe test, and the probe mounts the pane at 123 columns on three cases (live-fast, full, open-square: the live fast payload with the
Stormbrand square of run j-20261011-0430-e070 open, the build answer in) and prints, per card of the Главная tab (Agents, Merge, PoB runs),
the px height of every in-flow Svg in drawing order (the card's title first) and the card's height. The baseline draws one Svg per row, so
this is its row heights. No PoB, no window: `claude plugin test` runs the mod in a mock.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "50ea5412"
MOD = "mods/pob-slots"
TABLE = ROOT / MOD / "test" / "baseline-rows-837.ts"
WORK = ROOT / "artifacts" / "baseline_rows_837"
FIXTURES = ["fixtures.ts", "kit.ts", "fast-live.ts", "buildpanel-answer.ts", "rowheights.ts"]
CARDS = ["Agents", "Merge", "PoB runs"]

PROBE = r"""import { test, mock } from 'claude-code/testing'
import { FAST, SLOW, ORCH, TICKETS } from './fixtures'
import { LIVE_FAST } from './fast-live'
import { BUILD_816 } from './buildpanel-answer'
import { PROPS } from './kit'
import { flowH, flowSvgs } from './rowheights'
const CASES: [string, string, boolean][] = [['live-fast', LIVE_FAST, false], ['full', FAST, false], ['open-square', LIVE_FAST, true]]
for (const [name, fast, build] of CASES) {
  test(`probe ${name}`, { timeoutMs: 90_000 }, async ($, on) => {
    const clock = mock.clock(on)
    const all: Record<string, string> = { fast, tickets: TICKETS, slow: SLOW, orch: ORCH }
    on('process.run', async (_$: any, e: any) => {
      if (e.argv[2] === 'build') return { value: { exitCode: 0, stdout: BUILD_816, stderr: '', isStdoutTruncated: false } } as any
      return { value: { exitCode: 0, stdout: all[e.argv[2]] ?? '{}', stderr: '', isStdoutTruncated: false } } as any
    })
    on('ui.open', async () => ({ value: { isOpen: true } }) as any)
    on('ui.status', async () => ({ value: undefined }) as any)
    on('fs.write', async () => ({ value: undefined }) as any)
    void $.command.run({ command: 'pob', args: '', origin: 'user', presentation: 'text' }).catch(() => {})
    await clock.settle()
    const ui = await $.ui.mount({ plugin: 'pob-slots', surface: 'desktop', component: 'Pane', requestId: 'pob', props: PROPS(123) })
    if (build) {
      const job = JSON.parse(fast).runs.running.find((j: any) => j.id === 'j-20261011-0430-e070')
      await ui.press({ key: `run-pick-${job.id}` }); await clock.settle()
      await ui.press({ key: `cell-${job.id}-stormbrand-1` }); await clock.settle()
    }
    const tree = await (ui as any).drawn()
    const cards = tree.children[2].children.slice(0, 3)
    console.log('BASEROWS ' + JSON.stringify({ case: name, cards: cards.map((c: any) => ({ rows: flowSvgs(c).map((s: any) => s.h), h: flowH(c) })) }))
    await ui.unmount()
  })
}
"""


def claude_exe() -> str:
    return shutil.which("claude") or os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"


def extract_baseline(dest: Path) -> None:
    """The baseline's mod folder at BASELINE, written under `dest` (overwriting what is there)."""
    raw = subprocess.run(["git", "-C", str(ROOT), "archive", BASELINE, "--", f"{MOD}/hooks", f"{MOD}/assets", f"{MOD}/.claude-plugin",
                          f"{MOD}/tsconfig.json", f"{MOD}/types"], capture_output=True, check=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        tf.extractall(dest, filter="data")


def measure() -> dict[str, list[dict]]:
    """{case: [{rows: [px...], h: px} for Agents, Merge, PoB runs]} read off the baseline's drawn tree."""
    WORK.mkdir(parents=True, exist_ok=True)
    extract_baseline(WORK)
    mod = WORK / MOD
    (mod / "test").mkdir(exist_ok=True)
    for f in FIXTURES:
        shutil.copyfile(ROOT / MOD / "test" / f, mod / "test" / f)
    (mod / "test" / "probe.test.tsx").write_text(PROBE, encoding="utf-8")
    r = subprocess.run([claude_exe(), "plugin", "test", "."], cwd=mod, capture_output=True, text=True, timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (r.stdout or "") + (r.stderr or "")
    cases: dict[str, list[dict]] = {}
    for m in re.finditer(r"^BASEROWS (\{.*\})$", out, flags=re.M):
        d = json.loads(m.group(1))
        cases[d["case"]] = d["cards"]
    if len(cases) != 3:
        raise SystemExit(f"the baseline probe printed {len(cases)} of 3 cases (exit {r.returncode}):\n{out[-3000:]}")
    return cases


def render_ts(cases: dict[str, list[dict]]) -> str:
    lines = [
        f"// GENERATED by `python scripts/baseline_rows_837.py --write` from the baseline {BASELINE} (#837): the px height of every in-flow Svg of",
        "// each card of the Главная tab (the card's title first, then its rows, the baseline draws one Svg per row) and the card's height, per case.",
        "// Do not edit by hand: the script prints the same table and `--check` compares it with this one.",
        "export type BaseCard = { rows: number[]; h: number }",
        "export const BASELINE_ROWS: Record<string, Record<string, BaseCard>> = {",
    ]
    for case, cards in cases.items():
        lines.append(f"  '{case}': {{")
        for name, c in zip(CARDS, cards):
            lines.append(f"    '{name}': {{ h: {c['h']}, rows: [{', '.join(str(x) for x in c['rows'])}] }},")
        lines.append("  },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="rewrite the checked-in table")
    ap.add_argument("--check", action="store_true", help="exit 1 when the baseline's numbers differ from the checked-in table")
    args = ap.parse_args(argv)
    ts = render_ts(measure())
    print(ts, end="")
    if args.write:
        TABLE.write_text(ts, encoding="utf-8", newline="\n")
        print(f"written {TABLE}", file=sys.stderr)
    if args.check:
        have = TABLE.read_text(encoding="utf-8").replace("\r\n", "\n") if TABLE.exists() else ""
        if have != ts:
            print("the checked-in table differs from what the baseline renders", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
