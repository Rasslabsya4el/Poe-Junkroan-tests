"""#1029: `benchmark.py --force-keystone NAME` (PoB-free). The name resolves against the tree (exit 2 when unknown),
the skeleton's forced_nodes get the keystone's node id (the tree optimizers protect those, `skeleton.keystones` they do not), the row reads `with <NAME>` with a `-with-<name>` file stem, and the D40
keystone variants are off for that run."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph  # noqa: E402
from junkroan.pob import session as pob_session  # noqa: E402
from test_benchmark_resume import _patch_benchmark_main, _row  # noqa: E402


def test_unknown_keystone_exits_2_with_close_names_before_any_run(monkeypatch, tmp_path: Path, capsys) -> None:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    monkeypatch.setattr(benchmark, "run_one", lambda *_a, **_k: pytest.fail("a build started before the keystone name was checked"))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "--force-keystone", "Chaos Inoculatio", "--gear", "loot"])
    with pytest.raises(SystemExit) as exc:
        benchmark.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Chaos Inoculatio" in err
    assert "Chaos Inoculation" in err  # the close name the user meant
    assert not out_dir.exists()


def test_name_resolves_to_the_keystone_node_case_insensitively() -> None:
    graph = TreeGraph.load()
    node_id, name = benchmark.resolve_keystone_name(graph, "chaos inoculation")
    assert name == "Chaos Inoculation"
    node = graph.nodes[node_id]
    assert node.name == "Chaos Inoculation"
    assert node.kind == "keystone"


def test_forced_keystone_id_joins_the_skeleton_once() -> None:
    graph = TreeGraph.load()
    node_id = benchmark.resolve_keystone_name(graph, "Chaos Inoculation")[0]
    skeleton = SimpleNamespace(forced_nodes=[])
    benchmark.add_force_keystones(skeleton, graph, ["chaos inoculation", "Chaos Inoculation"])
    assert skeleton.forced_nodes == [node_id]


def test_forced_row_is_named_with_and_its_stem_is_with(monkeypatch, tmp_path: Path) -> None:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    seen: list[dict] = []

    class FakeSession:  # no PoB: the build stops at prepare_author, its row still carries the variant
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> bool:
            return False

    def fake_prepare_author(pob, slug, **kwargs):
        seen.append(kwargs)
        raise RuntimeError("stop before PoB")

    monkeypatch.setattr(pob_session, "PobSession", FakeSession)
    monkeypatch.setattr(benchmark, "prepare_author", fake_prepare_author)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "--gear", "loot", "--tag", "durable", "--force-keystone", "chaos inoculation"])
    benchmark.main()
    assert seen and seen[0]["force_keystones"] == ["Chaos Inoculation"]
    row = json.loads((out_dir / "rows" / "alpha-s1-with-chaos_inoculation.json").read_text(encoding="utf-8"))
    assert row["variant"] == "with Chaos Inoculation"
    assert not (out_dir / "rows" / "alpha-s1.json").exists()


def test_without_the_switch_the_names_are_unchanged(monkeypatch, tmp_path: Path) -> None:
    assert benchmark.result_stem({"slug": "alpha", "seed": 1}) == "alpha-s1"
    assert benchmark.result_stem({"slug": "alpha", "seed": 1, "variant": "no Imbalanced Guard"}) == "alpha-s1-no-imbalanced_guard"
    assert benchmark.result_stem({"slug": "alpha", "seed": 1, "variant": "with Chaos Inoculation"}) == "alpha-s1-with-chaos_inoculation"
    assert benchmark.variant_label() == ""
    assert benchmark.variant_label(["Imbalanced Guard"]) == "no Imbalanced Guard"
    assert benchmark.variant_label([], ["Chaos Inoculation"]) == "with Chaos Inoculation"

    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    monkeypatch.setattr(benchmark, "run_one", lambda slug, **_kw: _row(slug))
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "--workers", "1", "--no-variants", "--gear", "loot", "--tag", "durable"])
    assert benchmark.main() == 0
    assert (out_dir / "rows" / "alpha-s1.json").exists()


def test_force_keystone_turns_the_d40_variants_off(monkeypatch, tmp_path: Path) -> None:
    out_dir, _stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    # a base row that would otherwise plan a D40 variant for Imbalanced Guard
    monkeypatch.setattr(benchmark, "_variant_keystones", lambda _row: ["Imbalanced Guard"])
    calls: list[dict] = []

    def fake_run_one(slug, **kwargs):
        calls.append(kwargs)
        row = _row(slug)
        row["variant"] = benchmark.variant_label([], kwargs.get("force_keystones") or [])
        row["keystones"] = ["Imbalanced Guard"]
        return row

    monkeypatch.setattr(benchmark, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "beta", "--workers", "2", "--gear", "loot", "--tag", "durable", "--force-keystone", "Chaos Inoculation"])
    assert benchmark.main() == 0
    plan = json.loads((out_dir / "variants.json").read_text(encoding="utf-8"))
    assert plan["planned"] == []
    assert plan["base_rows"] == 2 and plan["base_done"] == 2
    assert all(not call.get("forbid_keystones") for call in calls)
    assert [call["force_keystones"] for call in calls] == [["Chaos Inoculation"], ["Chaos Inoculation"]]
    assert sorted(p.name for p in (out_dir / "rows").glob("*.json")) == ["alpha-s1-with-chaos_inoculation.json", "beta-s1-with-chaos_inoculation.json"]
