import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tests/fixtures/readings_queue"
NAMES = ["smite-s4.json", "absolution_minions-s4-no-eldritch_battery.json",
         "absolution_minions-s6.json"]
spec = importlib.util.spec_from_file_location("readings", ROOT / "scripts" / "readings.py")
readings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readings)


@pytest.fixture
def env(tmp_path):
    rows = tmp_path / "run" / "rows"
    rows.mkdir(parents=True)
    for n in NAMES:
        shutil.copy(SRC / n, rows / n)
    return tmp_path


def run(env, *args):
    return readings.main(["--queue", str(env / "queue.json"), *args])


def add(env, ref, seed, variant=None):
    a = ["add", "--run", str(env / "run"), "--ref", ref, "--seed", str(seed), "--note", "n"]
    if variant:
        a += ["--variant", variant]
    return run(env, *a)


def rows(env):
    return json.loads((env / "queue.json").read_text(encoding="utf-8"))["rows"]


def test_add_smite(env):
    assert add(env, "smite", 4) == 0
    r = rows(env)[0]
    assert r["pobbin_id"] == "ZopWMFtrGpNZ"
    assert r["author_pobbin_id"] == "XdmDHsFHiMlV"
    assert r["ratio_pct"] == 131 and r["life"] == 3779
    for k in ("seed", "ratio_pct", "ours", "author", "life"):
        assert isinstance(r[k], (int, float))


def test_add_twice(env):
    add(env, "smite", 4)
    add(env, "smite", 4)
    assert len(rows(env)) == 1


def test_variant(env):
    add(env, "absolution_minions", 4, "no-eldritch_battery")
    r = rows(env)[0]
    d = json.loads((env / "run/rows/absolution_minions-s4-no-eldritch_battery.json").read_text())
    assert r["variant"] == "no-eldritch_battery"
    assert r["pobbin_id"] == d["pobbin_id"]
    assert r["author_pobbin_id"] == d["author_pobbin_url"].rstrip("/").split("/")[-1]


def test_remove(env, capsys):
    add(env, "smite", 4)
    add(env, "absolution_minions", 6)
    capsys.readouterr()
    run(env, "remove", "--ref", "smite")
    assert "1" in capsys.readouterr().out.splitlines()
    assert not [r for r in rows(env) if r["ref"] == "smite"]


def test_missing_pobbin_id(env, capsys):
    p = env / "run/rows/smite-s4.json"
    d = json.loads(p.read_text())
    d.pop("pobbin_id")
    p.write_text(json.dumps(d))
    capsys.readouterr()
    assert add(env, "smite", 4) == 0
    assert rows(env)[0]["pobbin_id"] is None
    assert len(capsys.readouterr().err.strip().splitlines()) == 1


def test_missing_row_file(env, capsys):
    assert add(env, "nope", 1) == 2


def test_list_empty(env, capsys):
    assert run(env, "list") == 0
    assert "0 builds" in capsys.readouterr().out
    (env / "queue.json").write_text('{"updated": "x", "rows": []}')
    assert run(env, "list") == 0
    assert "0 builds" in capsys.readouterr().out


def test_list_rows(env, capsys):
    add(env, "smite", 4)
    capsys.readouterr()
    run(env, "list")
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "1 builds"


CORE = "core_audit-s4.json"  # a benchmark row file: audit list = 1 [error] + 2 [warning] lines


def test_add_benchmark_audit(env):
    shutil.copy(SRC / CORE, env / "run" / "rows" / CORE)
    assert add(env, "core_audit", 4) == 0
    r = rows(env)[0]
    assert r["audit"] == "1 errors / 2 warnings"
    assert r["floors"] is None


def test_add_benchmark_audit_absent(env):
    d = json.loads((SRC / CORE).read_text(encoding="utf-8"))
    d.pop("audit")
    (env / "run" / "rows" / CORE).write_text(json.dumps(d), encoding="utf-8")
    assert add(env, "core_audit", 4) == 0
    assert rows(env)[0]["audit"] is None


def test_fill_audit(env, capsys):
    shutil.copy(SRC / CORE, env / "run" / "rows" / CORE)
    run_dir = (env / "run").as_posix()
    queued = {"run_name": "", "ref": "core_audit", "seed": 4, "variant": "", "pobbin_id": "AbC",
              "author_pobbin_id": None, "ratio_pct": 90, "metric": "CombinedDPS", "ours": 1,
              "author": 2, "life": 3, "stop": "time", "note": "keep me",
              "added_at": "2026-10-13T00:00:00+00:00", "added_by": "brain"}
    other = dict(queued, run_dir="elsewhere/run", ref="other")
    (env / "queue.json").write_text(json.dumps(
        {"updated": "x", "rows": [dict(queued, run_dir=run_dir), other]}), encoding="utf-8")
    capsys.readouterr()
    assert run(env, "fill-audit", "--run", str(env / "run")) == 0
    got, rest = rows(env)
    assert got["audit"] == "1 errors / 2 warnings"
    assert got["note"] == "keep me" and got["pobbin_id"] == "AbC"
    assert "audit" not in rest and rest["note"] == "keep me"
    assert "1 filled" in capsys.readouterr().out
