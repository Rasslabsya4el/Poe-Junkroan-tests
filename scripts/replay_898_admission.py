"""Replay recorded PC-load samples through ``load_admission`` (#898, acceptance row 12).

Replay convention: every line of ``kinds_838_*.jsonl`` (keys ``ts``, ``total_busy_cores``) is ONE real one-minute
sample, t = ``ts`` as unix seconds. Walking the lines in order, from the 10th on (the first rolling 10-minute window:
420 samples give 411 evaluation points) ``load_admission`` is called with the samples whose t lies in the last 600 s,
now = that sample's t, DAY mode, cores = ``ncpu`` of the file, ``previous_wait`` = the previous evaluation's answer
(None at the start). Answers with reason ``no reading`` (a gap in ts) are counted separately.

Usage: python scripts/replay_898_admission.py [path.jsonl]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob.slot_budget import load_admission  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

DEFAULT_FILE = ROOT / "artifacts" / "runs" / "kinds_838_20261011-1116.jsonl"
EXPECTED_SAMPLES = 420
EXPECTED_POINTS = 411
MIN_POINT = 9  # index of the first sample with 10 samples behind it


ORCH_HOLD_CAP_S = 1800.0  # `start_admission_hold_cap_s` (#907)


def _longest_waits(samples: list[tuple[float, float]], rows: list[dict]) -> tuple[float, float]:
    """(#907) Longest unbroken run of `wait` answers, in seconds, without a cap and with the 30 min ORCH cap
    applied by the rule (waited_s accumulates over consecutive waits from the first one, reset after a go).
    The length of a run is read from the file's own times: last wait's t minus the first wait's t plus the spacing
    to the next sample (the median gap of the file), not an assumed minute."""
    gaps = sorted(b[0] - a[0] for a, b in zip(samples, samples[1:]))
    spacing = gaps[len(gaps) // 2] if gaps else 0.0
    out = []
    for cap in (None, ORCH_HOLD_CAP_S):
        prev: bool | None = None
        since: float | None = None
        best = 0.0
        for i in range(MIN_POINT, len(samples)):
            now = samples[i][0]
            waited = 0.0 if since is None else now - since
            adm = load_admission(samples[: i + 1], now, "day", prev, int(rows[i].get("ncpu", 12)), waited, cap)
            prev = not adm.go
            if adm.go:
                since = None
                continue
            if since is None:
                since = now
            best = max(best, now - since + spacing)
        out.append(best)
    return out[0], out[1]


def replay(path: Path) -> dict:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    samples = [(datetime.fromisoformat(r["ts"]).timestamp(), float(r["total_busy_cores"])) for r in rows]
    prev: bool | None = None
    answers: list[bool] = []
    ge_cap = no_reading = 0
    cap = None
    for i in range(MIN_POINT, len(samples)):
        now = samples[i][0]
        cores = int(rows[i].get("ncpu", 12))
        adm = load_admission(samples[: i + 1], now, "day", prev, cores)
        cap = adm.cap
        wait = not adm.go
        answers.append(wait)
        no_reading += adm.reason == "no reading"
        if adm.mean is not None and adm.mean >= adm.cap:
            ge_cap += 1
        prev = wait
    trans = list(zip(answers, answers[1:]))
    longest, longest_capped = _longest_waits(samples, rows)
    return {
        "longest_wait_s": longest,
        "longest_wait_capped_s": longest_capped,
        "samples": len(rows),
        "points": len(answers),
        "answers": answers,
        "wait": sum(answers),
        "ge_line": ge_cap,
        "go_to_wait": sum(1 for x, y in trans if not x and y),
        "wait_to_go": sum(1 for x, y in trans if x and not y),
        "max_busy": max((v for _, v in samples), default=0.0),
        "no_reading": no_reading,
        "cap": cap,
    }


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_FILE
    r = replay(path)
    print(f"file: {path.name}")
    print(f"samples read: {r['samples']}" + ("" if r["samples"] == EXPECTED_SAMPLES else f" (expected {EXPECTED_SAMPLES}: differs)"))
    print(f"evaluation points: {r['points']}" + ("" if r["points"] == EXPECTED_POINTS else f" (expected {EXPECTED_POINTS}: differs)"))
    print(f"wait answers: {r['wait']}")
    print(f"points with plain 10-minute mean >= {r['cap']}: {r['ge_line']}")
    print(f"go->wait: {r['go_to_wait']}, wait->go: {r['wait_to_go']}")
    print(f"max total_busy_cores: {r['max_busy']:.3f}")
    print(f"'no reading' answers: {r['no_reading']}")
    print(f"longest unbroken wait, no cap: {human_duration(r['longest_wait_s'])}")
    print(f"longest unbroken wait, 30 min ORCH cap: {human_duration(r['longest_wait_capped_s'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
