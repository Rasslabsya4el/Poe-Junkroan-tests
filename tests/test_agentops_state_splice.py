"""`_splice_state_entry` cuts by each entry's own time, never the entry being written.

Fixtures under tests/fixtures/state_splice/: `<sha>.txt` = the `Updated` block of
`git show <sha>^:docs/STATE.md`, `<sha>.entry.txt` = the line that commit added;
`5bce5fa.txt` = the block at 5bce5fa (7 lines, the chat brain's the 7th and newest)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.agentops.merge import (MAX_REVIEWS, MAX_STATE_WRITERS, _entry_time,
                                 _splice_review_entry, _splice_state_entry)

FX = Path(__file__).parent / "fixtures" / "state_splice"
LINE_RE = re.compile(r"^Updated \(([^)]*)\): (.*)$")
BRAIN = "the chat brain"


def _block(name: str) -> list[str]:
    return (FX / name).read_text(encoding="utf-8").splitlines()


def _splice(lines: list[str], writer: str, entry: str) -> list[str]:
    text = "# State\n\n" + "\n".join(lines) + "\n\nLast review: x\n"
    out = _splice_state_entry(text, writer, entry)
    return [l for l in out.split("\n") if l.startswith("Updated")]


def _writers(lines: list[str]) -> list[str]:
    return [LINE_RE.match(l).group(1) for l in lines]


def _time(line: str) -> str:
    return LINE_RE.match(line).group(2)[:16]


def test_new_writer_on_seven_line_block_cuts_two_oldest():
    block = _block("5bce5fa.txt")
    assert len(block) == 7 and _writers(block)[-1] == BRAIN
    out = _splice(block, "ORCH test", "2026-09-29 09:00 (ORCH test, x)")
    assert len(out) == MAX_STATE_WRITERS
    assert _writers(out)[0] == "ORCH test" and BRAIN in _writers(out)
    oldest_two = sorted(block, key=_time)[:2]
    cut = [l for l in block if l not in out]
    assert sorted(cut) == sorted(oldest_two)


def test_chat_brain_on_seven_line_block_cuts_one_oldest():
    block = _block("5bce5fa.txt")
    out = _splice(block, BRAIN, "2026-09-29 09:00 (the chat brain, x)")
    assert len(out) == MAX_STATE_WRITERS and _writers(out)[0] == BRAIN
    assert _writers(out).count(BRAIN) == 1
    others = [l for l in block if _writers([l])[0] != BRAIN]
    oldest = sorted(others, key=_time)[0]
    assert [l for l in others if l not in out] == [oldest]


@pytest.mark.parametrize("sha", ["c5b401d", "7cfea8b", "60d79ed", "dbb28c5", "19ae838"])
def test_replay_never_cuts_the_chat_brain(sha):
    block = _block(f"{sha}.txt")
    entry_line = _block(f"{sha}.entry.txt")[0]
    m = LINE_RE.match(entry_line)
    out = _splice(block, m.group(1), m.group(2))
    assert BRAIN in _writers(out)
    assert _writers(out)[0] == m.group(1)


def test_writer_already_in_short_block_moves_to_top_no_cut():
    block = [
        "Updated (a): 2026-09-28 10:00 one",
        "Updated (b): 2026-09-28 11:00 two",
        "Updated (c): 2026-09-28 12:00 three",
    ]
    out = _splice(block, "c", "2026-09-28 13:00 three again")
    assert _writers(out) == ["c", "a", "b"]
    assert out[0].endswith("three again")


def test_no_readable_time_counts_oldest_and_ties_cut_lowest_in_file():
    block = [f"Updated ({w}): {t}" for w, t in [
        ("a", "2026-09-28 10:00 x"), ("b", "no time here"), ("c", "2026-09-28 10:00 x"),
        ("d", "2026-09-28 10:00:30 x"), ("e", "2026-09-28 10:00 x"), ("f", "2026-09-28 10:00 x"),
    ]]
    out = _splice(block, "n", "2026-09-28 11:00 x")
    assert _writers(out) == ["n", "a", "c", "d", "e", "f"]  # b (no time) cut
    out = _splice(block[:1] + block[2:] + ["Updated (g): 2026-09-28 10:00 x"], "n",
                  "2026-09-28 11:00 x")
    assert _writers(out) == ["n", "a", "c", "d", "e", "f"]  # all tie: the lowest in the file (g) goes


def test_entry_time_is_found_anywhere_in_the_text():
    assert _entry_time("the chat brain, x; since 11:45 on 2026-09-30; (2026-09-30 12:45) y") == "2026-09-30 12:45"
    assert _entry_time("2026-09-29 10:00:30 head") == "2026-09-29 10:00"
    assert _entry_time("no time here") == ""


def test_gap_in_block_and_mid_text_time():
    orch = [f"Updated (ORCH {i}): 2026-09-29 {10 + i}:00 x" for i in range(6)]
    brain = ("Updated (the chat brain): the chat brain, the chat named by brain_chat_title; "
             "a chat since 11:45 on 2026-09-30; (2026-09-30 12:45) y")
    old = ["Updated (ORCH old1): 2026-09-28 10:00 x", "Updated (ORCH old2): 2026-09-28 11:00 x"]
    text = "\n".join(["# State", ""] + orch + [brain, ""] + old + ["", "Last review: x", ""])
    out = _splice_state_entry(text, "ORCH new", "2026-09-30 13:00 z").split("\n")
    idx = [i for i, l in enumerate(out) if l.startswith("Updated")]
    assert len(idx) == MAX_STATE_WRITERS
    assert idx == list(range(idx[0], idx[0] + len(idx)))  # one contiguous run
    assert any(out[i].startswith("Updated (the chat brain)") for i in idx)
    assert not any("ORCH 0)" in out[i] or "old" in out[i] for i in idx)
    assert any(l.startswith("Last review") for l in out)


def _state_text_of_full_block() -> str:
    # The live file's shape, built here (#571: a test never reads the live docs/STATE.md):
    # a full block of MAX_STATE_WRITERS writers, newest first, then a review line and the rest.
    lines = [f"Updated (ORCH w{i}): 2026-10-0{6 - i} 12:00 entry {i}" for i in range(MAX_STATE_WRITERS)]
    return ("# State\n\nWhat the machines run.\n\n" + "\n".join(lines)
            + "\n\nLast review: r.\n\n## Runs\n\n- a run\n")


def test_built_state_block_is_capped_in_one_run():
    text = _state_text_of_full_block()
    out = _splice_state_entry(text, "ORCH test", "2099-01-01 00:00 t").split("\n")
    idx = [i for i, l in enumerate(out) if l.startswith("Updated")]
    assert len(idx) == MAX_STATE_WRITERS == 6
    assert idx == list(range(idx[0], idx[0] + len(idx)))  # one contiguous run
    assert out[idx[0]].startswith("Updated (ORCH test): 2099-01-01 00:00")
    assert not any("ORCH w5)" in out[i] for i in idx)  # the oldest own time left
    assert [l for l in out if not l.startswith("Updated")] == \
        [l for l in text.split("\n") if not l.startswith("Updated")]


# -- `_splice_review_entry`: the `Last review` line keeps at most MAX_REVIEWS reviews ----------------

def _reviews(line: str) -> list[str]:
    body = line[len("Last review:"):]
    return [s.strip().rstrip(".") for s in re.split(r"\s*Before it:\s*", body)]


def _review_text(n_old: int) -> str:
    old = [f"2026-09-{30 - i:02d} 10:00 review {i}" for i in range(n_old)]
    line = "Last review: " + ". Before it: ".join(old) + "."
    return "# State\n\nUpdated (a): 2026-10-01 10:00 x\nUpdated (b): 2026-10-01 11:00 y\n\n" + line + "\n\nrest\n"


def test_eighteen_old_links_leave_three_reviews_other_lines_identical():
    text = _review_text(19)  # the newest + 18 `Before it:` links
    assert text.count("Before it:") == 18
    out = _splice_review_entry(text, "NEW entry.")
    old_lines, new_lines = text.split("\n"), out.split("\n")
    assert len(old_lines) == len(new_lines)
    diff = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert len(diff) == 1 and new_lines[diff[0]].startswith("Last review")
    assert _reviews(new_lines[diff[0]]) == ["NEW entry", "2026-09-30 10:00 review 0",
                                           "2026-09-29 10:00 review 1"]
    assert new_lines[diff[0]].count("Before it:") == 2 and new_lines[diff[0]].endswith(".")


def test_before_it_without_space_is_its_own_segment():
    text = "Updated: t\n\nLast review: A. Before it:2026-09-27 18:25 B. Before it: C.\n"
    out = _splice_review_entry(text, "N")
    assert out == "Updated: t\n\nLast review: N. Before it: A. Before it: 2026-09-27 18:25 B.\n"


def test_fewer_reviews_than_cap_all_kept_and_no_trailing_newline_kept():
    out = _splice_review_entry("Last review: A.", "N")
    assert out == "Last review: N. Before it: A."


def test_no_last_review_line_inserts_after_updated_block():
    text = "# State\n\nUpdated (a): x\nUpdated (b): y\n\nrest\n"
    out = _splice_review_entry(text, "N")
    assert out == "# State\n\nUpdated (a): x\nUpdated (b): y\n\nLast review: N.\n\nrest\n"
    assert _splice_review_entry("rest\n", "N") == "Last review: N.\n\nrest\n"


def _review_of(tag: str, size: int) -> str:
    return tag + " " + "y" * (size - len(tag) - 1)


def _review_line_of(text: str) -> str:
    return next(l for l in text.split("\n") if l.startswith("Last review"))


def test_byte_cap_drops_whole_older_entries_newest_first():
    text = "# State\n\nLast review: seed.\n"
    for tag in ("R1", "R2", "R3"):
        text = _splice_review_entry(text, _review_of(tag, 1400))
    text = _splice_review_entry(text, _review_of("R4", 500))
    line = _review_line_of(text)
    assert len(line.encode("utf-8")) < 3072
    revs = _reviews(line)
    assert [r[:2] for r in revs] == ["R4", "R3"]
    assert len(revs[0]) == 500 and len(revs[1]) == 1400


def test_single_review_over_the_cap_is_kept_whole():
    big = _review_of("BIG", 4000)
    out = _splice_review_entry("Last review: A.\n", big)
    assert _reviews(_review_line_of(out)) == [big]


def test_multibyte_entries_counted_in_bytes():
    new = "я" * 700  # 1400 bytes
    out = _splice_review_entry("Last review: " + ("ж" * 800) + ".\n", new)
    assert _reviews(_review_line_of(out)) == [new, "ж" * 800]
    out = _splice_review_entry("Last review: " + ("ж" * 1000) + ".\n", new)
    assert _reviews(_review_line_of(out)) == [new]


def _state_text_with_reviews(*entries: str) -> str:
    # Built here, never read from the live docs/STATE.md (#571): its content moves with every write.
    return ("# State\n\nUpdated (a): 2026-10-05 21:45 x\n\nLast review: "
            + ". Before it: ".join(entries) + ".\n\n## Runs\n")


@pytest.mark.parametrize("old_size, n_old, kept", [
    (1500, 2, 2),  # the live file's shape on 2026-10-05: two long entries, one old one dropped
    (400, 3, 3),   # short entries: MAX_REVIEWS kept, the third old one dropped
])
def test_built_state_review_line_capped_under_3kb(old_size, n_old, kept):
    olds = [_review_of(f"R{i}", old_size) for i in range(n_old)]
    out = _splice_review_entry(_state_text_with_reviews(*olds), "x" * 500)
    line = _review_line_of(out)
    size = len(line.encode("utf-8"))
    reviews = _reviews(line)
    assert len(reviews) == kept <= MAX_REVIEWS == 3
    assert reviews == ["x" * 500] + olds[:kept - 1]
    assert size < 3072, f"Last review line is {size} bytes"
    print(f"old {n_old} x {old_size} B + 500 B -> kept {len(reviews)}, line {size} B")


# -- #677: a finished ORCH's update never drops the brain's hand-off line -----------------------------

def _writers_of_text(text: str) -> list[str]:
    return [LINE_RE.match(l).group(1) for l in text.split("\n") if LINE_RE.match(l)]


def test_row1_orch_line_cut_first_brain_with_unreadable_time_kept():
    text = (FX / "ef13ebb.state.txt").read_text(encoding="utf-8")
    assert BRAIN in _writers_of_text(text)
    assert _entry_time([l for l in text.splitlines() if l.startswith("Updated (the chat")][0]) == ""
    out = _splice_state_entry(text, "ORCH 96ab41ac", "2026-10-09 19:26 x")
    writers = _writers_of_text(out)
    assert len(writers) == MAX_STATE_WRITERS
    assert writers[0] == "ORCH 96ab41ac" and BRAIN in writers
    assert "ORCH 73f6543d" not in writers


def test_row2_brain_line_kept_oldest_orch_cut():
    brain = "Updated (the chat brain): 19:4x hand-off, no readable time"
    orch = [f"Updated (ORCH o{i}): 2026-10-09 1{i}:00 e" for i in range(1, 6)]  # o1 oldest
    out = _splice(orch[:2] + [brain] + orch[2:], "ORCH new", "2026-10-09 19:30 n")
    assert len(out) == MAX_STATE_WRITERS
    assert _writers(out)[0] == "ORCH new" and BRAIN in _writers(out)
    assert "ORCH o1" not in _writers(out) and "ORCH o2" in _writers(out)


def test_non_orch_lines_cut_only_when_no_orch_line_left():
    lines = [f"Updated (w{i}): 2026-10-09 1{i}:00 e" for i in range(1, 6)]
    lines.append("Updated (ORCH only): 2026-10-09 10:00 e")
    out = _splice(lines, "w9", "2026-10-09 19:00 n")  # one ORCH line: it goes, whatever its time
    assert "ORCH only" not in _writers(out) and len(out) == MAX_STATE_WRITERS
    out = _splice(lines[:5], "w9", "2026-10-09 19:00 n")  # 5 others + new = 6: no cut
    assert len(out) == 6
    out = _splice(lines[:5] + ["Updated (w6): 2026-10-09 09:00 e"], "w9", "2026-10-09 19:00 n")
    assert "w6" not in _writers(out)  # no ORCH line left: the oldest other goes, as before


def test_row3_entry_with_own_heading_is_not_doubled():
    text = "# State\n\nUpdated (ORCH 1): 2026-10-09 10:00 old\n\nLast review: x\n"
    out = _splice_state_entry(text, "ORCH 1", "Updated (ORCH 1): 2026-10-09 19:26 y")
    assert [l for l in out.split("\n") if l.startswith("Updated")] == \
        ["Updated (ORCH 1): 2026-10-09 19:26 y"]
    out = _splice_state_entry(text, "ORCH 1", "Updated: 2026-10-09 19:26 y")
    assert "Updated (ORCH 1): 2026-10-09 19:26 y" in out and out.count("Updated") == 1


def test_row4_commit_refuses_an_entry_without_a_readable_time(tmp_path):
    import argparse
    import subprocess

    from tools.agentops.merge import run_commit_command

    def git(*a):
        return subprocess.run(["git", "-C", str(tmp_path), *a], capture_output=True, text=True,
                              check=True).stdout.strip()

    git("init", "-q")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATE.md").write_text("# State\n\nLast review: x\n", encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    head = git("rev-parse", "HEAD")
    args = argparse.Namespace(paths=["docs/STATE.md"], message="m", cwd=tmp_path,
                              lock=tmp_path / "lock", timeout=None,
                              state_entry="19:4x no date", state_as="w", review_entry=None)
    assert run_commit_command(args) == 2
    assert git("rev-parse", "HEAD") == head
