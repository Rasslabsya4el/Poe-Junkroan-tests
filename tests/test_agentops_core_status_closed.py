"""tools/agentops/core_update.py (issue #283, extended by #291): `core status` names, beside what
waits, the core issues this repo's last taken update closed and the ones a waiting update would
close -- read from local git (the taken side's replaced version) and the home's commit messages
plus its core-issue label list (both sides), filtered to commits that actually touch a manifest
path (#291 rule 1). It also names an own core issue that is already CLOSED but was not named by any
manifest-touching commit of either range (#291 rule 2). No network: the home's GitHub read is
stubbed the same way `test_agentops_core_update.py` does; a real git repo is used only for the
bootstrap row, exactly like `test_agentops_core_update_commit.py`'s pattern."""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

from tests import stood_clock
from tests.home_tree_fake import tree_reply  # #148: the home's tree read (`git/trees/<sha>?recursive=1`)
from tools.agentops import core_update

HOME_REPO = "someone/home-repo"
TARGET_REPO = "someone/target-repo"

A = "a0000000" * 5
B = "b1111111" * 5
C = "c2222222" * 5

COMBINED_JQ = (".commits[] | {sha: .sha, message: .commit.message, "
               "parents: [.parents[].sha], date: .commit.committer.date}")
ISSUE_LIST_KEY = ("issue", "list", "--repo", HOME_REPO, "--label", "core-issue", "--state", "all",
                  "--limit", "500", "--json", "number,title,body,state")


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _fake_result(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _commits_payload(rows: list[dict]) -> str:
    return "".join(json.dumps({"parents": [], "date": "2026-01-01T00:00:00Z", **row}) + "\n"
                   for row in rows)


def _issues_payload(rows: list[dict]) -> str:
    return json.dumps(rows)


def _commit_files_key(sha: str):
    return ("api", f"repos/{HOME_REPO}/commits/{sha}", "--jq", ".files[].filename")


def _manifest_key(sha: str):
    return ("api", f"repos/{HOME_REPO}/contents/tools/agentops/core_manifest.txt?ref={sha}",
            "--jq", ".content")


def _graphql_reply(query: str, files: dict) -> str:
    """The home's `history(path:)` read (#881): per aliased path, the commits whose files name it."""

    repo: dict = {}
    for alias, path in re.findall(r'(h\d+): object\(oid: "[0-9a-f]+"\) \{ \.\.\. on Commit \{ '
                                  r'history\(first: 100, path: ("[^"]*")', query):
        wanted = json.loads(path)
        nodes = [{"oid": sha, "committedDate": "2026-01-01T00:00:00Z"}
                 for sha, text in files.items() if wanted in text.split()]
        repo[alias] = {"history": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}
    return json.dumps({"data": {"repository": repo}})


def _make_runner(table: dict, log: list, files: dict | None = None):
    def runner(args):
        key = tuple(args)
        log.append(key)
        if files is not None and key[:2] == ("api", "graphql"):
            return _fake_result(stdout=_graphql_reply(key[3], files))
        if key not in table:
            raise AssertionError(f"unexpected gh call: {args}")
        return _fake_result(stdout=table[key])
    return runner


def _init_target(tmp_path: Path, *, core_version: str, core_version_before: str | None = None) -> Path:
    """A target that is not a real git repo (like `test_agentops_core_update.py`'s `_init_target`):
    `_taken_before` must fail closed (git commands error, no crash) whenever this is used."""

    target = tmp_path / "target"
    target.mkdir()
    (target / ".git").mkdir()
    (target / "config").mkdir()
    settings = {
        "repo": TARGET_REPO,
        "brain_chat_title": "Brain",
        "context_line": 150000,
        "claude_projects_dir": "target-repo",
        "bridge_dir": str(target / "var" / "agentops"),
        "bridge_lock": "var/locks/bridge.lock",
        "local_modules": [],
        "home": HOME_REPO,
        "core_version": core_version,
        "update_rule": "word",
    }
    if core_version_before is not None:
        settings["core_version_before"] = core_version_before
    (target / "config" / "orchestration.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")

    (target / "tools" / "agentops").mkdir(parents=True)
    (target / "tools" / "agentops" / "core_manifest.txt").write_text("a.txt\n", encoding="utf-8")
    (target / "a.txt").write_text("A\n", encoding="utf-8")
    return target


def _compare_calls(log: list) -> list:
    return [c for c in log if c[0] == "api" and "/compare/" in c[1]]


def _issue_list_calls(log: list) -> list:
    return [c for c in log if c[:2] == ("issue", "list")]


# -- three commits shared by row 1 (taken) and row 2 (waiting): only s1 touches the manifest AND --
# -- names an issue; s2 touches only a non-manifest file; s3 touches the manifest but names nothing

_THREE_COMMITS = [
    {"sha": "s1", "message": "commit s1, closes #11"},
    {"sha": "s2", "message": "commit s2, closes #12"},
    {"sha": "s3", "message": "commit s3, no issue ref"},
]

_THREE_COMMITS_FILES = {
    "s1": "a.txt\n",
    "s2": "docs/STATE.md\n",
    "s3": "a.txt\n",
}

_ELEVEN_TWELVE_OPEN = _issues_payload([
    {"number": 11, "title": "Issue eleven", "body": f"**repo:** {TARGET_REPO}\n\nmore text", "state": "OPEN"},
    {"number": 12, "title": "Issue twelve", "body": f"**repo:** {TARGET_REPO}\n\nmore text", "state": "OPEN"},
])


# -- row 1: taken range, 3 commits -- only the manifest-touching, issue-naming one counts ---------

def test_row1_taken_filters_refs_to_manifest_touching_commits(tmp_path) -> None:
    target = _init_target(tmp_path, core_version=B, core_version_before=A)
    log: list = []
    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): B + "\n",
        ("api", f"repos/{HOME_REPO}/compare/{A}...{B}?per_page=1000&page=1", "--jq", COMBINED_JQ):
            _commits_payload(_THREE_COMMITS),
        _manifest_key(B): _b64("a.txt\n"),
        ISSUE_LIST_KEY: _ELEVEN_TWELVE_OPEN,
    }
    runner = _make_runner(table, log, _THREE_COMMITS_FILES)

    result = core_update.run_core_status(target, gh_runner=runner)

    assert result.closed_taken == [11]
    assert result.closed_waiting == []
    assert result.closed_older == []
    assert "#11" in result.message
    assert "(this repo's)" in result.message
    assert "#12" not in result.message
    assert len(_compare_calls(log)) == 1
    assert len(_issue_list_calls(log)) == 1


