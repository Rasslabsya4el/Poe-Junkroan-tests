"""Root conftest (#839): by day every pytest process tree the system starts runs BELOW_NORMAL.

A worker's own bare ``python -m pytest`` has no wrapper, so the one place that reaches every pytest tree is
this hook: the pytest process lowers its own priority class and its children (xdist workers via execnet,
PoB workers of pob-marked tests) inherit it. By night nothing changes. Never raises."""
import os
import sys
from pathlib import Path


def _is_day_now() -> bool:
    """The budget's "day" period (play is always day); ``JUNKROAN_FORCE_PERIOD=day|night`` forces it for
    tests. Same rule as ``tools.agentops.full_run.is_day_now``; False when the budget cannot be read."""
    forced = os.environ.get("JUNKROAN_FORCE_PERIOD", "").strip().lower()
    if forced in ("day", "night"):
        return forced == "day"
    try:
        src = str(Path(__file__).resolve().parent / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from junkroan.pob import slot_budget
        return slot_budget.load_budget().period == "day"
    except Exception:
        return False


def pytest_configure(config):
    # xdist workers are started by the controller and inherit its class: only the controller (no
    # PYTEST_XDIST_WORKER) acts, but lowering a worker too is harmless.
    try:
        if not _is_day_now():
            return
        import psutil
        me = psutil.Process()
        if os.name == "nt":
            if me.nice() == psutil.NORMAL_PRIORITY_CLASS:  # never raise a class that is already lower
                me.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        elif me.nice() < 10:
            me.nice(10)
    except Exception:
        pass
