"""core_check monitor exemptions (#830): the plugin-id literal is stripped only under the monitor
prefixes, and under them L2 still fails on every word but `slot`/`slots`."""

from __future__ import annotations

from tools.agentops.core_check import PATTERNS_PATH, check_file, read_patterns, run_check

LITERAL = "po" + "b" + "-s" + "lots"


def _run(tmp_path, rel, line):
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(line + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(rel + "\n", encoding="utf-8")
    rows, ok = run_check(root=tmp_path, manifest_path=manifest, patterns_path=PATTERNS_PATH)
    return rows[0], ok


def test_literal_stripped_only_under_monitor_prefixes(tmp_path):
    row, ok = _run(tmp_path, "docs/x.md", f"plugin {LITERAL} here")
    assert not ok and row.counts["L1"] > 0
    row, ok = _run(tmp_path, f"mods/{LITERAL}/hooks/x.ts", f"plugin {LITERAL} here")
    assert ok and row.counts["L1"] == 0


def test_monitor_l2_only_slot_word_is_exempt(tmp_path):
    for word, passes in (("keymaster", False), ("filler", False), ("slots", True), ("a slot", True)):
        row, ok = _run(tmp_path, "mods/x/a.ts", f"the {word} card")
        assert ok is passes, word
        assert row.counts["L2"] > 0, word  # the report column stays raw


def test_check_file_signature_unchanged(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("hello\n", encoding="utf-8")
    assert check_file(f, "a.md", read_patterns(PATTERNS_PATH)).counts["L2"] == 0


def test_manifest_lists_monitor_paths_but_not_other_lines_with_the_literal(tmp_path):
    row, ok = _run(tmp_path, "tools/agentops/core_manifest.txt", f"mods/{LITERAL}/hooks/kit.tsx")
    assert ok and row.counts["L1"] == 0
    row, ok = _run(tmp_path, "tools/agentops/core_manifest.txt", f"docs/{LITERAL}.md")
    assert not ok and row.counts["L1"] > 0
