"""#992 rows 4 and 5: a computing build's `after` is never an English step name, and every log that holds a full
`step start:` line carries `stage_index` / `stage_count`.

`after` (an older pipeline's log: ended stages, no start lines) is the plain word of the last ended stage, the same word
the stage's own running state takes (#985's list), or the generic «считается» when the catalog does not know the stage. Checked on every
recorded log of the fixtures; the counts are printed.

    python -m pytest -q -s -p no:cacheprovider mods/pob-slots/bin/test_addon_after_word.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()
FIX = Path(__file__).resolve().parent / "fixtures"
LOGS = sorted(FIX.rglob("logs/*.log")) + sorted(FIX.rglob("logs/*.log.txt"))


def _stage(lines: list[str]) -> dict:
    with tempfile.TemporaryDirectory() as t:
        log = Path(t) / "x.log"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        keep, addon.stage_shares = addon.stage_shares, lambda: None
        try:
            return addon.build_stage(log, 0.0, 400.0)
        finally:
            addon.stage_shares = keep


def test_after_is_the_plain_word_of_the_last_ended_stage():
    for stage, word in {"skeleton applied": "собирает скелет", "gear pass 1 (empty tree)": "подбирает Items",
                        "anoint": "выбирает Anoint", "loop pass 4": "правит Tree", "flasks": "подбирает Flasks"}.items():
        assert _stage([f"  {stage}      2.7 min  value"]) == {"after": word}, stage
    # a stage the catalog does not know has no plain word of its own: the generic «считается», never the English name
    assert _stage(["  a stage nobody wrote down      2.7 min  value"]) == {"after": "считается"}


def test_every_recorded_log_has_no_english_after_and_every_step_line_has_its_scale():
    words = set(addon.STATUS_WORDS.values())
    ascii_after = no_scale = with_step = with_after = 0
    keep, addon.stage_shares = addon.stage_shares, lambda: None
    try:
        for log in LOGS:
            text = log.read_text(encoding="utf-8", errors="replace")
            st = addon.build_stage(log, 0.0, 400.0)
            if "after" in st:
                with_after += 1
                assert st["after"] in words, (log.name, st)
                ascii_after += st["after"].isascii()
            full = [ln for ln in text.splitlines()[:-1 if not text.endswith("\n") else None] if ln.startswith("step start: ")]
            if any(addon._catalog().step_of(ln[len("step start: "):]) for ln in full):  # a real catalog step is named
                with_step += 1
                no_scale += not ("stage_index" in st and "stage_count" in st)
    finally:
        addon.stage_shares = keep
    print(f"{len(LOGS)} recorded logs: {with_after} with `after`, ASCII-only `after`: {ascii_after}; "
          f"{with_step} with a full step line, without stage_index/stage_count: {no_scale}")
    assert LOGS and ascii_after == 0 and no_scale == 0
