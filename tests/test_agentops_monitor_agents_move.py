"""#885 E2a: the agents panel moved from `tools/agentops/monitor.py` to `tools/agentops/monitor_agents.py`.

The new module loads with `junkroan`, `token_meter` and `cloud_lane` blocked (a repo that ships the core
but not the monitor has none of them), `panel_agents` on an empty projects folder gives the value
`monitor.panel_agents` gives, every moved name is the same object from both modules, and the two constants
that used to come from `token_meter` keep their values.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.agentops import monitor, monitor_agents
from tools.agentops.util import no_window_flags

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)

MOVED = (
    "ROOT", "REPO", "DEFAULT_PROJECTS_DIR", "DEFAULT_PRICES_PATH",
    "_MODEL_ID_RE", "_MODEL_ALIASES", "_ISSUE_IN_NAME_RE",
    "model_display_name", "display_model", "_tool_summary", "MainScan", "_cache_key", "_Cache",
    "_MAIN_CACHE", "_SUBAGENT_CACHE", "_COMPLETED_CACHE", "_ANSWERED_CACHE",
    "scan_main_transcript", "cached_main_scan", "cached_subagent_turns", "completed_agent_ids",
    "answered_tool_use_ids", "turn_cost_total", "_issue_from_name", "_seconds_since",
    "build_subagent_row", "build_session_row", "_ORCH_NAME_RE", "_is_orch", "load_orch_state",
    "attach_held_issues", "_matches_state", "panel_agents", "live_sessions_raw",
)

# Runs in a fresh interpreter: the three names are blocked before the module is imported, so any
# module-level import of them fails the import instead of passing silently.
_PROBE = """
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

for blocked in ("junkroan", "token_meter", "tools.agentops.cloud_lane"):
    sys.modules[blocked] = None

from tools.agentops import monitor_agents

now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
result = monitor_agents.panel_agents([], projects_dir=Path(sys.argv[1]), prices={},
                                     repo_cwd=Path(sys.argv[2]), now=now)
print(json.dumps(result))
"""


def _token_meter():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import token_meter

    return token_meter


def test_the_module_imports_and_panels_with_junkroan_token_meter_and_cloud_lane_blocked(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    proc = subprocess.run([sys.executable, "-c", _PROBE, str(projects), str(ROOT)], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120, env=env, creationflags=no_window_flags())
    assert proc.returncode == 0, proc.stderr
    in_process = monitor.panel_agents([], projects_dir=projects, prices={}, repo_cwd=ROOT, now=NOW)
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == in_process == {"sessions": []}


def test_every_moved_name_is_the_same_object_in_monitor_and_monitor_agents():
    for name in MOVED:
        assert getattr(monitor, name) is getattr(monitor_agents, name), name


def test_the_constants_that_came_from_token_meter_keep_their_values():
    token_meter = _token_meter()
    assert monitor_agents.DEFAULT_PROJECTS_DIR == token_meter.DEFAULT_PROJECTS_DIR
    assert monitor_agents.DEFAULT_PRICES_PATH == token_meter.DEFAULT_PRICES_PATH
    assert monitor_agents.REPO == "Rasslabsya4el/Poe-Junkroan"
    assert monitor_agents.ROOT == ROOT
