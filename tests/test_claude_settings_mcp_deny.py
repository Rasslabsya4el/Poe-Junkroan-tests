"""#345: the repo's permissions.deny covers whole MCP servers and holds no duplicate line."""
import json
from pathlib import Path

import pytest

SETTINGS = Path(__file__).resolve().parents[1] / ".claude" / "settings.json"
SERVERS = ("ccd_directory", "ccd_host", "ccd_pr", "ccd_sidebar", "ccd_view", "ccd_window",
           "mcp-registry", "scheduled-tasks")


def _deny() -> list[str]:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]


@pytest.mark.parametrize("server", SERVERS)
def test_server_denied(server):
    deny = _deny()
    assert f"mcp__{server}" in deny or f"mcp__{server}__*" in deny


def test_no_duplicate_deny_lines():
    deny = _deny()
    assert len(deny) == len(set(deny))
