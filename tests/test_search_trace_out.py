import argparse
import json

from junkroan.cli import search_argv
from junkroan.search.trace_out import merge_considered, with_total, write_trace_out

A = {"m1": {"forced:kept": {"generated": 3, "evaluated": 2}, "forced-missing:unique:Body Armour": {"generated": 1, "evaluated": 0}}}
B = {"m1": {"forced:kept": {"generated": 1, "evaluated": 1}}, "m2": {"forced:kept": {"generated": 4, "evaluated": 4}}}


def test_merge_sums_move_class_kind():
    m = merge_considered([A, B, None])
    assert m["m1"]["forced:kept"] == {"generated": 4, "evaluated": 3}
    assert m["m2"]["forced:kept"] == {"generated": 4, "evaluated": 4}
    assert m["m1"]["forced-missing:unique:Body Armour"] == {"generated": 1, "evaluated": 0}


def test_total_sums_over_moves(tmp_path):
    doc = write_trace_out(tmp_path / "t" / "trace.json", [A, B])
    assert doc["total"]["forced:kept"] == {"generated": 8, "evaluated": 7}
    assert doc["total"]["forced-missing:unique:Body Armour"]["evaluated"] == 0
    assert json.loads((tmp_path / "t" / "trace.json").read_text()) == doc
    assert with_total({})["total"] == {}


def test_cli_passes_trace_out():
    ns = argparse.Namespace(dry_run=False, no_variants=False, trace_out="x/t.json")
    argv = search_argv(ns, "/tmp/r.json", "Fireball")
    assert argv[argv.index("--trace-out") + 1] == "x/t.json"
    assert "--trace-out" not in search_argv(argparse.Namespace(dry_run=False, no_variants=False), "/tmp/r.json", "Fireball")
