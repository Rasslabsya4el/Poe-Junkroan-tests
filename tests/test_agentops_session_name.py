"""#214: the ORCH session's name carries the repo (`orch <REPO_NAME> #N #M`, `REPO_NAME` = the
part after the slash of the settings file's `repo`, read through `core_settings.load`, never
hard-coded), so a wake by name is never ambiguous between two repos sharing one Claude Code
install. Every reader that parses a session name must accept both this new form and the old
`orch #N ...` form. No real `claude.exe`, `gh` or PoB; the acceptance table's rows 1-6 are marked
below."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tools.agentops.dispatch as dp  # noqa: E402
from tools.agentops import monitor  # noqa: E402
from tools.agentops.dispatch import (  # noqa: E402
    REPO_NAME,
    build_command,
    find_own_session_id,
)
import token_meter as tm  # noqa: E402
import cost_levers as cl  # noqa: E402

from tests.test_agentops_dispatch import (  # noqa: E402
    FakeClaude,
    FakeGh,
    _dispatcher,
    _issue,
)


# -- row 1: two settings, two names -------------------------------------------------------------

def test_row1_two_repos_name_their_sessions_differently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dp, "REPO_NAME", "one")
    name_a = build_command([1], "claude.exe")[3]
    monkeypatch.setattr(dp, "REPO_NAME", "two")
    name_b = build_command([1], "claude.exe")[3]

    assert name_a == "orch one #1"
    assert name_b == "orch two #1"
    assert name_a != name_b


def test_repo_name_is_the_part_after_the_slash_of_the_settings_file() -> None:
    # #214: "nothing of one repo is written into a core file" -- REPO_NAME is derived from the
    # settings loader's own `repo`, never a literal.
    assert dp.REPO_NAME == dp.REPO.rsplit("/", 1)[-1]
    assert dp.REPO_NAME == dp._load_settings()["repo"].rsplit("/", 1)[-1]


# -- row 2: a repo name with digits or a dash never leaks a fake issue number --------------------

def test_row2_repo_name_with_digits_and_dash_leaks_no_issue_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dp, "REPO_NAME", "orch-port-test")
    name = build_command([1, 2, 3], "claude.exe")[3]

    assert name == "orch orch-port-test #1 #2 #3"
    assert dp._ISSUE_RE.findall(name) == ["1", "2", "3"]


def test_row2_repo_name_with_digits_read_back_by_every_number_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dp, "REPO_NAME", "repo2")
    name = build_command([7], "claude.exe")[3]
    assert name == "orch repo2 #7"

    assert dp._ISSUE_RE.findall(name) == ["7"]
    assert monitor._issue_from_name(name) == 7
    assert tm.all_issues(name) == [7]


# -- row 3: an old-form live session is still adopted and woken by its own name -------------------

def test_row3_old_form_session_still_adopted_and_woken(tmp_path: Path) -> None:
    claude = FakeClaude()
    claude.add_session("old01", name="orch #40", state="working", status="busy",
                       startedAt=int(time.time() * 1000) - 60_000)
    gh = FakeGh(candidates=[_issue(40), _issue(41, 2)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh)

    d.tick()  # adopts "old01" from its old-form name
    assert [c.session for c in d.sessions] == ["old01"]
    assert d.sessions[0].name == "orch #40"

    gh.claim(40)
    report = d.tick()  # #41 is a ready candidate the adopted session does not hold: it is woken

    assert report.woke == (41,)
    assert claude.waked and claude.waked[0][0] == "orch #40"  # addressed by its own old-form name


# -- row 4: the wake of a tracked session is addressed to its own name, 1 call -------------------

def test_row4_wake_addresses_the_sessions_own_name_one_call(tmp_path: Path) -> None:
    claude = FakeClaude()
    gh = FakeGh(candidates=[_issue(1)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh)
    d.tick()  # starts one session named via the new form

    started_name = claude.started[0][1][3]
    assert started_name == f"orch {REPO_NAME} #1"

    gh.claim(1)
    d.tick()
    gh._candidates = [_issue(2, 2)]
    d.tick()  # #2 becomes ready: exactly one wake, addressed to the started name

    assert len(claude.waked) == 1
    assert claude.waked[0][0] == started_name


# -- row 5: every reader that parses a session name accepts both forms ---------------------------

NEW_NAME = f"orch {REPO_NAME} #5 #6"
OLD_NAME = "orch #5 #6"


@pytest.mark.parametrize("name", [NEW_NAME, OLD_NAME])
def test_row5_find_own_session_id_accepts_both_forms(name: str) -> None:
    claude = FakeClaude()
    claude.add_session("own1", name=name, kind="background", state="working",
                       cwd=str(dp.ROOT))
    assert find_own_session_id(claude, env={}, cwd=dp.ROOT) == "own1"


@pytest.mark.parametrize("name", [NEW_NAME, OLD_NAME])
def test_row5_dispatch_adopt_live_reads_issues_off_both_forms(tmp_path: Path, name: str) -> None:
    claude = FakeClaude()
    claude.add_session("adopted1", name=name, state="working", status="busy",
                       startedAt=int(time.time() * 1000) - 60_000)
    gh = FakeGh(candidates=[_issue(5), _issue(6, 2)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh)
    d.tick()

    assert d.sessions[0].offered == (5, 6)


@pytest.mark.parametrize("name", [NEW_NAME, OLD_NAME])
def test_row5_monitor_is_orch_and_issue_from_name_accept_both_forms(name: str) -> None:
    assert monitor._is_orch({"name": name}) is True
    assert monitor._issue_from_name(f"orch {REPO_NAME} #9") == 9
    assert monitor._issue_from_name("orch #9") == 9


@pytest.mark.parametrize("name", [NEW_NAME, OLD_NAME])
def test_row5_monitor_held_issues_accepts_both_forms(tmp_path: Path, name: str) -> None:
    held = monitor._held_issues([{"name": name, "cwd": str(dp.ROOT)}], repo_cwd=dp.ROOT)
    assert held == {5: name, 6: name}


@pytest.mark.parametrize("name", [NEW_NAME, OLD_NAME])
def test_row5_token_meter_finishing_reads_issue_numbers_off_both_forms(name: str) -> None:
    assert tm.all_issues(name) == [5, 6]


@pytest.mark.parametrize("name", [f"orch {REPO_NAME} #200", "orch #200"])
def test_row5_token_meter_classify_chat_accepts_both_forms(name: str) -> None:
    assert tm.classify_chat(name, brain_pattern=r"opus|fable", orch_pattern=r"orch") == "ORCH"


@pytest.mark.parametrize("name", [f"orch {REPO_NAME} #200", "orch #200"])
def test_row5_cost_levers_classify_chat_accepts_both_forms(name: str) -> None:
    assert cl.tm.classify_chat(
        name, brain_pattern=cl.DEFAULT_BRAIN_TITLE_PATTERN, orch_pattern=cl.DEFAULT_ORCH_TITLE_PATTERN
    ) == "ORCH"
