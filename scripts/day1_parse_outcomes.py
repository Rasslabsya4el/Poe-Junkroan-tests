"""#1119 unit 3: PoB's parse outcome for every day-1 line that has none (`missing` in day1_lines.py).

Writes `src/junkroan/pob/corpus_data/parse_outcomes.json`: {exact line: {ok, unsupported, extra, mod_types}}, the
shape `scripts/day1_lines.py` reads. Each line goes through PoB's own mod parser (`PobSession.parse_mods`, which
is `modLib.parseMod`); the file is the only output.

- Only the lines `day1_lines.py` lists as `missing` are sent to PoB; a line already in the file is kept, never
  re-parsed.
- Batches of BATCH_SIZE lines, the file rewritten (atomically) after each batch: a run killed halfway keeps every
  finished batch, and the next run parses only what is left.
- Deterministic bytes: keys sorted, two-space indent, one trailing newline; input order does not change the file.

Run (a PoB job: through the runs queue, never by hand): `python scripts/day1_parse_outcomes.py`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from day1_lines import PARSE_OUTCOMES  # noqa: E402

BATCH_SIZE = 100

ParseMods = Callable[[list[str]], list[Mapping[str, Any]]]
EntryOf = Callable[[Mapping[str, Any]], Any]


def missing_lines(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """The distinct lines of the day1_lines rows whose outcome is `missing`, sorted."""

    return sorted({str(row["line"]) for row in rows if row["outcome"] == "missing"})


def outcome_entry(result: Mapping[str, Any]) -> dict[str, Any]:
    """One PoB parse result (`PobSession.parse_mods` item) -> the parse_outcomes.json entry."""

    mod_types = sorted({str(mod["type"]) for mod in result.get("mods") or () if mod.get("type")})
    return {
        "extra": str(result.get("extra") or ""),
        "mod_types": mod_types,
        "ok": bool(result.get("ok")),
        "unsupported": bool(result.get("unsupported")),
    }


def read_outcomes(path: Path) -> dict[str, dict[str, Any]]:
    """The file's entries, or {} when it does not exist yet."""

    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def write_outcomes(path: Path, entries: Mapping[str, Mapping[str, Any]]) -> None:
    """Whole-file write through a temporary file, so a kill never leaves half a JSON file."""

    text = json.dumps({line: entries[line] for line in sorted(entries)}, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def parse_batches(
    lines: Iterable[str],
    parse_mods: ParseMods,
    path: Path,
    *,
    batch_size: int = BATCH_SIZE,
    entry: EntryOf = outcome_entry,
) -> int:
    """Parse the given lines that the file does not hold yet; merge and write the file after each batch.

    `parse_mods` takes a list of lines and returns PoB's results (each with its `line`). `entry` turns one result
    into the value stored under its line (default: the parse_outcomes.json entry; #1125 passes its mod list).
    Returns the number of lines parsed in this call. A line PoB returns no result for is an error, never a silent gap.
    """

    entries = read_outcomes(path)
    todo = sorted({str(line) for line in lines} - entries.keys())
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        by_line = {str(result.get("line")): result for result in parse_mods(batch)}
        absent = [line for line in batch if line not in by_line]
        if absent:
            raise RuntimeError(f"PoB returned no result for {len(absent)} line(s), first: {absent[0]!r}")
        for line in batch:
            entries[line] = entry(by_line[line])
        write_outcomes(path, entries)
    return len(todo)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession
    from day1_lines import day1_rows, load_corpus

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PARSE_OUTCOMES,
                        help="where the entries are written (a queued run sits in a snapshot: pass a path under artifacts/)")
    out = parser.parse_args(argv).out
    out.parent.mkdir(parents=True, exist_ok=True)
    rails = Rails.load()
    corpus = load_corpus(rails)
    lines = missing_lines(day1_rows(rails, corpus))
    print(f"missing lines: {len(lines)}; already in {PARSE_OUTCOMES.name}: {len(corpus.parse_outcomes)}")
    with PobSession(run_id="day1-parse-outcomes") as pob:
        parsed = parse_batches(lines, pob.parse_mods, out)
    print(f"parsed {parsed} lines into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
