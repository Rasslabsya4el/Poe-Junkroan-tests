"""`tools/agentops/gh_call.run_gh` is the one `gh` adapter of every `gh` call in tools/agentops; its contract holds (fakes only, no network)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tools.agentops import (  # noqa: E402
    areas, cloud_lane, core_issue, core_update, dispatch, full_run, gh_call, loop_stop_cli, merge, monitor_issues, port,
    provisional, streams,
)
from tools.agentops.gh_call import GH_TIMEOUT_SECONDS, GhCalledProcessError, is_transient_gh_failure, run_gh  # noqa: E402

#: #1176: the default plugin cache and enabled settings a port call reads are the test's own (conftest `plugin_home`)
pytestmark = pytest.mark.usefixtures("plugin_home")

SITES = ["areas", "cloud_lane", "core_issue", "core_update", "full_run", "loop_stop_cli", "merge",
         "dispatch", "monitor_issues", "port", "provisional", "streams"]
TRANSIENT = "error connecting to api.github.com: dial tcp: i/o timeout"
PLAIN = "gh: Not Found (HTTP 404)"


@pytest.mark.parametrize("name", SITES)
def test_old_inline_gh_form_is_gone_and_adapter_is_used(name):
    text = (ROOT / "tools" / "agentops" / f"{name}.py").read_text(encoding="utf-8")
    assert len(re.findall(r"\[\s*\"gh\"\s*,\s*\*args", text)) == 0
    assert len(re.findall(r"subprocess\.\w+\(\s*\[\s*\"gh\"", text)) == 0
    assert text.count("run_gh") >= 2  # the import and at least one use


class FakePopen:
    """Stands in for `subprocess.Popen`: records argv, kwargs and the communicate call."""

    instances: list["FakePopen"] = []
    answer: tuple = (0, "", "")
    hang_first = False

    def __init__(self, argv, **kwargs):
        self.args = list(argv)
        self.kwargs = kwargs
        self.pid = 4242
        self.returncode, self._out, self._err = type(self).answer
        self.communicate_calls: list[tuple] = []
        self.killed = False
        self.stdout = self.stderr = self.stdin = None
        type(self).instances.append(self)

    def communicate(self, input=None, timeout=None):
        self.communicate_calls.append((input, timeout))
        if type(self).hang_first and len(self.communicate_calls) == 1:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self._out, self._err

    def kill(self):
        self.killed = True


@pytest.fixture
def fake(monkeypatch):
    FakePopen.instances = []
    FakePopen.answer = (0, "", "")
    FakePopen.hang_first = False
    monkeypatch.setattr(gh_call.subprocess, "Popen", FakePopen)
    killed: list = []
    monkeypatch.setattr(gh_call, "_kill_tree", lambda proc: killed.append(proc.pid))
    FakePopen.tree_kills = killed
    return FakePopen


def test_one_timeout_is_passed_and_pipes_are_captured(fake):
    assert GH_TIMEOUT_SECONDS == 45.0
    run_gh(["issue", "list"])
    proc = fake.instances[-1]
    assert proc.args == ["gh", "issue", "list"]
    assert proc.communicate_calls == [(None, GH_TIMEOUT_SECONDS)]
    assert proc.kwargs["stdout"] == subprocess.PIPE and proc.kwargs["stderr"] == subprocess.PIPE
    assert proc.kwargs["stdin"] is None and proc.kwargs["cwd"] is None
    assert proc.kwargs["text"] is True and proc.kwargs["encoding"] == "utf-8" and proc.kwargs["errors"] == "replace"


def test_stdin_text_and_cwd_cloud_lane_and_full_run_pattern(fake, tmp_path):
    fake.answer = (0, "{}", "")
    result = run_gh(["issue", "comment", "5", "--body-file", "-"], cwd=tmp_path, input="body", timeout=7.0)
    proc = fake.instances[-1]
    assert proc.communicate_calls == [("body", 7.0)]
    assert proc.kwargs["stdin"] == subprocess.PIPE and proc.kwargs["cwd"] == str(tmp_path)
    assert isinstance(result, subprocess.CompletedProcess) and result.stdout == "{}" and result.returncode == 0


def test_bytes_in_bytes_out_areas_pattern(fake):
    fake.answer = (0, b"\xff[1]", b"")
    result = run_gh(["api", "graphql", "--input", "-"], input=b"{}", text=False)
    proc = fake.instances[-1]
    assert "text" not in proc.kwargs and "encoding" not in proc.kwargs
    assert proc.communicate_calls[0][0] == b"{}"
    assert result.stdout == b"\xff[1]"


def test_check_true_raises_with_the_transient_flag_loop_stop_pattern(fake):
    fake.answer = (1, "", TRANSIENT)
    with pytest.raises(GhCalledProcessError) as caught:
        run_gh(["api", "x"], check=True)
    assert isinstance(caught.value, subprocess.CalledProcessError)
    assert caught.value.returncode == 1 and caught.value.transient is True
    fake.answer = (1, "", PLAIN)
    with pytest.raises(GhCalledProcessError) as caught:
        run_gh(["api", "x"], check=True)
    assert caught.value.transient is False


def test_nonzero_without_check_returns_and_flags_transient(fake):
    fake.answer = (1, "", TRANSIENT)
    flaky = run_gh(["issue", "view", "1"])
    assert flaky.returncode == 1 and flaky.transient is True
    fake.answer = (1, "", PLAIN)
    assert run_gh(["issue", "view", "1"]).transient is False
    fake.answer = (0, "ok", "")
    assert run_gh(["issue", "view", "1"]).transient is False


def test_transient_check_is_the_anomalies_one():
    from junkroan.runs.anomalies import is_transient_gh_failure as original
    samples = [[TRANSIENT], [PLAIN], ["HTTP 502 Bad Gateway"], ["gh: HTTP 503"], ["dial tcp: lookup api.github.com"],
               ["pytest: 3 failed"], [], ["secondary rate limit, github"]]
    for tail in samples:
        assert is_transient_gh_failure(tail) == original(tail), tail


def test_timeout_kills_the_tree_and_raises_timeout_expired(fake):
    fake.hang_first = True
    with pytest.raises(subprocess.TimeoutExpired):
        run_gh(["issue", "list"], timeout=3.0)
    assert fake.tree_kills == [4242]


def test_real_process_timeout_returns_in_seconds(monkeypatch):
    real = subprocess.Popen
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    monkeypatch.setattr(gh_call.subprocess, "Popen", lambda argv, **kw: real(sleeper, **kw))
    import time
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_gh(["api", "x"], timeout=1.0)
    assert time.monotonic() - started < 20


# -- one example per former site: it hands its old arguments to the adapter ----------------------------------

@pytest.fixture
def seen(monkeypatch):
    calls: list = []

    def fake_run_gh(args, **kwargs):
        calls.append((list(args), kwargs))
        return gh_call.GhResult(["gh", *args], 0, '{"state": "OPEN", "stateReason": ""}', "")

    for module in (areas, cloud_lane, core_issue, core_update, full_run, loop_stop_cli, merge):
        monkeypatch.setattr(module, "run_gh", fake_run_gh)
    return calls


def test_areas_site(seen):
    areas._default_runner(["api", "graphql"], b"data")
    assert seen == [(["api", "graphql"], {"input": b"data", "text": False})]


def test_cloud_lane_site(seen, tmp_path):
    cloud_lane.LaneGh(cwd=tmp_path)._run(["issue", "list"], "stdin")
    assert seen == [(["issue", "list"], {"cwd": tmp_path, "input": "stdin", "timeout": GH_TIMEOUT_SECONDS})]


def test_cloud_lane_keeps_an_explicit_timeout(seen, tmp_path):
    cloud_lane.LaneGh(cwd=tmp_path, timeout=9.0)._run(["issue", "list"])
    assert seen[0][1]["timeout"] == 9.0


def test_core_issue_site(seen):
    core_issue._gh_runner(["repo", "view"])
    assert seen == [(["repo", "view"], {})]


def test_core_update_site(seen):
    core_update._gh_runner(["api", "repos/a/b/compare"])
    assert seen == [(["api", "repos/a/b/compare"], {})]


def test_full_run_site(seen, tmp_path):
    full_run._real_gh(tmp_path)(["issue", "list"])
    assert seen == [(["issue", "list"], {"cwd": tmp_path})]


def test_loop_stop_cli_site_checks_and_returns_stdout(seen):
    assert loop_stop_cli._gh(["issue", "list"]) == '{"state": "OPEN", "stateReason": ""}'
    assert seen == [(["issue", "list"], {"check": True})]


def test_merge_site(seen, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert merge.read_issue_state(12) == ("OPEN", "")
    assert seen == [(["issue", "view", "12", "--json", "state,stateReason"], {})]


# -- unit 5b: the other sites ----------------------------------------------------------------------------------

def test_no_inline_gh_subprocess_form_in_tools_agentops():
    inline = re.compile(r"\[\s*\"gh\"\s*,")
    offenders = []
    for path in sorted((ROOT / "tools" / "agentops").glob("*.py")):
        if path.name == "gh_call.py":
            continue
        offenders += [path.name for _ in inline.finditer(path.read_text(encoding="utf-8"))]
    assert len(offenders) == 0, offenders


def test_anomalies_uses_the_adapters_transient_check_and_has_no_copy():
    from junkroan.runs import anomalies
    text = (ROOT / "src" / "junkroan" / "runs" / "anomalies.py").read_text(encoding="utf-8")
    assert "_TRANSIENT_MARKER_RE" not in text and "_GH_WORD_RE" not in text
    for tail in ([TRANSIENT], [PLAIN], ["HTTP 502 Bad Gateway"], ["pytest: 3 failed"], []):
        assert anomalies.is_transient_gh_failure(tail) == is_transient_gh_failure(tail), tail


@pytest.fixture
def seen_b(monkeypatch):
    calls: list = []
    answer = {"stdout": "[]"}

    def fake_run_gh(args, **kwargs):
        calls.append((list(args), kwargs))
        return gh_call.GhResult(["gh", *args], 0, answer["stdout"], "")

    for module in (dispatch, monitor_issues, port, provisional, streams):
        monkeypatch.setattr(module, "run_gh", fake_run_gh)
    return calls


def test_dispatch_site(seen_b, tmp_path):
    dispatch.GhCli(cwd=tmp_path)._run(["issue", "list"], "stdin")
    assert seen_b == [(["issue", "list"], {"cwd": tmp_path, "input": "stdin", "timeout": 60.0})]


def test_dispatch_site_keeps_the_injected_runner(seen_b):
    got = dispatch.GhCli(runner=lambda args, stdin: ("fake", args, stdin))._run(["x"], "s")
    assert got == ("fake", ["x"], "s") and seen_b == []


def test_monitor_issues_site(seen_b, tmp_path):
    assert monitor_issues.GhIssuesCli(repo="o/r", cwd=tmp_path, timeout=7.0).list_all() == []
    assert seen_b == [(["issue", "list", "-R", "o/r", "--state", "all", "--json", monitor_issues.ISSUE_FIELDS,
                        "--limit", "500"], {"cwd": tmp_path, "timeout": 7.0})]


def test_monitor_issues_site_still_raises_on_a_failed_call(monkeypatch):
    monkeypatch.setattr(monitor_issues, "run_gh", lambda args, **kw: gh_call.GhResult(["gh"], 1, "", "boom"))
    with pytest.raises(RuntimeError, match="boom"):
        monitor_issues.GhIssuesCli().list_all()


def test_port_check_machine_ready_site(seen_b, tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"enabledPlugins": {"mattpocock-skills@claude-plugins-official": true}}', encoding="utf-8")

    def version(args, **kwargs):
        seen_b.append((list(args), kwargs))
        return gh_call.GhResult(["gh", *args], 0, "gh version 2.101.0", "")

    monkeypatch.setattr(port, "run_gh", version)
    port.check_machine_ready(settings)
    assert seen_b == [(["--version"], {})]


def test_port_sync_labels_site(seen_b):
    created, there = port.sync_labels("o/r", labels={})
    assert (created, there) == ([], [])
    assert seen_b == [(["label", "list", "-R", "o/r", "--json", "name", "--limit", "200"], {})]


def test_port_plan_port_site(seen_b, monkeypatch, tmp_path):
    for name in ("check_home_clean", "check_machine_ready", "check_target_ready", "check_no_agents_md_only"):
        monkeypatch.setattr(port, name, lambda *a, **k: None)
    monkeypatch.setattr(port, "read_manifest", lambda *a, **k: [])
    monkeypatch.setattr(port, "find_clashes", lambda *a, **k: [])
    monkeypatch.setattr(port, "_stub_plan", lambda *a, **k: [])
    monkeypatch.setattr(port, "load_core_labels", lambda *a, **k: {"x": {}})
    files, labels = port.plan_port(tmp_path, "o/r", settings_path=tmp_path / "settings.json")
    assert labels == ["x"]
    assert seen_b == [(["label", "list", "-R", "o/r", "--json", "name", "--limit", "200"], {})]


def test_provisional_site(seen_b, tmp_path):
    provisional.GhCli(cwd=tmp_path)._run(["label", "create", "p"], "stdin")
    assert seen_b == [(["label", "create", "p"], {"cwd": tmp_path, "input": "stdin", "timeout": 60.0})]


def test_streams_site(seen_b):
    streams.StreamKeeper("o/r")._run(["api", "graphql"], "stdin")
    assert seen_b == [(["api", "graphql"], {"cwd": streams.ROOT, "input": "stdin", "timeout": 60})]
