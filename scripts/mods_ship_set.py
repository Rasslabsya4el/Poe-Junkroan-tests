"""Which of mods/pob-slots/test/ may ship in the core manifest.

    python scripts/mods_ship_set.py [--no-stubs] [--write]

A file ships only when (1) core_check finds 0 L1 / judged L2 / L3 in it, and no H in it when it is a .md file (the
rule run_check fails on: an H count in a .ts/.tsx file is reported, not failed), (2) every file it
imports (transitively) ships too, (3) its tests are green in a scratch target with the stub project.ts/addon.tsx.
Rules 1 and 2 need no claude CLI; rule 3 does (``mods test`` in a scratch target) and is skipped by --no-stubs.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.agentops import core_check  # noqa: E402

MANIFEST = ROOT / "tools" / "agentops" / "core_manifest.txt"
MOD = "mods/pob-slots"
TEST_DIR = f"{MOD}/test/"
IMPORT = re.compile(r"""from\s+['"](\.[^'"]*)['"]""")
# hooks/draw.ts is made by `mods test` (sync_shared); hooks/addon.tsx and hooks/project.ts are the stubs' files.
GENERATED = {f"{MOD}/hooks/draw": "mods/shared/draw.ts"}
PROJECT_OWN = {f"{MOD}/hooks/addon", f"{MOD}/hooks/project"}
CLASSES = ("ships", "L1", "L2", "L3", "H", "import", "fails-with-stubs")


def manifest_entries(manifest: Path = MANIFEST) -> list[str]:
    return core_check.read_manifest(manifest)


def resolve(root: Path, src: str, spec: str) -> str | None:
    parts: list[str] = []
    for seg in (Path(src).parent / spec).as_posix().split("/"):
        if seg == "..":
            parts.pop()
        elif seg != ".":
            parts.append(seg)
    key = "/".join(parts)
    if key in PROJECT_OWN:
        return None
    if key in GENERATED:
        return GENERATED[key]
    for ext in ("", ".ts", ".tsx", ".d.ts", "/index.d.ts", "/index.ts"):
        if (root / (key + ext)).is_file():
            return key + ext
    raise AssertionError(f"{src}: import {spec} resolves to nothing")


def imports(root: Path, rel: str) -> list[str]:
    if not rel.endswith((".ts", ".tsx")) or rel.endswith(".d.ts"):
        return []
    found = (resolve(root, rel, s) for s in IMPORT.findall((root / rel).read_text(encoding="utf-8")))
    return [r for r in found if r]


def rule1(root: Path, rel: str, patterns) -> str | None:
    """The first failing class of one file as it stands, or None."""
    row = core_check.check_file(root / rel, rel, patterns)
    for key in core_check.PATTERN_KEYS:
        n = row.l2_judged if key == "L2" and row.l2_judged is not None else row.counts.get(key, 0)
        if n > 0:
            return key
    # run_check (core_check.py) fails on H of a .md entry only; an issue number in a test's comment (#161) is no failure
    return "H" if row.h > 0 and rel.endswith(".md") else None


def candidates(root: Path = ROOT, manifest: Path = MANIFEST) -> dict[str, str]:
    """path -> status for every file of mods/pob-slots/test/, rules 1 and 2 only ("ships" = not yet dropped)."""
    patterns = core_check.read_patterns(root / "config" / "core_leak_patterns.json")
    outside = set(manifest_entries(manifest)) - {m for m in manifest_entries(manifest) if m.startswith(TEST_DIR)}
    files = sorted(p.relative_to(root).as_posix() for p in (root / MOD / "test").iterdir() if p.is_file())
    status = {f: (rule1(root, f, patterns) or "ships") for f in files}
    # manifest files outside the test dir already pass `core check` (it judges H on .md files only): they stand
    home_ok = set(outside)

    def ok(f: str) -> bool:
        return status.get(f) == "ships" or (f not in status and f in home_ok)

    changed = True
    while changed:
        changed = False
        for f, s in status.items():
            if s == "ships" and not all(ok(i) for i in imports(root, f)):
                status[f] = "import"
                changed = True
    return status


def scratch_target(tmp: Path, root: Path, shipping: set[str], manifest: Path = MANIFEST) -> Path:
    """The manifest's mods/ files (test lines replaced by ``shipping``) plus the port stubs, as a target."""
    from tools.agentops import port

    scratch = tmp / "target"
    rels = {e for e in manifest_entries(manifest) if e.startswith("mods/") and not e.startswith(TEST_DIR)} | shipping
    for rel in rels:
        dest = scratch / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / rel, dest)
    port.write_monitor_stubs(scratch, "someone/some-repo", port.HOME_ROOT)
    return scratch


