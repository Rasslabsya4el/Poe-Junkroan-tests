"""junkroan CLI: flags become a request (docs/REQUEST.md); dry runs go through the search echo."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from junkroan.cli import main, request_from_args, search_argv

ROOT = Path(__file__).resolve().parents[1]


def test_flags_become_a_request(capsys) -> None:
    rc = main(["build", "--skill", "Storm Brand", "--mode", "hit", "--ascendancy", "Hierophant,Inquisitor", "--level", "80", "--unique", "Body Armour=Hyrri's Ire".replace("\\", ""),
               "--scaling", "Int:0.3", "--config", "multiplierRage=20", "--forbid-supports", "Decay", "--utilities", "Grace", "--print-request"])
    assert rc == 0
    req = json.loads(capsys.readouterr().out)
    assert req["skill"] == "Storm Brand" and req["mode"] == "hit" and req["ascendancy"] == ["Hierophant", "Inquisitor"] and req["level"] == 80
    assert req["scaling"] == {"stat": "Int", "seed_points": 0.3} and req["config"] == {"multiplierRage": 20}
    assert req["forbid_supports"] == ["Decay"] and req["utilities"] == ["Grace"] and "Body Armour" in req["uniques"]


def test_request_file_with_flag_overrides(tmp_path, capsys) -> None:
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"skill": "Smite", "mode": "hit", "ascendancy": "auto", "top": 2}), encoding="utf-8")
    assert main(["build", str(f), "--ascendancy", "Slayer", "--print-request"]) == 0
    req = json.loads(capsys.readouterr().out)
    assert req["ascendancy"] == ["Slayer"] and req["top"] == 2 and req["skill"] == "Smite"


def test_dry_run_echoes_through_the_search() -> None:
    assert main(["build", "--skill", "Smite", "--mode", "hit", "--ascendancy", "Slayer", "--dry-run"]) == 0


def test_no_variants_reaches_the_search_as_flags() -> None:
    """The cheapest run (one full build per candidate) has to be reachable from `junkroan build`."""

    plain = search_argv(argparse.Namespace(dry_run=False, no_variants=False), "/tmp/r.json", "Storm Brand")
    assert plain == ["Storm Brand", "--request", "/tmp/r.json"]
    cheap = search_argv(argparse.Namespace(dry_run=True, no_variants=True), "/tmp/r.json", "Storm Brand")
    assert cheap == ["Storm Brand", "--request", "/tmp/r.json", "--dry-run", "--no-unique-variants", "--no-mutation"]


def test_seeds_reach_the_search_as_a_flag_and_the_request_as_a_field() -> None:
    """D71: the finalists are built `--seeds` times. The flag drives the run, the request
    field drives the echo's estimate, and both carry the same number."""

    argv = search_argv(argparse.Namespace(dry_run=False, no_variants=True, seeds=2), "/tmp/r.json", "Storm Brand")
    assert argv == ["Storm Brand", "--request", "/tmp/r.json", "--seeds", "2", "--no-unique-variants", "--no-mutation"]
    assert search_argv(argparse.Namespace(dry_run=False, no_variants=False, seeds=None), "/tmp/r.json", "Smite") == ["Smite", "--request", "/tmp/r.json"]


def test_full_ranks_and_loop_budget_reach_the_search() -> None:
    argv = search_argv(argparse.Namespace(dry_run=False, no_variants=False, seeds=None, full_ranks="1,3,9", loop_seconds=300), "/tmp/r.json", "Cold Snap")
    assert argv == ["Cold Snap", "--request", "/tmp/r.json", "--full-ranks", "1,3,9", "--loop-seconds", "300"]


def test_seeds_flag_becomes_a_request_field(capsys) -> None:
    assert main(["build", "--skill", "Storm Brand", "--mode", "hit", "--ascendancy", "Inquisitor", "--seeds", "2", "--top", "1", "--print-request"]) == 0
    req = json.loads(capsys.readouterr().out)
    assert req["seeds"] == 2 and req["top"] == 1
    assert main(["build", "--skill", "Storm Brand", "--mode", "hit", "--ascendancy", "Inquisitor", "--print-request"]) == 0
    assert "seeds" not in json.loads(capsys.readouterr().out)  # unset means the request's default (3)


def test_the_launcher_runs_in_a_fresh_checkout() -> None:
    """`scripts/junkroan.py` is the CLI without installing the package: `python -m junkroan.cli`
    needs `src` on sys.path, which a fresh checkout or worktree does not have."""

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "junkroan.py"), "build", "--skill", "Smite", "--mode", "hit", "--ascendancy", "Slayer", "--print-request"],
                          capture_output=True, text=True, env=env, cwd=str(ROOT.parent))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["skill"] == "Smite"
