import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_898_admission.py"


def test_replay_hysteresis(tmp_path):
    spec = importlib.util.spec_from_file_location("replay_898", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    vals = [7.9] * 10 + [9.2] * 10 + [8.5] * 10 + [7.9] * 10
    f = tmp_path / "w.jsonl"
    f.write_text(
        "".join(
            json.dumps({"ts": f"2026-10-11T12:{(61 * i) // 60:02d}:{(61 * i) % 60:02d}", "ncpu": 12, "total_busy_cores": v}) + "\n"
            for i, v in enumerate(vals)
        ),
        encoding="utf-8",
    )
    r = mod.replay(f)
    assert (r["samples"], r["points"], r["no_reading"]) == (40, 31, 0)
    a = r["answers"]
    assert a[0] is False  # 7.9: go
    first_wait = a.index(True)
    last_wait = len(a) - 1 - a[::-1].index(True)
    assert all(a[first_wait : last_wait + 1])  # 8.5 block keeps wait (between lines), no flapping
    assert a[-1] is False  # back under 8.0
    assert (r["go_to_wait"], r["wait_to_go"]) == (1, 1)
    assert r["max_busy"] == 9.2
