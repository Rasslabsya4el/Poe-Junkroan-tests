import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests/fixtures/readings_request/search-volcanic_fissure"
spec = importlib.util.spec_from_file_location("readings_req", ROOT / "scripts" / "readings.py")
readings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readings)

BENCH = ROOT / "tests/fixtures/readings_queue/smite-s4.json"


@pytest.fixture
def env(tmp_path, monkeypatch):
    shutil.copytree(FIX, tmp_path / "build")
    uploads = []
    monkeypatch.setattr(readings, "upload_code", lambda code: uploads.append(code) or f"ID{len(uploads):02d}")
    return tmp_path, uploads


def run(tmp, *args):
    return readings.main(["--queue", str(tmp / "q.json"), *args])


def rows(tmp):
    return json.loads((tmp / "q.json").read_text(encoding="utf-8"))["rows"]


def add_rank(tmp, n):
    return run(tmp, "add", "--build", str(tmp / "build"), "--rank", str(n), "--note", "n", "--run-name", "RN")


def test_request_rank_1(env):
    tmp, uploads = env
    assert add_rank(tmp, 1) == 0
    r = rows(tmp)[0]
    assert r["metric"] == "TotalDotDPS" and r["ours"] == 216282 and r["life"] == 4513
    assert r["seed"] == 2 and r["pobbin_id"] == "ID01"
    assert r["author_pobbin_id"] is None and r["ratio_pct"] is None and r["author"] is None
    assert r["audit"] == "0 errors / 3 warnings" and r["floors"] == "ok" and r["rank"] == 1
    assert uploads == ["FAKECODE-01 marauder_chieftain_imperial_staff"]


def test_request_list_and_remove(env, capsys):
    tmp, _ = env
    add_rank(tmp, 1)
    add_rank(tmp, 2)
    assert rows(tmp)[1]["ours"] == 118825 and rows(tmp)[1]["life"] == 4510
    assert run(tmp, "list") == 0
    assert "2 builds" in capsys.readouterr().out
    ref = rows(tmp)[0]["ref"]
    run(tmp, "remove", "--ref", ref)
    assert [r["rank"] for r in rows(tmp)] == [2]


def test_bad_rank(env):
    tmp, _ = env
    with pytest.raises(ValueError):
        add_rank(tmp, 9)


def test_benchmark_row_unchanged(tmp_path, monkeypatch):
    (tmp_path / "run/rows").mkdir(parents=True)
    shutil.copy(BENCH, tmp_path / "run/rows/smite-s4.json")
    monkeypatch.setattr(readings, "_now", lambda: "T")
    assert readings.main(["--queue", str(tmp_path / "q.json"), "add", "--run", "run/x", "--ref", "smite",
                          "--seed", "4", "--note", "n  x", "--run-name", "RN"]) == 2  # missing rows file
    readings.main(["--queue", str(tmp_path / "q.json"), "add", "--run", str(tmp_path / "run"), "--ref", "smite",
                   "--seed", "4", "--note", "n  x", "--run-name", "RN"])
    r = rows(tmp_path)[0]
    r.pop("run_dir")
    # expected = the benchmark row of this fixture (no audit key in the row file): #961 adds audit/floors as null
    assert r == {"run_name": "RN", "ref": "smite", "seed": 4, "variant": "", "pobbin_id": "ZopWMFtrGpNZ",
                 "author_pobbin_id": "XdmDHsFHiMlV", "ratio_pct": 131, "metric": "CombinedDPS", "ours": 737408,
                 "author": 561007, "life": 3779, "stop": "converged", "audit": None, "floors": None,
                 "note": "n x", "added_at": "T", "added_by": "brain"}
