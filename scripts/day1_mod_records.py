"""#1125 unit 1: PoB's mod list for every day-1 line whose outcome is full or partial (mod records).

Writes `src/junkroan/pob/corpus_data/day1_mod_records.json`: {exact line: [mod, ...]}, each mod `{name, type, value,
flags, keyword_flags, tags}` (the fields `scripts/build_unique_index.py:92` keeps, tags whole). Lines with outcome
none or missing get no record.

- Only the distinct lines of the `scripts/day1_lines.py` rows whose outcome is full or partial go to PoB
  (`PobSession.parse_mods`); the line is sent with its ranges rolled at the midpoint (`roll_line`, as
  `junkroan.optimizer.jewel_lines`), the record is keyed by the line as the rows write it.
- The batch loop, the resume after a kill and the atomic whole-file write are `day1_parse_outcomes.parse_batches`.
- Deterministic bytes: keys sorted, two-space indent, one trailing newline; input order does not change the file.

Run (a PoB job: through the runs queue, never by hand): `python scripts/day1_mod_records.py [--out PATH]`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from day1_parse_outcomes import BATCH_SIZE, ParseMods, parse_batches, read_outcomes  # noqa: E402
from junkroan.optimizer.jewel_lines import roll_line  # noqa: E402

MOD_FIELDS = ("name", "type", "value", "flags", "keyword_flags", "tags")
RECORD_OUTCOMES = frozenset({"full", "partial"})
MOD_RECORDS = ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "day1_mod_records.json"


def mod_records_lines(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """The distinct lines of the day1_lines rows whose outcome is full or partial, sorted."""

    return sorted({str(row["line"]) for row in rows if row["outcome"] in RECORD_OUTCOMES})


def mod_record_entry(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One PoB parse result (`PobSession.parse_mods` item) -> the record's mod list."""

    return [{field: mod.get(field) for field in MOD_FIELDS} for mod in result.get("mods") or ()]


def _rolled(parse_mods: ParseMods) -> ParseMods:
    """PoB parses each line with its ranges rolled at the midpoint; each result is labelled with the line as written."""

    def parse(batch: list[str]) -> list[Mapping[str, Any]]:
        by_text = {str(result.get("line")): result for result in parse_mods(sorted({roll_line(line) for line in batch}))}
        return [{**by_text[roll_line(line)], "line": line} for line in batch if roll_line(line) in by_text]

    return parse


def parse_records(lines: Iterable[str], parse_mods: ParseMods, path: Path, *, batch_size: int = BATCH_SIZE) -> int:
    """Write the mod list of every given line the file does not hold yet. Returns the number of lines parsed."""

    return parse_batches(lines, _rolled(parse_mods), path, batch_size=batch_size, entry=mod_record_entry)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession
    from day1_lines import day1_rows, load_corpus

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=MOD_RECORDS,
                        help="where the records are written (a queued run sits in a snapshot: pass a path under artifacts/)")
    out = parser.parse_args(argv).out
    out.parent.mkdir(parents=True, exist_ok=True)
    rails = Rails.load()
    corpus = load_corpus(rails)
    lines = mod_records_lines(day1_rows(rails, corpus))
    print(f"full + partial lines: {len(lines)}; already in {out.name}: {len(read_outcomes(out))}")
    with PobSession(run_id="day1-mod-records") as pob:
        parsed = parse_records(lines, pob.parse_mods, out)
    print(f"parsed {parsed} lines into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
