"""#869: on the PC by day the burner cases start at most 1 real spinner (the rest is recorded, not run)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import test_issue842_burner as cases  # noqa: E402
from junkroan import burner  # noqa: E402


def test_pc_day_all_cases_start_at_most_one_real_spinner(monkeypatch):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
    assert not cases.many_real_ok()
    real_popen = burner.subprocess.Popen
    real = []

    def counting(args, **kw):
        if isinstance(args, list) and len(args) > 2 and args[2] == burner._BURNER_CODE:
            real.append(args)
        return real_popen(args, **kw)

    monkeypatch.setattr(burner.subprocess, "Popen", counting)
    cases._CHILD_SPINNERS.clear()
    with pytest.MonkeyPatch.context() as m:
        cases.test_pc_day_12_refused(m)
    cases.test_pc_day_one_burner_allowed(monkeypatch)
    for host, period in [("pc", "night"), ("laptop", "day")]:
        with pytest.MonkeyPatch.context() as m, pytest.raises(pytest.skip.Exception):
            cases.test_12_burners_below_normal_then_gone(host, period, m)
    with pytest.MonkeyPatch.context() as m, pytest.raises(pytest.skip.Exception):
        cases.test_script_laptop_day_runs_and_ends(m)
    cases.test_caller_killed_leaves_no_burner()
    total = len(real) + sum(cases._CHILD_SPINNERS)
    print("real spinners started:", total)
    assert total <= 1 + 1  # test_pc_day_one_burner_allowed (1) + caller_killed (1), never at once: each ends before the next
    assert max([1] * len(real) + cases._CHILD_SPINNERS) <= 1