def mods_test(scratch: Path, installed: Path, root: Path = ROOT) -> str:
    env = dict(os.environ, AGENTOPS_MODS_REPO=str(scratch), AGENTOPS_MODS_DIR=str(installed))
    r = subprocess.run([sys.executable, "-m", "tools.agentops", "mods", "test", "pob-slots"], cwd=root, env=env,
                       capture_output=True, text=True, timeout=900,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (r.stdout or "") + (r.stderr or "")


def failing_files(out: str, shipping: set[str]) -> set[str]:
    """Shipping test files named on a failure line of the output (by file name)."""
    bad = [ln for ln in out.splitlines() if re.search(r"\b(fail|error|not ok|✗|×)", ln, re.I)
           and not re.search(r"\d+\s+fail", ln, re.I)]
    names = {f: Path(f).name for f in shipping}
    return {f for f, n in names.items() if any(n in ln or Path(n).stem.split(".")[0] in ln for ln in bad)}


def run_with_stubs(root: Path, status: dict[str, str], tmp: Path, log=print) -> str:
    """Rule 3 fixed point: run, drop the files whose tests fail, re-run until 0 fail. Returns the last output."""
    while True:
        shipping = {f for f, s in status.items() if s == "ships"}
        scratch = scratch_target(tmp / f"r{len(shipping)}", root, shipping)
        out = mods_test(scratch, tmp / "installed")
        m = re.search(r"plugin test: (\d+) pass, (\d+) fail, exit (-?\d+)", out)
        log(m.group(0) if m else out)
        if m and int(m.group(2)) == 0 and int(m.group(3)) == 0:
            return out
        bad = failing_files(out, shipping)
        if not bad:
            raise SystemExit("plugin test fails but no file is named:\n" + out)
        for f in bad:
            status[f] = "fails-with-stubs"
        _drop_orphans(root, status)


def _drop_orphans(root: Path, status: dict[str, str]) -> None:
    """A dropped test file's helpers stay shipped only while some shipping file still needs them (rule 2 holds
    in the other direction already: a file whose import is dropped is dropped)."""
    changed = True
    while changed:
        changed = False
        for f, s in list(status.items()):
            if s == "ships" and not all(status.get(i, "ships") == "ships" for i in imports(root, f)):
                status[f] = "import"
                changed = True
    needed = {i for f, s in status.items() if s == "ships" and ".test." in f for i in imports(root, f)}
    stack = list(needed)
    while stack:
        for i in imports(root, stack.pop()):
            if i not in needed:
                needed.add(i)
                stack.append(i)
    for f, s in status.items():
        if s == "ships" and ".test." not in f and f not in needed:
            status[f] = "import"


def compute(root: Path = ROOT, stubs: bool = True, log=print) -> dict[str, str]:
    status = candidates(root)
    _drop_orphans(root, status)
    if stubs:
        with tempfile.TemporaryDirectory(dir=root / ".claude") as t:
            run_with_stubs(root, status, Path(t), log)
    return status


def write_manifest(shipping: set[str], manifest: Path = MANIFEST) -> None:
    lines = manifest.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if not ln.strip().startswith(TEST_DIR)]
    for rel in sorted(shipping):  # the other lines keep their order; each test line goes before the first greater one
        mods = [i for i, ln in enumerate(kept) if ln.strip().startswith("mods/")]
        at = next((i for i in mods if kept[i].strip() > rel), mods[-1] + 1)
        kept.insert(at, rel)
    out = kept
    manifest.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--no-stubs", action="store_true", help="rules 1 and 2 only (no claude CLI)")
    a = ap.parse_args()
    status = compute(ROOT, stubs=not a.no_stubs)
    for f, s in status.items():
        print(f"{s:17} {f}")
    totals = {c: sum(1 for s in status.values() if s == c) for c in CLASSES}
    print("totals: " + ", ".join(f"{c} {n}" for c, n in totals.items()))
    if a.write:
        write_manifest({f for f, s in status.items() if s == "ships"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
