"""#666 row 3: the merge suite's worker probe asks the budget with the merge_suite role."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _template() -> str:
    return json.loads((ROOT / "config" / "orchestration.json").read_text(encoding="utf-8"))["merge_suite_workers_probe"]


def test_probe_prints_the_worker_count_line():
    assert "--suite-workers" in _template()


def test_probe_runs_and_prints_a_workers_line():
    cmd = _template().replace("python ", f'"{sys.executable}" ', 1)
    result = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0
    assert result.stdout.strip().splitlines()[-1].startswith("workers ")


def test_verdict_role_still_answers_go_wait(tmp_path):
    budget = tmp_path / "budget.json"
    day = {"hours": [0, 24], "total": 7, "others": 2, "min_free_ram_gb": 0, "merge_suite": 6}
    budget.write_text(json.dumps({"day": day, "night": {**day, "hours": [0, 0]}}), encoding="utf-8")
    env = {**os.environ, "JUNKROAN_POB_BUDGET": str(budget)}

    def run(cmd: str) -> int:
        cmd = cmd.replace("python ", f'"{sys.executable}" ', 1)
        return subprocess.run(cmd, shell=True, cwd=ROOT, env=env, capture_output=True, timeout=120).returncode

    assert run("python scripts/machine_load.py --need 6 --role merge_suite") == 0
    assert run("python scripts/machine_load.py --need 7 --role merge_suite") == 3
    assert run("python scripts/machine_load.py --need 3 --role other") == 3