# -- row 2: the same 3 commits, now as the waiting range -------------------------------------------

def test_row2_waiting_filters_refs_to_manifest_touching_commits(tmp_path) -> None:
    target = _init_target(tmp_path, core_version=B)
    log: list = []
    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): C + "\n",
        ("api", f"repos/{HOME_REPO}/compare/{B}...{C}?per_page=1000&page=1", "--jq", COMBINED_JQ):
            _commits_payload(_THREE_COMMITS),
        _manifest_key(C): _b64("a.txt\n"),
        ISSUE_LIST_KEY: _ELEVEN_TWELVE_OPEN,
    }
    runner = _make_runner(table, log, _THREE_COMMITS_FILES)

    result = core_update.run_core_status(target, gh_runner=runner)

    assert result.closed_taken == []
    assert result.closed_waiting == [11]
    assert result.closed_older == []
    assert "#11" in result.message
    assert "#12" not in result.message
    assert len(_compare_calls(log)) == 1
    assert len(_issue_list_calls(log)) == 1


# -- row 3: an own CLOSED core issue named by no commit of either (empty) range -------------------

def test_row3_own_closed_issue_named_by_no_commit_is_reported_as_closed_older(tmp_path) -> None:
    target = _init_target(tmp_path, core_version=B)
    log: list = []
    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): B + "\n",
        ISSUE_LIST_KEY: _issues_payload([
            {"number": 13, "title": "Issue thirteen", "body": f"**repo:** {TARGET_REPO}\n\nmore",
             "state": "CLOSED"},
        ]),
    }
    runner = _make_runner(table, log)

    result = core_update.run_core_status(target, gh_runner=runner)

    assert result.closed_older == [13]
    lines_naming_13 = [line for line in result.message.splitlines() if "#13" in line]
    assert len(lines_naming_13) == 1
    assert "closed" in lines_naming_13[0] and "taken core" in lines_naming_13[0]
    lines_naming_13_open = [line for line in result.message.splitlines()
                            if "#13" in line and ("waiting" in line.lower() and "would close" in line.lower())]
    assert lines_naming_13_open == []
    assert len(_compare_calls(log)) == 0
    assert len(_issue_list_calls(log)) == 1


# -- row 4: both ranges nonempty, each names its own issue, no own closed issue outside them ------

