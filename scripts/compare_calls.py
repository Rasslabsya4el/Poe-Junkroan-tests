"""Compare two PoB call transcripts written by `RecordingPob` (the refactor proof of #35).

A refactor that must reproduce builds to the digit makes the same PoB calls in the same order with
the same arguments. This prints, for two transcripts (files) or two directories of them (paired by
file name): the verdict IDENTICAL or DIFFERENT, the first differing call with the calls before it,
the calls per method on each side, and whether the difference is one of order only (the same
calls, another sequence). Exit code 0 when every pair is identical, 1 otherwise.

`load_xml` calls are compared by XML length, not hash: PoB writes an element's attributes (and some
siblings) in Lua `pairs` order, which changes from one process to the next, so the same build
exports different bytes of the same length (measured on #35 P2: 30 and 231 such calls, the final
builds equal up to attribute and sibling order, every other call equal to the hash). The verdict line
says how many calls were matched that way; `--strict-xml` compares their hashes too.

`#978`: a run also writes `<stem>.lists.json` next to its transcript, the sha256 of each saved support list it
started with (`absent` when the file did not exist). Two runs whose records differ for a list either one
consulted started from different inputs: the verdict is NOT COMPARABLE and no call diff is printed. A side
without a record gets the line `(no saved-list record)` and the comparison goes on as before.

    python scripts/compare_calls.py artifacts/proof-35/base artifacts/proof-35/head
    python scripts/compare_calls.py base/skeleton-stormbrand.calls.jsonl head/skeleton-stormbrand.calls.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

CONTEXT_CALLS = 6  # calls shown before the first difference
XML_LEN = re.compile(r'"len":(\d+)')
STRICT_XML = False  # set by --strict-xml


def read_calls(path: Path) -> list[dict[str, Any]]:
    calls = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                calls.append(json.loads(line))
            except json.JSONDecodeError as exc:  # a transcript cut by a crash ends in a partial line
                calls.append({"seq": None, "method": "<unreadable line>", "args": f"line {number}: {exc.msg}", "preview": line[:80]})
    return calls


def key(call: dict[str, Any]) -> tuple[str, str]:
    method = str(call.get("method"))
    if method == "load_xml" and not STRICT_XML:
        m = XML_LEN.search(str(call.get("preview", "")))
        if m:
            return method, f"len {m.group(1)}"
    return method, str(call.get("args"))


def by_length_only(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> int:
    """Calls whose key matched while their argument hashes differ (load_xml equal by length)."""
    return sum(1 for left, right in zip(a, b) if key(left) == key(right) and left.get("args") != right.get("args"))


def first_difference(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> int | None:
    """Index of the first call that differs (method or argument hash), or of the first call one
    side has and the other does not; None when the two are equal."""

    for index, (left, right) in enumerate(zip(a, b)):
        if key(left) != key(right):
            return index
    return None if len(a) == len(b) else min(len(a), len(b))


def show(call: dict[str, Any] | None) -> str:
    if call is None:
        return "(no call: this transcript ends here)"
    return f"#{call.get('seq')} {call.get('method')} {call.get('args')} {call.get('preview', '')}"


def lists_path(transcript: Path) -> Path:
    """#978: the sidecar of a transcript: `<stem>.lists.json` beside `<stem>.calls.jsonl`."""
    stem = transcript.name[:-len(".calls.jsonl")] if transcript.name.endswith(".calls.jsonl") else transcript.stem
    return transcript.with_name(f"{stem}.lists.json")


def read_lists(transcript: Path) -> dict[str, str] | None:
    path = lists_path(transcript)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def short(value: str | None) -> str:
    if value is None:
        return "not consulted"
    return value if value == "absent" else value[:16]


def list_differences(left: dict[str, str], right: dict[str, str]) -> list[tuple[str, str | None, str | None]]:
    """The saved lists consulted by either side whose records differ; None where a side did not consult it."""
    return [(name, left.get(name), right.get(name)) for name in sorted(set(left) | set(right)) if left.get(name) != right.get(name)]


def describe_lists(record: dict[str, str]) -> str:
    return ", ".join(f"{name} {short(value)}" for name, value in sorted(record.items())) or "(none consulted)"


def compare_pair(name: str, left: Path, right: Path) -> bool:
    a, b = read_calls(left), read_calls(right)
    lists_a, lists_b = read_lists(left), read_lists(right)
    head = f"== {name}: {len(a)} calls vs {len(b)} calls"
    if lists_a is not None and lists_b is not None:
        differing = list_differences(lists_a, lists_b)
        if differing:
            detail = "; ".join(f"{list_name}: left {short(x)} / right {short(y)}" for list_name, x, y in differing)
            print(f"{head}: NOT COMPARABLE: saved support list differs ({detail})")
            return False
    index = first_difference(a, b)
    print(f"{head}: {'IDENTICAL' if index is None else 'DIFFERENT'}")
    for side, record in (("left", lists_a), ("right", lists_b)):
        if record is not None:
            print(f"   saved lists {side}:  {describe_lists(record)}")
    if lists_a is None or lists_b is None:
        print("   (no saved-list record)")
    if index is None:
        loose = by_length_only(a, b)
        if loose:
            print(f"   ({loose} load_xml calls equal by XML length, their bytes differ: PoB's attribute order)")
        return True
    print(f"first difference at call {index + 1} (the calls before it are equal):")
    for call in a[max(0, index - CONTEXT_CALLS):index]:
        print(f"    {show(call)}")
    print(f"  left:  {show(a[index] if index < len(a) else None)}")
    print(f"  right: {show(b[index] if index < len(b) else None)}")
    counts_a, counts_b = Counter(str(c.get("method")) for c in a), Counter(str(c.get("method")) for c in b)
    rows = [(method, counts_a.get(method, 0), counts_b.get(method, 0)) for method in sorted(set(counts_a) | set(counts_b))]
    print("calls per method (left / right):")
    for method, left_count, right_count in rows:
        mark = "" if left_count == right_count else "   <- differs"
        print(f"    {method:<28} {left_count:>7} {right_count:>7}{mark}")
    same_multiset = Counter(map(key, a)) == Counter(map(key, b))
    print("order only: the same calls in another sequence" if same_multiset else "not order only: the two sides make different calls")
    return False


def pairs(left: Path, right: Path) -> list[tuple[str, Path, Path]]:
    if left.is_file() and right.is_file():
        return [(left.name, left, right)]
    if left.is_dir() and right.is_dir():
        names_left = {p.name for p in left.glob("*.calls.jsonl")}
        names_right = {p.name for p in right.glob("*.calls.jsonl")}
        for missing in sorted(names_left ^ names_right):
            print(f"== {missing}: only in {'left' if missing in names_left else 'right'}")
        return [(name, left / name, right / name) for name in sorted(names_left & names_right)]
    raise SystemExit(f"compare two files or two directories: {left} / {right}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("left", type=Path, help="transcript file or directory (e.g. the base commit's)")
    parser.add_argument("right", type=Path, help="transcript file or directory (e.g. the head commit's)")
    parser.add_argument("--strict-xml", action="store_true", help="compare load_xml calls by hash, not by length")
    args = parser.parse_args()
    global STRICT_XML
    STRICT_XML = args.strict_xml
    found = pairs(args.left, args.right)
    if not found:
        print("no transcript pairs found")
        return 1
    results = [compare_pair(name, left, right) for name, left, right in found]
    print(f"\n{sum(results)} of {len(results)} transcripts identical")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
