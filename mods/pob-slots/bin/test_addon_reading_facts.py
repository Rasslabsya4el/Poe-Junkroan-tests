"""Plain-python check of collect._reading_facts (#683 r5: a reading's row in a reader's words): python test_reading_facts.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()  # the project's add-on: the subject of this file

REF = "03 marauder_chieftain_no_blood_magic_imperial_staff"
SKELETON = {"class_name": "Marauder", "ascendancy": "Chieftain", "main_link": ["Volcanic Fissure", "Immolate"],
            "forbid_keystones": ["Blood Magic"], "forbid_supports": [], "forbid_utilities": []}
AUDIT = ["[warning] not modelled by PoB: Ignited enemies cannot Ignite you (Cauterisation): worth zero in every number here",
         "[error] fixed point: the loop was not at a fixed point: one more pass gained +1.7% (swaps +1.7%)"]


def test_request_row():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / f"{REF}.json").write_text(json.dumps({"skeleton": json.dumps(SKELETON), "audit": AUDIT, "floors_missed": [
            "PhysicalMaximumHitTaken 4,120 < 6,000"]}), encoding="utf-8")
        row = {"run_dir": d, "ref": REF, "seed": 2, "variant": "", "rank": 3, "metric": "TotalDotDPS", "ours": 156945,
               "audit": "1 errors / 1 warnings", "floors": "ok"}
        seen: dict = {}
        out = addon._reading_facts(row, {}, seen)
        assert (out["name"], out["var"], out["class"], out["asc"]) == ("Volcanic Fissure", "без Blood Magic", "Marauder", "Chieftain"), out
        assert out["ours_h"] == "157k" and "TotalDotDPS" not in out["metric_label"], out
        assert (out["errors"], out["warnings"], out["floors_bad"]) == (1, 1, True), out
        # the failed ones first; no word of the code in a sentence
        assert out["said"][0] == [True, "поиск остановился рано: ещё один проход дал +1.7 %"], out["said"]
        assert out["said"][1] == [False, "PoB не считает: Ignited enemies cannot Ignite you (Cauterisation)"], out["said"]
        assert out["said"][2][0] is True and out["said"][2][1].startswith("ниже порога защиты: ") and "PhysicalMaximumHitTaken" not in out["said"][2][1], out["said"]
        assert out["said"][2][1].endswith(" 4,120 при пороге 6,000"), out["said"]
        # the file is read once: the second call takes the cache
        (key, got), = seen.items()
        again: dict = {}
        assert addon._reading_facts(row, {key: {**got, "skill": "From Cache"}}, again)["name"] == "From Cache"


def test_benchmark_row():
    out = addon._reading_facts({"run_dir": "nowhere", "ref": "absolution_minions", "seed": 4, "variant": "no-eldritch_battery",
                                  "metric": "CombinedDPS", "ours": 412000, "stop": "time"}, {}, {})
    assert (out["name"], out["var"], out["ours_h"]) == ("Absolution Minions", "без Eldritch Battery", "412k"), out
    # a check nobody ran is not known: no mark, no sentence
    assert (out["errors"], out["warnings"], out["floors_bad"], out["said"]) == (None, None, None, []), out


def test_queue_strings_only():
    out = addon._reading_facts({"run_dir": "nowhere", "ref": "cold_dot", "seed": 1, "audit": "2 errors / 5 warnings",
                                  "floors": "PhysicalMaximumHitTaken 4,120 < 6,000"}, {}, {})
    assert (out["errors"], out["warnings"], out["floors_bad"]) == (2, 5, True), out
    assert len(out["said"]) == 1 and "PhysicalMaximumHitTaken" not in out["said"][0][1], out["said"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