def test_row4_no_older_closed_issue_outside_nonempty_ranges(tmp_path) -> None:
    target = _init_target(tmp_path, core_version=B, core_version_before=A)
    log: list = []
    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): C + "\n",
        ("api", f"repos/{HOME_REPO}/compare/{A}...{B}?per_page=1000&page=1", "--jq", COMBINED_JQ):
            _commits_payload([{"sha": "t1", "message": "fix the update, closes #11"}]),
        ("api", f"repos/{HOME_REPO}/compare/{B}...{C}?per_page=1000&page=1", "--jq", COMBINED_JQ):
            _commits_payload([{"sha": "t2", "message": "fix the other thing, closes #12"}]),
        _manifest_key(B): _b64("a.txt\n"),
        _manifest_key(C): _b64("a.txt\n"),
        _commit_files_key("t1"): "a.txt\n",
        _commit_files_key("t2"): "a.txt\n",
        ISSUE_LIST_KEY: _ELEVEN_TWELVE_OPEN,
    }
    runner = _make_runner(table, log, {"t1": "a.txt\n", "t2": "a.txt\n"})

    result = core_update.run_core_status(target, gh_runner=runner)

    assert result.closed_taken == [11]
    assert result.closed_waiting == [12]
    assert result.closed_older == []
    assert len(_compare_calls(log)) == 2
    assert len(_issue_list_calls(log)) == 1


# -- the bootstrap: no `core_version_before` key, found from local git history --------------------

GIT_TIMEOUT = 30


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = stood_clock.run(args, cwd=str(cwd),
                             encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)
    assert result.returncode == 0, f"{args} failed: {result.stderr}"
    return result


def _settings_text(core_version: str) -> str:
    return json.dumps({
        "repo": TARGET_REPO,
        "brain_chat_title": "Brain",
        "context_line": 150000,
        "claude_projects_dir": "target-repo",
        "bridge_dir": "var/agentops",
        "bridge_lock": "var/locks/bridge.lock",
        "local_modules": [],
        "home": HOME_REPO,
        "core_version": core_version,
        "update_rule": "word",
    }, indent=2) + "\n"


def test_bootstrap_taken_before_found_from_git_history_when_the_key_is_missing(tmp_path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    _run(["git", "init", "-b", "main"], target)
    _run(["git", "config", "user.email", "test@example.com"], target)
    _run(["git", "config", "user.name", "Test"], target)

    (target / "config").mkdir()
    (target / "config" / "orchestration.json").write_text(_settings_text(A), encoding="utf-8")
    (target / "tools" / "agentops").mkdir(parents=True)
    (target / "tools" / "agentops" / "core_manifest.txt").write_text("a.txt\n", encoding="utf-8")
    _run(["git", "add", "."], target)
    _run(["git", "commit", "-m", "core_version at A"], target)

    (target / "config" / "orchestration.json").write_text(_settings_text(B), encoding="utf-8")
    _run(["git", "add", "config/orchestration.json"], target)
    _run(["git", "commit", "-m", "core_version at B"], target)

    settings = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))
    assert "core_version_before" not in settings

    before = core_update._taken_before(target, settings)
    assert before == A

    log: list = []
    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): B + "\n",
        ("api", f"repos/{HOME_REPO}/compare/{A}...{B}?per_page=1000&page=1", "--jq", COMBINED_JQ):
            _commits_payload([{"sha": "s1", "message": "closes #99"}]),
        _manifest_key(B): _b64("a.txt\n"),
        _commit_files_key("s1"): "a.txt\n",
        ISSUE_LIST_KEY: _issues_payload([
            {"number": 99, "title": "Issue ninety-nine", "body": f"**repo:** {TARGET_REPO}\n\nmore",
             "state": "OPEN"},
        ]),
    }
    runner = _make_runner(table, log, {"s1": "a.txt\n"})

    result = core_update.run_core_status(target, gh_runner=runner)

    assert result.closed_taken == [99]
    assert "#99" in result.message


# -- the update writes `core_version_before` -----------------------------------------------------

def _home_gh_runner(*, head: str, a_txt: str = "A1\n"):
    manifest_text = "a.txt\n"
    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): head + "\n",
        ("api", f"repos/{HOME_REPO}/contents/tools/agentops/core_manifest.txt?ref={head}", "--jq", ".content"):
            _b64(manifest_text),
        ("api", f"repos/{HOME_REPO}/contents/a.txt?ref={head}", "--jq", ".content"): _b64(a_txt),
        # #148: the home's whole tree at head, in one call (`core_update.tree`): the blobs the contents calls serve
        ("api", f"repos/{HOME_REPO}/git/trees/{head}?recursive=1"): tree_reply(
            {"tools/agentops/core_manifest.txt": manifest_text.encode("utf-8"), "a.txt": a_txt.encode("utf-8")}).stdout,
    }

    def runner(args):
        key = tuple(args)
        if key not in table:
            raise AssertionError(f"unexpected gh call: {args}")
        return _fake_result(stdout=table[key])
    return runner


def test_update_writes_core_version_before(tmp_path) -> None:
    target = _init_target(tmp_path, core_version=A)

    result = core_update.run_core_update(target, gh_runner=_home_gh_runner(head=B))

    assert "a.txt" in result.changed
    settings = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))
    assert settings["core_version"] == B
    assert settings["core_version_before"] == A
