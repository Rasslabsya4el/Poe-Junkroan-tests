"""Row 1 guard, pane half (#796 u4e): the pane's generic files hold no word of the project they serve. Lines of
`hooks/register.tsx`, `hooks/kit.tsx`, `hooks/tokens.ts` and `mods/shared/draw.ts` matching `pob|build|laptop|junkroan|poe`
(case-insensitive) are counted per word and must be 0. The ONE exception: the string literal `pob-slots` (the installed
folder name; the plugin loader wants it in the file that declares each atom), stripped before matching; its line count is printed.
(A plugin test cannot read files: a hooks module imports nothing but its own files and "claude-code".)

    python -m pytest -q -s bin/test_generic_words_pane.py
"""
from pathlib import Path

MOD = Path(__file__).resolve().parent.parent
FILES = [MOD / "hooks" / "register.tsx", MOD / "hooks" / "kit.tsx", MOD / "hooks" / "tokens.ts", MOD.parent / "shared" / "draw.ts"]
WORDS = ["pob", "build", "laptop", "junkroan", "poe"]
EXCEPTION = "pob-slots"


def test_pane_generic_files_have_no_project_words():
    counts = {w: 0 for w in WORDS}
    covered = 0
    bad = []
    for f in FILES:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if EXCEPTION in line:
                covered += 1
            rest = line.replace(EXCEPTION, "").lower()
            for w in WORDS:
                if w in rest:
                    counts[w] += 1
                    bad.append(f"{f.name}:{n} {w}: {line.strip()[:80]}")
    print(f"{len(FILES)} files: " + ", ".join(f"{w} {counts[w]}" for w in WORDS) + f"; lines covered by the '{EXCEPTION}' exception: {covered}")
    assert not bad, bad
