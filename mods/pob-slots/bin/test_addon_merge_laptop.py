"""Plain-python check of collect.merge_laptop (#667): python test_merge_laptop.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()  # the project's add-on: the subject of this file


def pc():
    return {"running": [], "queued": [],
            "history": [{"tag": "P1-#600", "host": "pc", "end": "2026-10-09T13:07:00Z"},
                        {"tag": "P1-#609", "host": "pc", "end": "2026-10-09T11:51:00Z"}]}


def test_laptop_runs_join_the_card():
    r = pc()
    lap = {"runs": {"running": [{"tag": "P1-#648", "host": "laptop"}], "queued": [{"tag": "P1-#648-2", "host": "laptop"}],
                    "recent": [{"tag": "P1-#604", "host": "laptop", "end": "2026-10-09T12:27:00Z"}]}}
    addon.merge_laptop(r, lap)
    assert [j["tag"] for j in r["running"]] == ["P1-#648"]
    assert [j["tag"] for j in r["queued"]] == ["P1-#648-2"]
    assert [j["tag"] for j in r["history"]] == ["P1-#600", "P1-#604", "P1-#609"]


def test_laptop_out_of_reach_keeps_its_last_rows_stale():
    r = pc()
    addon.merge_laptop(r, {"error": "ssh timeout", "offline": {"seen": "02:31"},
                             "last": {"running": [{"tag": "P1-#555", "host": "laptop"}], "queued": [{"tag": "P1-#556", "host": "laptop"}]}})
    assert r["running"] == [{"tag": "P1-#555", "host": "laptop", "stale": True, "stale_since": "02:31"}]
    assert r["queued"][0]["stale"] is True and len(r["history"]) == 2


def test_laptop_never_read_adds_nothing():
    r = pc()
    addon.merge_laptop(r, {"error": "ssh timeout", "offline": {}})
    assert r["running"] == [] and r["queued"] == [] and len(r["history"]) == 2


def test_last_runs_come_from_the_cached_reading():
    cache = {"at": "2026-10-10T02:31:00", "data": {"runs": {"running": [{"tag": "A"}], "queued": [], "recent": [{"tag": "H"}]}}}
    assert addon.last_runs(cache) == {"running": [{"tag": "A"}], "queued": []}
    assert addon.last_runs(None) == {"running": [], "queued": []}


if __name__ == "__main__":
    test_laptop_runs_join_the_card()
    test_laptop_out_of_reach_keeps_its_last_rows_stale()
    test_laptop_never_read_adds_nothing()
    test_last_runs_come_from_the_cached_reading()
    print("ok")
